"""FR-4.1, FR-5.1, FR-5.3, FR-5.5: Standard mode scoring."""

from __future__ import annotations

import pytest

from weaksquare.core.chess_rules import PuzzleDataError
from weaksquare.core.modes.standard import StandardMode
from weaksquare.core.puzzle import Puzzle, PuzzleRef


def puzzle(fen: str, moves: str, themes: str = "fork") -> Puzzle:
    return Puzzle(PuzzleRef("lichess", "T1"), fen, tuple(moves.split()), 1500, tuple(themes.split()), "", ())


LONG = puzzle("6rk/2p2q2/1p4rp/2PR1b1p/P6Q/1P2p1PP/5P1N/3R2K1 w - - 0 36", "h2f3 f5g4 h3g4 f7f3 d5h5 f3d1")
MATE1 = puzzle("6Qk/p1p3pp/4N3/1p6/2q1r1n1/2B5/PP4PP/3R1R1K b - - 0 28", "h8g8 f1f8")
mode = StandardMode()


def test_win_plays_replies_and_records_once() -> None:
    s = mode.start(LONG, 1000)
    f1 = mode.on_move(s, "f5g4", 2000)
    assert (f1.kind, f1.reply, f1.attempt) == ("correct", "h3g4", None)
    f2 = mode.on_move(s, "f7f3", 3000)
    assert (f2.kind, f2.reply) == ("correct", "d5h5")
    f3 = mode.on_move(s, "f3d1", 4500)
    assert f3.kind == "solved" and f3.finished
    assert f3.attempt is not None
    assert (f3.attempt.win, f3.attempt.first_move_correct, f3.attempt.line_correct) == (True, True, True)
    assert f3.attempt.help_used == "none" and f3.attempt.time_ms == 3500
    assert mode.give_up(s, 9000) is None


def test_wrong_move_is_a_loss_then_continues() -> None:
    s = mode.start(LONG, 0)
    assert mode.on_move(s, "f5g4", 100).kind == "correct"
    wrong = mode.on_move(s, "f7f6", 200)  # legal, not the solution
    assert wrong.kind == "wrong" and wrong.attempt is not None
    assert (wrong.attempt.win, wrong.attempt.first_move_correct, wrong.attempt.line_correct) == (False, True, False)
    # Board unchanged (move taken back): the right move still works, with nothing more recorded.
    again = mode.on_move(s, "f7f6", 300)
    assert again.kind == "wrong" and again.attempt is None
    assert mode.on_move(s, "f7f3", 400).kind == "correct"
    last = mode.on_move(s, "f3d1", 500)
    assert last.kind == "solved" and last.attempt is None


def test_wrong_first_move() -> None:
    s = mode.start(LONG, 0)
    f = mode.on_move(s, "f7f6", 10)
    assert f.attempt is not None and not f.attempt.first_move_correct and not f.attempt.win


def test_alternative_mate_wins() -> None:
    s = mode.start(MATE1, 0)
    f = mode.on_move(s, "d1d8", 10)
    assert f.kind == "solved" and f.attempt is not None and f.attempt.win


def test_illegal_and_garbage_moves_change_nothing() -> None:
    s = mode.start(MATE1, 0)
    for bad in ["a1a8", "zz", "", "f1f8q"]:
        assert mode.on_move(s, bad, 1).kind == "illegal"
    assert s.attempt is None and not s.failed


def test_give_up_is_a_loss() -> None:
    s = mode.start(MATE1, 0)
    r = mode.give_up(s, 50)
    assert r is not None and not r.win and not r.first_move_correct


def test_illegal_puzzle_data_is_refused() -> None:
    with pytest.raises(PuzzleDataError):
        mode.start(puzzle(MATE1.fen, "h8g8 a2a5"), 0)
