"""QA v0.4 (rc2, Adam's manual-test changes): FR-5.12 Try again over the bridge. A practice run records
nothing (attempts, sync queue, session stats, Stats), the engine stays refused until the practice run
ends (FR-7.3), and Standard-mode scoring is unchanged. Written by the independent QA pass."""

from __future__ import annotations

import shutil
import sqlite3

import chess
import pytest

from tests.fakes.engine import FakeEngine, plant_managed_install
from tests.helpers import build_api


@pytest.fixture(autouse=True)
def _reset() -> None:
    FakeEngine.instances.clear()


def _api(paths, clock, fixture_puzzles_db):  # type: ignore[no-untyped-def]
    from weaksquare import config
    from weaksquare.adapters.db.migrate import migrate

    shutil.copyfile(fixture_puzzles_db, paths.puzzles_db)
    migrate(paths.user_db, config.MIGRATIONS_DIR / "user", clock)
    return build_api(paths, clock)


def _moves(api, sid) -> list[str]:  # type: ignore[no-untyped-def]
    s = api._sessions._session(sid)
    with s.lock:
        return list(s.current.state.puzzle.moves)


def _long_puzzle(api):  # type: ignore[no-untyped-def]
    sid = api.start_session({"queue_size": 50})["data"]["session_id"]
    for _ in range(50):
        view = api.next_puzzle(sid)["data"]
        if len(_moves(api, sid)) >= 4:
            board = chess.Board(view["fen"])
            board.push_uci(view["opponent_move"])
            return sid, board
    pytest.fail("no 4-ply puzzle")


def _wrong(board: chess.Board, right: str) -> str:
    return next(m.uci() for m in board.legal_moves if m.uci() != right and not board.gives_check(m))


def _snapshot(paths, api, sid):  # type: ignore[no-untyped-def]
    conn = sqlite3.connect(paths.user_db)
    try:
        rows = conn.execute("SELECT * FROM attempts ORDER BY id").fetchall()
    finally:
        conn.close()
    return rows, api.get_session_stats(sid)["data"], api.get_stats()["data"]


def _refused(r: dict) -> bool:
    return (not r["ok"]) and r["error"]["code"] == "conflict"


def test_qa_practice_records_nothing_and_hides_the_engine(paths, clock, fixture_puzzles_db) -> None:  # type: ignore[no-untyped-def]
    api = _api(paths, clock, fixture_puzzles_db)
    plant_managed_install(paths)
    sid, board = _long_puzzle(api)
    moves = _moves(api, sid)
    start = board.fen()

    # Try again before the end is refused (FR-5.12)
    assert _refused(api.retry_puzzle(sid))
    first = api.submit_move(sid, _wrong(board, moves[1]))["data"]
    assert first["kind"] == "wrong" and first["outcome"] is not None  # the real attempt: a loss
    assert _refused(api.retry_puzzle(sid))  # decided but not over: still refused
    for uci in moves[1::2]:
        api.submit_move(sid, uci)
    before = _snapshot(paths, api, sid)

    # practice run 1: wrong move, correct move, hint, answer
    assert api.retry_puzzle(sid)["ok"]
    for purpose in ("start", "panel", "board"):
        assert _refused(api.analyze_position(sid, start, purpose))  # FR-7.3 during practice
    assert _refused(api.get_refutation(sid))
    fb = api.submit_move(sid, _wrong(board, moves[1]))["data"]
    assert fb["kind"] == "wrong" and fb["outcome"] is None
    assert _refused(api.analyze_position(sid, start, "panel"))  # lost-but-playing is in progress
    fb = api.submit_move(sid, moves[1])["data"]
    assert fb["kind"] == "correct" and fb["outcome"] is None
    if len(moves) > 4:
        h = api.request_help(sid, "hint")["data"]
        assert h["outcome"] is None
        assert _refused(api.analyze_position(sid, start, "panel"))
    a = api.request_help(sid, "answer")["data"]
    assert a["outcome"] is None and a["refute"] is True
    assert api.analyze_position(sid, start, "start")["ok"]  # the practice run ended: allowed again
    assert api.get_refutation(sid)["ok"]
    assert _snapshot(paths, api, sid) == before

    # practice run 2: solved cleanly
    assert api.retry_puzzle(sid)["ok"]
    for uci in moves[1::2]:
        fb = api.submit_move(sid, uci)["data"]
        assert fb["outcome"] is None
    assert fb["kind"] == "solved"
    assert _snapshot(paths, api, sid) == before

    # practice run 3: Next mid-practice (a skip) records nothing for this puzzle
    assert api.retry_puzzle(sid)["ok"]
    api.submit_move(sid, _wrong(board, moves[1]))
    nxt = api.next_puzzle(sid)
    assert nxt["ok"]
    rows, stats, report = _snapshot(paths, api, sid)
    assert rows == before[0] and stats == before[1] and report == before[2]


def test_qa_standard_scoring_is_unchanged(paths, clock, fixture_puzzles_db) -> None:  # type: ignore[no-untyped-def]
    """The wrong-move branch changed (no decision when an attempt exists): a normal puzzle still records
    exactly one attempt per puzzle with the same fields as before."""
    api = _api(paths, clock, fixture_puzzles_db)
    sid, _board = _long_puzzle(api)
    moves = _moves(api, sid)
    ids = []
    # (a) clean solve -> win
    for uci in moves[1::2]:
        fb = api.submit_move(sid, uci)["data"]
    assert fb["kind"] == "solved" and fb["outcome"]["win"] is True
    ids.append(fb["outcome"]["attempt_id"])
    # (b) wrong, wrong again, then finish -> one loss, decided on the first wrong move
    sid2, b2 = _long_puzzle(api)
    m2 = _moves(api, sid2)
    o1 = api.submit_move(sid2, _wrong(b2, m2[1]))["data"]["outcome"]
    o2 = api.submit_move(sid2, _wrong(b2, m2[1]))["data"]["outcome"]
    assert o1 is not None and o1["win"] is False and o2 is None
    ids.append(o1["attempt_id"])
    for uci in m2[1::2]:
        assert api.submit_move(sid2, uci)["data"]["outcome"] is None
    # (c) hint then a wrong move -> decided once, by the hint
    sid3, b3 = _long_puzzle(api)
    m3 = _moves(api, sid3)
    h = api.request_help(sid3, "hint")["data"]["outcome"]
    assert h is not None
    ids.append(h["attempt_id"])
    assert api.submit_move(sid3, _wrong(b3, m3[1]))["data"]["outcome"] is None
    conn = sqlite3.connect(paths.user_db)
    try:
        rows = [
            conn.execute(
                "SELECT win, first_move_correct, line_correct, help_used FROM attempts WHERE id = ?", (i,)
            ).fetchone()
            for i in ids
        ]
        dup = conn.execute(
            "SELECT COUNT(*) FROM attempts WHERE session_id IN (?, ?, ?) GROUP BY session_id, puzzle_id"
            " HAVING COUNT(*) > 1",
            (sid, sid2, sid3),
        ).fetchall()
    finally:
        conn.close()
    assert rows == [(1, 1, 1, "none"), (0, 0, 0, "none"), (0, 0, 0, "hint")], rows
    assert dup == []  # one attempt per puzzle
