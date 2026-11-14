# reddit-search

Reddit search for research agents. It is an MCP server (stdio) and a CLI. Use it together with web search to find
first-hand experience: fixes, workarounds, recommendations and niche communities. It uses the free
[Arctic Shift](https://github.com/ArthurHeitmann/arctic_shift) archive API. It needs no API key.

## Install / register

You need [uv](https://docs.astral.sh/uv/) and git access to this repository. A private repository needs
`gh auth login` or equivalent git credentials.

Claude Code (one command):

```
claude mcp add reddit-search -- uvx --from git+https://github.com/mattlau1/reddit-search-mcp reddit-search-mcp
```

Other MCP clients (`.mcp.json` or equivalent):

```json
{
  "mcpServers": {
    "reddit-search": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/mattlau1/reddit-search-mcp", "reddit-search-mcp"]
    }
  }
}
```

CLI (no installation):

```
uvx --from git+https://github.com/mattlau1/reddit-search-mcp reddit-search subreddits learnpy
uvx --from git+https://github.com/mattlau1/reddit-search-mcp reddit-search search learnpython "asyncio shutdown" --limit 10 --after 2024-01-01
uvx --from git+https://github.com/mattlau1/reddit-search-mcp reddit-search comments learnpython asyncio --limit 5
uvx --from git+https://github.com/mattlau1/reddit-search-mcp reddit-search thread https://www.reddit.com/r/learnpython/comments/1xprhls/
```

Local development: clone the repository. Then run `uv run reddit-search-mcp` or `uv run reddit-search ...`.
To register the clone, use `uv run --directory /path/to/reddit-search reddit-search-mcp`.

## Tools

- `find_subreddits(name_or_prefix)` - finds subreddits whose name starts with the text. It gives subscribers and description.
- `search_posts(subreddit, query, limit=25, after, before, sort)` - searches titles and text for keywords.
- `search_comments(subreddit, query, limit=25, after, before, sort)` - searches comment bodies for keywords.
- `get_thread(post_id_or_url, max_comments=100)` - returns a post and its comment tree. The tree indents replies.

The server does these steps automatically:

1. It splits the query into words.
2. It adds everyday synonyms from offline WordNet data.
3. It requests candidates for a few query variants.
4. It ranks the candidates locally. Original words rank above synonyms. A result that matches more of the query
   ranks higher. Comment hits on the same thread count as evidence.

Each result lists the words that matched and gives its reddit.com permalink. The server caches responses on disk.
Use short, plain keywords.

## Limits

- Keyword search needs a subreddit. There is no global search. `find_subreddits` matches name prefixes only, not
  topics. Guess names from the topic.
- Matching uses the literal words and their synonyms. It is not semantic.
- Arctic Shift is a free service with one maintainer and no uptime guarantee. Expect timeouts and 429 errors.
  The client retries with backoff, then returns a clear error.
- Scores and comment counts are unreliable for about 36 hours after posting. Archive data may lag.
- Comment search is slow and may time out on busy subreddits. Use `after` and `before` to narrow the search.
- The content is Reddit data. Reddit's terms apply to it.

## Using Arctic Shift responsibly

One person runs Arctic Shift ([Arthur Heitmann](https://github.com/ArthurHeitmann),
[project](https://github.com/ArthurHeitmann/arctic_shift)). Its API docs ask users to "be considerate". For
massive amounts of data, they ask users to use the monthly dumps. Rate limits are dynamic. 429 responses carry
`X-RateLimit-Reset`. By default, this client follows these rules:

- It uses one client for the whole process. It sends at most 2 requests at the same time. It waits at least 0.75 s
  between request starts.
- After a 429 error, a timeout or a "slow down" error, it starts a global cooldown. The cooldown honours
  `Retry-After` and `X-RateLimit-Reset`. The backoff grows after each consecutive failure. It applies to all
  parallel requests.
- It keeps a disk cache (24 h for searches, 6 h for threads). A repeated query costs no requests.
- It sends at most 8 requests for each search call (typically 6-7 with a cold cache, 0 with a warm cache). It
  trims every call with `fields=`. It skips the expansion when the plain query already fills the page.
- It sends an honest `User-Agent` that names this project.

Do not lower these defaults. Do not add parallelism. Credit Arctic Shift and its maintainer when you use
results. For bulk or offline access, download the
[dumps](https://github.com/ArthurHeitmann/arctic_shift/blob/master/download_links.md). Do not use the API.

## Configuration

| Variable | Default | Effect |
| --- | --- | --- |
| `REDDIT_SEARCH_CACHE_DIR` | `$XDG_CACHE_HOME` or `%LOCALAPPDATA%` or `~/.cache`, plus `/reddit-search` | Cache location |
| `REDDIT_SEARCH_NO_CACHE` | unset | Set to `1` to disable the cache |
| `REDDIT_SEARCH_MIN_GAP` | `0.75` | Minimum seconds between request starts. Do not lower it. |

If the server cannot create or write the cache directory, it runs without a cache. To clear the cache, delete the
cache directory.

## Development

- `uv run pytest` runs the offline tests. `uv run pytest -m live` runs the live smoke test against Arctic Shift.
- To rebuild the synonyms, run `scripts/build_synonyms.py`. The output is `src/reddit_search/data/synonyms.json.gz`.
- The synonyms come from Princeton WordNet 3.0, (c) 2006 Princeton University. This project redistributes them under the
  WordNet 3.0 licence (`src/reddit_search/data/WORDNET-LICENSE.txt`).

## Licence

MIT. See `LICENSE`. The bundled WordNet data stays under its own WordNet licence. Arctic Shift's code has no
licence file. This project only calls its public API. It includes none of its code.
