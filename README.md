# reddit-search

MCP server (stdio) and CLI that give research agents Reddit access, the way they have web search. A thin
wrapper over the free [Arctic Shift](https://github.com/ArthurHeitmann/arctic_shift) archive API. No API key.
No query expansion: the calling agent rephrases queries itself.

## Tools

- `find_subreddits(name_or_prefix)` - subreddits whose name starts with the text (subscribers, description).
- `search_posts(subreddit, query, limit=25, after, before, sort)` - keyword search of titles and text.
- `search_comments(subreddit, query, limit=25, after, before, sort)` - keyword search of comment bodies.
- `get_thread(post_id_or_url, max_comments=100)` - post plus indented comment tree.

Every post carries its reddit.com permalink.

## Register

`.mcp.json`:

```json
{
  "mcpServers": {
    "reddit-search": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/reddit-search", "reddit-search-mcp"]
    }
  }
}
```

Or: `claude mcp add reddit-search -- uv run --directory /path/to/reddit-search reddit-search-mcp`

## CLI

```
uv run reddit-search subreddits learnpy
uv run reddit-search search learnpython "asyncio shutdown" --limit 10 --after 2024-01-01
uv run reddit-search comments learnpython asyncio --limit 5
uv run reddit-search thread https://www.reddit.com/r/learnpython/comments/1xprhls/
```

## Limits

- Keyword search needs a subreddit; there is no global search. Subreddit discovery is by name prefix only
  (no topic or description search), so agents must guess names.
- Matching is literal words, not semantic.
- Free single-maintainer service with no uptime guarantee; busy subreddits can time out. The client retries
  with backoff and honours Retry-After, then returns a clear error.
- Scores and comment counts are unreliable for about 36 hours after posting. Archive data may lag.
- Content is Reddit data and subject to Reddit's terms. Arctic Shift's code has no licence file; this project
  only calls its public API and includes none of its code.

## Tests

`uv run pytest` (offline). Live smoke test: `uv run pytest -m live`.
