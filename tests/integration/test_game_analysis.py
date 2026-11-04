"""v0.8 analysis queue on the background engine (FR-11.8, 11.9, 11.31; ARCHITECTURE §3 decision 12): every
ply graded and stored, the same settings never analyzed twice, cancel, one job at a time, and a puzzle
refutation that stays prompt while a game is being analyzed."""

from __future__ import annotations

import threading
import time

import pytest

from tests.fakes.engine import FakeEngine, plant_managed_install
from tests.integration.test_engine_service import start, wrong_move
from weaksquare.adapters.db.repos.game_analysis import GameAnalysisRepo
from weaksquare.core.errors import ValidationError

MATE = '[White "player_a"]\n[Black "opponent_b"]\n[Result "1-0"]\n[TimeControl "180+0"]\n\n1. e4 { [%clk 0:02:59] } e5 { [%clk 0:02:58] } 2. Qh5 { [%clk 0:02:50] } Nc6 { [%clk 0:02:40] } 3. Bc4 { [%clk 0:02:45] } Nf6 { [%clk 0:00:10] } 4. Qxf7# { [%clk 0:02:40] } 1-0\n'
TRAP = '[White "player_a"]\n[Black "opponent_c"]\n[Result "0-1"]\n\n1. e4 e5 2. Nf3 Nc6 3. Bc4 Nd4 4. Nxe5 Qg5 5. Nxf7 Qxg2 6. Rf1 Qxe4+ 7. Be2 Nf3# 0-1\n'


@pytest.fixture(autouse=True)
def _reset() -> None:
    FakeEngine.instances.clear()


def _wait(services, job: str | None) -> str:  # type: ignore[no-untyped-def]
    assert job is not None
    from weaksquare.jobs.runner import JobRunner

    runner: JobRunner = services.analysis._runner  # the same runner as the app's
    st = runner.wait(job, 10)
    assert st is not None
    return st.state


def _bg(services) -> FakeEngine:  # type: ignore[no-untyped-def]
    return next(e for e in FakeEngine.instances if e.options[0] == 6)  # 8 CPUs: 7 interactive threads, 6 here


def test_a_game_is_graded_ply_by_ply_on_the_background_engine(services, paths) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    gid = services.games.import_pgn(MATE).game_id
    assert _wait(services, services.analysis.queue([gid])) == "done"
    rows = GameAnalysisRepo(services.db).rows(gid)
    assert [r.move_san for r in rows] == ["e4", "e5", "Qh5", "Nc6", "Bc4", "Nf6", "Qxf7#"]
    assert rows[-1].eval_after.mate == 0  # the final mate is read from the board, not the engine
    assert rows[5].low_clock is True and rows[0].low_clock is False and rows[5].clock_s == 10.0
    assert all(r.phase == "opening" for r in rows)
    game = services.games.get(gid)
    assert (game.analysis_status, game.analysis_think_s, game.analysis_engine) == ("analyzed", 0.3, "Stockfish 19")
    bg = _bg(services)
    assert len(bg.calls) == 7  # every position before a move; the mated final position needs no search
    assert {c[1:] for c in bg.calls} == {(0.3, 3)}  # 0.3 s per position, MultiPV 3 (FR-11.8)


def test_the_same_settings_are_never_analyzed_twice(services, paths) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    gid = services.games.import_pgn(MATE).game_id
    _wait(services, services.analysis.queue([gid]))
    calls = len(_bg(services).calls)
    assert services.analysis.queue([gid]) is None  # FR-11.31
    again = services.games.import_pgn(MATE)  # a re-import reuses it too (FR-11.7)
    assert again.game_id == gid and again.analyzed and services.analysis.queue([again.game_id]) is None
    services.analysis.set_settings(think_s=0.5)  # new settings: it's no longer current
    assert not services.analysis.is_current(services.games.get(gid))
    _wait(services, services.analysis.queue([gid]))
    assert len(_bg(services).calls) == calls * 2 and services.games.get(gid).analysis_think_s == 0.5
    _wait(services, services.analysis.queue([gid], force=True))  # an explicit re-analysis still works


