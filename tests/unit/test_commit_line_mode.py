"""FR-4.2 Commit the line: the mode's state machine and grading."""

from __future__ import annotations

import pytest

from weaksquare.core.errors import ConflictError, ValidationError
from weaksquare.core.modes.commit_line import MAX_PLIES, CommitLineMode, max_plies
from weaksquare.core.puzzle import Puzzle, PuzzleRef


def puzzle(fen: str, moves: str) -> Puzzle:
    return Puzzle(PuzzleRef("lichess", "T1"), fen, tuple(moves.split()), 1500, ("fork",), "", ())


# Solution after the opponent's h2f3: f5g4 (you) h3g4 (reply) f7f3 (you) d5h5 (reply) f3d1 (you).
LONG = puzzle("6rk/2p2q2/1p4rp/2PR1b1p/P6Q/1P2p1PP/5P1N/3R2K1 w - - 0 36", "h2f3 f5g4 h3g4 f7f3 d5h5 f3d1")
SOLUTION = ["f5g4", "h3g4", "f7f3", "d5h5", "f3d1"]
MATE1 = puzzle("6Qk/p1p3pp/4N3/1p6/2q1r1n1/2B5/PP4PP/3R1R1K b - - 0 28", "h8g8 f1f8")  # d1d8 also mates
mode = CommitLineMode()


def test_the_whole_line_right_is_a_win_with_full_calculation_accuracy() -> None:
    s = mode.start(LONG, 1000)
    r = mode.on_submit(s, SOLUTION, 9000)
    assert r.win and r.attempt is not None
    assert (r.attempt.win, r.attempt.first_move_correct, r.attempt.line_correct) == (True, True, True)
    assert r.attempt.help_used == "none" and r.attempt.time_ms == 8000
    assert (r.replies_correct, r.replies_total) == (2, 2)
    assert [g.player for g in r.grades] == [True, False, True, False, True]
    assert all(g.correct for g in r.grades) and r.extra == ()
    assert s.finished and s.first_wrong is None
    assert len(r.line_sounds) == 5


def test_a_wrong_predicted_reply_does_not_cost_the_win() -> None:
    # You expected g1h2 instead of h3g4; your own moves are still the solution's (and legal on your board).
    s = mode.start(LONG, 0)
    r = mode.on_submit(s, ["f5g4", "g1h2", "f7f3", "d5h5", "f3d1"], 1)
    assert r.win and r.attempt is not None and r.attempt.win
    assert [g.correct for g in r.grades] == [True, False, True, True, True]
    assert (r.replies_correct, r.replies_total) == (1, 2)


def _legal(state: object, line: list[str]) -> bool:
    try:
        mode.parse_line(state, line)  # type: ignore[arg-type]
        return True
    except ValidationError:
        return False


def test_after_a_wrong_prediction_only_exact_moves_count() -> None:
    s = mode.start(LONG, 0)
    assert _legal(s, ["f5g4", "g1h2", "f7f6"])
    r = mode.on_submit(s, ["f5g4", "g1h2", "f7f6"], 1)
    assert not r.win
    assert s.first_wrong is None  # f7f6 wasn't played in the real position: no refutation


def test_reply_accuracy_is_separate_from_the_win() -> None:
    s = mode.start(LONG, 0)
    # Right moves of yours, but stopping after the first: the rest of yours are missing, so a loss.
    r = mode.on_submit(s, ["f5g4", "h3g4", "f7f3"], 5)
    assert not r.win and r.attempt is not None and not r.attempt.win
    assert r.attempt.first_move_correct
    assert [g.correct for g in r.grades] == [True, True, True, False, False]
    assert r.grades[3].played is None and r.grades[4].played is None  # missing
    assert (r.replies_correct, r.replies_total) == (1, 2)
    assert s.first_wrong is None  # nothing was played in the real position that was wrong


def test_a_wrong_first_move_is_a_loss_and_refutable() -> None:
    s = mode.start(LONG, 0)
    r = mode.on_submit(s, ["f7f6"], 5)
    assert not r.win and r.attempt is not None and not r.attempt.first_move_correct
    assert s.first_wrong == (s.start_fen, "f7f6")


