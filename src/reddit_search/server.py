from mcp.server.fastmcp import FastMCP

from . import core

mcp = FastMCP("reddit-search", instructions=(
    "Reddit search for research. Use it alongside web search whenever user experience matters: fixes for "
    "niche software or hardware problems, workarounds, recommendations, first-hand reports. Web search "
    "rarely surfaces small Reddit threads, so search the relevant subreddit directly."))


def _run(fn, *a, **k) -> str:
    try:
        return fn(*a, **k)
    except core.RedditSearchError as e:
        return f"ERROR: {e}"


@mcp.tool()
def find_subreddits(name_or_prefix: str, limit: int = 15) -> str:
    """Find subreddits whose NAME starts with the given text (not a topic search). Reddit keyword search
    requires a subreddit, so use this first. Guess names from the topic: product/software name, game,
    hobby, no spaces (e.g. 'marvel', 'homeassistant', 'sourdough'). Try several guesses. Returns name,
    subscribers and short description."""
    return _run(core.find_subreddits, name_or_prefix, limit)


@mcp.tool()
def search_posts(subreddit: str, query: str, limit: int = 25, after: str | None = None,
                 before: str | None = None, sort: str = "desc") -> str:
    """Keyword search of post titles+text in ONE subreddit (subreddit is required; there is no
    site-wide search). Every word in the query must appear, so keep queries to 1-2 words and run many
    of them: 'wifi keeps dropping' misses a post titled 'my wifi drops'. Many posts are screenshots with
    vague titles ('this weird thing', 'help pls') and no text, so try the plainest single nouns too, plus
    synonyms and the technical terms an expert would use. Search comments as well: answers use precise
    terms. after/before are dates like 2024-01-31; sort is 'desc' (newest) or 'asc'. Results are
    snippets: call get_thread on promising ids to read the actual answers."""
    return _run(core.search_posts, subreddit, query, limit, after, before, sort)


@mcp.tool()
def search_comments(subreddit: str, query: str, limit: int = 25, after: str | None = None,
                    before: str | None = None, sort: str = "desc") -> str:
    """Keyword search of comment bodies in ONE subreddit (required). Every word must appear: keep queries to 1-2 words
    and try several, including the technical terms people answering would use. Good for finding recommendations or fixes buried in threads. Each hit shows the parent post
    id; use get_thread to read the surrounding discussion. May time out on very busy subreddits: narrow
    with after/before."""
    return _run(core.search_comments, subreddit, query, limit, after, before, sort)


@mcp.tool()
def get_thread(post_id_or_url: str, max_comments: int = 100) -> str:
    """Fetch a post and its comment tree (indented, trimmed). Accepts a reddit URL or post id. Read
    threads to get real answers; search snippets are not enough. Scores/comment counts are unreliable for
    ~36h after posting."""
    return _run(core.get_thread, post_id_or_url, max_comments)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
