"""QA v0.10 with the real Stockfish 19 (`uv run pytest -m engine`): a whole game through the one pipeline
(analysis on the background engine, tags, the puzzle hook), for Missed (you are White and miss 8.Rd8#) and
Allowed (you are Black and allow it with 7...Qh6??). Checks the side to move, the solver and the solution."""

from __future__ import annotations

import chess
import pytest

from tests.engine.test_game_analysis_real import real_services  # noqa: F401 - fixture
from weaksquare.adapters.db.repos.game_analysis import GameAnalysisRepo
from weaksquare.core.filters import FilterSpec

pytestmark = pytest.mark.engine

GAME = (
    '[White "player_a"]\n[Black "opponent_b"]\n[Result "*"]\n[SetUp "1"]\n'
    '[FEN "1n4k1/ppp2ppp/5q2/4p3/8/8/PPP2PPP/RN1R2K1 w - - 0 1"]\n\n'
    "1. a3 a6 2. Nd2 b6 3. a4 Nd7 4. Nb1 Nb8 5. h3 c6 6. g3 c5 7. c3 Qh6 8. Kg2 Qf6 *\n"
)
BEFORE_QH6 = "1n4k1/5ppp/pp3q2/2p1p3/P7/2P3PP/1P3P2/RN1R2K1 b - - 0 7"
AFTER_QH6 = "1n4k1/5ppp/pp5q/2p1p3/P7/2P3PP/1P3P2/RN1R2K1 w - - 1 8"
MINE = FilterSpec(source="my", exclude_solved_here=False, exclude_played_on_lichess=False)


def _analyze(s, runner, color: str) -> int:  # type: ignore[no-untyped-def]
    gid = int(s.games.import_pgn(GAME).game_id)
    s.games.set_user_color(gid, color)
    st = runner.wait(s.analysis.queue([gid]), 120)
    assert st is not None and st.state == "done", st
    return gid


def _puzzles(s) -> list[tuple]:  # type: ignore[no-untyped-def,type-arg]
    with s.db.session() as conn:
        return conn.execute(
            "SELECT ply, fen, solution_uci, player_color, solve_as, kind, origin, status, themes FROM custom_puzzles"
            " ORDER BY ply"
        ).fetchall()


def test_qa_a_missed_mate_in_a_real_game_becomes_your_puzzle(real_services) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    s, runner = real_services
    gid = _analyze(s, runner, "white")
    row = GameAnalysisRepo(s.db).rows(gid)[14]
    assert row.move_san == "Kg2" and row.classification == "blunder" and row.kind == "missed"
    pz = [p for p in _puzzles(s) if p[0] == 14]
    assert pz, _puzzles(s)
    _ply, fen, sol, color, solve_as, kind, origin, status, themes = pz[0]
    assert (fen, sol, color, solve_as, kind, origin, status) == (
        AFTER_QH6,
        "d1d8",
        "white",
        "you",
        "missed",
        "coach",
        "active",
    )
    assert chess.Board(fen).turn == chess.WHITE and "mateIn1" in themes.split()
    assert all(p[3] == "white" or p[4] == "opponent" for p in _puzzles(s))  # nothing from Black's own errors as yours
    view = s.sessions.next_puzzle(s.sessions.start(MINE).session_id)
    assert view.player_color == "white" and not view.solve_as_opponent


@pytest.mark.xfail(
    strict=True,
    reason="v0.10-B2: from a +1.5 position, a blunder that allows mate is classed Missed (EDGE rule), so no Allowed puzzle",
)
def test_qa_an_allowed_mate_in_a_real_game_is_solved_as_your_opponent(real_services) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    s, runner = real_services
    gid = _analyze(s, runner, "black")
    row = GameAnalysisRepo(s.db).rows(gid)[13]
    assert row.fen_before == BEFORE_QH6 and row.classification == "blunder" and row.kind == "allowed"
    pz = [p for p in _puzzles(s) if p[0] == 13]
    assert pz, _puzzles(s)
    fen, sol, color, solve_as, kind = pz[0][1:6]
    assert (fen, sol, color, solve_as, kind) == (AFTER_QH6, "d1d8", "white", "opponent", "allowed")
    sid = s.sessions.start(MINE).session_id
    view = s.sessions.next_puzzle(sid)
    while view.game_ply != 13:
        view = s.sessions.next_puzzle(sid)
    assert view.player_color == "white" and view.solve_as_opponent  # board from White's side: you play them
    assert s.sessions.submit_move(sid, "d1d8").outcome.win
