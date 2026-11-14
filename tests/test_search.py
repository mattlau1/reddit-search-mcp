import httpx
import pytest

from reddit_search import client as cl
from reddit_search import core, expand


def test_content_words_and_stem():
    assert expand.content_words("How do I fix a crash in my laptop?") == ["fix", "crash", "laptop"]
    assert expand.stem("crashes") == expand.stem("crashed") == expand.stem("crash")
    assert expand.stem("laptops") == expand.stem("laptop")


def test_synonym_expansion_is_capped_and_single_word():
    (c,) = expand.build_concepts("crash")
    assert 0 < len(c.syns) <= expand.MAX_SYNS_PER_WORD
    assert "wreck" in c.syns and "clash" in c.syns
    assert "collapse" not in c.syns  # loose side meaning, not a shipped synonym
    assert all(s.isalpha() for s in c.syns)
    # plural / inflected query words still find synonyms
    assert expand.build_concepts("crashes")[0].syns


def test_matched_terms_are_deduplicated_in_order():
    cs = expand.build_concepts("crash crash")
    _, matched = expand.score_text(cs, "A crash here", "")
    assert matched == ["crash"]


def test_unknown_word_has_no_synonyms_but_is_kept():
    (c,) = expand.build_concepts("learnpythonxyz")
    assert c.word == "learnpythonxyz" and c.syns == []


def test_plan_priorities_and_budget():
    cs = expand.build_concepts("crash laptop")
    plan = expand.plan_post_queries(cs, 6)
    assert plan[0] == "crash laptop" and plan[1:3] == ["crash", "laptop"]
    assert any(q.endswith(" laptop") and not q.startswith("crash") for q in plan)  # synonym x other concept
    assert len(plan) == len(set(plan)) <= 6
    assert expand.plan_post_queries(cs, 0) == []
    single = expand.plan_post_queries(expand.build_concepts("crash"), 6)
    assert single[0] == "crash" and len(single) == 6


def test_comment_or_query():
    q = expand.comment_or_query(expand.build_concepts("crash laptop"))
    assert q.startswith("crash OR laptop OR ") and q.count(" OR ") <= 7


def test_ranking_prefers_originals_coverage_and_comment_evidence():
    cs = expand.build_concepts("crash laptop")
    posts = {
        "a": {"id": "a", "title": "crash in my browser", "selftext": "", "num_comments": 0},
        "b": {"id": "b", "title": "How do i fix this wreck on my laptop ?", "selftext": "", "num_comments": 3},
        "c": {"id": "c", "title": "unrelated keyboard question", "selftext": "", "num_comments": 9},
    }
    ranked = expand.rank_posts(cs, posts, {})
    assert [p["id"] for _, _, p in ranked] == ["b", "a"]  # covers both concepts; c has no match
    assert ranked[0][1] == ["wreck", "laptop"]
    # comment evidence lifts a weaker thread
    cs1 = expand.build_concepts("crash")
    posts = {"a": {"id": "a", "title": "crash here", "selftext": "", "num_comments": 0},
             "b": {"id": "b", "title": "my wreck problem", "selftext": "", "num_comments": 1}}
    base = expand.rank_posts(cs1, posts, {})
    assert base[0][2]["id"] == "a"
    boosted = expand.rank_posts(cs1, posts, {"b": ["update the driver, the crash goes away", "ram", "clash", "clang"]})
    assert boosted[0][2]["id"] == "b"


def _fake_api(rows_by_query, calls):
    def fake(path, params, retries=2, deadline=None):
        calls.append((path, params))
        if path == "/comments/search":
            return []
        if path == "/posts/ids":
            return []
        return rows_by_query.get(params["query"], [])
    return fake


def test_search_posts_finds_synonym_only_thread_and_respects_budget(monkeypatch):
    target = {"id": "t1", "title": "How do i fix this wreck on my laptop ?", "selftext": "", "num_comments": 4,
              "created_utc": 1717683184, "score": 5}
    other = {"id": "o1", "title": "tips for laptop patterns", "selftext": "", "num_comments": 1,
             "created_utc": 1717683184, "score": 1}
    calls = []
    monkeypatch.setattr(core, "api_get", _fake_api({"laptop": [other], "wreck laptop": [target]}, calls))
    out = core.search_posts("learnpython", "crash laptop", limit=5)
    assert out.index("[t1]") < out.index("[o1]")
    assert "matched: wreck, laptop" in out
    assert len(calls) <= core.MAX_REQUESTS


