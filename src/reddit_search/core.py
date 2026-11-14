"""Shared core: API client and compact text formatting."""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone

import httpx

BASE = "https://arctic-shift.photon-reddit.com/api"
HEADERS = {"User-Agent": "reddit-search-mcp/0.1 (agent research tool)"}
RETRY_STATUS = {429, 500, 502, 503, 504}


class RedditSearchError(Exception):
    """Error with a message written for the calling agent."""


def api_get(path: str, params: dict, retries: int = 4, client: httpx.Client | None = None) -> list | dict:
    params = {k: v for k, v in params.items() if v is not None and v != ""}
    own = client is None
    client = client or httpx.Client(timeout=45, headers=HEADERS)
    last = "unknown error"
    try:
        for attempt in range(retries + 1):
            wait = 2.0 * (2**attempt)
            try:
                r = client.get(BASE + path, params=params)
            except httpx.TransportError as e:
                last = f"network error: {type(e).__name__}"
            else:
                body = None
                try:
                    body = r.json()
                except ValueError:
                    pass
                err = body.get("error") if isinstance(body, dict) else None
                if r.status_code == 200 and not err:
                    return body["data"] if isinstance(body, dict) and "data" in body else body
                last = f"HTTP {r.status_code}: {err or r.text[:120]}"
                timeout = bool(err and "imeout" in err)
                if r.status_code == 429:
                    try:
                        wait = max(wait, float(r.headers.get("Retry-After", 0)))
                    except ValueError:
                        pass
                elif r.status_code not in RETRY_STATUS and not timeout:
                    raise RedditSearchError(f"Arctic Shift rejected the request ({last}).")
            if attempt < retries:
                time.sleep(min(wait, 30))
    finally:
        if own:
            client.close()
    raise RedditSearchError(
        f"Arctic Shift unavailable after {retries + 1} tries ({last}). It is a free single-maintainer "
        "service. Busy subreddits time out on keyword search: retry later, narrow with after/before, "
        "or use a more specific query."
    )


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


def search_posts(subreddit: str, query: str, limit: int = 25, after: str | None = None,
                 before: str | None = None, sort: str = "desc") -> str:
    sub = clean_sub(subreddit)
    rows = api_get("/posts/search", {
        "subreddit": sub, "query": query, "limit": min(max(limit, 1), 100),
        "after": parse_time(after), "before": parse_time(before), "sort": sort,
        "fields": "id,title,created_utc,score,num_comments,selftext,author",
    })
    if not rows:
        return (f"No posts in r/{sub} matching {query!r}. Try different words (lay terms, synonyms, "
                "fewer words) or check the subreddit name with find_subreddits.")
    out = [f"{len(rows)} posts in r/{sub} for {query!r} (sorted by date {sort}; scores of posts <36h old are unreliable):"]
    for r in rows:
        out.append(f"[{r['id']}] {r.get('title', '')} | {date(r.get('created_utc'))} | "
                   f"score {r.get('score')} | {r.get('num_comments')} comments\n"
                   f"  {permalink(sub, r['id'])}")
        body = snippet(r.get("selftext"), 200)
        if body:
            out.append(f"  {body}")
    return "\n".join(out)


def search_comments(subreddit: str, query: str, limit: int = 25, after: str | None = None,
                    before: str | None = None, sort: str = "desc") -> str:
    sub = clean_sub(subreddit)
    rows = api_get("/comments/search", {
        "subreddit": sub, "body": query, "limit": min(max(limit, 1), 100),
        "after": parse_time(after), "before": parse_time(before), "sort": sort,
        "fields": "id,body,link_id,score,created_utc,author",
    })
    if not rows:
        return f"No comments in r/{sub} matching {query!r}. Try other words or search_posts."
    out = [f"{len(rows)} comments in r/{sub} for {query!r}:"]
    for r in rows:
        pid = (r.get("link_id") or "").removeprefix("t3_")
        out.append(f"[{r['id']}] {date(r.get('created_utc'))} | score {r.get('score')} | "
                   f"post {pid} {permalink(sub, pid)}\n  {snippet(r.get('body'), 300)}")
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
