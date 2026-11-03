"""FR-4.4 Danger spotting: safe-candidate verification (ROADMAP v0.6 Done when) and the call/refute rules."""

from __future__ import annotations

import random

import pytest

from weaksquare.core.errors import ConflictError, ValidationError
from weaksquare.core.modes.danger import (
    MAX_LOSS_CP,
    DangerMode,
    ScoredMove,
    pick_safe,
    safe_candidates,
    wants_safe,
)
from weaksquare.core.puzzle import Puzzle, PuzzleRef


def puzzle(fen: str, moves: str) -> Puzzle:
    return Puzzle(PuzzleRef("lichess", "D1"), fen, tuple(moves.split()), 1500, ("fork",), "", ())


# White blunders with Nf3 (h2f3); Black refutes with Bg4 (f5g4).
LONG = puzzle("6rk/2p2q2/1p4rp/2PR1b1p/P6Q/1P2p1PP/5P1N/3R2K1 w - - 0 36", "h2f3 f5g4 h3g4 f7f3 d5h5 f3d1")
# Black's Kxg8 (h8g8) blunders into mate: Rf8# (f1f8), and Rd8# (d1d8) mates too.
MATE1 = puzzle("6Qk/p1p3pp/4N3/1p6/2q1r1n1/2B5/PP4PP/3R1R1K b - - 0 28", "h8g8 f1f8")
SAFE = "h4e4"  # a legal non-blunder for White in LONG
mode = DangerMode()


# ---- safe-candidate verification -------------------------------------------------------------------


def test_safe_means_within_50_cp_of_the_best_line() -> None:
    lines = [
        ScoredMove("a", 30, None),
        ScoredMove("b", 30 - MAX_LOSS_CP, None),
        ScoredMove("c", 30 - MAX_LOSS_CP - 1, None),
    ]
    assert [m.move for m in safe_candidates(lines, "z")] == ["a", "b"]


def test_the_real_blunder_is_never_safe() -> None:
    lines = [ScoredMove("bl", 40, None), ScoredMove("ok", 35, None)]
    assert [m.move for m in safe_candidates(lines, "bl")] == ["ok"]


def test_a_move_that_allows_a_mate_is_never_safe() -> None:
    lines = [ScoredMove("a", -900, None), ScoredMove("b", None, -3)]
    assert [m.move for m in safe_candidates(lines, "z")] == ["a"]  # a is the best line, however bad


def test_when_best_is_a_mate_only_mates_are_safe() -> None:
    lines = [ScoredMove("m1", None, 1), ScoredMove("m3", None, 3), ScoredMove("cp", 900, None)]
    assert [m.move for m in safe_candidates(lines, "z")] == ["m1", "m3"]


def test_best_is_the_best_of_all_lines_not_the_first() -> None:
    lines = [ScoredMove("a", 0, None), ScoredMove("b", 200, None)]
    assert [m.move for m in safe_candidates(lines, "z")] == ["b"]


def test_no_lines_or_no_qualifying_move_gives_none() -> None:
    assert safe_candidates([], "z") == []
    assert safe_candidates([ScoredMove("bl", 10, None)], "bl") == []
    assert pick_safe(random.Random(1), []) is None


def test_about_half_safe_and_an_owed_slot_is_always_safe() -> None:
    rng = random.Random(42)
    picks = [wants_safe(rng, False) for _ in range(2000)]
    assert 0.45 < sum(picks) / len(picks) < 0.55
    assert all(wants_safe(rng, True) for _ in range(50))


def test_pick_is_random_among_the_safe_moves() -> None:
    rng = random.Random(7)
    safe = [ScoredMove(m, 0, None) for m in ("a", "b", "c")]
    assert {pick_safe(rng, safe).move for _ in range(100)} == {"a", "b", "c"}  # type: ignore[union-attr]


# ---- the state machine -----------------------------------------------------------------------------


def test_start_checks_the_candidate() -> None:
    with pytest.raises(ValidationError):
        mode.start(LONG, 0, "e1e8", True)  # illegal
    with pytest.raises(ValidationError):
        mode.start(LONG, 0, "h2f3", True)  # the blunder can't be the safe one
    with pytest.raises(ValidationError):
        mode.start(LONG, 0, SAFE, False)  # a non-blunder can't be the unsafe one


def test_safe_called_safe_wins() -> None:
    s = mode.start(LONG, 0, SAFE, True)
    r = mode.on_call(s, "safe", 4000)
    assert r.correct and r.is_safe and not r.refute and s.finished
    assert r.attempt is not None and r.attempt.win and r.attempt.first_move_correct
    assert r.attempt.time_ms == 4000 and s.decisive_ms == 4000