def test_strong_exact_hit_skips_expansion(monkeypatch):
    rows = [{"id": f"p{i}", "title": "crash laptop", "selftext": "", "num_comments": 1, "created_utc": 1}
            for i in range(5)]
    calls = []
    monkeypatch.setattr(core, "api_get", _fake_api({"crash laptop": rows, "crash": rows[:1]}, calls))
    out = core.search_posts("x", "crash laptop", limit=5)
    assert out.count("[p") == 5 and len(calls) == 2  # phrase + first single word, nothing more


def test_all_requests_failing_raises(monkeypatch):
    def boom(*a, **k):
        raise core.RedditSearchError("down")
    monkeypatch.setattr(core, "api_get", boom)
    with pytest.raises(core.RedditSearchError):
        core.search_posts("x", "crash")


# ---------- client ----------

def _client(handler, tmp_path=None, **k):
    return cl.ApiClient(http=httpx.Client(transport=httpx.MockTransport(handler)), min_gap=0,
                        cache_dir=tmp_path, **k)


def test_cache_hit_costs_no_request(tmp_path):
    n = []
    def h(req):
        n.append(1)
        return httpx.Response(200, json={"data": [{"id": "a"}]})
    c = _client(h, tmp_path)
    assert c.get("/posts/search", {"query": "x"}) == [{"id": "a"}]
    assert c.get("/posts/search", {"query": "x"}) == [{"id": "a"}]
    assert len(n) == 1
    c.get("/posts/search", {"query": "y"})
    assert len(n) == 2


def test_cache_expires(tmp_path, monkeypatch):
    n = []
    def h(req):
        n.append(1)
        return httpx.Response(200, json={"data": []})
    c = _client(h, tmp_path)
    c.get("/posts/search", {"query": "x"})
    real = cl.time.time
    monkeypatch.setattr(cl.time, "time", lambda: real() + cl.SEARCH_TTL + 5)
    c.get("/posts/search", {"query": "x"})
    assert len(n) == 2


def test_429_sets_global_cooldown_and_honours_retry_after(monkeypatch):
    sleeps = []
    monkeypatch.setattr(cl.time, "sleep", lambda s: sleeps.append(s))
    t = httpx.MockTransport(lambda req: httpx.Response(429, headers={"Retry-After": "7"}, json={"data": None, "error": "slow"}))
    c = cl.ApiClient(http=httpx.Client(transport=t), min_gap=0, cache_dir=None)
    with pytest.raises(cl.RedditSearchError, match="unavailable"):
        c.get("/x", {}, retries=2)
    assert c.requests_made == 3
    assert sleeps and max(sleeps) >= 6.5  # waited for the Retry-After cooldown before retrying


def test_timeout_message_is_retried_then_succeeds(monkeypatch):
    monkeypatch.setattr(cl.time, "sleep", lambda s: None)
    seq = iter([httpx.Response(200, json={"data": None, "error": "Timeout. Maybe slow down a bit"}),
                httpx.Response(200, json={"data": [1]})])
    c = cl.ApiClient(http=httpx.Client(transport=httpx.MockTransport(lambda r: next(seq))), min_gap=0, cache_dir=None)
    assert c.get("/x", {}) == [1]


def test_min_gap_spaces_requests(monkeypatch):
    sleeps = []
    monkeypatch.setattr(cl.time, "sleep", lambda s: sleeps.append(s))
    t = httpx.MockTransport(lambda r: httpx.Response(200, json={"data": []}))
    c = cl.ApiClient(http=httpx.Client(transport=t), min_gap=0.75, cache_dir=None)
    c.get("/a", {}); c.get("/b", {})
    assert sleeps and 0.3 < sleeps[0] <= 0.75


def test_user_agent_is_honest():
    ua = cl.user_agent()
    assert ua.startswith("reddit-search/") and "github.com/mattlau1/reddit-search-mcp" in ua and "@" not in ua


def test_deadline_stops_waiting_on_cooldown(monkeypatch):
    sleeps = []
    monkeypatch.setattr(cl.time, "sleep", lambda s: sleeps.append(s))
    t = httpx.MockTransport(lambda req: httpx.Response(429, headers={"Retry-After": "50"}, json={"data": None, "error": "slow"}))
    c = cl.ApiClient(http=httpx.Client(transport=t), min_gap=0, cache_dir=None)
    with pytest.raises(cl.RedditSearchError, match="time budget"):
        c.get("/x", {}, retries=3, deadline=cl.time.monotonic() + 10)
    assert c.requests_made == 1 and not sleeps
