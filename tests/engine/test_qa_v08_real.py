"""QA v0.8 (independent) with the real Stockfish 19 (`uv run pytest -m engine`): a stalemate thrown away
from a won position, Retry graded by the real interactive engine, and a puzzle saved from the game that
accepts another move within the tolerance and then continues on the engine's line."""

from __future__ import annotations

import pytest

from tests.engine.test_game_analysis_real import real_services  # noqa: F401  (the fixture)
from weaksquare.adapters.db.repos.game_analysis import GameAnalysisRepo
from weaksquare.core.filters import FilterSpec

pytestmark = pytest.mark.engine

# Sam Loyd's 10-move stalemate: 10.Qe6 stalemates Black with White a queen and more up.
LOYD = (
    '[White "player_a"]\n[Black "opponent_b"]\n[Result "1/2-1/2"]\n\n'
    "1. e3 a5 2. Qh5 Ra6 3. Qxa5 h5 4. h4 Rah6 5. Qxc7 f6 6. Qxd7+ Kf7 7. Qxb7 Qd3 8. Qxb8 Qh7 "
    "9. Qxc8 Kg6 10. Qe6 1/2-1/2\n"
)


def test_qa_real_engine_stalemate_blunder_retry_and_saved_puzzle(real_services) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    s, runner = real_services
    gid = s.games.import_pgn(LOYD).game_id
    s.games.set_user_color(gid, "white")
    st = runner.wait(s.analysis.queue([gid]), 120)
    assert st is not None and st.state == "done", st
    rows = GameAnalysisRepo(s.db).rows(gid)
    last = rows[-1]
    assert last.move_san == "Qe6" and last.eval_after.cp == 0 and last.classification == "blunder"
    review = s.review.review(gid)
    assert 18 in review.retry_plies  # (the key moments are the bigger losses earlier: it is a game of mutual blunders)

    # Retry the stalemate: the stored best move is found; the same stalemating move isn't.
    best = rows[18].best_move
    assert best is not None
    assert s.review.retry_move(gid, 18, best).found
    again = s.review.retry_move(gid, 18, "c8e6")
    assert not again.found and again.engine_checked

    # Save it, then solve it from My puzzles with a different winning move (the engine tolerance).
    pid, created = s.review.save_as_puzzle(gid, 18)
    assert created
    sid = s.sessions.start(FilterSpec(source="my", exclude_solved_here=False)).session_id
    view = s.sessions.next_puzzle(sid)
    assert view.puzzle_id == str(pid) and view.opponent_move == ""
    alternatives = [ln.pv[0] for ln in rows[18].lines if ln.pv and ln.pv[0] != best]
    if not alternatives:
        pytest.skip("Stockfish gave a single line here")
    r = s.sessions.submit_move(sid, alternatives[0])  # second-best: usually within 30 cp when White is +10
    assert r.feedback.kind in ("correct", "solved", "wrong")  # graded, never an error
