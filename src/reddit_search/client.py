"""Polite, process-wide Arctic Shift client.

Arctic Shift is a free service run by one person. This client:
- shares ONE connection pool per process, with at most MAX_INFLIGHT requests in flight;
- keeps a minimum gap between request starts (REDDIT_SEARCH_MIN_GAP seconds, default 0.75);
- enforces a global cooldown on 429 / timeout / "slow down" errors (honours Retry-After and
  X-RateLimit-Reset), so parallel callers never keep hammering a struggling server;
- caches successful responses on disk (24h for searches, 6h for threads) so repeats cost nothing.
Env: REDDIT_SEARCH_MIN_GAP, REDDIT_SEARCH_CACHE_DIR, REDDIT_SEARCH_NO_CACHE=1.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path

import httpx

BASE = "https://arctic-shift.photon-reddit.com/api"
PROJECT_URL = "https://github.com/mattlau1/reddit-search-mcp"
MAX_INFLIGHT = 2
DEFAULT_MIN_GAP = 0.75
RETRY_STATUS = {429, 500, 502, 503, 504}
SEARCH_TTL = 24 * 3600
THREAD_TTL = 6 * 3600
MAX_COOLDOWN = 60.0


class RedditSearchError(Exception):
    """Error with a message written for the calling agent."""


def _version() -> str:
    try:
        from importlib.metadata import version
        return version("reddit-search-mcp")
    except Exception:
        return "dev"


def user_agent() -> str:
    return f"reddit-search/{_version()} (+{PROJECT_URL})"


def default_cache_dir() -> Path:
    if os.environ.get("REDDIT_SEARCH_CACHE_DIR"):
        return Path(os.environ["REDDIT_SEARCH_CACHE_DIR"])
    base = os.environ.get("XDG_CACHE_HOME") or os.environ.get("LOCALAPPDATA") or str(Path.home() / ".cache")
    return Path(base) / "reddit-search"


def _ttl(path: str) -> int:
    return THREAD_TTL if path.startswith(("/comments/tree", "/posts/ids")) else SEARCH_TTL


class ApiClient:
    def __init__(self, http: httpx.Client | None = None, min_gap: float | None = None,
                 cache_dir: Path | None | bool = True, base: str = BASE):
        self._http = http
        self.base = base
        if min_gap is None:
            try:
                min_gap = float(os.environ.get("REDDIT_SEARCH_MIN_GAP", DEFAULT_MIN_GAP))
            except ValueError:
                min_gap = DEFAULT_MIN_GAP
        self.min_gap = max(0.0, min_gap)
        if cache_dir is True:
            try:
                cache_dir = None if os.environ.get("REDDIT_SEARCH_NO_CACHE") else default_cache_dir()
            except (RuntimeError, KeyError, OSError):  # no resolvable home: run without a cache
                cache_dir = None
        self.cache_dir = cache_dir or None
        self._sem = threading.Semaphore(MAX_INFLIGHT)
        self._lock = threading.Lock()
        self._next_start = 0.0
        self._cool_until = 0.0
        self._fails = 0
        self.requests_made = 0  # network requests (cache misses), for reporting/tests

    # ----- cache -----
    def _cache_path(self, path: str, params: dict) -> Path | None:
        if not self.cache_dir:
            return None
        key = hashlib.sha256(json.dumps([path, sorted(params.items())], default=str).encode()).hexdigest()
        return self.cache_dir / key[:2] / f"{key}.json"

    def _cache_read(self, p: Path | None, ttl: int):
        if p is None:
            return None
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
            if time.time() - doc["t"] <= ttl:
                return doc
        except (OSError, ValueError, KeyError):
            pass
        return None

    def _cache_write(self, p: Path | None, data) -> None:
        if p is None:
            return
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
            tmp.write_text(json.dumps({"t": time.time(), "data": data}), encoding="utf-8")
            os.replace(tmp, p)
        except OSError:
            pass  # cache is best effort

    # ----- throttle -----
    def _cooldown(self, seconds: float) -> None:
        with self._lock:
            self._cool_until = max(self._cool_until, time.monotonic() + min(max(seconds, 0.0), MAX_COOLDOWN))

    def _wait_turn(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                start = max(now, self._next_start, self._cool_until)
                if start <= now:
                    self._next_start = now + self.min_gap
                    return
            time.sleep(min(start - now, MAX_COOLDOWN))

    def _client(self) -> httpx.Client:
        if self._http is None:
            self._http = httpx.Client(timeout=20, headers={"User-Agent": user_agent()})
        return self._http

    # ----- request -----
    def get(self, path: str, params: dict, retries: int = 2, deadline: float | None = None):
        params = {k: v for k, v in params.items() if v is not None and v != ""}
        cp = self._cache_path(path, params)
        hit = self._cache_read(cp, _ttl(path))
        if hit is not None:
            return hit["data"]
        last = "unknown error"
        for attempt in range(retries + 1):
            if deadline is not None and max(self._cool_until, time.monotonic()) > deadline:
                last = f"{last}. The client stopped to stay within the time budget"
                break
            with self._sem:
                self._wait_turn()
                self.requests_made += 1
                try:
                    r = self._client().get(self.base + path, params=params)
                except httpx.TransportError as e:
                    r = None
                    last = f"network error: {type(e).__name__}"
            if r is None:
                self._fail(None, 2.0)
                continue
            body = None
            try:
                body = r.json()
            except ValueError:
                pass
            err = body.get("error") if isinstance(body, dict) else None
            reset = self._reset_seconds(r) if r.status_code == 429 else 0.0
            if r.status_code == 200 and not err:
                with self._lock:
                    self._fails = 0
                remaining = r.headers.get("X-RateLimit-Remaining")
                if remaining is not None and remaining.strip() == "0":
                    self._cooldown(self._reset_seconds(r))
                data = body["data"] if isinstance(body, dict) and "data" in body else body
                self._cache_write(cp, data)
                return data
            last = f"HTTP {r.status_code}: {err or r.text[:120]}"
            slow = bool(err and ("imeout" in err or "timed out" in err or "slow down" in err))
            if r.status_code == 429:
                self._fail(r, reset or 5.0)
            elif r.status_code in RETRY_STATUS or slow:
                self._fail(r, 2.0)
            else:
                raise RedditSearchError(f"Arctic Shift rejected the request ({last}).")
        raise RedditSearchError(
            f"Arctic Shift unavailable ({last}). It is a free service with one maintainer. "
            "Busy subreddits time out on keyword search. Retry later, narrow the search with after and before, "
            "or use a more specific query.")

    @staticmethod
    def _reset_seconds(r: httpx.Response) -> float:
        for h in ("Retry-After", "X-RateLimit-Reset"):
            try:
                v = float(r.headers.get(h, ""))
            except ValueError:
                continue
            if v > 0:
                return v
        return 0.0

    def _fail(self, r, base_wait: float) -> None:
        """Global cooldown: escalates with consecutive failures; honours server-provided reset times."""
        with self._lock:
            self._fails += 1
            n = self._fails
        wait = base_wait * (2 ** min(n - 1, 3))
        if r is not None and r.status_code == 429:  # the reset header is only meaningful on a 429
            wait = max(wait, self._reset_seconds(r))
        self._cooldown(wait)

    def close(self) -> None:
        if self._http is not None:
            self._http.close()
            self._http = None


_default: ApiClient | None = None
_default_lock = threading.Lock()


def default_client() -> ApiClient:
    global _default
    with _default_lock:
        if _default is None:
            _default = ApiClient()
        return _default
