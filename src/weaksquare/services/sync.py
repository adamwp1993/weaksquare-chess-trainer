"""The Lichess sync queue (FR-6.8–6.12, 6.16, 6.16a; ARCHITECTURE §5 "Sync").

A decided attempt is appended with sync_status 'pending', then `kick()` starts one `lichess_sync` job
that drains the queue: grouped by angle, fewer than 100 per request, one solution per puzzle per
request (Lichess answers per puzzle id). Nothing is marked synced without a success response, so a
timeout means the batch is sent again later (at-least-once; Lichess only rates a first attempt).

Failures never block solving. A network error or 5xx retries with backoff (30 s up to 10 min), a 429
waits at least a minute, a 401 marks the account expired (FR-6.4), and any other refusal marks that
batch failed so it isn't retried forever. Retries go through the injected scheduler.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol

from weaksquare.core.clock import Clock
from weaksquare.core.lichess import MAX_BATCH, BatchResult, LichessClient, Solution
from weaksquare.core.scoring import RatingStatus, rating_status
from weaksquare.jobs.runner import CancelToken, JobRunner, ProgressFn

log = logging.getLogger(__name__)

JOB_KIND = "lichess_sync"
BACKOFF_S = (30, 60, 120, 300, 600)
RATE_LIMIT_MIN_S = 60

SyncState = Literal["idle", "syncing", "offline", "waiting", "signed_out"]


class Pending(Protocol):
    attempt_id: int
    puzzle_id: str
    win: bool
    rated: bool
    angle: str


class AttemptSyncRow(Protocol):
    attempt_id: int
    sync_status: str | None
    rated: bool | None
    already_played: bool | None
    rating_diff: int | None


class Repo(Protocol):
    def pending(self, account: str, limit: int = 1000) -> list: ...  # list[Pending]

    def pending_count(self, account: str | None) -> int: ...

    def mark_synced(
        self, results: list[tuple[int, int | None]], rating_after: tuple[int, int] | None, at: str
    ) -> None: ...

    def mark(self, attempt_ids: list[int], status: str, at: str) -> None: ...

    def attempts(self, attempt_ids: list[int]) -> list: ...  # list[AttemptSyncRow]

    def played_before(self, puzzle_id: str) -> bool: ...

    def session_change(self, session_id: int) -> int | None: ...


class History(Protocol):
    def add(self, rows: list[tuple[str, str | None, bool | None]]) -> int: ...


class Account(Protocol):
    def account_id(self) -> str | None: ...

    def token(self) -> str | None: ...

    def mark_expired(self) -> None: ...

    def update_rating(self, rating: int | None, provisional: bool | None) -> None: ...

    def note_reachable(self) -> None: ...

    def is_signed_in(self) -> bool: ...


class Scheduler(Protocol):
    def call_later(self, delay_s: float, fn: Callable[[], None]) -> None: ...


@dataclass(frozen=True)
class SyncStatus:
    state: SyncState
    pending: int


@dataclass(frozen=True)
class RatingInfo:
    """One attempt's rating change as the result panel shows it (FR-6.11b)."""

    attempt_id: int
    status: RatingStatus
    diff: int | None


@dataclass(frozen=True)
class SyncUpdate:
    status: SyncStatus
    attempts: list[RatingInfo] = field(default_factory=list)  # attempts whose rating info changed


@dataclass(frozen=True)
class QueueFields:
    """How a new attempt enters the queue (FR-6.16, FR-4.6 badge)."""

    account: str | None
    already_played: bool


@dataclass(frozen=True)
class SyncDeps:
    repo: Repo
    history: History
    account: Account
    lichess: LichessClient
    runner: JobRunner
    scheduler: Scheduler
    clock: Clock
    is_network_error: Callable[[BaseException], bool]
    is_unauthorized: Callable[[BaseException], bool]
    retry_after: Callable[[BaseException], float | None]  # a 429's Retry-After, else None
    is_rate_limited: Callable[[BaseException], bool]


