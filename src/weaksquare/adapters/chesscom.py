"""`ChesscomClient` over the shared HTTP client (v0.8, FR-10.7, FR-11.24, FR-11.27, FR-11.32).

chess.com's **Published-Data API only** (`api.chess.com/pub/…`), never the website's internal
"callback" endpoints. **Strictly one request at a time:** a lock serializes every call made through
this client, from any thread, because parallel requests get HTTP 429. The User-Agent is the shared
client's, which names the app and the repo URL as contact (never a personal email). ETags make an
unchanged month cost a 304. A 429 waits (`Retry-After`, else a doubling backoff) and tries again, a few
times; 410 is permanent.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from weaksquare.adapters.http import HttpClient, HttpError, RateLimited
from weaksquare.core.chesscom import API_BASE
from weaksquare.core.games import Archive, ChesscomProfile, valid_username

RATE_LIMIT_TRIES = 4


class ChesscomNotFound(HttpError):
    """HTTP 404: no such player (Verify) or no such archive."""


class ChesscomGone(HttpError):
    """HTTP 410: the resource is permanently gone; never ask for it again."""


class ChesscomGames:
    def __init__(
        self,
        http: HttpClient,
        base: str = API_BASE,
        *,
        sleep: Callable[[float], None] = time.sleep,
        backoff_s: float = 2.0,
    ) -> None:
        self._http = http
        self._base = base.rstrip("/")
        self._lock = threading.Lock()  # FR-10.7: one request at a time, across threads
        self._sleep = sleep
        self._backoff_s = backoff_s

    def _get(self, url: str, etag: str | None = None) -> tuple[int, Any, str | None]:
        if not url.startswith(self._base + "/"):
            raise ValueError("only the Published-Data API is used (FR-11.32)")
        delay = self._backoff_s
        for attempt in range(RATE_LIMIT_TRIES):
            with self._lock:
                try:
                    r = self._http.get_json_cached(url, etag)
                    return r.status, r.data, r.etag
                except RateLimited as e:
                    if attempt == RATE_LIMIT_TRIES - 1:
                        raise
                    wait = e.retry_after_s if e.retry_after_s is not None else delay
                except HttpError as e:
                    if e.status == 404:
                        raise ChesscomNotFound(str(e), status=404, retryable=False) from None
                    if e.status == 410:
                        raise ChesscomGone(str(e), status=410, retryable=False) from None
                    raise
            self._sleep(min(wait, 60.0))  # outside the lock: nothing else is sent meanwhile anyway
            delay *= 2
        raise AssertionError("unreachable")  # pragma: no cover

    def profile(self, username: str) -> ChesscomProfile:
        """FR-11.24's Verify: the public profile, or `ChesscomNotFound`."""
        if not valid_username(username):
            raise ValueError("not a chess.com username")
        _, data, _ = self._get(f"{self._base}/player/{username.lower()}")
        d = data if isinstance(data, dict) else {}
        name = d.get("username")
        return ChesscomProfile(
            username=name if isinstance(name, str) and name else username,
            name=d.get("name") if isinstance(d.get("name"), str) else None,
            url=d.get("url") if isinstance(d.get("url"), str) else None,
            avatar=d.get("avatar") if isinstance(d.get("avatar"), str) else None,
            joined=d.get("joined") if isinstance(d.get("joined"), int) else None,
        )

    def archives(self, username: str) -> list[str]:
        if not valid_username(username):
            raise ValueError("not a chess.com username")
        _, data, _ = self._get(f"{self._base}/player/{username.lower()}/games/archives")
        items = data.get("archives") if isinstance(data, dict) else None
        return [u for u in items if isinstance(u, str)] if isinstance(items, list) else []

    def archive(self, url: str, etag: str | None) -> Archive:
        status, data, new_etag = self._get(url, etag)
        if status == 304:
            return Archive(304, [], etag)
        games = data.get("games") if isinstance(data, dict) else None
        return Archive(status, [g for g in games if isinstance(g, dict)] if isinstance(games, list) else [], new_etag)
