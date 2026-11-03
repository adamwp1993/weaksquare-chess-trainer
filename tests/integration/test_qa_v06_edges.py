"""QA v0.6 (independent pass, qa/QA-v0.6.md): edge cases for Name the idea first (FR-4.3), Danger spotting
(FR-4.4) and mistake reasons (§7.3), over the bridge with a real user.db, the fixture puzzles and the fake
engine. Tests marked xfail(strict=True) pin a reported bug and flip to a failure once it's fixed."""

from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any

import chess
import pytest

from tests.fakes.engine import FakeEngine
from tests.integration.test_modes_v06 import OPEN, _danger_session, _until, api, err, ok, rows, state, wrong_move
from weaksquare.core.clock import FixedClock
from weaksquare.core.engine import EngineError
from weaksquare.core.modes.danger import DangerState

__all__ = ["api"]  # the fixture, re-used


def _engine() -> FakeEngine:
    return FakeEngine.instances[-1]


# ---- Danger spotting: nothing gives the answer away before the end (FR-4.4) -------------------------


# Regression test for v0.6-B1 (fixed in QA round 1).
def test_b1_loading_a_danger_puzzle_does_the_same_work_whatever_the_answer(api, paths) -> None:  # type: ignore[no-untyped-def]
    """The time a Danger puzzle takes to appear must not depend on whether its candidate is safe:
    otherwise a slow load means "Safe" and an instant one means "Unsafe"."""
    sid = _danger_session(api, paths)
    work: dict[bool, set[int]] = {True: set(), False: set()}
    calls_before = 0
    for _ in range(16):
        if FakeEngine.instances:
            calls_before = len(_engine().calls)
        ok(api.next_puzzle(sid))
        st: DangerState = state(api, sid)
        made = len(_engine().calls) - calls_before if FakeEngine.instances else 0
        work[st.is_safe].add(made)
    assert work[True] and work[False]
    assert work[True] == work[False], f"engine searches per load: safe {work[True]}, blunder {work[False]}"


def test_nothing_before_the_call_reveals_the_truth(api, paths) -> None:  # type: ignore[no-untyped-def]
    sid = _danger_session(api, paths)
    st = _until(api, sid, False)
    blunder = st.puzzle.moves[0]
    # every read the front end can make before the call
    stats = ok(api.get_session_stats(sid))
    assert blunder not in json.dumps(stats)
    assert err(api.request_help(sid, "hint")) == "conflict"  # no Hint before the call
    assert err(api.get_refutation(sid)) == "conflict"
    assert err(api.analyze_position(sid, st.puzzle.fen, "start")) == "conflict"
    assert err(api.analyze_position(sid, st.puzzle.fen, "board")) == "conflict"
    assert ok(api.get_reason_prompt(sid)) is None
    assert err(api.submit_move(sid, st.candidate)) == "conflict"  # moving before the call
    assert err(api.retry_puzzle(sid)) == "conflict"


def test_show_answer_before_the_call_is_a_loss_with_no_suggestion(api, paths, clock: FixedClock) -> None:  # type: ignore[no-untyped-def]
    sid = _danger_session(api, paths)
    st = _until(api, sid, False)
    clock.advance(seconds=1)
    help_ = ok(api.request_help(sid, "answer"))
    assert help_["outcome"] and not help_["outcome"]["win"]
    assert help_["outcome"]["danger"]["is_safe"] is False and help_["outcome"]["danger"]["call"] is None
    assert help_["answer_moves"][0] == st.puzzle.moves[0]
    assert err(api.call_danger(sid, "unsafe")) == "conflict"  # decided: no call after the answer
    prompt = ok(api.get_reason_prompt(sid))
    assert prompt["source"] == "danger" and prompt["suggested"] is None  # help decided it: not "rushed"
    got = rows(paths, "SELECT win, help_used, danger_call, sync_status FROM attempts ORDER BY id DESC LIMIT 1")
    assert got == [(0, "answer", None, "local")]