def test_games_queue_in_order_one_job_at_a_time(services, paths) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    a = services.games.import_pgn(MATE).game_id
    b = services.games.import_pgn(TRAP).game_id
    job = services.analysis.queue([a])
    job2 = services.analysis.queue([b, a])  # joins the running job; a isn't queued twice
    assert job2 == job
    assert _wait(services, job) == "done"
    assert services.games.get(a).analysis_status == "analyzed" and services.games.get(b).analysis_status == "analyzed"
    assert services.analysis.status().job_id is None


def test_cancel_stops_the_queue_and_keeps_nothing_partial(services, paths) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    a = services.games.import_pgn(MATE).game_id
    b = services.games.import_pgn(TRAP).game_id
    gate = threading.Event()
    FakeEngine.instances.clear()
    real_init = FakeEngine.__init__

    def gated(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        real_init(self, *args, **kwargs)
        self.gate = gate

    FakeEngine.__init__ = gated  # type: ignore[method-assign]
    try:
        job = services.analysis.queue([a, b])
        assert job is not None
        for _ in range(200):
            if FakeEngine.instances and FakeEngine.instances[0].entered.is_set():
                break
            time.sleep(0.01)
        st = services.analysis.status()
        assert st.current == a and st.waiting == (b,)
        services.analysis._runner.cancel(job)
        gate.set()
        assert _wait(services, job) == "cancelled"
    finally:
        FakeEngine.__init__ = real_init  # type: ignore[method-assign]
    assert GameAnalysisRepo(services.db).rows(a) == [] and services.games.get(a).analysis_status == "none"
    assert services.analysis.status().waiting == ()


def test_a_puzzle_refutation_is_prompt_while_a_game_is_analyzed(services, paths) -> None:  # type: ignore[no-untyped-def]
    """ROADMAP v0.8 Done when: interactive requests never wait behind background work."""
    plant_managed_install(paths)
    gid = services.games.import_pgn(TRAP).game_id
    gate = threading.Event()
    real_init = FakeEngine.__init__

    def gate_background(self, path="fake.exe", threads=1, hash_mb=16):  # type: ignore[no-untyped-def]
        real_init(self, path, threads, hash_mb)
        if threads == 6:  # the background engine only
            self.gate = gate

    FakeEngine.__init__ = gate_background  # type: ignore[method-assign]
    try:
        job = services.analysis.queue([gid])
        for _ in range(200):
            if any(e.entered.is_set() for e in FakeEngine.instances):
                break
            time.sleep(0.01)
        bg = _bg(services)
        assert bg.entered.is_set() and not gate.is_set()  # the analysis is mid-search, blocked

        sid, view, moves = start(services)
        services.sessions.submit_move(sid, wrong_move(view, moves))
        services.sessions.request_help(sid, "answer")
        t0 = time.monotonic()
        r = services.sessions.get_refutation(sid)
        assert time.monotonic() - t0 < 1.0 and r.line  # it never waited for the gated background engine
        interactive = [e for e in FakeEngine.instances if e is not bg]
        assert interactive and interactive[0].calls
    finally:
        gate.set()
        FakeEngine.__init__ = real_init  # type: ignore[method-assign]
    assert _wait(services, job) == "done"


def test_without_stockfish_the_job_fails_clearly(services) -> None:  # type: ignore[no-untyped-def]
    gid = services.games.import_pgn(MATE).game_id
    job = services.analysis.queue([gid])
    assert _wait(services, job) == "failed"
    st = services.analysis._runner.status(job)
    assert st.error_code == "engine_not_installed" and "Install Stockfish" in st.message


def test_review_settings_are_validated(services) -> None:  # type: ignore[no-untyped-def]
    st = services.analysis.set_settings(
        think_s=1.0, thresholds={"inaccuracy": 40, "mistake": 90, "blunder": 250}, tolerance_cp=20, key_moments=8
    )
    assert (st.think_s, st.thresholds.mistake, st.tolerance_cp, st.key_moments) == (1.0, 90, 20, 8)
    for bad in (
        {"think_s": 0.05},
        {"think_s": "1"},
        {"thresholds": {"inaccuracy": 100, "mistake": 50, "blunder": 200}},
        {"thresholds": {"inaccuracy": 50}},
        {"tolerance_cp": 500},
        {"key_moments": 0},
        {"key_moments": 11},
    ):
        with pytest.raises(ValidationError):
            services.analysis.set_settings(**bad)
    with pytest.raises(ValidationError):
        services.analysis.queue(["1"])  # type: ignore[list-item]
