"""Import your Lichess puzzle history (FR-6.17): GET /api/puzzle/activity, incrementally with `since`.

It feeds the "exclude played on Lichess" filter (FR-3.9) and the "already played" badge. The table
is a cache for the signed-in account: it's cleared when a different account signs in. The next
`since` is saved only after the stream completes, and the upsert is idempotent, so a broken
import simply runs again from the old point.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from weaksquare.core.lichess import LichessClient
from weaksquare.jobs.runner import CancelToken, JobFailed, JobRunner, ProgressFn

log = logging.getLogger(__name__)

JOB_KIND = "lichess_history_import"
SINCE_KEY = "lichess.history_since_ms"
ACCOUNT_KEY = "lichess.history_account"
CHUNK = 1000


class Account(Protocol):
    def account_id(self) -> str | None: ...

    def token(self) -> str | None: ...

    def mark_expired(self) -> None: ...


class HistoryRepo(Protocol):
    def add(self, rows: list[tuple[str, str | None, bool | None]]) -> int: ...

    def count(self) -> int: ...

    def clear(self) -> None: ...


class Settings(Protocol):
    def get(self, key: str) -> Any | None: ...

    def set(self, key: str, value: Any) -> None: ...


def iso_from_ms(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).isoformat(timespec="seconds")


class HistoryService:
    def __init__(
        self,
        account: Account,
        lichess: LichessClient,
        repo: HistoryRepo,
        settings: Settings,
        runner: JobRunner,
        is_network_error: Callable[[BaseException], bool],
        is_unauthorized: Callable[[BaseException], bool],
        on_done: Callable[[], None] = lambda: None,
    ) -> None:
        self._account = account
        self._lichess = lichess
        self._repo = repo
        self._settings = settings
        self._runner = runner
        self._is_network_error = is_network_error
        self._is_unauthorized = is_unauthorized
        self._on_done = on_done

    def count(self) -> int:
        return self._repo.count()

    def start_import(self) -> str | None:
        if self._account.account_id() is None or not self._account.token():
            return None
        running = self._runner.active(JOB_KIND)
        if running:
            return running[0].id
        return self._runner.submit(JOB_KIND, self._import)

    def _import(self, progress: ProgressFn, cancel: CancelToken) -> str:
        account, token = self._account.account_id(), self._account.token()
        if account is None or not token:
            return "Not signed in"
        if self._settings.get(ACCOUNT_KEY) != account:
            self._repo.clear()  # another account's history doesn't apply
            self._settings.set(SINCE_KEY, None)
            self._settings.set(ACCOUNT_KEY, account)
        since = self._settings.get(SINCE_KEY)
        since = since if isinstance(since, int) and since > 0 else None
        newest = 0
        added = 0
        chunk: list[tuple[str, str | None, bool | None]] = []
        try:
            for entry in self._lichess.activity(token, since):
                chunk.append((entry.puzzle_id, iso_from_ms(entry.date_ms), entry.win))
                newest = max(newest, entry.date_ms)
                if len(chunk) >= CHUNK:
                    added += self._repo.add(chunk)
                    chunk = []
                    progress(None, f"Importing your Lichess puzzle history… {added:,}")
                    cancel.raise_if_cancelled()
            added += self._repo.add(chunk)
        except Exception as e:
            if self._is_unauthorized(e):
                self._account.mark_expired()
                raise JobFailed(
                    "expired", "Your Lichess sign-in has expired. Sign in again.", retryable=False
                ) from None
            if self._is_network_error(e):
                raise JobFailed("offline", "Couldn't reach Lichess to import your puzzle history.") from None
            raise
        if newest:
            self._settings.set(SINCE_KEY, newest + 1)
        log.info("Lichess history: %d entries imported", added)
        self._on_done()
        return f"Imported {added:,} puzzles from your Lichess history"
