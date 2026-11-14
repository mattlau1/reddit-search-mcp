import pytest

from reddit_search import core


def test_parse_post_id():
    assert core.parse_post_id("abc123") == "abc123"
    assert core.parse_post_id("t3_ABC123") == "abc123"
    assert core.parse_post_id("https://www.reddit.com/r/Foo/comments/abc123/how_do_i/") == "abc123"
    assert core.parse_post_id("https://redd.it/abc123") == "abc123"
    with pytest.raises(core.RedditSearchError):
        core.parse_post_id("not a post!")


def test_clean_sub_and_snippet():
    assert core.clean_sub("r/Python/") == "Python"
    assert core.clean_sub("https://www.reddit.com/r/Python") == "Python"
    assert core.snippet("a  b\n\nc", 50) == "a b c"
    assert core.snippet("x" * 300, 200).endswith("…") and len(core.snippet("x" * 300, 200)) == 200


def test_search_posts_format(monkeypatch):
    rows = [{"id": "abc", "title": "T qq", "created_utc": 1717683184, "score": 3, "num_comments": 2, "selftext": "hello  world"}]
    monkeypatch.setattr(core, "api_get", lambda path, p, retries=2, deadline=None: rows if "posts/search" in path else [])
    out = core.search_posts("r/foo", "qq")
    assert "https://www.reddit.com/r/foo/comments/abc/" in out and "2024-06-06" in out and "hello world" in out


def test_thread_tree(monkeypatch):
    post = [{"id": "p1", "title": "T", "subreddit": "foo", "selftext": "", "score": 1, "num_comments": 2,
             "created_utc": 1717683184, "author": "a"}]
    tree = [{"kind": "t1", "data": {"author": "x", "score": 4, "body": "top", "replies": {"kind": "Listing", "data": {"children": [
        {"kind": "t1", "data": {"author": "y", "score": 1, "body": "child", "replies": ""}}]}}}},
        {"kind": "more", "data": {"count": 5, "children": []}}]
    monkeypatch.setattr(core, "api_get", lambda path, p, **k: post if "posts" in path else tree)
    out = core.get_thread("https://reddit.com/r/foo/comments/p1/t/")
    assert "- u/x (4): top" in out and "  - u/y (1): child" in out and "+5 more" in out


@pytest.mark.live
def test_live_smoke():
    assert "r/" in core.find_subreddits("learnpy")
    assert "[" in core.search_posts("learnpython", "asyncio", limit=3)
    assert "u/" in core.get_thread("1xprhls")
