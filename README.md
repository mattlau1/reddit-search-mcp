# reddit-search

Reddit search for research agents: an MCP server (stdio) and CLI, to use alongside web search for first-hand
experience (fixes, workarounds, recommendations, niche communities). Backed by the free
[Arctic Shift](https://github.com/ArthurHeitmann/arctic_shift) archive API. No API key.

## Install / register

Needs [uv](https://docs.astral.sh/uv/) and git access to this repo (private repos need `gh auth login` or
equivalent git credentials).

Claude Code, one line:

```
claude mcp add reddit-search -- uvx --from git+https://github.com/mattlau1/reddit-search reddit-search-mcp
```

Any other MCP client (`.mcp.json` or equivalent):

```json
{
  "mcpServers": {
    "reddit-search": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/mattlau1/reddit-search", "reddit-search-mcp"]
    }
  }
}
```

CLI without installing:

```
uvx --from git+https://github.com/mattlau1/reddit-search reddit-search subreddits learnpy
uvx --from git+https://github.com/mattlau1/reddit-search reddit-search search learnpython "asyncio shutdown" --limit 10 --after 2024-01-01
uvx --from git+https://github.com/mattlau1/reddit-search reddit-search comments learnpython asyncio --limit 5
uvx --from git+https://github.com/mattlau1/reddit-search reddit-search thread https://www.reddit.com/r/learnpython/comments/1xprhls/
```

Local development form: clone, then `uv run reddit-search-mcp` (register with
`uv run --directory /path/to/reddit-search reddit-search-mcp`) or `uv run reddit-search ...`.

## Tools

- `find_subreddits(name_or_prefix)` - subreddits whose name starts with the text (subscribers, description).
- `search_posts(subreddit, query, limit=25, after, before, sort)` - keyword search of titles and text.
- `search_comments(subreddit, query, limit=25, after, before, sort)` - keyword search of comment bodies.
- `get_thread(post_id_or_url, max_comments=100)` - post plus indented comment tree.

Automatic, so callers need not coach queries: the query is split into words, everyday synonyms are added
(offline WordNet data), candidates are fetched for a few variants and ranked locally (original words beat
synonyms, covering more of the query beats less, comment hits on the same thread count as evidence). Each
result says which words matched and carries its reddit.com permalink. Responses are cached on disk.
Pass short plain keywords.

## Limits

- A subreddit is required for keyword search; there is no global search. Use `find_subreddits` (name prefix
  only, not topic search) and guess names from the topic.
- Matching is literal words plus synonyms, not semantic.
- Arctic Shift is a free single-maintainer service with no uptime guarantee: expect timeouts and 429s. The
  client retries with backoff, then returns a clear error.
- Scores and comment counts are unreliable for about 36 hours after posting; archive data may lag.
- Comment search is slow and may time out on busy subreddits: narrow with `after`/`before`.
- Content is Reddit data and subject to Reddit's terms.

## Using Arctic Shift responsibly

Arctic Shift is a free service run by one person ([Arthur Heitmann](https://github.com/ArthurHeitmann),
[project](https://github.com/ArthurHeitmann/arctic_shift)). Its API docs ask users to "be considerate" and,
for massive amounts of data, to use the monthly dumps instead; rate limits are dynamic and 429 responses
carry `X-RateLimit-Reset`. This client follows that by default:

- one process-wide client, at most 2 requests in flight, at least 0.75 s between request starts;
- a global cooldown on 429, timeout or "slow down" errors, honouring `Retry-After` / `X-RateLimit-Reset`,
  with backoff that grows on consecutive failures and applies to all parallel requests;
- disk cache (24 h for searches, 6 h for threads), so repeated queries cost nothing;
- at most 8 requests per search call (typically 6-7 cold, 0 warm), `fields=` trimming on every call, and
  the expansion is skipped when the plain query already fills the page;
- an honest `User-Agent` naming this project.

Please do not lower these defaults or add parallelism. Credit Arctic Shift and its maintainer when you use
results. For bulk or offline access, download the
[dumps](https://github.com/ArthurHeitmann/arctic_shift/blob/master/download_links.md) instead of hitting the API.

## Configuration

| Variable | Default | Effect |
| --- | --- | --- |
| `REDDIT_SEARCH_CACHE_DIR` | `$XDG_CACHE_HOME` or `%LOCALAPPDATA%` or `~/.cache`, plus `/reddit-search` | cache location |
| `REDDIT_SEARCH_NO_CACHE` | unset | set to `1` to disable the cache |
| `REDDIT_SEARCH_MIN_GAP` | `0.75` | minimum seconds between request starts (do not lower) |

If the cache directory cannot be created or written, the server runs without a cache. To clear the cache,
delete the cache directory.

## Development

- `uv run pytest` runs the offline tests; `uv run pytest -m live` runs the live smoke test against Arctic Shift.
- Rebuild synonyms with `scripts/build_synonyms.py` (output: `src/reddit_search/data/synonyms.json.gz`).
- Synonyms come from Princeton WordNet 3.0, (c) 2006 Princeton University, redistributed under the WordNet 3.0
  licence (`src/reddit_search/data/WORDNET-LICENSE.txt`).

## Licence

MIT, see `LICENSE`. The bundled WordNet data stays under its own WordNet licence. Arctic Shift's code has no
licence file; this project only calls its public API and includes none of its code.
