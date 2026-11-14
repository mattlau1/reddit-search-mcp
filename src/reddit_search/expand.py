"""Offline query broadening and local ranking.

Arctic Shift post search is an AND of exact words, so one unlucky word misses a thread. We split the query
into content words ("concepts"), add everyday WordNet synonyms for each (data/synonyms.json.gz, built by
scripts/build_synonyms.py from Princeton WordNet 3.0), fetch candidates for a few of those variants, then
rank the union locally: original words beat synonyms, matching more distinct concepts beats matching one,
and comment hits on the same thread add evidence.
"""
from __future__ import annotations

import gzip
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources

STOPWORDS = frozenset("""
a about above after again all also am an and any are as at be because been before being below between both
but by can could did do does doing down during each few for from further had has have having he her here hers
him his how i if in into is it its just me more most my no nor not of off on once only or other our out over
own same she should so some such than that the their them then there these they this those through to too
under until up very was we were what when where which while who whom why will with would you your yours
anyone anything someone something thing things get got getting im ive dont cant wont
""".split())

MAX_SYNS_PER_WORD = 5
MAX_CONCEPTS = 4
ORIGINAL_W = 1.0
SYN_W = 0.55


@lru_cache(maxsize=1)
def _table() -> dict[str, list[str]]:
    with resources.files("reddit_search").joinpath("data/synonyms.json.gz").open("rb") as f:
        return json.loads(gzip.decompress(f.read()))


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def stem(w: str) -> str:
    """Crude, symmetric stemmer used only for matching (applied to both query and text)."""
    if len(w) > 4 and w.endswith("ies"):
        w = w[:-3] + "y"
    elif len(w) > 4 and w.endswith(("sses", "xes", "zes", "ches", "shes")):
        w = w[:-2]
    elif len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        w = w[:-1]
    if len(w) > 5 and w.endswith("ing"):
        w = w[:-3]
    elif len(w) > 4 and w.endswith("ed"):
        w = w[:-2]
    if len(w) > 3 and w[-1] == w[-2] and w[-1] not in "lsz":
        w = w[:-1]
    return w.rstrip("e") if len(w) > 3 else w


def _lookup(word: str) -> list[str]:
    t = _table()
    cands = [word]
    if word.endswith("ies"):
        cands.append(word[:-3] + "y")
    for suf in ("es", "s", "ing", "ed", "d"):
        if word.endswith(suf) and len(word) > len(suf) + 2:
            base = word[: -len(suf)]
            cands += [base, base + "e"]
            if len(base) > 2 and base[-1] == base[-2]:
                cands.append(base[:-1])
    for c in cands:
        if c in t:
            return t[c]
    return []


def content_words(query: str) -> list[str]:
    seen, out = set(), []
    for w in tokens(query):
        if w in STOPWORDS or (len(w) < 2 and not w.isdigit()) or w in seen:
            continue
        seen.add(w)
        out.append(w)
    return out


@dataclass
class Concept:
    word: str
    syns: list[str] = field(default_factory=list)

    def terms(self):
        yield self.word, ORIGINAL_W
        for s in self.syns:
            yield s, SYN_W


def build_concepts(query: str) -> list[Concept]:
    words = content_words(query)[:MAX_CONCEPTS]
    originals = {stem(w) for w in words}
    out = []
    for w in words:
        syns, seen = [], set()
        for s in _lookup(w):
            if stem(s) in originals or stem(s) in seen or s == w:
                continue
            seen.add(stem(s))
            syns.append(s)
            if len(syns) >= MAX_SYNS_PER_WORD:
                break
        out.append(Concept(w, syns))
    return out


# ---------- request planning ----------

