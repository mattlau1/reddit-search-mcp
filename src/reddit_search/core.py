"""Shared core: tool implementations and compact text formatting."""
from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from . import client as _client
from . import expand
from .client import RedditSearchError

CALL_DEADLINE = 40.0  # seconds; no new request or retry cooldown is started past this
MAX_REQUESTS = 8      # network requests per search call, comment search and id lookup included


def api_get(path: str, params: dict, retries: int = 2, deadline: float | None = None) -> list | dict:
    return _client.default_client().get(path, params, retries=retries, deadline=deadline)


# ---------- helpers ----------

def date(ts) -> str:
    if not ts:
        return "?"
    return datetime.fromtimestamp(float(ts), timezone.utc).strftime("%Y-%m-%d")


def snippet(text: str | None, n: int) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()
    if t in ("[removed]", "[deleted]"):
        return t
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def permalink(sub: str, post_id: str) -> str:
    return f"https://www.reddit.com/r/{sub}/comments/{post_id}/"


def clean_sub(s: str) -> str:
    s = s.strip()
    s = re.sub(r"^(https?://(www\.|old\.)?reddit\.com)?/?r/", "", s, flags=re.I)
    return s.strip("/ ")


def parse_post_id(s: str) -> str:
    """Accept a bare id, t3_id, or any reddit post URL (incl. redd.it)."""
    s = s.strip()
    m = re.search(r"/comments/([a-z0-9]+)", s, re.I) or re.search(r"redd\.it/([a-z0-9]+)", s, re.I)
    if m:
        return m.group(1).lower()
    s = re.sub(r"^t3_", "", s, flags=re.I)
    if re.fullmatch(r"[a-z0-9]{2,10}", s, re.I):
        return s.lower()
    raise RedditSearchError(f"Cannot parse a post id from {s!r}. Give a reddit URL or the base-36 id.")


def parse_time(s: str | None) -> str | None:
    return s or None  # API accepts ISO dates like 2024-01-31


# ---------- tools ----------

def find_subreddits(prefix: str, limit: int = 15) -> str:
    prefix = clean_sub(prefix)
    rows = api_get("/subreddits/search", {
        "subreddit_prefix": prefix, "limit": min(max(limit, 1), 50),
        "fields": "display_name,subscribers,public_description,over18",
    })
    if not rows:
        return (f"No subreddit names start with {prefix!r}. The API matches name prefixes only, not topics: "
                "guess other names (software/product name, hobby, game, no spaces) and try again.")
    out = [f"{len(rows)} subreddits starting with {prefix!r} (by subscribers):"]
    for r in rows:
        nsfw = " [NSFW]" if r.get("over18") else ""
        out.append(f"r/{r['display_name']} ({r.get('subscribers') or 0:,} subs){nsfw}: "
                   f"{snippet(r.get('public_description'), 110)}")
    return "\n".join(out)


def _fanout(jobs, deadline_at: float):
    """Run (path, params, retries) jobs, 2 at a time, in priority order. Returns [(rows|None, err|None)].
    Jobs not started before the deadline are skipped (None, None)."""
    results = []
    with ThreadPoolExecutor(max_workers=2) as ex:
        for i in range(0, len(jobs), 2):
            batch = jobs[i:i + 2]
            if i and time.monotonic() > deadline_at:
                results += [(None, None)] * len(batch)
                continue
            futs = [ex.submit(api_get, *j, deadline_at) for j in batch]
            for f in futs:
                try:
                    results.append((f.result(), None))
                except RedditSearchError as e:
                    results.append((None, e))
    return results


POST_FIELDS = "id,title,created_utc,score,num_comments,selftext,author"


