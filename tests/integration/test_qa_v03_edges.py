"""v0.3 edge cases written by the independent QA pass (qa/QA-v0.3.md).

Tests marked xfail(strict=True) document an open bug by its ID; they flip to a failure once it's fixed,
so the fix commit removes the marker (and keeps the test as the regression test).
"""

from __future__ import annotations

import logging
import random
import shutil
import time
from typing import Any

import httpx
import pytest

from tests.fakes.desktop import FakeBrowser, FakeScheduler, ListenerFactory
from tests.fakes.lichess import FAKE_TOKEN, FakeLichess, network_error, rate_limited
from tests.helpers import FakeDesktop
from weaksquare import config
from weaksquare.adapters.db.migrate import migrate
from weaksquare.adapters.http import HttpClient, HttpError, RateLimited, Unauthorized
from weaksquare.adapters.lichess import LichessHttp, is_network_error
from weaksquare.adapters.secret_store import MemorySecretStore
from weaksquare.app import build_services
from weaksquare.bridge.api import Api
from weaksquare.core.filters import FilterSpec, RatioBucket
from weaksquare.core.lichess import Solution
from weaksquare.core.scoring import angle_for, rating_status
from weaksquare.jobs.runner import JobRunner

OPEN = {"min_popularity": None, "min_plays": None, "exclude_solved_here": False, "exclude_played_on_lichess": False}


# ---- angle rule extras (FR-6.13/6.14, decision 2) ---------------------------------------------------
@pytest.mark.parametrize(
    "spec",
    [
        FilterSpec(exclude_themes=("fork",)),
        FilterSpec(rating_min=1800, rating_max=2000),
        FilterSpec(side="black"),
        FilterSpec(exclude_solved_here=False, only_my_misses=True),
    ],
)
def test_qa_non_theme_filters_keep_mix(spec: FilterSpec) -> None:
    assert angle_for(spec, ("fork", "middlegame", "short"), 2) == "mix"


@pytest.mark.parametrize(
    "length,expected", [(1, "oneMove"), (2, "short"), (3, "long"), (4, "veryLong"), (9, "veryLong")]
)
def test_qa_length_theme_for_every_length(length: int, expected: str) -> None:
    narrowed = FilterSpec(lengths=(min(length, 4),))
    assert angle_for(narrowed, ("fork", "endgame"), length) == expected


def test_qa_all_mode_reports_the_motif_not_the_phase() -> None:
    spec = FilterSpec(themes=("endgame", "fork", "pin"), match="all")
    assert angle_for(spec, ("pin", "fork", "endgame", "long"), 3) == "fork"


def test_qa_ratio_angle_uses_bucket_themes() -> None:
    spec = FilterSpec(ratios=(RatioBucket(("endgame",), 50), RatioBucket(("mateIn2",), 50)))
    assert angle_for(spec, ("endgame", "mateIn2", "short"), 2) == "mateIn2"  # motif tier first
    assert angle_for(spec, ("endgame", "long"), 3) == "endgame"


def test_qa_rating_status_edges() -> None:
    # Signed out (or offline) and queued: "Will sync later".
    assert rating_status(rated=True, already_played=False, sync_status="pending", rating_diff=None,
                         online=False) == "offline"  # fmt: skip
    # A returned 0 is never shown as a number.
    assert rating_status(rated=True, already_played=False, sync_status="synced", rating_diff=0,
                         online=True) == "not_rated"  # fmt: skip