def plan_post_queries(concepts: list[Concept], budget: int) -> list[str]:
    """Ordered, deduplicated AND-queries for the posts endpoint (which has no OR)."""
    if not concepts or budget <= 0:
        return []
    words = [c.word for c in concepts]
    plan: list[str] = []

    def add(q: str):
        if q not in plan:
            plan.append(q)

    if len(words) > 1:
        add(" ".join(words))
    for w in words[:3]:
        add(w)
    # synonym variants, nearest first, rotating across concepts; keep the other concepts' words so a
    # synonym of one concept is checked against the rest of the query before spending a bare lookup
    for rank in range(MAX_SYNS_PER_WORD):
        for i, c in enumerate(concepts):
            if rank < len(c.syns) and len(words) > 1:
                others = [w for j, w in enumerate(words) if j != i]
                add(" ".join([c.syns[rank]] + others))
    for rank in range(MAX_SYNS_PER_WORD):
        for c in concepts:
            if rank < len(c.syns):
                add(c.syns[rank])
    return plan[:budget]


def comment_or_query(concepts: list[Concept], max_terms: int = 8) -> str:
    """One websearch-syntax OR query for the comments endpoint: originals first, then top synonyms."""
    terms: list[str] = []
    for rank in range(MAX_SYNS_PER_WORD + 1):
        for c in concepts:
            ts = [c.word] + c.syns
            if rank < len(ts) and ts[rank] not in terms:
                terms.append(ts[rank])
    return " OR ".join(terms[:max_terms])


# ---------- ranking ----------

def _stems(text: str) -> set[str]:
    return {stem(t) for t in tokens(text)}


def concept_hits(concept: Concept, title_stems: set[str], body_stems: set[str]) -> tuple[float, str | None]:
    best, term_used = 0.0, None
    for term, w in concept.terms():
        st = stem(term)
        for stems, where in ((title_stems, 1.0), (body_stems, 0.7)):
            if st in stems and w * where > best:
                best, term_used = w * where, term
    return best, term_used


def score_text(concepts: list[Concept], title: str, body: str = "") -> tuple[float, list[str]]:
    ts, bs = _stems(title), _stems(body)
    total, matched, n = 0.0, [], 0
    for c in concepts:
        s, term = concept_hits(c, ts, bs)
        if term:
            total += s
            n += 1
            if term not in matched:
                matched.append(term)
    if len(concepts) > 1 and n == len(concepts):
        total += 1.0  # covers every concept of the query
    return total, matched


def comment_evidence(concepts: list[Concept], bodies: list[str]) -> float:
    """0..1: how much the comments on a thread talk about the query. Distinct matched terms count (an
    original word fully, each synonym a third), so a thread whose comments use several variants of the
    concept beats one that mentions a single common synonym in passing."""
    seen: set[tuple[int, str]] = set()
    stems = [_stems(b) for b in bodies]
    for i, c in enumerate(concepts):
        for term, w in c.terms():
            if any(stem(term) in bs for bs in stems):
                seen.add((i, term))
    originals = {i for i, c in enumerate(concepts) if (i, c.word) in seen}
    synonyms = sum(1 for i, t in seen if t != concepts[i].word)
    total = len(originals) + min(synonyms, 3 * len(concepts)) / 3
    return min(1.0, total / max(len(concepts), 1))


def rank_posts(concepts: list[Concept], posts: dict[str, dict], comments_by_post: dict[str, list[str]]):
    """Return [(score, matched_terms, post)] best first."""
    ranked = []
    for pid, p in posts.items():
        s, matched = score_text(concepts, p.get("title") or "", p.get("selftext") or "")
        ev = comment_evidence(concepts, comments_by_post.get(pid, [])) if comments_by_post.get(pid) else 0.0
        s += 0.4 * ev
        nc = p.get("num_comments") or 0
        s += 0.15 if nc > 0 else 0.0
        s += 0.1 if nc >= 5 else 0.0
        if s <= 0.3 and not matched:
            continue
        ranked.append((s, matched, p))
    ranked.sort(key=lambda x: (-x[0], -(x[2].get("created_utc") or 0)))
    return ranked