def search_posts(subreddit: str, query: str, limit: int = 25, after: str | None = None,
                 before: str | None = None, sort: str = "desc") -> str:
    sub = clean_sub(subreddit)
    limit = min(max(limit, 1), 100)
    per = max(limit, 50)
    concepts = expand.build_concepts(query) or [expand.Concept(w) for w in expand.tokens(query)[:2]]
    if not concepts:
        raise RedditSearchError("Empty query: give at least one keyword.")
    deadline_at = time.monotonic() + CALL_DEADLINE
    common = {"subreddit": sub, "after": parse_time(after), "before": parse_time(before), "sort": sort}
    plan = expand.plan_post_queries(concepts, min(MAX_REQUESTS - 2, 6))
    post_jobs = [("/posts/search", {**common, "query": q, "limit": per, "fields": POST_FIELDS}, 2 if i == 0 else 1)
                 for i, q in enumerate(plan)]
    comment_job = ("/comments/search", {**common, "body": expand.comment_or_query(concepts), "limit": 100,
                                        "fields": "id,body,link_id"}, 1)
    posts: dict[str, dict] = {}
    errors, ok = [], 0

    def take(results, n_post):
        nonlocal ok
        for k, (rows, err) in enumerate(results):
            if err:
                errors.append(err)
            elif rows is not None:
                ok += 1
                if k < n_post:
                    for r in rows:
                        posts.setdefault(r["id"], r)
        return results

    # Strong exact result: the AND of every query word already fills the page, so skip the expansion.
    first = take(_fanout(post_jobs[:2], deadline_at), min(2, len(post_jobs)))
    strong = len(concepts) > 1 and first and first[0][0] is not None and len(first[0][0]) >= limit
    comment_rows: list[dict] = []
    if not strong:
        rest = post_jobs[2:]
        res = take(_fanout(rest + [comment_job], deadline_at), len(rest))
        if res and res[-1][0]:
            comment_rows = res[-1][0]
    if not ok:
        raise errors[0] if errors else RedditSearchError("No response from Arctic Shift.")

    by_post: dict[str, list[str]] = {}
    for c in comment_rows:
        pid = (c.get("link_id") or "").removeprefix("t3_")
        if pid:
            by_post.setdefault(pid, []).append(c.get("body") or "")
    extra = sorted((pid for pid in by_post if pid not in posts), key=lambda p: -len(by_post[p]))[:10]
    if extra and time.monotonic() < deadline_at + 10:
        try:
            for r in api_get("/posts/ids", {"ids": ",".join(extra), "fields": POST_FIELDS}, 1, deadline_at + 10) or []:
                posts.setdefault(r["id"], r)
        except RedditSearchError as e:
            errors.append(e)

    ranked = expand.rank_posts(concepts, posts, by_post)[:limit]
    if not ranked:
        return (f"No posts in r/{sub} matching {query!r} (also tried synonyms). Check the subreddit name "
                "with find_subreddits, or try the plainest nouns for the topic.")
    searched = ", ".join(plan)
    note = f" ({len(errors)} lookup(s) failed or were skipped: results may be incomplete)" if errors else ""
    out = [f"{len(ranked)} posts in r/{sub} for {query!r}, best match first{note}. Searched variants: {searched}"
           + (" + comments" if comment_rows else "") + ". Scores of posts <36h old are unreliable."]
    for s, matched, r in ranked:
        out.append(f"[{r['id']}] {r.get('title', '')} | {date(r.get('created_utc'))} | "
                   f"score {r.get('score')} | {r.get('num_comments')} comments | matched: {', '.join(matched) or 'comments'}\n"
                   f"  {permalink(sub, r['id'])}")
        body = snippet(r.get("selftext"), 200)
        if body:
            out.append(f"  {body}")
    return "\n".join(out)


