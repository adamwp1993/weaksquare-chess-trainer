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


# ---- v0.2: Hint and Show answer (FR-5.2, FR-5.4, §7.2) -----------------------------------------
from weaksquare.core.errors import ConflictError  # noqa: E402


def test_hint_then_correct_line_is_a_loss_with_hint() -> None:
    s = mode.start(LONG, 0)
    h = mode.on_help(s, "hint", 100)
    assert h.hint_square == "f5" and h.attempt is not None
    assert (h.attempt.win, h.attempt.help_used, h.attempt.line_correct) == (False, "hint", False)
    assert mode.on_move(s, "f5g4", 200).kind == "correct"
    assert mode.on_move(s, "f7f3", 300).kind == "correct"
    last = mode.on_move(s, "f3d1", 400)
    assert last.kind == "solved" and last.attempt is None  # recorded once, at the hint
    assert mode.give_up(s, 500) is None


def test_answer_needs_a_hint_first_mid_puzzle() -> None:
    s = mode.start(LONG, 0)
    with pytest.raises(ConflictError):
        mode.on_help(s, "answer", 10)
    assert s.attempt is None  # refusing records nothing


def test_hint_then_answer_gives_the_rest_and_ends_the_puzzle() -> None:
    s = mode.start(LONG, 0)
    mode.on_move(s, "f5g4", 10)  # first move right; the reply h3g4 is played
    hint = mode.on_help(s, "hint", 20)
    assert hint.hint_square == "f7" and hint.attempt is not None and hint.attempt.first_move_correct
    ans = mode.on_help(s, "answer", 30)
    assert ans.attempt is None  # already decided by the hint
    assert ans.answer_moves == ("f7f3", "d5h5", "f3d1") and ans.answer_fen == s.board.fen()
    assert mode.on_move(s, "f7f3", 40).kind == "illegal"  # the answer ended the puzzle


def test_answer_after_a_wrong_move_is_free_and_needs_no_hint() -> None:
    s = mode.start(LONG, 0)
    wrong = mode.on_move(s, "f7f6", 10)
    assert wrong.attempt is not None and wrong.attempt.help_used == "none"
    ans = mode.on_help(s, "answer", 20)
    assert ans.attempt is None and ans.answer_moves == tuple(LONG.moves[1:])


def test_help_after_the_end_is_free_and_replays_from_the_start() -> None:
    s = mode.start(MATE1, 0)
    assert mode.on_move(s, "f1f8", 10).attempt.win  # type: ignore[union-attr]
    ans = mode.on_help(s, "answer", 20)
    assert ans.attempt is None and ans.answer_moves == ("f1f8",) and ans.answer_fen == s.start_fen
    with pytest.raises(ConflictError):
        mode.on_help(s, "hint", 30)


def test_answer_records_answer_when_it_decides() -> None:
    s = mode.start(LONG, 0)
    s.hinted = True  # e.g. a hint on an earlier visit that was decided elsewhere
    ans = mode.on_help(s, "answer", 10)
    assert ans.attempt is not None and ans.attempt.help_used == "answer" and not ans.attempt.win


def test_first_wrong_move_is_kept_for_the_refutation() -> None:
    """§7.2 step 2: the move that lost the puzzle (and the position before it) is what gets refuted."""
    s = mode.start(LONG, 0)
    mode.on_move(s, "f5g4", 100)
    before = s.board.fen()
    mode.on_move(s, "f7f6", 200)
    mode.on_move(s, "f7f5", 300)  # a second wrong move doesn't replace the first
    assert s.first_wrong == (before, "f7f6")
    answer = mode.on_help(s, "answer", 400)
    assert answer.refute is True


def test_no_refutation_without_a_wrong_move() -> None:
    s = mode.start(LONG, 0)
    mode.on_help(s, "hint", 100)
    assert mode.on_help(s, "answer", 200).refute is False
    s2 = mode.start(MATE1, 0)
    mode.on_move(s2, "f1f8", 100)
    assert s2.first_wrong is None and mode.on_help(s2, "answer", 200).refute is False


def test_refute_also_after_the_end() -> None:
    s = mode.start(MATE1, 0)
    mode.on_move(s, "f1f7", 100)  # wrong
    mode.on_move(s, "f1f8", 200)  # then solves the line
    assert s.finished and mode.on_help(s, "answer", 300).refute is True


def test_practice_run_never_decides_anything() -> None:
    """FR-5.12 Try again: a wrong move, a hint, the answer and moving on decide nothing."""
    s = mode.start_practice(LONG, 0)
    assert s.practice and s.next_index == 1
    wrong = mode.on_move(s, "f7f6", 100)
    assert wrong.kind == "wrong" and wrong.attempt is None
    assert mode.on_move(s, "f5g4", 200).kind == "correct"
    assert mode.on_help(s, "hint", 300).attempt is None
    answer = mode.on_help(s, "answer", 400)  # free, no Hint needed
    assert answer.attempt is None and answer.answer_moves
    assert mode.give_up(mode.start_practice(LONG, 0), 500) is None


def test_practice_run_can_be_solved() -> None:
    s = mode.start_practice(MATE1, 0)
    fb = mode.on_move(s, "f1f8", 100)
    assert fb.kind == "solved" and fb.finished and fb.attempt is None
