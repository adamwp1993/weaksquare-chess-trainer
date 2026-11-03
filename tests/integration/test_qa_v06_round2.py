"""QA v0.6 round 2 (qa/QA-v0.6.md): edges of the round-1 fixes B1, B3, B4, B5 and B6, over the bridge with
the fixture puzzles and the fake engine."""

from __future__ import annotations

import threading
from typing import Any

from tests.fakes.engine import FakeEngine, plant_managed_install
from tests.integration.test_modes_v06 import OPEN, _danger_session, _until, api, err, ok, state, wrong_move
from weaksquare.core.clock import FixedClock
from weaksquare.core.engine import EngineError
from weaksquare.core.modes.danger import DangerState

__all__ = ["api"]


def _engine() -> FakeEngine:
    return FakeEngine.instances[-1]


# ---- B1: every Danger load does the same engine work ----------------------------------------------


def test_b1_every_load_is_one_multipv_search_of_the_raw_position(api, paths) -> None:  # type: ignore[no-untyped-def]
    sid = _danger_session(api, paths)
    for _ in range(12):
        n0 = len(_engine().calls) if FakeEngine.instances else 0
        ok(api.next_puzzle(sid))
        st: DangerState = state(api, sid)
        new = _engine().calls[n0:]
        assert [(fen, mpv) for fen, _, mpv in new] == [(st.start_fen, 5)], (st.is_safe, new)


# ---- B3: one refutation search, shared, and its failure ------------------------------------------


def _lost_with_engine(api: Any, paths: Any, clock: FixedClock) -> tuple[int, Any]:
    plant_managed_install(paths)
    sid = ok(api.start_session(OPEN))["session_id"]
    ok(api.next_puzzle(sid))
    st = state(api, sid)
    clock.advance(seconds=10)
    ok(api.submit_move(sid, wrong_move(st.board.fen(), st.puzzle.moves[1])))
    ok(api.request_help(sid, "hint"))
    ok(api.request_help(sid, "answer"))
    ok(api.analyze_position(sid, st.board.fen(), "panel"))  # start the engine process
    return sid, st


def test_b3_a_failed_shared_search_errors_both_callers_and_can_be_retried(api, paths, clock: FixedClock) -> None:  # type: ignore[no-untyped-def]
    sid, _ = _lost_with_engine(api, paths, clock)
    eng = _engine()
    gate = threading.Event()
    eng.gate, eng.fail = gate, EngineError("crashed")
    eng.entered.clear()
    out: dict[str, Any] = {}
    t1 = threading.Thread(target=lambda: out.setdefault("a", api.get_refutation(sid)))
    t1.start()
    assert eng.entered.wait(5)
    t2 = threading.Thread(target=lambda: out.setdefault("b", api.get_refutation(sid)))
    t2.start()
    t2.join(0.3)
    gate.set()
    t1.join(10)
    t2.join(10)
    assert not t1.is_alive() and not t2.is_alive(), "a caller hung"
    assert not out["a"]["ok"] and not out["b"]["ok"]
    eng.gate, eng.fail = None, None
    assert ok(api.get_refutation(sid))["line"]  # nothing left stuck: the next ask searches again


def test_b3_waiting_caller_after_moving_on_doesnt_hang(api, paths, clock: FixedClock) -> None:  # type: ignore[no-untyped-def]
    sid, _ = _lost_with_engine(api, paths, clock)
    eng = _engine()
    gate = threading.Event()
    eng.gate = gate
    eng.entered.clear()
    out: dict[str, Any] = {}
    t1 = threading.Thread(target=lambda: out.setdefault("a", api.get_refutation(sid)))
    t1.start()
    assert eng.entered.wait(5)
    t2 = threading.Thread(target=lambda: out.setdefault("b", api.get_reason_prompt(sid)))
    t2.start()
    t2.join(0.3)
    nxt: dict[str, Any] = {}
    t3 = threading.Thread(target=lambda: nxt.setdefault("n", api.next_puzzle(sid)))  # move on mid-search
    t3.start()
    t3.join(0.3)
    gate.set()
    for t in (t1, t2, t3):
        t.join(15)
        assert not t.is_alive(), "hung"
    assert nxt["n"]["ok"]
    assert out["b"]["ok"]  # the prompt degrades to no refutation-based suggestion, never an error


