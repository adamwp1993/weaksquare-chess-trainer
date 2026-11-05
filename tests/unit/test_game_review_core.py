"""core/game_review.py and core/tolerance.py (v0.8): grading thresholds, mate swings, decided positions,
Missed / Allowed / Other, phases, key moments, the per-side summary, and the 30 cp tolerance."""

from __future__ import annotations

import chess
import pytest

from weaksquare.core.engine import EngineLine
from weaksquare.core.game_review import (
    MoveRow,
    Score,
    Thresholds,
    grade,
    grade_game,
    key_moments,
    missed_or_allowed,
    phase_of,
    side_summary,
    white_eval,
)
from weaksquare.core.tolerance import validate_tolerance, within_tolerance

TH = Thresholds()


def cp(n: int) -> Score:
    return Score(n, None)


def mate(n: int) -> Score:
    return Score(None, n)


@pytest.mark.parametrize(
    "before, after, cls, loss",
    [
        (cp(30), cp(-19), "good", 49),
        (cp(30), cp(-20), "inaccuracy", 50),
        (cp(30), cp(-69), "inaccuracy", 99),
        (cp(30), cp(-70), "mistake", 100),
        (cp(30), cp(-169), "mistake", 199),
        (cp(30), cp(-170), "blunder", 200),
        (cp(0), cp(40), "good", 0),  # a better-than-expected move is never a loss
    ],
)
def test_thresholds_at_each_boundary(before: Score, after: Score, cls: str, loss: int) -> None:
    assert grade(before, after, False, TH) == (loss, cls)


def test_the_best_move_is_best_whatever_the_noise() -> None:
    assert grade(cp(50), cp(-40), True, TH) == (0, "best")


@pytest.mark.parametrize(
    "before, after",
    [
        (cp(0), mate(-3)),  # walked into a forced mate
        (mate(4), cp(120)),  # gave up a forced mate for a position that isn't winning
    ],
)
def test_mate_swings_are_blunders(before: Score, after: Score) -> None:
    assert grade(before, after, False, TH)[1] == "blunder"


@pytest.mark.parametrize(
    "before, after",
    [
        (cp(900), cp(600)),  # still winning after the move
        (cp(-700), cp(-1000)),  # already lost
        (mate(-2), mate(-1)),  # already being mated
        (mate(5), cp(800)),  # a slower win
    ],
)
def test_decided_positions_are_not_penalized(before: Score, after: Score) -> None:
    assert grade(before, after, False, TH) == (0, "good")


def test_leaving_the_decided_zone_is_penalized() -> None:
    assert grade(cp(600), cp(-100), False, TH) == (700, "blunder")


def test_custom_thresholds_and_validation() -> None:
    assert grade(cp(0), cp(-60), False, Thresholds(30, 60, 90, 500))[1] == "mistake"
    with pytest.raises(ValueError):
        Thresholds(100, 50, 200).validate()


@pytest.mark.parametrize(
    "before, after, cls, kind",
    [
        (cp(300), cp(50), "blunder", "missed"),
        (cp(20), cp(-250), "blunder", "allowed"),
        (cp(20), mate(-4), "blunder", "allowed"),
        (cp(80), cp(-40), "mistake", "other"),
        (cp(300), cp(240), "inaccuracy", None),  # only mistakes and blunders get a kind
    ],
)
def test_missed_allowed_other(before: Score, after: Score, cls: str, kind: str | None) -> None:
    assert missed_or_allowed(before, after, cls) == kind


def test_phase_from_lichess_division_and_from_the_rule() -> None:
    start = chess.Board()
    assert phase_of(start, 0, {"middle": 20, "end": 60}) == "opening"
    assert phase_of(start, 30, {"middle": 20, "end": 60}) == "middlegame"
    assert phase_of(start, 59, {"middle": 20, "end": 60}) == "endgame"
    assert phase_of(start, 30, {"middle": 20}) == "middlegame"  # no endgame reached
    assert phase_of(start, 4, None) == "opening"
    assert phase_of(start, 24, None) == "middlegame"  # move 13
    assert phase_of(chess.Board("4k3/8/8/8/8/8/R3P3/4K2R w - - 0 40"), 78, None) == "endgame"


def _line(cp_white: int | None, pv: str, mate_white: int | None = None) -> list[EngineLine]:
    return [EngineLine(cp=cp_white, mate=mate_white, pv=tuple(pv.split()))]