def search_comments(subreddit: str, query: str, limit: int = 25, after: str | None = None,
                    before: str | None = None, sort: str = "desc") -> str:
    sub = clean_sub(subreddit)
    limit = min(max(limit, 1), 100)
    per = max(limit, 50)
    concepts = expand.build_concepts(query) or [expand.Concept(w) for w in expand.tokens(query)[:2]]
    if not concepts:
        raise RedditSearchError("Empty query: give at least one keyword.")
    common = {"subreddit": sub, "after": parse_time(after), "before": parse_time(before), "sort": sort,
              "limit": per, "fields": "id,body,link_id,score,created_utc,author"}
    jobs = []
    if len(concepts) > 1:
        jobs.append(("/comments/search", {**common, "body": " ".join(c.word for c in concepts)}, 2))
    jobs.append(("/comments/search", {**common, "body": expand.comment_or_query(concepts)}, 1))
    rows: dict[str, dict] = {}
    errors, ok = [], 0
    for i, job in enumerate(jobs):
        (res, err), = _fanout([job], time.monotonic() + CALL_DEADLINE)
        if err:
            errors.append(err)
            continue
        ok += 1
        for r in res or []:
            rows.setdefault(r["id"], r)
        if i == 0 and len(jobs) > 1 and len(rows) >= limit:
            break  # exact AND match already fills the page
    if not ok:
        raise errors[0]
    ranked = []
    for r in rows.values():
        s, matched = expand.score_text(concepts, r.get("body") or "")
        ranked.append((s, matched, r))
    ranked.sort(key=lambda x: (-x[0], -(x[2].get("created_utc") or 0)))
    ranked = ranked[:limit]
    if not ranked:
        return f"No comments in r/{sub} matching {query!r} (also tried synonyms). Try other words or search_posts."
    note = f" ({len(errors)} lookup(s) failed: results may be incomplete)" if errors else ""
    out = [f"{len(ranked)} comments in r/{sub} for {query!r}, best match first{note}:"]
    for s, matched, r in ranked:
        pid = (r.get("link_id") or "").removeprefix("t3_")
        out.append(f"[{r['id']}] {date(r.get('created_utc'))} | score {r.get('score')} | matched: "
                   f"{', '.join(matched) or '?'} | post {pid} {permalink(sub, pid)}\n  {snippet(r.get('body'), 300)}")
    out.append("Use get_thread with a post id to read the whole discussion.")
    return "\n".join(out)


def _children(node: dict) -> list[dict]:
    reps = node.get("replies")
    if isinstance(reps, dict):
        return reps.get("data", {}).get("children", [])
    if isinstance(reps, list):
        return reps
    return []


def get_thread(post: str, max_comments: int = 100, body_chars: int = 600) -> str:
    pid = parse_post_id(post)
    posts = api_get("/posts/ids", {
        "ids": pid, "fields": "id,title,subreddit,selftext,score,num_comments,created_utc,author"})
    if not posts:
        raise RedditSearchError(f"Post {pid} not found in the archive (very new, or never archived).")
    p = posts[0]
    sub = p.get("subreddit", "_")
    out = [f"{p.get('title')}  [{pid}]",
           f"r/{sub} | u/{p.get('author')} | {date(p.get('created_utc'))} | score {p.get('score')} | "
           f"{p.get('num_comments')} comments | {permalink(sub, pid)}"]
    text = (p.get("selftext") or "").strip()
    if text:
        out.append(snippet(text, 2000))
    tree = api_get("/comments/tree", {"link_id": f"t3_{pid}", "limit": max_comments})
    shown = 0
    lines: list[str] = []

    def walk(nodes, depth):
        nonlocal shown
        for n in nodes:
            d = n.get("data", {})
            if n.get("kind") == "more":
                k = d.get("count") or len(d.get("children", []))
                lines.append("  " * depth + f"(+{k} more replies not shown)")
                continue
            if shown >= max_comments:
                return
            shown += 1
            lines.append("  " * depth + f"- u/{d.get('author')} ({d.get('score')}): {snippet(d.get('body'), body_chars)}")
            walk(_children(d), depth + 1)

    walk(tree, 0)
    out.append(f"\nComments (showing {shown} of {p.get('num_comments')}):" if lines else "\n(no comments archived)")
    out.extend(lines)
    return "\n".join(out)