def test_moving_on_before_the_call_is_a_local_loss(api, paths) -> None:  # type: ignore[no-untyped-def]
    sid = _danger_session(api, paths)
    _until(api, sid, True)
    n = len(rows(paths, "SELECT id FROM attempts"))
    ok(api.next_puzzle(sid))
    got = rows(paths, "SELECT mode, win, danger_safe, danger_call, sync_status FROM attempts ORDER BY id")
    assert len(got) == n + 1 and got[-1] == ("danger_spotting", 0, 1, None, "local")


def test_rated_is_forced_off_and_nothing_is_ever_queued(api, paths) -> None:  # type: ignore[no-untyped-def]
    sid = _danger_session(api, paths)
    for _ in range(6):
        ok(api.next_puzzle(sid))
        ok(api.call_danger(sid, "safe"))
    got = rows(paths, "SELECT DISTINCT sync_status, rated, angle FROM attempts")
    assert got == [("local", None, None)]


def test_danger_is_refused_with_the_depth_ladder(api, paths) -> None:  # type: ignore[no-untyped-def]
    sid = _danger_session(api, paths)
    assert err(api.start_session({**OPEN, "order": "depth_ladder"}, True, "danger_spotting")) == "invalid_argument"
    ok(api.next_puzzle(sid))
    assert sid


def test_an_engine_failure_shows_the_blunder_and_owes_a_safe_one(api, paths) -> None:  # type: ignore[no-untyped-def]
    # Since v0.6-B1 every load runs the search, so a failure can hit any puzzle: while the engine fails, every
    # puzzle shows the blunder, and once a safe slot was drawn during that, the next puzzle is owed one.
    sid = _danger_session(api, paths)
    ok(api.next_puzzle(sid))
    eng = _engine()
    eng.fail = EngineError("crashed")
    session = api._sessions._session(sid)
    for _ in range(8):
        ok(api.next_puzzle(sid))
        st: DangerState = state(api, sid)
        assert not st.is_safe  # no verified safe move: the blunder
        if session.owed_safe:
            break
    assert session.owed_safe, "no safe slot drawn in 8 failed loads (seeded rng)"
    eng.fail = None
    ok(api.next_puzzle(sid))
    st = state(api, sid)
    assert st.is_safe  # the owed safe candidate


def test_a_danger_win_doesnt_hide_the_puzzle_from_exclude_solved_here(api, paths) -> None:  # type: ignore[no-untyped-def]
    spec = {**OPEN, "exclude_solved_here": True}
    total = ok(api.count_matches(spec))
    sid = _danger_session(api, paths)
    st = _until(api, sid, True)
    assert ok(api.call_danger(sid, "safe"))["outcome"]["win"]
    assert ok(api.count_matches(spec)) == total
    st2 = _until(api, sid, False)
    ok(api.call_danger(sid, "unsafe"))
    assert ok(api.submit_move(sid, st2.puzzle.moves[1]))["outcome"]["win"]
    assert ok(api.count_matches(spec)) == total
    assert st.puzzle.ref.id


def test_a_danger_miss_after_a_standard_miss_keeps_it_in_only_my_misses(api, paths, clock: FixedClock) -> None:  # type: ignore[no-untyped-def]
    """The latest *non-Danger* attempt decides Only my misses: a Danger win doesn't clear a real miss."""
    sid = ok(api.start_session(OPEN))["session_id"]
    ok(api.next_puzzle(sid))
    st = state(api, sid)
    ok(api.submit_move(sid, wrong_move(st.board.fen(), st.puzzle.moves[1])))
    missed = {**OPEN, "only_my_misses": True}
    assert ok(api.count_matches(missed)) == 1
    # a Danger win on the same puzzle, written as the app would
    conn = sqlite3.connect(paths.user_db)
    try:
        conn.execute(
            "INSERT INTO attempts (puzzle_source, puzzle_id, session_id, mode, started_at, finished_at, win,"
            " help_used, first_move_correct, line_correct, time_ms, sync_status)"
            " VALUES ('lichess', ?, ?, 'danger_spotting', '2026-01-01T12:00:00', '2026-01-01T12:00:05', 1,"
            " 'none', 1, 1, 5000, 'local')",
            (st.puzzle.ref.id, sid),
        )
        conn.commit()
    finally:
        conn.close()
    assert ok(api.count_matches(missed)) == 1
    clock.advance(days=2)
    assert ok(api.get_srs_status())["scheduled"] == 1  # the Danger win doesn't move its box either


