"""SyncService against the fake Lichess client and a real user.db (FR-6.8–6.12, 6.16, 6.16a)."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from tests.fakes.desktop import FakeScheduler
from tests.fakes.lichess import FAKE_TOKEN, FakeLichess, network_error, rate_limited
from weaksquare.adapters.db.connection import Database
from weaksquare.adapters.db.migrate import migrate
from weaksquare.adapters.db.repos.lichess import LichessHistoryRepo, SyncRepo
from weaksquare.adapters.db.repos.user_data import AttemptsRepo, SyncFields
from weaksquare.adapters.http import HttpError, RateLimited, Unauthorized
from weaksquare.adapters.lichess import is_network_error, is_unauthorized
from weaksquare.config import MIGRATIONS_DIR
from weaksquare.core.clock import FixedClock
from weaksquare.core.modes.base import AttemptResult
from weaksquare.core.puzzle import PuzzleRef
from weaksquare.jobs.runner import JobRunner
from weaksquare.services.sync import SyncDeps, SyncService, SyncUpdate, batches

WIN = AttemptResult(win=True, first_move_correct=True, line_correct=True, help_used="none", time_ms=1)
LOSS = AttemptResult(win=False, first_move_correct=False, line_correct=False, help_used="none", time_ms=1)


@dataclass
class FakeAccount:
    id: str | None = "player_a"
    secret: str | None = FAKE_TOKEN
    expired: bool = False
    ratings: list[tuple[int | None, bool | None]] = field(default_factory=list)
    reachable: int = 0

    def account_id(self) -> str | None:
        return self.id

    def token(self) -> str | None:
        return self.secret

    def mark_expired(self) -> None:
        self.expired = True
        self.id = self.secret = None

    def update_rating(self, rating: int | None, provisional: bool | None) -> None:
        self.ratings.append((rating, provisional))

    def note_reachable(self) -> None:
        self.reachable += 1


class Harness:
    def __init__(self, tmp_path: Path, clock: FixedClock, lichess: FakeLichess | None = None) -> None:
        p = tmp_path / "user.db"
        migrate(p, MIGRATIONS_DIR / "user", clock)
        self.db = Database(p, tmp_path / "none.db")
        with self.db.session() as c:
            c.execute("INSERT INTO sessions (started_at, mode, filters_json) VALUES ('t', 'standard', '{}')")
        self.lichess = lichess or FakeLichess()
        self.account = FakeAccount()
        self.scheduler = FakeScheduler()
        self.runner = JobRunner()
        self.repo = SyncRepo(self.db)
        self.history = LichessHistoryRepo(self.db)
        self.updates: list[SyncUpdate] = []
        self.svc = SyncService(
            SyncDeps(
                repo=self.repo,
                history=self.history,
                account=self.account,
                lichess=self.lichess,
                runner=self.runner,
                scheduler=self.scheduler,
                clock=clock,
                is_network_error=is_network_error,
                is_unauthorized=is_unauthorized,
                retry_after=lambda e: e.retry_after_s if isinstance(e, RateLimited) else None,
                is_rate_limited=lambda e: isinstance(e, RateLimited),
            ),
            notify=self.updates.append,
        )

    def add(
        self, pid: str, *, win: bool = True, rated: bool = True, angle: str = "mix", account: str | None = "player_a"
    ) -> int:
        return AttemptsRepo(self.db).append(
            PuzzleRef("lichess", pid), 1, "standard", "t", "t", WIN if win else LOSS, 1500,
            SyncFields("pending", rated, angle, account, False),
        )  # fmt: skip

    def sync(self) -> None:
        job = self.svc.kick()
        if job:
            st = self.runner.wait(job, 10)
            assert st is not None and st.state == "done", st

    def status_of(self, aid: int) -> tuple[str | None, int | None]:
        r = self.repo.attempts([aid])[0]
        return r.sync_status, r.rating_diff


@pytest.fixture
def h(tmp_path: Path, clock: FixedClock):  # type: ignore[no-untyped-def]
    harness = Harness(tmp_path, clock)
    yield harness
    harness.db.close_all()


def test_syncs_and_records_rating_changes(h: Harness) -> None:
    a = h.add("P1")
    b = h.add("P2", win=False)
    h.sync()
    call = h.lichess.batch_calls[0]
    assert call.angle == "mix" and call.token == FAKE_TOKEN
    assert [(s.id, s.win, s.rated) for s in call.solutions] == [("P1", True, True), ("P2", False, True)]
    assert h.status_of(a) == ("synced", 8)
    assert h.status_of(b) == ("synced", -12)
    # The new rating comes from the response (FR-6.11a/d), stored on the batch's last attempt.
    assert h.account.ratings == [(1830, False)]
    assert [p.rating for p in h.repo.rating_points()] == [1830]
    assert h.history.count() == 2  # synced puzzles count as played on Lichess
    assert h.svc.status().pending == 0
    assert h.updates[-1].status.state == "idle"


def test_batches_are_under_100_and_grouped_by_angle(h: Harness) -> None:
    for i in range(150):
        h.add(f"F{i}", angle="fork")
    for i in range(5):
        h.add(f"M{i}")
    h.sync()
    sizes = [(c.angle, len(c.solutions)) for c in h.lichess.batch_calls]
    assert sizes == [("fork", 99), ("fork", 51), ("mix", 5)]
    assert all(len(c.solutions) < 100 for c in h.lichess.batch_calls)  # FR-6.9
    assert h.svc.status().pending == 0


def test_one_solution_per_puzzle_per_request() -> None:
    @dataclass
    class Row:
        attempt_id: int
        puzzle_id: str
        angle: str = "mix"

    rows = [Row(1, "A"), Row(2, "B"), Row(3, "A")]
    assert [[r.attempt_id for r in b] for _, b in batches(rows)] == [[1, 2], [3]]


def test_rated_off_sends_rated_false(h: Harness) -> None:
    """FR-6.15."""
    a = h.add("P1", rated=False)
    h.sync()
    assert h.lichess.batch_calls[0].solutions[0].rated is False
    assert h.status_of(a) == ("synced", 0)


def test_skipped_puzzles_are_not_errors(h: Harness) -> None:
    """FR-6.12: puzzles no longer on Lichess are skipped by the server."""
    h.lichess.skip_ids = {"GONE1"}
    a = h.add("GONE1")
    b = h.add("P2")
    h.sync()
    assert h.status_of(a) == ("skipped", None)
    assert h.status_of(b)[0] == "synced"


def test_offline_backs_off_then_resends(h: Harness) -> None:
    """FR-6.16a: never marked synced without a success; a failed batch is resent later."""
    h.lichess.batch_errors = [network_error(), network_error()]
    a = h.add("P1")
    h.sync()
    assert h.status_of(a) == ("pending", None)
    assert h.svc.status().state == "offline"
    assert h.scheduler.delays == [30]
    h.scheduler.run_next()
    h.runner.wait(h.runner.active()[0].id, 5) if h.runner.active() else None
    for j in h.runner.active():
        h.runner.wait(j.id, 5)
    assert h.scheduler.delays == [60]  # backoff grows
    h.scheduler.run_next()
    for j in h.runner.active():
        h.runner.wait(j.id, 5)
    assert h.status_of(a) == ("synced", 8)
    assert len(h.lichess.batch_calls) == 3  # the same solve, sent until Lichess confirmed it


def test_5xx_counts_as_offline(h: Harness) -> None:
    h.lichess.batch_errors = [HttpError("x returned HTTP 502", status=502)]
    h.add("P1")
    h.sync()
    assert h.svc.status().state == "offline" and h.scheduler.delays == [30]


def test_429_waits_at_least_a_minute(h: Harness) -> None:
    """FR-6.10."""
    h.lichess.batch_errors = [rate_limited(None)]
    h.add("P1")
    h.sync()
    assert h.svc.status().state == "waiting"
    assert h.scheduler.delays == [60]
    h2_errors = [rate_limited(120)]
    h.lichess.batch_errors = h2_errors
    h.scheduler.pending.clear()
    h.svc._retry_scheduled = False
    h.sync()
    assert h.scheduler.delays == [120]


def test_401_marks_the_account_expired_and_keeps_the_queue(h: Harness) -> None:
    h.lichess.batch_errors = [Unauthorized("x returned HTTP 401", status=401, retryable=False)]
    a = h.add("P1")
    h.sync()
    assert h.account.expired
    assert h.status_of(a) == ("pending", None)
    assert h.svc.status().state == "signed_out"
    assert h.scheduler.pending == []


def test_other_refusals_mark_the_batch_failed(h: Harness) -> None:
    h.lichess.batch_errors = [HttpError("x returned HTTP 400", status=400, retryable=False)]
    a = h.add("P1", angle="fork")
    b = h.add("P2")
    h.sync()
    assert h.status_of(a) == ("failed", None)
    assert h.status_of(b)[0] == "synced"


def test_solves_sync_only_to_their_account(h: Harness) -> None:
    mine = h.add("P1", account="player_a")
    nobody = h.add("P2", account=None)
    other = h.add("P3", account="player_b")
    h.sync()
    assert h.status_of(mine)[0] == "synced"
    assert h.status_of(nobody)[0] == "synced"  # made while signed out: goes to the next sign-in
    assert h.status_of(other)[0] == "pending"


def test_no_account_no_requests(h: Harness) -> None:
    h.account.id = None
    h.add("P1")
    assert h.svc.kick() is None
    assert h.lichess.batch_calls == []
    assert h.svc.status().state == "signed_out" and h.svc.status().pending == 1


def test_solving_never_waits_for_a_slow_sync(h: Harness) -> None:
    """FR-6.16: kick() returns at once while a batch is in flight; new solves join the next round."""
    gate = threading.Event()
    h.lichess.gate = gate
    h.add("P1")
    job = h.svc.kick()
    assert job is not None
    a2 = h.add("P2")  # recorded while the first batch is in flight
    assert h.svc.kick() == job  # no second job; it will loop
    gate.set()
    h.runner.wait(job, 10)
    assert h.status_of(a2)[0] == "synced"
