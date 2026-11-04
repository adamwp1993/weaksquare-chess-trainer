"""v0.8 Game Review service: the review built from stored analysis (FR-11.11–11.14), Retry mode with the
tolerance (FR-11.15), Save as puzzle (FR-11.16), and mistake reasons on game moves (FR-5.7, 5.8)."""

from __future__ import annotations

import chess
import pytest

from tests.fakes.engine import FakeEngine, plant_managed_install
from tests.integration.test_engine_service import start, wrong_move
from weaksquare.adapters.db.repos.game_analysis import GameAnalysisRepo
from weaksquare.core.engine import EngineLine
from weaksquare.core.errors import ConflictError, ValidationError
from weaksquare.core.game_review import grade_game

SCHOLAR = '[White "opponent_b"]\n[Black "player_a"]\n[Result "1-0"]\n\n1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7# 1-0\n'
MOVES = ["e2e4", "e7e5", "d1h5", "b8c6", "f1c4", "g8f6", "h5f7"]


def L(cp: int | None, pv: str, mate: int | None = None) -> EngineLine:
    return EngineLine(cp=cp, mate=mate, pv=tuple(pv.split()))


ANALYSES = [
    [L(30, "e2e4 e7e5")],
    [L(30, "e7e5")],
    [L(40, "d1h5")],
    [L(-60, "b8c6")],
    [L(-50, "f1c4")],
    # Black to move before 3...Nf6??: Qe7 is best (Black +0.4), g6 is close (+0.2), Qf6 is worse (0.0)
    [L(-40, "d8e7 g1f3"), L(-20, "g7g6 h5f3"), L(0, "d8f6 b1c3")],
    [L(None, "h5f7", mate=1)],
    None,
]


@pytest.fixture(autouse=True)
def _reset() -> None:
    FakeEngine.instances.clear()


@pytest.fixture
def game(services) -> int:  # type: ignore[no-untyped-def]
    gid = services.games.import_pgn(SCHOLAR).game_id
    services.games.set_user_color(gid, "black")  # nobody is signed in here, so the color is set by hand
    rows = grade_game(chess.STARTING_FEN, MOVES, ANALYSES)
    GameAnalysisRepo(services.db).replace(gid, rows, "analyzed", 0.3, "Stockfish 19")
    return int(gid)


def test_an_unanalyzed_game_has_its_moves_but_no_grades(services) -> None:  # type: ignore[no-untyped-def]
    gid = services.games.import_pgn(SCHOLAR).game_id
    v = services.review.review(gid)
    assert not v.analyzed and [m.san for m in v.moves][-1] == "Qxf7#"
    assert all(m.classification is None for m in v.moves) and v.key_moments == () and v.summaries == ()


def test_the_review_shows_symbols_graph_lines_refutations_and_key_moments(services, game: int) -> None:  # type: ignore[no-untyped-def]
    v = services.review.review(game)
    assert v.analyzed and v.game.user_color == "black"
    nf6 = v.moves[5]
    assert (nf6.symbol, nf6.classification, nf6.kind, nf6.best_san) == ("??", "blunder", "allowed", "Qe7")
    assert nf6.refutation == ("h5f7",) and nf6.eval_white == 1000 and nf6.eval_text == "#1"
    assert [ln.sans[0] for ln in nf6.lines] == ["Qe7", "g6", "Qf6"] and nf6.lines[0].score == "+0.4"
    assert v.moves[-1].eval_text == "#"
    assert v.key_moments == (5,) and v.retry_plies == (5,)  # your (Black's) errors only
    white, black = v.summaries
    assert (black.blunders, white.blunders) == (1, 0)
    assert nf6.suggested_reason == "missedResource"  # the refutation is a capture that mates (FR-5.9)
    assert v.ask_reasons


def test_retry_finds_moves_within_the_tolerance_from_the_stored_lines(services, game: int) -> None:  # type: ignore[no-untyped-def]
    best = services.review.retry_move(game, 5, "d8e7")
    assert best.found and best.best_san == "Qe7" and best.reply_line == ()
    close = services.review.retry_move(game, 5, "g7g6")  # 20 cp worse: within 30
    assert close.found and close.played_score == "+0.2"
    worse = services.review.retry_move(game, 5, "d8f6")  # 40 cp worse
    assert not worse.found and worse.best_line[:1] == ("d8e7",) and worse.reply_line == ("b1c3",)