# ---- Name the idea first (FR-4.3) -------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["fork", {"a": 1}, 5, None, [1, 2], ["fork", "pin", "skewer", "attraction"]])
def test_set_idea_tags_with_bad_types_is_invalid_not_internal(api, bad) -> None:  # type: ignore[no-untyped-def]
    sid = ok(api.start_session(OPEN, True, "name_idea"))["session_id"]
    ok(api.next_puzzle(sid))
    assert err(api.set_idea_tags(sid, ["deflection"], bad)) == "invalid_argument"
    ok(api.set_idea_tags(sid, ["deflection"], ["fork", "fork", "fork", "fork"]))  # duplicates collapse to one


def test_tags_after_the_puzzle_is_decided_are_refused(api) -> None:  # type: ignore[no-untyped-def]
    sid = ok(api.start_session(OPEN, True, "name_idea"))["session_id"]
    ok(api.next_puzzle(sid))
    ok(api.set_idea_tags(sid, [], ["fork"]))
    assert err(api.set_idea_tags(sid, [], ["pin"])) == "conflict"  # once per puzzle
    assert err(api.call_danger(sid, "safe")) == "conflict"  # wrong mode


def test_unknown_pattern_is_suggested_when_no_tag_was_a_motif(api, clock: FixedClock) -> None:  # type: ignore[no-untyped-def]
    from weaksquare.core.themes import IDEA_PAYOFF, motif_themes

    sid = ok(api.start_session(OPEN, True, "name_idea"))["session_id"]
    for _ in range(30):
        ok(api.next_puzzle(sid))
        st = state(api, sid)
        if motif_themes(st.puzzle.themes):
            break
    wrong_tag = next(t for t in IDEA_PAYOFF if t not in st.puzzle.themes)
    ok(api.set_idea_tags(sid, [], [wrong_tag]))
    clock.advance(seconds=10)  # not rushed
    fb = ok(api.submit_move(sid, wrong_move(st.board.fen(), st.puzzle.moves[1])))
    out = fb["outcome"]
    assert out["idea"]["found"] == 0 and out["idea"]["extra"] == 1
    ok(api.request_help(sid, "answer"))
    assert ok(api.get_reason_prompt(sid))["suggested"] == "unknownPattern"  # no engine: no missedResource


def test_name_the_idea_rushed_counts_from_start_solving(api, clock: FixedClock) -> None:  # type: ignore[no-untyped-def]
    sid = ok(api.start_session(OPEN, True, "name_idea"))["session_id"]
    ok(api.next_puzzle(sid))
    st = state(api, sid)
    clock.advance(seconds=60)  # a long think while tagging…
    ok(api.set_idea_tags(sid, [], ["fork"]))
    clock.advance(seconds=1)  # …then a fast wrong move
    ok(api.submit_move(sid, wrong_move(st.board.fen(), st.puzzle.moves[1])))
    ok(api.request_help(sid, "answer"))
    assert ok(api.get_reason_prompt(sid))["suggested"] == "rushed"


# ---- mistake reasons (§7.3) -------------------------------------------------------------------------


def test_rushed_at_exactly_the_threshold_is_not_rushed_in_danger(api, paths, clock: FixedClock) -> None:  # type: ignore[no-untyped-def]
    sid = _danger_session(api, paths)
    _until(api, sid, True)
    clock.advance(seconds=3)
    ok(api.call_danger(sid, "unsafe"))  # wrong: it was safe
    assert ok(api.get_reason_prompt(sid))["suggested"] is None
    _until(api, sid, True)
    clock.advance(seconds=2.9)
    ok(api.call_danger(sid, "unsafe"))
    assert ok(api.get_reason_prompt(sid))["suggested"] == "rushed"