def test_a_wrong_move_after_matching_plies_is_refutable_in_the_real_position() -> None:
    s = mode.start(LONG, 0)
    r = mode.on_submit(s, ["f5g4", "h3g4", "f7f6"], 5)
    assert not r.win
    assert s.first_wrong is not None and s.first_wrong[1] == "f7f6"
    board = s.board.copy()
    board.push_uci("f5g4")
    board.push_uci("h3g4")
    assert s.first_wrong[0] == board.fen()


def test_extra_moves_after_the_solution_are_ignored() -> None:
    s = mode.start(LONG, 0)
    line = SOLUTION + _one_more(s)
    r = mode.on_submit(s, line, 5)
    assert r.win and r.extra == tuple(line[5:])
    assert len(r.grades) == 5


def _one_more(state: object) -> list[str]:
    board = state.board.copy()  # type: ignore[attr-defined]
    for m in SOLUTION:
        board.push_uci(m)
    return [next(iter(board.legal_moves)).uci()]


def test_an_alternative_mate_is_accepted() -> None:
    s = mode.start(MATE1, 0)
    r = mode.on_submit(s, ["d1d8"], 5)
    assert r.win and r.grades[0].correct and r.grades[0].expected == "f1f8"


def test_illegal_or_empty_or_too_long_lines_are_refused() -> None:
    s = mode.start(LONG, 0)
    for bad in ([], ["e2e4"], ["f5g4", "f5g4"], "f5g4", None, ["zz"]):
        with pytest.raises(ValidationError):
            mode.on_submit(s, bad, 1)
    assert not s.finished


def test_length_cap_hidden_and_shown() -> None:
    assert max_plies(LONG, length_shown=False) == MAX_PLIES  # never depends on the length (v0.5-B3)
    assert max_plies(LONG, length_shown=True) == 5
    s = mode.start(LONG, 0, length_shown=True)
    with pytest.raises(ValidationError):
        mode.on_submit(s, SOLUTION + _one_more(s), 1)
    assert mode.on_submit(s, SOLUTION, 1).win


def test_on_move_is_refused_and_submit_happens_once() -> None:
    s = mode.start(LONG, 0)
    with pytest.raises(ConflictError):
        mode.on_move(s, "f5g4", 1)
    mode.on_submit(s, SOLUTION, 1)
    with pytest.raises(ConflictError):
        mode.on_submit(s, SOLUTION, 2)


def test_hint_before_submit_is_a_loss_and_submit_records_nothing_more() -> None:
    s = mode.start(LONG, 0)
    h = mode.on_help(s, "hint", 10)
    assert h.hint_square == "f5" and h.attempt is not None
    assert (h.attempt.win, h.attempt.help_used) == (False, "hint")
    r = mode.on_submit(s, SOLUTION, 20)
    assert r.attempt is None and not r.win  # already decided: the grades still show
    assert all(g.correct for g in r.grades)


def test_show_answer_needs_a_hint_first_then_ends_the_puzzle() -> None:
    s = mode.start(LONG, 0)
    with pytest.raises(ConflictError):
        mode.on_help(s, "answer", 1)
    mode.on_help(s, "hint", 2)
    a = mode.on_help(s, "answer", 3)
    assert a.attempt is None  # Hint already decided the loss
    assert a.answer_fen == s.start_fen and list(a.answer_moves) == SOLUTION
    assert s.finished
    with pytest.raises(ConflictError):
        mode.on_submit(s, SOLUTION, 4)


def test_help_after_submit_is_free() -> None:
    s = mode.start(LONG, 0)
    mode.on_submit(s, ["f7f6"], 1)
    a = mode.on_help(s, "answer", 2)
    assert a.attempt is None and a.refute and list(a.answer_moves) == SOLUTION
    with pytest.raises(ConflictError):
        mode.on_help(s, "hint", 3)


def test_give_up_before_submit_is_a_loss_once() -> None:
    s = mode.start(LONG, 0)
    result = mode.give_up(s, 50)
    assert result is not None and not result.win and result.time_ms == 50
    assert mode.give_up(s, 60) is None


def test_practice_never_decides() -> None:
    s = mode.start_practice(LONG, 0)
    r = mode.on_submit(s, SOLUTION, 1)
    assert r.attempt is None and s.practice
    assert all(g.correct for g in r.grades)
    assert mode.give_up(mode.start_practice(LONG, 0), 1) is None