# ---- HTTP: token handling and error classes (SR-7, FR-6.4, FR-6.10) -----------------------------------
def _http(handler: Any) -> tuple[HttpClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def h(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return handler(req)

    return HttpClient(transport=httpx.MockTransport(h), sleep=lambda s: None), seen


def test_qa_token_is_per_request_and_never_in_errors() -> None:
    http, seen = _http(lambda r: httpx.Response(500, text=f"echo {r.headers.get('authorization')}"))
    lc = LichessHttp(http)
    with pytest.raises(HttpError) as e:
        lc.account(FAKE_TOKEN)
    assert FAKE_TOKEN not in str(e.value) and FAKE_TOKEN not in repr(e.value)
    assert seen and all(r.headers["authorization"].endswith(FAKE_TOKEN) for r in seen)
    assert all(FAKE_TOKEN not in str(r.url) for r in seen)
    assert "authorization" not in {k.lower() for k in http._client.headers}
    http.close()


def test_qa_429_is_not_retried_and_keeps_retry_after() -> None:
    http, seen = _http(lambda r: httpx.Response(429, headers={"Retry-After": "120"}))
    with pytest.raises(RateLimited) as e:
        LichessHttp(http).solve_batch(FAKE_TOKEN, "mix", [Solution("00008", True, True)])
    assert e.value.retry_after_s == 120 and len(seen) == 1
    http.close()


def test_qa_401_is_unauthorized_and_not_retried() -> None:
    http, seen = _http(lambda r: httpx.Response(401))
    with pytest.raises(Unauthorized):
        LichessHttp(http).account(FAKE_TOKEN)
    assert len(seen) == 1
    http.close()


# Regression test for v0.3-B1 (fixed in QA round 1).
def test_qa_unexpected_response_is_not_a_network_error() -> None:
    http, _ = _http(lambda r: httpx.Response(200, json=["not", "an", "object"]))
    lc = LichessHttp(http)
    with pytest.raises(HttpError) as e:
        lc.account(FAKE_TOKEN)
    assert not is_network_error(e.value)  # else the account check goes 'offline' and rechecks forever
    with pytest.raises(HttpError) as e2:
        lc.solve_batch(FAKE_TOKEN, "mix", [Solution("00008", True, True)])
    assert not is_network_error(e2.value)  # else the sync resends the batch with backoff forever
    http.close()


# ---- wired services: secrets never leak, edge flows -------------------------------------------------
class Wired:
    def __init__(self, paths: config.Paths, clock: Any, fixture_puzzles_db: Any) -> None:
        shutil.copyfile(fixture_puzzles_db, paths.puzzles_db)
        migrate(paths.user_db, config.MIGRATIONS_DIR / "user", clock)
        self.events: list[tuple[str, Any]] = []
        self.lichess = FakeLichess()
        self.listeners = ListenerFactory()
        self.runner = JobRunner()
        self.secrets = MemorySecretStore()
        self.scheduler = FakeScheduler()
        self.services = build_services(
            paths, clock, self.runner, random.Random(7), secrets=self.secrets, lichess=self.lichess,
            scheduler=self.scheduler, browser=FakeBrowser(), make_listener=self.listeners,
            emit=lambda n, p: self.events.append((n, p)),
        )  # fmt: skip
        s = self.services
        self.api = Api(paths=paths, desktop=FakeDesktop(), clock=clock, dev_mode=True, runner=self.runner,
                       puzzle_db=s.puzzle_db, mixer=s.mixer, sessions=s.sessions, presets=s.presets, stats=s.stats,
                       ui_settings=s.ui_settings, db_update=s.db_update, account=s.account, sync=s.sync,
                       history=s.history)  # fmt: skip

    def settle(self) -> None:
        for _ in range(10):
            jobs = self.runner.active()
            if not jobs:
                return
            for j in jobs:
                self.runner.wait(j.id, 5)

    def close(self) -> None:
        self.runner.cancel_all(2)
        self.services.close()


@pytest.fixture
def w(paths, clock, fixture_puzzles_db):  # type: ignore[no-untyped-def]
    wired = Wired(paths, clock, fixture_puzzles_db)
    yield wired
    wired.close()


def data(r: dict) -> Any:
    assert r["ok"], r
    return r["data"]


def _check_in(w: Wired) -> None:
    """Signed in through the launch check (a stored token validated against GET /api/account)."""
    w.secrets.set("lichess", FAKE_TOKEN)
    job = w.services.account.check()
    assert job is not None
    w.runner.wait(job, 5)
    w.settle()


def _solve_one(api: Api, sid: int) -> dict:
    view = data(api.next_puzzle(sid))
    with api._sessions._puzzles._db.session() as c:
        moves = c.execute("SELECT moves FROM pz.puzzles WHERE id = ?", (view["puzzle_id"],)).fetchone()[0].split()
    fb = None
    for uci in moves[1::2]:
        fb = data(api.submit_move(sid, uci))
    assert fb is not None
    return fb["outcome"]


def test_qa_token_never_in_logs_events_or_job_messages(w: Wired, caplog: pytest.LogCaptureFixture) -> None:
    """SR-1/SR-7: a whole session (check-in, history import, sync, network/400/429 failures, sign-out) at
    DEBUG level; the token never appears in a log record, a pushed event, a job result or a bridge reply."""
    caplog.set_level(logging.DEBUG)
    _check_in(w)
    sid = data(w.api.start_session(OPEN, True))["session_id"]
    replies: list[Any] = [_solve_one(w.api, sid)]
    w.settle()
    w.lichess.batch_errors = [
        network_error(),
        HttpError("https://lichess.org/api/puzzle/batch/mix returned HTTP 400", status=400, retryable=False),
    ]
    replies.append(_solve_one(w.api, sid))
    w.settle()
    w.scheduler.run_next()
    w.settle()
    w.lichess.batch_errors = [rate_limited(5)]
    replies.append(_solve_one(w.api, sid))
    w.settle()
    w.lichess.revoke_error = network_error()
    replies.append(w.api.sign_out(False))
    assert replies[-1]["error"]["code"] == "revoke_failed"
    replies.append(w.api.sign_out(True))
    replies += [w.api.get_account_status(), w.api.get_sync_status(), w.api.get_rating_history()]
    blob = "\n".join([r.getMessage() for r in caplog.records] + [repr(e) for e in w.events] + [repr(replies)])
    assert w.events, "events were captured"
    assert FAKE_TOKEN not in blob
    assert w.secrets.get("lichess") is None


def test_qa_sign_in_job_never_leaks_the_code_or_token(w: Wired, caplog: pytest.LogCaptureFixture) -> None:
    """The real sign-in job with a callback whose state doesn't match, then a refused exchange:
    neither the code nor a token reaches the log, an event or the job's error message."""
    caplog.set_level(logging.DEBUG)
    w.listeners.query = {"code": ["SECRETCODE42"], "state": ["wrong"]}
    job = data(w.api.start_sign_in())
    w.settle()
    st = w.runner.status(job)
    assert st is not None and st.state == "failed"
    blob = "\n".join([r.getMessage() for r in caplog.records] + [repr(e) for e in w.events] + [repr(st)])
    assert "SECRETCODE42" not in blob and FAKE_TOKEN not in blob
    assert w.secrets.get("lichess") is None


def test_qa_sign_out_keeps_pending_and_hides_rating(w: Wired) -> None:
    _check_in(w)
    assert data(w.api.get_account_status())["rating"] == 1834
    w.lichess.batch_errors = [network_error()]
    sid = data(w.api.start_session(OPEN, True))["session_id"]
    out = _solve_one(w.api, sid)
    w.settle()
    assert data(w.api.get_sync_status())["pending"] == 1
    data(w.api.sign_out(False))
    st = data(w.api.get_account_status())
    assert st["state"] == "signed_out" and st["rating"] is None and st["username"] is None
    assert data(w.api.get_sync_status())["pending"] == 1  # stays queued
    r = data(w.api.get_attempt_ratings([out["attempt_id"]]))[0]
    assert r["status"] == "offline"  # Will sync later


def test_qa_solve_while_signed_out_syncs_after_sign_in_with_its_angle(w: Wired) -> None:
    spec = {**OPEN, "themes": ["fork"]}
    sid = data(w.api.start_session(spec, False))["session_id"]
    out = _solve_one(w.api, sid)
    assert out["lichess"]["status"] == "unrated"
    assert not w.lichess.batch_calls
    _check_in(w)
    assert len(w.lichess.batch_calls) == 1
    call = w.lichess.batch_calls[0]
    assert call.angle == "fork" and [s.rated for s in call.solutions] == [False]


@pytest.mark.parametrize(
    "method,args",
    [
        ("start_session", (OPEN, "false")),
        ("start_session", (OPEN, 0)),
        ("sign_out", ("yes",)),
        ("sign_out", (1,)),
        ("get_attempt_ratings", ([0],)),
        ("get_attempt_ratings", ([-3],)),
        ("get_attempt_ratings", ([1.5],)),
        ("get_attempt_ratings", ("1,2",)),
        ("start_sign_in", ("extra",)),
        ("get_account_status", (1,)),
    ],
)
def test_qa_bridge_rejects_bad_arguments(w: Wired, method: str, args: tuple) -> None:
    r = getattr(w.api, method)(*args)
    assert r["ok"] is False and r["error"]["code"] == "invalid_argument", r


def test_qa_second_sign_in_while_waiting_is_refused(w: Wired) -> None:
    w.listeners.hold = True
    first = data(w.api.start_sign_in())
    for _ in range(100):
        if w.listeners.made and w.listeners.made[0].started.is_set():
            break
        time.sleep(0.02)
    r = w.api.start_sign_in()
    assert r["ok"] is False and r["error"]["code"] == "conflict", r
    data(w.api.cancel_sign_in())
    w.runner.wait(first, 5)
    assert data(w.api.get_account_status())["state"] == "signed_out"


def test_qa_exactly_99_then_1(w: Wired) -> None:
    """FR-6.9 at the boundary: 100 pending solves of one angle go out as 99 + 1."""
    from weaksquare.adapters.db.repos.user_data import AttemptsRepo, SyncFields
    from weaksquare.core.modes.base import AttemptResult
    from weaksquare.core.puzzle import PuzzleRef

    win = AttemptResult(win=True, first_move_correct=True, line_correct=True, help_used="none", time_ms=1)
    repo = AttemptsRepo(w.services.db)
    with w.services.db.session() as c:
        c.execute("INSERT INTO sessions (started_at, mode, filters_json) VALUES ('t', 'standard', '{}')")
    for i in range(100):
        repo.append(PuzzleRef("lichess", f"P{i:04d}"), 1, "standard", "t", "t", win, 1500,
                    SyncFields("pending", True, "mix", None, False))  # fmt: skip
    _check_in(w)
    assert [len(c.solutions) for c in w.lichess.batch_calls] == [99, 1]
    assert data(w.api.get_sync_status())["pending"] == 0


def test_qa_history_import_401_expires_the_account(w: Wired) -> None:
    _check_in(w)
    w.secrets.set("lichess", FAKE_TOKEN + "x")  # revoked elsewhere: the fake answers 401
    job = w.services.history.start_import()
    assert job is not None
    w.runner.wait(job, 5)
    assert data(w.api.get_account_status())["state"] == "expired"
    assert w.secrets.get("lichess") is None


def test_qa_offline_then_reconnect_drains_the_queue(w: Wired) -> None:
    """Adam's manual flow, automated against the fake: offline solves wait, the reconnect check drains them."""
    w.secrets.set("lichess", FAKE_TOKEN)
    w.lichess.account_error = network_error()
    job = w.services.account.check()
    assert job is not None
    w.runner.wait(job, 5)
    assert data(w.api.get_account_status())["state"] == "offline"
    sid = data(w.api.start_session(OPEN, True))["session_id"]
    w.lichess.batch_errors = [network_error()] * 3
    outs = [_solve_one(w.api, sid) for _ in range(3)]
    w.settle()
    assert data(w.api.get_sync_status())["pending"] == 3
    rs = data(w.api.get_attempt_ratings([o["attempt_id"] for o in outs]))
    assert {r["status"] for r in rs} == {"offline"}
    w.lichess.account_error = None
    w.lichess.batch_errors = []
    for _ in range(10):  # the reconnect check and any sync retry
        if not w.scheduler.pending:
            break
        w.scheduler.run_next()
        w.settle()
    assert data(w.api.get_account_status())["state"] == "signed_in"
    assert data(w.api.get_sync_status())["pending"] == 0
    rs = data(w.api.get_attempt_ratings([o["attempt_id"] for o in outs]))
    assert {r["status"] for r in rs} == {"done"}
    assert data(w.api.get_session_stats(sid))["rating_change"] == sum(r["diff"] for r in rs)


# Regression test for v0.3-B3 (fixed in QA round 1).
def test_qa_failed_sign_in_after_the_exchange_revokes_the_new_token(w: Wired) -> None:
    """The code exchange succeeds, then GET /api/account fails (network drop). The new token isn't
    stored, so nothing can ever revoke it: it stays valid on Lichess for about a year (SR-15, FR-6.6)."""
    from tests.fakes.desktop import STATE

    w.listeners.query = None  # filled below with the job's own state
    made: list[Any] = []

    def factory(accept):  # type: ignore[no-untyped-def]
        listener = ListenerFactory(query={"code": ["c0de"], "state": [STATE]})(accept)
        made.append(listener)
        return listener

    w.services.account._d = type(w.services.account._d)(
        **{**w.services.account._d.__dict__, "make_listener": factory, "new_secret": _secrets()}
    )
    w.lichess.account_error = network_error()
    job = data(w.api.start_sign_in())
    w.settle()
    st = w.runner.status(job)
    assert st is not None and st.state == "failed"
    assert w.secrets.get("lichess") is None
    assert w.lichess.revoked == [FAKE_TOKEN]  # the orphaned token should be revoked


def _secrets():  # type: ignore[no-untyped-def]
    from tests.fakes.desktop import secrets_sequence

    return secrets_sequence()


def test_qa_post_json_resends_on_5xx() -> None:
    """Evidence for v0.3-B4: post_json (used by the live test's batch POST) retries a 5xx, so one
    `-m live` run can push the same 3 solves up to 4 times (SR-13: at most 3 per run)."""
    http, seen = _http(lambda r: httpx.Response(503))
    with pytest.raises(HttpError):
        http.post_json("https://lichess.org/api/puzzle/batch/mix", {"solutions": []}, token=FAKE_TOKEN)
    assert len(seen) == 4
    http.close()


# Regression test for v0.3-B5 (fixed in QA round 1).
def test_qa_no_request_during_the_429_wait(w: Wired) -> None:
    """FR-6.10 / Lichess API rule: after a 429, wait a full minute before the next request. A solve
    recorded during that minute must not send a batch before the scheduled retry."""
    _check_in(w)
    sid = data(w.api.start_session(OPEN, True))["session_id"]
    w.lichess.batch_errors = [rate_limited()]
    _solve_one(w.api, sid)
    w.settle()
    assert len(w.lichess.batch_calls) == 1 and data(w.api.get_sync_status())["state"] == "waiting"
    _solve_one(w.api, sid)  # 10 seconds later, say
    w.settle()
    assert len(w.lichess.batch_calls) == 1, "a batch was sent during the 429 wait"
    w.scheduler.run_next()  # the minute is up
    w.settle()
    assert data(w.api.get_sync_status())["pending"] == 0


def test_b4_batches_are_sent_once_per_call() -> None:
    """Regression for v0.3-B4: a batch POST is never resent inside the HTTP client (the live test sends
    its 3 solves exactly once; the sync service does its own backoff)."""
    http, seen = _http(lambda r: httpx.Response(503))
    with pytest.raises(HttpError):
        http.post_json("https://lichess.org/api/puzzle/batch/mix", {"solutions": []}, token=FAKE_TOKEN, retry=False)
    assert len(seen) == 1
    with pytest.raises(HttpError):
        LichessHttp(http).solve_batch(FAKE_TOKEN, "mix", [Solution("00008", False, False)])
    assert len(seen) == 2
    http.close()


def test_b5_a_sign_in_may_cut_a_network_backoff_short_but_never_a_429_wait(w: Wired) -> None:
    """Regression for v0.3-B5: during a network backoff a new solve waits, but a sign-in (force) may
    retry at once; after a 429 even that waits for the scheduled retry."""
    _check_in(w)
    sid = data(w.api.start_session(OPEN, True))["session_id"]
    w.lichess.batch_errors = [network_error()]
    _solve_one(w.api, sid)
    w.settle()
    assert len(w.lichess.batch_calls) == 1
    _solve_one(w.api, sid)
    w.settle()
    assert len(w.lichess.batch_calls) == 1  # held for the backoff
    w.services.sync.kick(force=True)
    w.settle()
    assert len(w.lichess.batch_calls) == 2 and data(w.api.get_sync_status())["pending"] == 0
    w.lichess.batch_errors = [rate_limited()]
    _solve_one(w.api, sid)
    w.settle()
    calls = len(w.lichess.batch_calls)
    w.services.sync.kick(force=True)
    w.settle()
    assert len(w.lichess.batch_calls) == calls  # never during the 429 wait


# Regression test for v0.3-B8 (fixed in QA round 2).
def test_qa_429_after_a_forced_retry_still_waits_a_minute(w: Wired) -> None:
    """Round 2. A network error schedules a 30 s retry; a sign-in (force) retries at once and works; a
    429 then arrives while the 30 s timer is still pending. `_schedule_retry("rate")` sees a retry
    already scheduled and adds no 60 s timer, so the old 30 s timer fires (at most 30 s after the
    429), clears the hold and sends: the minute Lichess asked for is cut short (FR-6.10)."""
    _check_in(w)
    sid = data(w.api.start_session(OPEN, True))["session_id"]
    w.lichess.batch_errors = [network_error()]
    _solve_one(w.api, sid)
    w.settle()
    assert w.scheduler.delays == [30]
    w.services.sync.kick(force=True)  # e.g. a sign-in; succeeds
    w.settle()
    w.lichess.batch_errors = [rate_limited()]
    _solve_one(w.api, sid)  # the success cleared the offline hold, so this sends and gets the 429
    w.settle()
    assert data(w.api.get_sync_status())["state"] == "waiting"
    calls = len(w.lichess.batch_calls)
    assert any(d >= 60 for d in w.scheduler.delays), w.scheduler.delays  # a full-minute timer exists
    w.scheduler.run_next()  # the old 30 s timer fires first
    w.settle()
    assert len(w.lichess.batch_calls) == calls, "a batch was sent before the 429 minute was up"


# Regression test for v0.3-B9 (fixed in QA round 2 follow-up).
def test_qa_network_backoff_after_a_forced_success_still_holds_new_solves(w: Wired) -> None:
    """Round 2 follow-up (B8 review). Network error (30 s timer, hold); a forced kick succeeds (hold
    cleared, the old timer still pending); the next batch fails with a network error again. New solves
    must wait for a retry instead of each sending a request (the B5 behavior for network backoff)."""
    _check_in(w)
    sid = data(w.api.start_session(OPEN, True))["session_id"]
    w.lichess.batch_errors = [network_error()]
    _solve_one(w.api, sid)
    w.settle()
    w.services.sync.kick(force=True)  # e.g. a reconnect check; succeeds
    w.settle()
    w.lichess.batch_errors = [network_error()]
    _solve_one(w.api, sid)  # fails: offline again
    w.settle()
    calls = len(w.lichess.batch_calls)
    _solve_one(w.api, sid)
    w.settle()
    assert len(w.lichess.batch_calls) == calls, "a new solve sent a request during the network backoff"


def test_qa_two_429s_in_a_row_each_wait_their_own_time(w: Wired) -> None:
    _check_in(w)
    sid = data(w.api.start_session(OPEN, True))["session_id"]
    w.lichess.batch_errors = [rate_limited(), rate_limited(90)]
    _solve_one(w.api, sid)
    w.settle()
    assert w.scheduler.delays == [60]
    w.services.sync.kick(force=True)
    w.settle()
    assert len(w.lichess.batch_calls) == 1  # a forced kick never cuts a 429 wait
    w.scheduler.run_next()  # minute up: second 429 with Retry-After 90
    w.settle()
    assert len(w.lichess.batch_calls) == 2 and w.scheduler.delays == [90]
    _solve_one(w.api, sid)
    w.settle()
    assert len(w.lichess.batch_calls) == 2
    w.scheduler.run_next()
    w.settle()
    assert data(w.api.get_sync_status())["pending"] == 0