def test_reasons_off_never_asks_in_danger_either(api, paths) -> None:  # type: ignore[no-untyped-def]
    ok(api.set_setting("reasons.ask", "off"))
    sid = _danger_session(api, paths)
    _until(api, sid, False)
    ok(api.call_danger(sid, "safe"))
    assert ok(api.get_reason_prompt(sid)) is None


def test_reason_for_an_earlier_puzzle_is_saved_without_a_suggestion(api, paths, clock: FixedClock) -> None:  # type: ignore[no-untyped-def]
    sid = ok(api.start_session(OPEN))["session_id"]
    ok(api.next_puzzle(sid))
    st = state(api, sid)
    clock.advance(seconds=1)
    aid = ok(api.submit_move(sid, wrong_move(st.board.fen(), st.puzzle.moves[1])))["outcome"]["attempt_id"]
    ok(api.request_help(sid, "answer"))
    ok(api.get_reason_prompt(sid))
    ok(api.next_puzzle(sid))  # moved on
    ok(api.set_mistake_reason(aid, "didntLook", "<b>html</b> stays text"))
    got = rows(paths, "SELECT reason, suggested_reason, note FROM mistake_reasons")
    assert got == [("didntLook", None, "<b>html</b> stays text")]


def test_practice_run_keeps_the_original_attempts_prompt(api, clock: FixedClock) -> None:  # type: ignore[no-untyped-def]
    sid = ok(api.start_session(OPEN))["session_id"]
    ok(api.next_puzzle(sid))
    st = state(api, sid)
    clock.advance(seconds=10)
    aid = ok(api.submit_move(sid, wrong_move(st.board.fen(), st.puzzle.moves[1])))["outcome"]["attempt_id"]
    ok(api.request_help(sid, "answer"))
    ok(api.retry_puzzle(sid))
    # mid-practice the puzzle isn't over: no prompt yet
    assert ok(api.get_reason_prompt(sid)) is None
    ok(api.request_help(sid, "hint"))
    ok(api.request_help(sid, "answer"))
    p = ok(api.get_reason_prompt(sid))
    assert p["attempt_id"] == aid  # practice never creates its own prompt (FR-5.8)


def test_misclick_is_excluded_from_stats_by_mode_details_and_reason_stats(api, paths, clock: FixedClock) -> None:  # type: ignore[no-untyped-def]
    sid = _danger_session(api, paths)
    _until(api, sid, False)
    aid = ok(api.call_danger(sid, "safe"))["outcome"]["attempt_id"]
    before = ok(api.get_stats())
    danger_before = next(m for m in before["by_mode"] if m["key"] == "danger_spotting")
    ok(api.set_mistake_reason(aid, "misclick"))
    after = ok(api.get_stats())
    danger_after = next((m for m in after["by_mode"] if m["key"] == "danger_spotting"), None)
    assert after["misclicks"] == 1
    assert (danger_after["attempts"] if danger_after else 0) == danger_before["attempts"] - 1
    d0, d1 = before["details"], after["details"]
    assert d1["danger_blunder"] == d0["danger_blunder"] - 1
    r = ok(api.get_reason_stats(None, "danger_spotting"))
    assert (r["tagged"], r["misclicks"]) == (0, 1)


def test_misclick_warning_appears_at_a_quarter_of_eight(api, paths, clock: FixedClock) -> None:  # type: ignore[no-untyped-def]
    sid = ok(api.start_session({**OPEN, "exclude_solved_here": False}))["session_id"]
    ids = []
    for _ in range(8):
        ok(api.next_puzzle(sid))
        st = state(api, sid)
        clock.advance(seconds=10)
        ids.append(ok(api.submit_move(sid, wrong_move(st.board.fen(), st.puzzle.moves[1])))["outcome"]["attempt_id"])
    for aid in ids[:6]:
        ok(api.set_mistake_reason(aid, "didntLook"))
    ok(api.set_mistake_reason(ids[6], "misclick"))
    assert ok(api.get_stats())["misclick_warning"] is False  # 1 of 7 tagged
    ok(api.set_mistake_reason(ids[7], "misclick"))
    assert ok(api.get_stats())["misclick_warning"] is True  # 2 of 8 = 25%
    assert ok(api.get_reason_stats())["misclick_warning"] is True