def test_safe_called_unsafe_loses() -> None:
    s = mode.start(LONG, 0, SAFE, True)
    r = mode.on_call(s, "unsafe", 10)
    assert not r.correct and r.attempt is not None and not r.attempt.win and not r.attempt.first_move_correct


def test_blunder_called_safe_loses() -> None:
    s = mode.start(LONG, 0, "h2f3", False)
    r = mode.on_call(s, "safe", 10)
    assert not r.correct and not r.is_safe and r.attempt is not None and not r.attempt.win
    assert s.finished


def test_blunder_called_unsafe_then_the_refutation_wins() -> None:
    s = mode.start(LONG, 0, "h2f3", False)
    r = mode.on_call(s, "unsafe", 1000)
    assert r.correct and r.refute and r.attempt is None and not s.finished
    assert " b " in r.fen  # the blunder was played: Black to move
    f = mode.on_move(s, "f5g4", 3000)
    assert f.kind == "solved" and f.finished and f.attempt is not None
    assert f.attempt.win and f.attempt.first_move_correct and f.attempt.line_correct


def test_a_wrong_refutation_loses_and_ends_the_puzzle() -> None:
    s = mode.start(LONG, 0, "h2f3", False)
    mode.on_call(s, "unsafe", 1000)
    f = mode.on_move(s, "f7f6", 1500)
    assert f.kind == "wrong" and f.finished and f.attempt is not None
    assert not f.attempt.win and f.attempt.first_move_correct  # the call was right
    assert s.first_wrong is not None and s.decisive_ms == 500


def test_any_mating_refutation_is_accepted() -> None:
    s = mode.start(MATE1, 0, "h8g8", False)
    mode.on_call(s, "unsafe", 10)
    f = mode.on_move(s, "d1d8", 20)
    assert f.kind == "solved" and f.attempt is not None and f.attempt.win


def test_illegal_refutation_is_ignored() -> None:
    s = mode.start(LONG, 0, "h2f3", False)
    mode.on_call(s, "unsafe", 0)
    assert mode.on_move(s, "a1a8", 1).kind == "illegal" and not s.finished


def test_moves_before_the_call_and_second_calls_are_refused() -> None:
    s = mode.start(LONG, 0, SAFE, True)
    with pytest.raises(ConflictError):
        mode.on_move(s, "h4e4", 1)
    with pytest.raises(ValidationError):
        mode.on_call(s, "maybe", 1)
    mode.on_call(s, "safe", 2)
    with pytest.raises(ConflictError):
        mode.on_call(s, "unsafe", 3)


def test_no_hint_before_the_call_and_show_answer_is_a_loss() -> None:
    s = mode.start(LONG, 0, "h2f3", False)
    with pytest.raises(ConflictError):
        mode.on_help(s, "hint", 1)
    h = mode.on_help(s, "answer", 2)
    assert h.attempt is not None and h.attempt.help_used == "answer" and not h.attempt.win
    assert h.answer_moves == LONG.moves and s.finished  # the blunder and its refutation
    with pytest.raises(ConflictError):
        mode.on_call(s, "unsafe", 3)


def test_show_answer_on_a_safe_candidate_reveals_it() -> None:
    s = mode.start(LONG, 0, SAFE, True)
    h = mode.on_help(s, "answer", 2)
    assert h.answer_moves == (SAFE,) and h.attempt is not None


def test_help_while_refuting_works_as_in_standard() -> None:
    s = mode.start(LONG, 0, "h2f3", False)
    mode.on_call(s, "unsafe", 0)
    with pytest.raises(ConflictError):
        mode.on_help(s, "answer", 1)  # Show answer unlocks after Hint
    h = mode.on_help(s, "hint", 2)
    assert h.hint_square == "f5" and h.attempt is not None and h.attempt.help_used == "hint"
    a = mode.on_help(s, "answer", 3)
    assert a.attempt is None and s.finished


def test_help_after_the_end_is_free() -> None:
    s = mode.start(LONG, 0, SAFE, True)
    mode.on_call(s, "safe", 1)
    assert mode.on_help(s, "answer", 2).attempt is None


def test_give_up_is_a_loss_once() -> None:
    s = mode.start(LONG, 0, SAFE, True)
    r = mode.give_up(s, 5)
    assert r is not None and not r.win and not r.first_move_correct
    assert mode.give_up(s, 6) is None


def test_practice_never_decides() -> None:
    s = mode.start_practice(LONG, 0, "h2f3", False)
    r = mode.on_call(s, "unsafe", 1)
    assert r.attempt is None and r.refute
    assert mode.on_move(s, "f5g4", 2).attempt is None