def test_grade_game_scores_every_move_from_the_movers_side_and_reads_the_final_mate() -> None:
    # Scholar's mate: 1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6?? 4. Qxf7#
    moves = ["e2e4", "e7e5", "d1h5", "b8c6", "f1c4", "g8f6", "h5f7"]
    analyses = [
        _line(30, "e2e4"),
        _line(30, "e7e5"),
        _line(40, "d1h5"),
        _line(-60, "b8c6"),  # White's eval -0.6: black is better
        _line(-50, "f1c4"),
        _line(-40, "d8e7"),  # black's best is ...Qe7
        _line(None, "h5f7", mate_white=1),  # after Nf6 white mates in 1
        None,  # checkmate: game over
    ]
    rows = grade_game(chess.STARTING_FEN, moves, analyses)
    nf6 = rows[5]
    assert (nf6.mover, nf6.move_san, nf6.best_move) == ("black", "Nf6", "d8e7")
    assert nf6.eval_before == cp(40) and nf6.eval_after == mate(-1)
    assert nf6.classification == "blunder" and nf6.kind == "allowed"
    assert nf6.refutation == ("h5f7",)
    last = rows[6]
    assert last.eval_after == mate(0) and last.classification == "best" and last.refutation == ()
    assert white_eval(last) == 1000 and white_eval(nf6) == 1000
    assert [r.ply for r in key_moments(rows, "black")] == [5]


def test_grade_game_needs_one_analysis_per_position() -> None:
    with pytest.raises(ValueError):
        grade_game(chess.STARTING_FEN, ["e2e4"], [_line(0, "e2e4")])


def _row(ply: int, mover: str, cls: str, loss: int, phase: str = "middlegame", low: bool | None = None) -> MoveRow:
    return MoveRow(ply, "", "", "", mover, cp(0), cp(0), None, (), (), loss, cls, None, phase, low, None)


def test_key_moments_are_the_largest_losses_in_game_order() -> None:
    rows = [_row(i, "white", c, loss) for i, (c, loss) in enumerate(
        [("blunder", 400), ("good", 10), ("inaccuracy", 60), ("mistake", 150), ("blunder", 300), ("inaccuracy", 55)]
    )] + [_row(10, "black", "blunder", 900)]  # fmt: skip
    assert [r.ply for r in key_moments(rows, "white", 3)] == [0, 3, 4]
    assert [r.ply for r in key_moments(rows, "white", 10)] == [0, 2, 3, 4, 5]
    assert key_moments(rows, "white", 0) == []


def test_side_summary_counts_phases_and_low_clock_errors() -> None:
    rows = [
        _row(0, "white", "good", 10, "opening", False),
        _row(2, "white", "mistake", 120, "middlegame", True),
        _row(4, "white", "blunder", 300, "endgame", False),
        _row(6, "white", "inaccuracy", 50, "endgame", True),
        _row(1, "black", "blunder", 500),
    ]
    s = side_summary(rows, "white", 77.5)
    assert (s.moves, s.inaccuracies, s.mistakes, s.blunders, s.avg_cp_loss) == (4, 1, 1, 1, 120.0)
    assert s.platform_accuracy == 77.5 and s.low_clock_errors == 1
    assert s.by_phase["endgame"].blunders == 1 and s.by_phase["opening"].avg_cp_loss == 10.0
    assert side_summary(rows, "black").low_clock_errors is None  # no clock data


@pytest.mark.parametrize(
    "best, played, ok",
    [
        (cp(100), cp(70), True),
        (cp(100), cp(69), False),
        (cp(100), cp(150), True),
        (mate(3), mate(5), True),  # any forced mate counts
        (mate(3), cp(900), False),
        (cp(200), mate(0), True),  # it mates on the board
        (cp(1500), cp(1200), True),  # clamped at 1000 both ways
    ],
)
def test_within_tolerance(best: Score, played: Score, ok: bool) -> None:
    assert within_tolerance(best, played, 30) is ok


def test_tolerance_validation() -> None:
    assert validate_tolerance(30) == 30
    for bad in (-1, 301, 2.5, True):
        with pytest.raises(ValueError):
            validate_tolerance(bad)  # type: ignore[arg-type]


def test_score_json_round_trip() -> None:
    for s in (cp(12), mate(-3), mate(0)):
        assert Score.from_json(s.to_json()) == s


def test_v010_b2_walking_into_mate_from_a_winning_position_is_allowed() -> None:
    """v0.10-B2 regression: +1.5 or better before, mated after: the tactic that decided it was allowed."""
    from weaksquare.core.game_review import Score, missed_or_allowed

    assert missed_or_allowed(Score(200), Score(mate=-1), "blunder") == "allowed"
    assert missed_or_allowed(Score(400), Score(-300), "blunder") == "missed"  # a missed win stays Missed
    assert missed_or_allowed(Score(0), Score(-300), "blunder") == "allowed"
    assert missed_or_allowed(Score(0), Score(-50), "mistake") == "other"