def batches(rows: list, max_size: int = MAX_BATCH) -> list[tuple[str, list]]:
    """Group pending rows by angle (oldest first), at most `max_size` per batch and at most one row
    per puzzle id per batch."""
    out: list[tuple[str, list]] = []
    open_batches: dict[str, list[list]] = {}
    for row in rows:
        lists = open_batches.setdefault(row.angle, [])
        target = next((b for b in lists if len(b) < max_size and all(r.puzzle_id != row.puzzle_id for r in b)), None)
        if target is None:
            target = []
            lists.append(target)
            out.append((row.angle, target))
        target.append(row)
    return out


class SyncService:
    def __init__(self, deps: SyncDeps, notify: Callable[[SyncUpdate], None] = lambda u: None) -> None:
        self._d = deps
        self._notify = notify
        self._lock = threading.Lock()
        self._job: str | None = None
        self._again = False
        self._state: SyncState = "idle"
        self._backoff_step = 0
        self._retry_scheduled = False
        self._retry_generation = 0  # only the newest scheduled retry acts
        # Why a retry is waiting: "rate" after a 429 (nothing may be sent until it fires, FR-6.10),
        # "offline" after a network error or 5xx (a new sign-in or reconnect may try sooner).
        self._hold: str | None = None

    # ---- status ---------------------------------------------------------------------------------
    def status(self) -> SyncStatus:
        account = self._d.account.account_id()
        with self._lock:
            state = self._state
        if account is None:
            state = "signed_out"
        return SyncStatus(state, self._d.repo.pending_count(account))

    def _set(self, state: SyncState, changed: list | None = None) -> None:
        with self._lock:
            self._state = state
        self._notify(SyncUpdate(self.status(), changed or []))

    def _online(self) -> bool:
        with self._lock:
            state = self._state
        return self._d.account.is_signed_in() and state not in ("offline", "waiting")

    def _infos(self, rows: list) -> list[RatingInfo]:
        online = self._online()
        return [
            RatingInfo(
                r.attempt_id,
                rating_status(rated=r.rated, already_played=r.already_played, sync_status=r.sync_status,
                              rating_diff=r.rating_diff, online=online),
                r.rating_diff,
            )
            for r in rows
        ]  # fmt: skip

    def attempt_ratings(self, attempt_ids: list[int]) -> list[RatingInfo]:
        return self._infos(self._d.repo.attempts(attempt_ids))

    # ---- hooks for the session (v0.3) -------------------------------------------------------------
    def played_before(self, puzzle_id: str) -> bool:
        return self._d.repo.played_before(puzzle_id)

    def fields_for(self, puzzle_id: str) -> QueueFields:
        """Who a new attempt syncs to, and whether Lichess has seen the puzzle from you already."""
        return QueueFields(self._d.account.account_id(), self._d.repo.played_before(puzzle_id))

    def session_change(self, session_id: int) -> int | None:
        return self._d.repo.session_change(session_id)

    def announce(self) -> None:
        """Push the current status (e.g. after the history import changed its count)."""
        self._notify(SyncUpdate(self.status()))

    def recorded(self) -> None:
        """An attempt was appended: sync it (never blocks, FR-6.16)."""
        try:
            self.kick()
        except Exception:
            log.exception("couldn't start the sync")

    # ---- the queue ------------------------------------------------------------------------------
    def kick(self, force: bool = False) -> str | None:
        """Drain the queue now if there's an account to sync to. Never blocks (FR-6.16).

        While a backoff retry is waiting, a new solve doesn't send anything: it joins the queue for
        that retry (v0.3-B5). `force` (a sign-in, or Lichess reachable again) may cut a network
        backoff short, but never the wait after a 429."""
        if self._d.account.account_id() is None or not self._d.account.token():
            self._notify(SyncUpdate(self.status()))
            return None
        with self._lock:
            held = self._hold == "rate" or (self._hold == "offline" and not force)
        if held:
            self._notify(SyncUpdate(self.status()))
            return None
        with self._lock:
            if self._job is not None:
                self._again = True
                return self._job
            self._again = False
            self._job = self._d.runner.submit(JOB_KIND, self._run)
            return self._job

    def _retry(self, generation: int) -> None:
        with self._lock:
            if generation != self._retry_generation:
                return  # replaced by a later retry (e.g. a 429's own wait): ignore (v0.3-B8)
            self._retry_scheduled = False
            self._hold = None
        self.kick()

    def _schedule_retry(self, delay_s: float, reason: str) -> None:
        """A network backoff keeps an already waiting retry. A 429 always starts its own full wait,
        so an older, shorter timer can never end it early (v0.3-B8)."""
        with self._lock:
            if self._retry_scheduled and reason != "rate":
                if self._hold is None:
                    self._hold = reason  # keep holding new solves until that retry (v0.3-B9)
                return
            self._hold = reason
            self._retry_scheduled = True
            self._retry_generation += 1
            generation = self._retry_generation
        self._d.scheduler.call_later(delay_s, lambda: self._retry(generation))

    def _run(self, progress: ProgressFn, cancel: CancelToken) -> str:
        try:
            while True:
                outcome = self._drain(cancel)
                with self._lock:
                    if outcome == "drained" and self._again:
                        self._again = False
                        continue
                    self._job = None
                return outcome
        except BaseException:
            with self._lock:
                self._job = None
            raise

    def _drain(self, cancel: CancelToken) -> str:
        account, token = self._d.account.account_id(), self._d.account.token()
        if account is None or not token:
            self._set("signed_out")
            return "signed out"
        rows = self._d.repo.pending(account)
        if not rows:
            self._set("idle")
            return "drained"
        self._set("syncing")
        for angle, batch in batches(rows):
            cancel.raise_if_cancelled()
            sols = [Solution(r.puzzle_id, r.win, r.rated) for r in batch]
            try:
                result = self._d.lichess.solve_batch(token, angle, sols)
            except Exception as e:
                stop = self._failed(e, batch)
                if stop:
                    return stop
                continue
            self._apply(batch, result)
        # More may have been queued meanwhile: the caller loops while `_again` is set.
        with self._lock:
            self._again = True
        return "drained"

    def _failed(self, e: Exception, batch: list) -> str | None:
        """Handle a failed batch. Returns a reason to stop draining, or None to go on."""
        if self._d.is_unauthorized(e):
            log.info("sync: Lichess says the sign-in is no longer valid")
            self._d.account.mark_expired()
            self._set("signed_out")
            return "expired"
        if self._d.is_rate_limited(e):
            after = self._d.retry_after(e)
            delay = max(RATE_LIMIT_MIN_S, after or 0)
            log.info("sync: rate-limited by Lichess, waiting %ss", delay)
            self._set("waiting")
            self._schedule_retry(delay, "rate")
            return "rate limited"
        if self._d.is_network_error(e):
            delay = BACKOFF_S[min(self._backoff_step, len(BACKOFF_S) - 1)]
            self._backoff_step += 1
            log.info("sync: Lichess unreachable (%s), retrying in %ss", type(e).__name__, delay)
            self._set("offline")
            self._schedule_retry(delay, "offline")
            return "offline"
        ids = [r.attempt_id for r in batch]
        log.warning("sync: Lichess refused a batch of %d (%s); marked failed", len(ids), e)
        self._d.repo.mark(ids, "failed", self._now())
        self._notify(SyncUpdate(self.status(), self._infos(self._d.repo.attempts(ids))))
        return None

    def _apply(self, batch: list, result: BatchResult) -> None:
        self._backoff_step = 0
        with self._lock:
            if self._hold == "offline":
                self._hold = None  # reachable again; the pending timer finds nothing to do
        now = self._now()
        rounds = {r.id: r for r in result.rounds}
        synced = [r for r in batch if r.puzzle_id in rounds]
        skipped = [r.attempt_id for r in batch if r.puzzle_id not in rounds]  # FR-6.12
        rating_after = (synced[-1].attempt_id, result.rating) if synced and result.rating is not None else None
        self._d.repo.mark_synced([(r.attempt_id, rounds[r.puzzle_id].rating_diff) for r in synced], rating_after, now)
        if skipped:
            self._d.repo.mark(skipped, "skipped", now)
        self._d.history.add([(r.puzzle_id, now, r.win) for r in synced])
        self._d.account.update_rating(result.rating, result.provisional)
        self._d.account.note_reachable()
        ids = [r.attempt_id for r in batch]
        self._notify(SyncUpdate(self.status(), self._infos(self._d.repo.attempts(ids))))

    def _now(self) -> str:
        return self._d.clock.now().isoformat(timespec="seconds")
