"""QA v0.5 (independent): edge cases for Commit the line grading (FR-4.2), the SRS schedule (FR-4.6)
and the depth ladder (FR-4.5) that the builder's tests don't pin."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from weaksquare.core.errors import ConflictError
from weaksquare.core.ladder import status
from weaksquare.core.modes.commit_line import CommitLineMode, max_plies
from weaksquare.core.puzzle import Puzzle, PuzzleRef
from weaksquare.core.srs import Card, Review, due_order, is_due, schedule

mode = CommitLineMode()

# Synthetic: black a7a6 (opponent), you h2h3, reply a6a5, then Re8# (solution) or Rd8# (also mate).
BACK_RANK = Puzzle(
    PuzzleRef("lichess", "QA1"), "6k1/pp3ppp/8/8/8/8/5PPP/3RR1K1 b - - 0 1",
    ("a7a6", "h2h3", "a6a5", "e1e8"), 1500, ("mateIn2",), "", (),
)  # fmt: skip
# From the fixture (FrexF): the last move f4b8 mates; g8b8 mates too.
FREXF = Puzzle(
    PuzzleRef("lichess", "QA2"), "kr6/pR4R1/2p5/8/q3PQ1p/Pn5P/KP4P1/8 b - - 0 41",
    ("b8b7", "g7g8", "b7b8", "f4b8"), 1500, ("mateIn2",), "", (),
)  # fmt: skip


# ---- Commit the line ------------------------------------------------------------------------------


def test_alternative_mate_on_a_later_ply_is_accepted_when_every_earlier_ply_matched() -> None:
    s = mode.start(FREXF, 0)
    r = mode.on_submit(s, ["g7g8", "b7b8", "g8b8"], 10)
    assert r.win and all(g.correct for g in r.grades)
    assert r.grades[-1].played == "g8b8" and r.grades[-1].expected == "f4b8"


def test_alternative_mate_after_a_wrong_prediction_is_not_accepted() -> None:
    s = mode.start(BACK_RANK, 0)
    # Your predicted reply (b7b6) is wrong, so your board isn't the real one: Rd8# there doesn't count.
    r = mode.on_submit(s, ["h2h3", "b7b6", "d1d8"], 10)
    assert not r.win
    assert [g.correct for g in r.grades] == [True, False, False]
    assert s.first_wrong is None  # the wrong move wasn't in the real position: no refutation
    # Same mate with the right prediction is accepted.
    s2 = mode.start(BACK_RANK, 0)
    assert mode.on_submit(s2, ["h2h3", "a6a5", "d1d8"], 10).win


def test_the_line_ends_at_an_accepted_mate_and_the_rest_is_extra() -> None:
    s = mode.start(FREXF, 0)
    r = mode.on_submit(s, ["g7g8", "b7b8", "g8b8"], 10)
    assert r.extra == ()
    assert (r.replies_correct, r.replies_total) == (1, 1)


def test_missing_reply_counts_as_not_predicted_and_missing_player_moves_lose() -> None:
    s = mode.start(BACK_RANK, 0)
    r = mode.on_submit(s, ["h2h3"], 10)
    assert not r.win and r.attempt is not None and r.attempt.first_move_correct
    assert (r.replies_correct, r.replies_total) == (0, 1)
    assert [g.played for g in r.grades] == ["h2h3", None, None]


def test_hint_then_submit_still_grades_but_stays_a_loss() -> None:
    s = mode.start(BACK_RANK, 0)
    h = mode.on_help(s, "hint", 5)
    assert h.attempt is not None and not h.attempt.win and h.hint_square == "h2"
    r = mode.on_submit(s, ["h2h3", "a6a5", "e1e8"], 10)
    assert not r.win and r.attempt is None  # already decided by the hint
    assert all(g.correct for g in r.grades)  # the line is still graded and shown


def test_show_answer_before_submit_ends_the_puzzle_and_submit_is_refused() -> None:
    s = mode.start(BACK_RANK, 0)
    mode.on_help(s, "hint", 1)
    mode.on_help(s, "answer", 2)
    with pytest.raises(ConflictError):
        mode.on_submit(s, ["h2h3"], 3)


def test_hidden_length_cap_is_the_same_for_every_puzzle() -> None:
    """Regression v0.5-B3: the cap used to be 2n+10, which gave the hidden length away."""
    assert max_plies(BACK_RANK, False) == 60
    long = Puzzle(PuzzleRef("lichess", "L"), BACK_RANK.fen, BACK_RANK.moves + ("x",) * 40, 1, (), "", ())
    assert max_plies(long, False) == 60


# ---- Spaced repetition ----------------------------------------------------------------------------

T0 = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def utc_day(at: datetime) -> date:
    return at.astimezone(UTC).date()


def test_srs_win_on_review_day_in_another_mode_does_not_move_the_box() -> None:
    card = schedule([Review(T0, "standard", False), Review(T0 + timedelta(days=1), "commit_line", True)],
                    (1, 3, 7), utc_day)  # fmt: skip
    assert card == Card(1, date(2026, 3, 2))


def test_srs_graduated_puzzle_ignores_further_srs_wins_and_is_never_due() -> None:
    rs = [Review(T0, "standard", False)] + [
        Review(T0 + timedelta(days=i), "spaced_repetition", True) for i in (1, 4, 9)
    ]
    card = schedule(rs, (1, 3), utc_day)
    assert card is not None and card.graduated and card.due is None
    assert not is_due(card, date(2030, 1, 1))
    assert due_order({"p": card}, date(2030, 1, 1)) == []


def test_srs_evening_miss_west_of_utc_is_due_the_next_local_morning() -> None:
    est = timezone(timedelta(hours=-5))
    late = datetime(2026, 3, 2, 3, 30, tzinfo=UTC)  # 22:30 on 1 March in UTC-5
    card = schedule([Review(late, "standard", False)], (1, 3), lambda at: at.astimezone(est).date())
    assert card is not None and card.due == date(2026, 3, 2)


def test_srs_shrinking_the_boxes_replays_history_with_the_new_boxes() -> None:
    rs = [Review(T0, "standard", False)] + [Review(T0 + timedelta(days=d), "spaced_repetition", True) for d in (1, 4)]
    assert schedule(rs, (1, 3, 7, 14, 30), utc_day) == Card(3, date(2026, 3, 12))
    card = schedule(rs, (1, 3), utc_day)  # box 2 was the last box: the second win graduated it
    assert card is not None and card.graduated


# ---- Depth ladder ---------------------------------------------------------------------------------


def test_ladder_exactly_at_threshold_moves_up_and_one_short_does_not() -> None:
    assert status("k", 2, [True] * 4 + [False], 80, 5).level == 3
    assert status("k", 2, [True] * 3 + [False] * 2, 80, 5).level == 2


def test_ladder_bigger_window_after_a_level_never_drops() -> None:
    st = status("k", 4, [False] * 3, 80, 50)
    assert st.level == 4 and st.top