def test_the_sync_code_never_reads_mistake_reasons() -> None:
    from pathlib import Path

    import weaksquare

    root = Path(weaksquare.__file__).parent
    for rel in ("services/sync.py", "adapters/db/repos/lichess.py", "adapters/lichess_client.py"):
        p = root / rel
        if p.exists():
            assert "mistake_reasons" not in p.read_text(encoding="utf-8"), rel


# ---- builder concern: the refutation searched twice ---------------------------------------------------


# Regression test for v0.6-B3 (fixed in QA round 1).
def test_b3_reason_prompt_and_why_it_fails_share_one_refutation_search(api, paths, clock: FixedClock) -> None:  # type: ignore[no-untyped-def]
    from tests.fakes.engine import plant_managed_install

    plant_managed_install(paths)
    sid = ok(api.start_session(OPEN))["session_id"]
    ok(api.next_puzzle(sid))
    st = state(api, sid)
    clock.advance(seconds=10)
    ok(api.submit_move(sid, wrong_move(st.board.fen(), st.puzzle.moves[1])))
    ok(api.request_help(sid, "hint"))
    # Show answer: the front end asks for the refutation (panel) and, the puzzle being over, the prompt
    ok(api.request_help(sid, "answer"))
    eng = _engine() if FakeEngine.instances else None
    n0 = len(eng.calls) if eng else 0
    gate = threading.Event()
    if eng is None:  # the engine starts on first use; make it now
        ok(api.analyze_position(sid, st.board.fen(), "panel"))
        eng = _engine()
        n0 = len(eng.calls)
    eng.gate = gate
    eng.entered.clear()
    out: dict[str, Any] = {}
    t1 = threading.Thread(target=lambda: out.setdefault("ref", api.get_refutation(sid)))
    t1.start()
    assert eng.entered.wait(5)
    t2 = threading.Thread(target=lambda: out.setdefault("prompt", api.get_reason_prompt(sid)))
    t2.start()
    t2.join(0.3)
    gate.set()
    t1.join(10)
    t2.join(10)
    assert out["ref"]["ok"] and out["prompt"]["ok"]
    searched = [c for c in eng.calls[n0:] if c[2] == 1]
    first = searched[0][0] if searched else None
    assert sum(1 for c in searched if c[0] == first) == 1, f"{len(searched)} refutation searches"
    assert chess.Board(first) if first else True


# Regression test for v0.6-B5 (fixed in QA round 1).
def test_b5_danger_wrong_refutation_is_explained_from_the_punishing_side(api, paths) -> None:  # type: ignore[no-untyped-def]
    sid = _danger_session(api, paths)
    st = _until(api, sid, False)
    ok(api.call_danger(sid, "unsafe"))
    after_blunder = st.board.fen()
    wrong = wrong_move(after_blunder, st.puzzle.moves[1])
    fb = ok(api.submit_move(sid, wrong))
    assert fb["kind"] == "wrong" and not fb["outcome"]["win"]
    help_ = ok(api.request_help(sid, "answer"))
    assert help_["refute"] is True  # the front end now loads "Why <move> fails"
    ref = ok(api.get_refutation(sid))
    board = chess.Board(after_blunder)
    board.push_uci(wrong)
    punisher = "white" if chess.Board(after_blunder).turn == chess.WHITE else "black"
    blunderer = "black" if punisher == "white" else "white"
    engine = api._sessions._engine
    for_you = engine.analyse(board, punisher, multipv=1).lines[0].score
    for_them = engine.analyse(board, blunderer, multipv=1).lines[0].score
    assert for_you != for_them
    assert ref["score"] == for_you, f"shown {ref['score']!r}; for you {for_you!r}, for the blunderer {for_them!r}"
