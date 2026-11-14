# reddit-search

MCP server (stdio) and CLI that give research agents Reddit access, the way they have web search. A thin
wrapper over the free [Arctic Shift](https://github.com/ArthurHeitmann/arctic_shift) archive API. No API key.
Callers need no search tricks: the server splits the query into words, adds everyday synonyms (offline
WordNet data), fetches candidates for a few variants and ranks them locally (original words beat synonyms,
covering more of the query beats covering less, comment hits on the same thread count as evidence). Each
result says which words matched.

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
- Matching is literal words plus WordNet synonyms, not semantic. Posts that are only a screenshot with a vague
  title are found through comment evidence, not their (missing) text.
- Free single-maintainer service with no uptime guarantee; busy subreddits can time out. The client retries
  with backoff and honours Retry-After, then returns a clear error.
- Scores and comment counts are unreliable for about 36 hours after posting. Archive data may lag.
- Content is Reddit data and subject to Reddit's terms. Arctic Shift's code has no licence file; this project
  only calls its public API and includes none of its code.

## Using Arctic Shift responsibly

Arctic Shift is a free service run by one person ([Arthur Heitmann](https://github.com/ArthurHeitmann),
[project](https://github.com/ArthurHeitmann/arctic_shift)). Its API docs ask users to "be considerate" and,
for massive amounts of data, to use the monthly dumps instead; rate limits are dynamic and 429 responses
carry `X-RateLimit-Reset`. This client follows that by default:

- one process-wide client, at most 2 requests in flight, at least 0.75 s between request starts
  (`REDDIT_SEARCH_MIN_GAP`);
- a global cooldown on 429, timeout or "slow down" errors, honouring `Retry-After` / `X-RateLimit-Reset`;
  backoff grows with consecutive failures and applies to all parallel requests;
- responses are cached on disk (24 h for searches, 6 h for threads) in `~/.cache/reddit-search`
  (`REDDIT_SEARCH_CACHE_DIR`, `REDDIT_SEARCH_NO_CACHE=1` to disable), so repeated queries cost nothing;
- at most 8 requests per search call (typically 6-7 cold, 0 warm), `fields=` trimming on every call, and the
  expansion is skipped when the plain query already fills the page;
- an honest `User-Agent` naming this project.

Please do not lower these defaults or add parallelism. If you need bulk or offline access, download the
[dumps](https://github.com/ArthurHeitmann/arctic_shift/blob/master/download_links.md) instead of hitting the API.

Synonyms come from Princeton WordNet 3.0 (`src/reddit_search/data/synonyms.json.gz`, built by
`scripts/build_synonyms.py`). WordNet is (c) 2006 Princeton University and is used under the WordNet 3.0
licence, which permits redistribution with its notice; the full text is in `src/reddit_search/data/WORDNET-LICENSE.txt`.

## Tests

`uv run pytest` (offline). Live smoke test: `uv run pytest -m live`.
