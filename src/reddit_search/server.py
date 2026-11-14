from mcp.server.fastmcp import FastMCP

from . import core

mcp = FastMCP("reddit-search", instructions=(
    "Reddit search for first-hand experience: user-reported fixes, workarounds and recommendations for "
    "niche software, hardware and hobbies. Pass plain words; synonyms and ranking are handled for you."))


def _run(fn, *a, **k) -> str:
    try:
        return fn(*a, **k)
    except core.RedditSearchError as e:
        return f"ERROR: {e}"
    except Exception as e:  # never leak a traceback to the agent
        return f"ERROR: unexpected {type(e).__name__}: {e}. Retry, or report this if it persists."


@mcp.tool()
def find_subreddits(name_or_prefix: str, limit: int = 15) -> str:
    """Find subreddits whose NAME starts with the text (not a topic search); guess names from the topic."""
    return _run(core.find_subreddits, name_or_prefix, limit)


@mcp.tool()
def search_posts(subreddit: str, query: str, limit: int = 25, after: str | None = None,
                 before: str | None = None, sort: str = "desc") -> str:
    """Search post titles and text in one subreddit (required). Broadens with synonyms and ranks best first."""
    return _run(core.search_posts, subreddit, query, limit, after, before, sort)


@mcp.tool()
def search_comments(subreddit: str, query: str, limit: int = 25, after: str | None = None,
                    before: str | None = None, sort: str = "desc") -> str:
    """Search comment bodies in one subreddit (required). Broadens with synonyms; hits show the parent post id."""
    return _run(core.search_comments, subreddit, query, limit, after, before, sort)


@mcp.tool()
def get_thread(post_id_or_url: str, max_comments: int = 100) -> str:
    """Fetch a post and its comment tree by reddit URL or post id. Read this for the actual answers."""
    return _run(core.get_thread, post_id_or_url, max_comments)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