# ---- B4: think time starts when the move has been animated ------------------------------------------


def test_b4_reply_delay_is_not_think_time_for_the_second_move(api, clock: FixedClock) -> None:  # type: ignore[no-untyped-def]
    sid = ok(api.start_session(OPEN))["session_id"]
    for _ in range(30):
        ok(api.next_puzzle(sid))
        st = state(api, sid)
        if len(st.puzzle.moves) >= 4:
            break
    clock.advance(seconds=10)
    ok(api.submit_move(sid, st.puzzle.moves[1]))  # right; the reply animates 300 ms later
    clock.advance(seconds=3.2)  # 2.9 s after the reply appeared
    ok(api.submit_move(sid, wrong_move(st.board.fen(), st.puzzle.moves[3])))
    ok(api.request_help(sid, "answer"))
    assert ok(api.get_reason_prompt(sid))["suggested"] == "rushed"  # rushed beats miscalculated


def test_b4_commit_submit_counts_from_after_the_opponent_move(api, clock: FixedClock) -> None:  # type: ignore[no-untyped-def]
    sid = ok(api.start_session(OPEN, True, "commit_line"))["session_id"]
    ok(api.next_puzzle(sid))
    st = state(api, sid)
    clock.advance(seconds=3.3)  # 2.8 s after the opponent's move
    bad = wrong_move(st.board.fen(), st.puzzle.moves[1])
    r = ok(api.submit_line(sid, [bad]))
    assert not r["outcome"]["win"]
    assert ok(api.get_reason_prompt(sid))["suggested"] == "rushed"


def test_b4_danger_call_has_no_animation_offset(api, paths, clock: FixedClock) -> None:  # type: ignore[no-untyped-def]
    sid = _danger_session(api, paths)
    _until(api, sid, True)
    clock.advance(seconds=3.2)  # Danger shows the raw position at once: 3.2 s is not rushed
    ok(api.call_danger(sid, "unsafe"))
    assert ok(api.get_reason_prompt(sid))["suggested"] is None


# ---- B5: whose side the evals are worded from ---------------------------------------------------------


def _scores(api: Any, sid: int, fen: str) -> str:
    return str(ok(api.analyze_position(sid, fen, "start"))["lines"][0]["score"])


def test_b5_engine_panel_after_a_refutation_is_for_the_punisher_and_after_a_safe_call_for_the_mover(api, paths) -> None:  # type: ignore[no-untyped-def]
    import chess

    sid = _danger_session(api, paths)
    st = _until(api, sid, False)
    ok(api.call_danger(sid, "unsafe"))
    ok(api.submit_move(sid, st.puzzle.moves[1]))
    after = chess.Board(st.puzzle.fen)
    after.push_uci(st.puzzle.moves[0])
    punisher = "white" if after.turn == chess.WHITE else "black"
    engine = api._sessions._engine
    shown = _scores(api, sid, after.fen())
    assert shown == engine.analyse(after, punisher, multipv=1).lines[0].score

    st2 = _until(api, sid, False)
    ok(api.call_danger(sid, "safe"))  # wrong call on the blunder: you stayed the mover
    board = chess.Board(st2.puzzle.fen)
    mover = "white" if board.turn == chess.WHITE else "black"
    assert _scores(api, sid, board.fen()) == engine.analyse(board, mover, multipv=1).lines[0].score


# ---- B6 -----------------------------------------------------------------------------------------------


def test_b6_all_time_still_counts_other_modes_and_misclicks_apart(api, paths, clock: FixedClock) -> None:  # type: ignore[no-untyped-def]
    sid = ok(api.start_session(OPEN))["session_id"]
    ok(api.next_puzzle(sid))
    st = state(api, sid)
    clock.advance(seconds=10)
    aid = ok(api.submit_move(sid, wrong_move(st.board.fen(), st.puzzle.moves[1])))["outcome"]["attempt_id"]
    ok(api.set_mistake_reason(aid, "misclick"))
    d = _danger_session(api, paths)
    _until(api, d, False)
    ok(api.call_danger(d, "safe"))
    bar = ok(api.get_session_stats(d))
    assert (bar["failed"], bar["all_time_failed"], bar["all_time_solved"]) == (1, 0, 0)
    assert err(api.get_reason_stats(None, "nope")) == "invalid_argument"