def test_retry_checks_other_moves_with_the_interactive_engine(services, paths, game: int) -> None:  # type: ignore[no-untyped-def]
    unchecked = services.review.retry_move(game, 5, "a7a6")  # no Stockfish: only the analysis's lines count
    assert not unchecked.found and not unchecked.engine_checked
    plant_managed_install(paths)
    r = services.review.retry_move(game, 5, "a7a6")
    assert r.engine_checked
    used = [e for e in FakeEngine.instances if e.calls]
    assert used and used[0].options[0] == 7  # the interactive engine (7 threads), never the background one
    again = services.review.retry_move(game, 5, "g8f6")  # repeating the blunder: mated
    assert not again.found and again.played_score.startswith("Mated")


def test_retry_rejects_bad_requests(services, game: int) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValidationError):
        services.review.retry_move(game, 4, "f1c4")  # White's move, and not a mistake
    with pytest.raises(ValidationError):
        services.review.retry_move(game, 5, "e1e2")  # illegal here
    with pytest.raises(ValidationError):
        services.review.retry_move(game, 99, "d8e7")
    unanalyzed = services.games.import_pgn('[White "a"]\n\n1. d4 d5 *').game_id
    with pytest.raises(ConflictError):
        services.review.retry_move(unanalyzed, 0, "d2d4")


def test_save_as_puzzle_stores_your_position_and_the_best_line_once(services, game: int) -> None:  # type: ignore[no-untyped-def]
    pid, created = services.review.save_as_puzzle(game, 5)
    assert created
    again, created2 = services.review.save_as_puzzle(game, 5)
    assert again == pid and not created2
    with services.db.session() as c:
        row = c.execute(
            "SELECT fen, solution_uci, length, player_color, origin, strict, kind, severity FROM custom_puzzles WHERE id = ?",
            (pid,),
        ).fetchone()
    board = chess.Board(row[0])
    assert board.turn == chess.BLACK and row[3] == "black"  # you solve as the side that moved
    assert row[1] == "d8e7" and row[2] == 1  # Qe7 g1f3 is cut to end on your move
    assert (row[4], row[5], row[6], row[7]) == ("manual", 0, "allowed", "blunder")
    assert services.review.review(game).moves[5].saved


def test_reasons_on_your_game_mistakes_and_retry_misses(services, game: int) -> None:  # type: ignore[no-untyped-def]
    services.review.set_game_reason(game, 5, "didntLook", "saw it too late")
    services.review.set_game_reason(game, 5, "miscalculated")
    assert services.review.review(game).moves[5].reason == "miscalculated"  # the latest choice counts
    with pytest.raises(ValidationError):
        services.review.set_game_reason(game, 4, "didntLook")  # not your move
    with pytest.raises(ValidationError):
        services.review.set_game_reason(game, 5, "bogus")
    miss = services.review.retry_move(game, 5, "d8f6")
    services.review.set_retry_reason(miss.retry_id, "missedResource")
    hit = services.review.retry_move(game, 5, "d8e7")
    with pytest.raises(ValidationError):
        services.review.set_retry_reason(hit.retry_id, "didntLook")
    with services.db.session() as c:
        sources = sorted(r[0] for r in c.execute("SELECT DISTINCT source FROM mistake_reasons"))
    assert sources == ["game", "retry"]


def test_game_review_only_asks_in_game_review_not_after_puzzles(services, paths, game: int) -> None:  # type: ignore[no-untyped-def]
    services.ui_settings.set("reasons.ask", "game_review")
    assert services.review.review(game).ask_reasons
    plant_managed_install(paths)
    sid, view, moves = start(services)
    services.sessions.submit_move(sid, wrong_move(view, moves))
    assert services.sessions.reason_prompt(sid) is None  # puzzles don't ask (FR-5.8)
    services.ui_settings.set("reasons.ask", "off")
    assert not services.review.review(game).ask_reasons
