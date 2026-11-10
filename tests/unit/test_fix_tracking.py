"""v1.0 fix tracking (REQUIREMENTS §10.8, FR-10.34–10.36): every status rule on synthetic data, the sample-size
guard, absent weaknesses, settings, the schedule and game health."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from weaksquare.core.coach import Report, Weakness
from weaksquare.core.errors import ValidationError
from weaksquare.core.fix_tracking import (
    BASELINE_GAMES,
    FIXED,
    IMPROVING,
    NEW,
    REGRESSED,
    TRAINING,
    CheckpointSettings,
    MyMove,
    Observation,
    PuzzleAccuracy,
    Schedule,
    Thresholds,
    Tracked,
    absent_means_zero,
    backfill_points,
    checked_settings,
    game_health,
    is_guarded,
    mark_training,
    next_status,
    observations,
    puzzle_accuracy,
    reason_groups,
    schedule_due,
    step,
)
from weaksquare.core.stats import AttemptRow

TH = Thresholds()
GOOD = PuzzleAccuracy(0.8, 25)  # passes the Fixed puzzle gate
WEAK = PuzzleAccuracy(0.6, 25)
FEW = PuzzleAccuracy(0.9, 10)


def _t(status: str = TRAINING, baseline: float = 4.0, streak: int = 0, themes: tuple[str, ...] = ("fork",),
       key: str = "allowed:fork") -> Tracked:  # fmt: skip
    return Tracked(key, key.split(":")[0], "Allowed: Fork", themes, baseline, 50, 1, status, 1, streak)


def _obs(per10: float, count: int, key: str = "allowed:fork") -> Observation:
    return Observation(key, key.split(":")[0], "Allowed: Fork", ("fork",), per10, count)


def _status(t: Tracked, per10: float, acc: PuzzleAccuracy = GOOD, in_mix: set[str] | None = None) -> tuple[str, int]:
    return next_status(t, per10, False, acc, in_mix if in_mix is not None else {t.key}, TH)


# ---- FR-10.35, rule by rule -------------------------------------------------------------------------------------


def test_at_or_under_75_percent_of_baseline_is_improving() -> None:
    assert _status(_t(), 3.0) == (IMPROVING, 0)
    assert _status(_t(), 3.1)[0] == TRAINING


def test_fixed_needs_two_checkpoints_in_a_row_at_half_the_baseline() -> None:
    first = _status(_t(), 2.0)
    assert first == (IMPROVING, 1)  # one checkpoint at 50% isn't enough
    assert _status(_t(IMPROVING, streak=1), 2.0) == (FIXED, 2)


def test_the_streak_resets_when_the_rate_goes_back_above_half() -> None:
    assert _status(_t(IMPROVING, streak=1), 2.5) == (IMPROVING, 0)
    assert _status(_t(IMPROVING, streak=0), 2.0) == (IMPROVING, 1)


def test_fixed_also_needs_75_percent_puzzle_accuracy() -> None:
    assert _status(_t(IMPROVING, streak=1), 2.0, WEAK)[0] == IMPROVING


def test_fixed_needs_at_least_20_puzzle_attempts() -> None:
    assert _status(_t(IMPROVING, streak=1), 2.0, FEW)[0] == IMPROVING


def test_puzzle_accuracy_alone_never_makes_fixed() -> None:
    """The game rate decides: perfect puzzles with an unchanged game rate stay where they were."""
    assert _status(_t(), 4.0, PuzzleAccuracy(1.0, 500))[0] == TRAINING
    assert _status(_t(IMPROVING, streak=5), 3.0, PuzzleAccuracy(1.0, 500))[0] == IMPROVING


def test_a_weakness_no_puzzle_trains_is_decided_by_the_game_rate_alone() -> None:
    t = _t(IMPROVING, streak=1, themes=(), key="time:low_clock")
    assert _status(t, 2.0, PuzzleAccuracy(None, 0))[0] == FIXED


def test_fixed_climbing_back_to_90_percent_is_regressed() -> None:
    assert _status(_t(FIXED, streak=3), 3.6) == (REGRESSED, 0)


def test_improving_climbing_back_to_90_percent_is_regressed() -> None:
    assert _status(_t(IMPROVING), 3.6) == (REGRESSED, 0)


def test_new_or_training_at_90_percent_isnt_regressed() -> None:
    assert _status(_t(TRAINING), 4.0)[0] == TRAINING
    assert _status(_t(NEW), 5.0, in_mix=set())[0] == NEW


def test_fixed_between_half_and_90_percent_stays_fixed() -> None:
    assert _status(_t(FIXED, streak=2), 3.0)[0] == FIXED


def test_improving_drifting_up_past_75_but_under_90_falls_back() -> None:
    assert _status(_t(IMPROVING), 3.2)[0] == TRAINING
    assert _status(_t(IMPROVING), 3.2, in_mix=set())[0] == NEW


def test_regressed_stays_until_it_improves() -> None:
    assert _status(_t(REGRESSED), 3.4)[0] == REGRESSED
    assert _status(_t(REGRESSED), 2.9)[0] == IMPROVING


# ---- FR-10.34: the sample-size guard ----------------------------------------------------------------------------


def test_the_guard_needs_few_occurrences_and_a_baseline_that_expected_few() -> None:
    """Adam, v1.0 build: both small. A common weakness dropping to 0 isn't guarded, so it can reach Fixed."""
    assert is_guarded(1, 1.0, 30, TH)  # expected 3, saw 1: noise either way
    assert is_guarded(4, 1.5, 30, TH)  # expected 4.5
    assert not is_guarded(5, 1.0, 30, TH)  # saw 5
    assert not is_guarded(0, 4.0, 30, TH)  # expected 12, saw 0: a real improvement
    assert not is_guarded(4, 2.0, 30, TH)  # expected 6


def test_a_guarded_metric_changes_no_status() -> None:
    t = _t(IMPROVING, streak=1)
    assert next_status(t, 0.5, True, GOOD, {t.key}, TH) == (IMPROVING, 1)
    assert next_status(_t(FIXED), 4.0, True, GOOD, set(), TH) == (FIXED, 0)


def test_step_marks_the_point_guarded_and_keeps_the_status() -> None:
    t = _t(IMPROVING, streak=1, baseline=1.0)
    out = step({t.key: t}, {t.key: _obs(0.3, 1)}, 30, 2, lambda th: GOOD, {t.key}, TH)
    assert out.tracked[t.key].status == IMPROVING and out.metrics[0].guarded and out.changes == []


# ---- step ------------------------------------------------------------------------------------------------------


def test_a_new_weakness_starts_tracking_with_its_own_rate_as_baseline() -> None:
    out = step({}, {"allowed:fork": _obs(3.0, 9)}, 30, 1, lambda th: WEAK, set(), TH)
    t = out.tracked["allowed:fork"]
    assert (t.baseline_per10, t.baseline_games, t.status, t.first_checkpoint) == (3.0, 30, NEW, 1)
    assert out.changes[0].old is None and out.changes[0].new == NEW


def test_the_first_checkpoints_baselines_come_from_the_baseline_window() -> None:
    out = step({}, {"allowed:fork": _obs(3.0, 9)}, 30, 1, lambda th: WEAK, set(), TH,
               baselines={"allowed:fork": (4.4, BASELINE_GAMES)})  # fmt: skip
    assert out.tracked["allowed:fork"].baseline_per10 == 4.4 and out.tracked["allowed:fork"].baseline_games == 50


def test_baselines_are_frozen() -> None:
    t = _t(baseline=4.0)
    out = step({t.key: t}, {t.key: _obs(9.0, 27)}, 30, 2, lambda th: GOOD, {t.key}, TH,
               baselines={t.key: (1.0, 50)})  # fmt: skip
    assert out.tracked[t.key].baseline_per10 == 4.0


def test_a_tactical_weakness_missing_from_the_report_counts_as_zero() -> None:
    t = _t(IMPROVING, streak=1)
    out = step({t.key: t}, {}, 30, 3, lambda th: GOOD, {t.key}, TH)
    assert out.metrics[0].per10 == 0 and out.metrics[0].count == 0
    assert out.tracked[t.key].status == FIXED and out.changes[0].old == IMPROVING


def test_a_whole_game_weakness_missing_from_the_report_isnt_measured() -> None:
    t = _t(IMPROVING, streak=1, themes=(), key="opening:Sicilian Defense")
    out = step({t.key: t}, {}, 30, 3, lambda th: GOOD, set(), TH)
    assert out.metrics == [] and out.tracked[t.key] == t


def test_absent_means_zero_for_tactics_and_habit_tags_only() -> None:
    assert (
        absent_means_zero("missed:fork") and absent_means_zero("allowed:pin") and absent_means_zero("habit:hungPiece")
    )
    for key in ("habit:castledLate", "time:low_clock", "opening:Italian Game", "endgame:rook", "phase:conversion"):
        assert not absent_means_zero(key)


def test_status_since_moves_only_when_the_status_changes() -> None:
    t = _t(TRAINING)
    same = step({t.key: t}, {t.key: _obs(4.0, 12)}, 30, 5, lambda th: GOOD, {t.key}, TH)
    assert same.tracked[t.key].status_since == 1
    moved = step({t.key: t}, {t.key: _obs(2.5, 8)}, 30, 5, lambda th: GOOD, {t.key}, TH)
    assert moved.tracked[t.key].status_since == 5


def test_new_and_training_swaps_arent_status_changes() -> None:
    t = _t(NEW)
    out = step({t.key: t}, {t.key: _obs(4.0, 12)}, 30, 2, lambda th: GOOD, {t.key}, TH)
    assert out.tracked[t.key].status == TRAINING and out.changes == []


def test_mark_training_follows_the_mix_and_leaves_decided_statuses_alone() -> None:
    a, b, c = _t(NEW, key="allowed:fork"), _t(TRAINING, key="missed:pin"), _t(FIXED, key="habit:hungPiece")
    out = mark_training({x.key: x for x in (a, b, c)}, ["allowed:fork", "habit:hungPiece"], 4)
    assert out["allowed:fork"].status == TRAINING and out["allowed:fork"].status_since == 4
    assert out["missed:pin"].status == NEW
    assert out["habit:hungPiece"].status == FIXED


# ---- observations and puzzle accuracy --------------------------------------------------------------------------


def _w(key: str, per10: float, count: int) -> Weakness:
    kind, _, name = key.partition(":")
    return Weakness(key, kind, name, key, count, per10, 300, per10 * 3, (name,), None, {"didntLook": 2})


def test_observations_take_every_game_weakness_of_a_report() -> None:
    r = Report("games", 30, None, None, {}, {}, [_w("missed:fork", 1, 3)], [_w("allowed:pin", 2, 6)],
               [_w("habit:hungPiece", 3, 9)], [_w("puzzle:skewer", 0, 4)], [], {}, 0,
               whole_game=[_w("time:low_clock", 1, 3)])  # fmt: skip
    assert set(observations(r)) == {"missed:fork", "allowed:pin", "habit:hungPiece", "time:low_clock"}


def _attempt(win: bool, themes: tuple[str, ...], at: datetime, reason: str | None = None) -> AttemptRow:
    return AttemptRow(win, win, win, 1500, themes, 2, reason=reason, finished_at=at)


def test_puzzle_accuracy_counts_attempts_on_the_themes_before_the_cutoff() -> None:
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    rows = [_attempt(True, ("fork",), t0), _attempt(False, ("fork", "pin"), t0), _attempt(True, ("pin",), t0),
            _attempt(False, ("fork",), t0, reason="misclick"), _attempt(True, ("fork",), t0 + timedelta(days=3))]  # fmt: skip
    assert puzzle_accuracy(("fork",), rows) == PuzzleAccuracy(0.667, 3)
    assert puzzle_accuracy(("fork",), rows, before=t0 + timedelta(days=1)) == PuzzleAccuracy(0.5, 2)
    assert puzzle_accuracy(("fork",), rows, dashboard={"fork": (7, 7)}) == PuzzleAccuracy(0.9, 10)
    assert puzzle_accuracy((), rows) == PuzzleAccuracy(None, 0)


# ---- settings and the schedule ---------------------------------------------------------------------------------


def test_default_settings_round_trip() -> None:
    d = CheckpointSettings()
    assert checked_settings(d.to_json()) == d
    assert (d.every_games, d.window, d.schedule.kind, d.auto_ai, d.notices) == (10, 30, "off", False, True)


@pytest.mark.parametrize("bad", [
    {"every_games": 4}, {"every_games": True}, {"window": 500}, {"schedule": {"kind": "monthly"}},
    {"schedule": {"kind": "weekday", "weekday": 7}}, {"thresholds": {"fixed": 0.8}},  # fixed above improving
    {"thresholds": {"regressed": 1.5}}, {"time_classes": []}, {"time_classes": ["hyperbullet"]},
    {"color": "red"}, {"auto_ai": "yes"}, {"surprise": 1}, [],
])  # fmt: skip
def test_bad_settings_are_refused(bad: object) -> None:
    with pytest.raises(ValidationError):
        checked_settings(bad)


def _local(at: datetime) -> date:
    return at.date()


MONDAY = datetime(2026, 11, 9, 12, tzinfo=UTC)


def test_the_schedule_is_off_by_default() -> None:
    assert not schedule_due(Schedule(), None, MONDAY, MONDAY + timedelta(days=30), _local)


def test_every_n_days_counts_from_the_last_time_or_when_it_was_turned_on() -> None:
    s = Schedule("days", days=3)
    assert not schedule_due(s, None, MONDAY, MONDAY + timedelta(days=2), _local)
    assert schedule_due(s, None, MONDAY, MONDAY + timedelta(days=3), _local)
    assert not schedule_due(s, MONDAY + timedelta(days=3), MONDAY, MONDAY + timedelta(days=5), _local)


def test_a_weekday_is_due_once_a_week_on_or_after_that_day() -> None:
    s = Schedule("weekday", weekday=2)  # Wednesday
    assert not schedule_due(s, None, MONDAY, MONDAY + timedelta(days=1), _local)  # Tuesday
    assert schedule_due(s, None, MONDAY, MONDAY + timedelta(days=2), _local)  # Wednesday
    assert schedule_due(s, None, MONDAY, MONDAY + timedelta(days=4), _local)  # Friday: missed while closed
    wed = MONDAY + timedelta(days=2)
    assert not schedule_due(s, wed, MONDAY, wed + timedelta(days=3), _local)  # served this week
    assert schedule_due(s, wed, MONDAY, wed + timedelta(days=7), _local)


def test_a_weekday_isnt_due_for_the_week_it_was_turned_on_after() -> None:
    s = Schedule("weekday", weekday=0)  # Monday; turned on Tuesday
    tue = MONDAY + timedelta(days=1)
    assert not schedule_due(s, None, tue, tue + timedelta(days=2), _local)
    assert schedule_due(s, None, tue, MONDAY + timedelta(days=7), _local)


def test_a_last_time_in_the_future_makes_it_due_now() -> None:
    assert schedule_due(Schedule("days", days=7), MONDAY + timedelta(days=30), MONDAY, MONDAY, _local)


# ---- game health (FR-10.36) and backfill points ----------------------------------------------------------------


def test_reason_groups_are_shares_of_the_four_groups_without_misclicks() -> None:
    assert reason_groups({"didntLook": 2, "missedResource": 1, "miscalculated": 1, "misclick": 5}) == {
        "process": 0.75, "calculation": 0.25, "knowledge": 0.0, "time": 0.0,
    }  # fmt: skip
    assert reason_groups({"misclick": 3}) == {}


def test_game_health_has_rates_cp_loss_by_phase_and_latest_ratings() -> None:
    r = Report("games", 2, None, None, {"blunders": 5.0, "mistakes": 10.0, "inaccuracies": 15.0}, {"win": 1, "loss": 1},
               [], [], [_w("habit:hungPiece", 5.0, 1)], [], [], {"rushed": 1}, 0)  # fmt: skip
    moves = {1: [MyMove(2, "opening", 10), MyMove(30, "middlegame", 200)], 2: [MyMove(70, "endgame", 3000)]}
    ratings = [("lichess", "2026-01-01T10:00:00", 1500), ("lichess", "2026-01-02T10:00:00", 1520),
               ("chesscom", "2026-01-01T10:00:00", 1300), ("paste", "2026-01-03", 9999)]  # fmt: skip
    h = game_health(r, moves, ratings)
    assert h["per10"] == {"blunders": 5.0, "mistakes": 10.0, "inaccuracies": 15.0}
    assert h["acpl"] == round((10 + 200 + 1000) / 3, 1)  # losses capped at 1000
    assert h["acpl_by_phase"] == {"opening": 10.0, "middlegame": 200.0, "endgame": 1000.0}
    assert h["habits"] == {"hungPiece": 5.0} and h["reasons"]["time"] == 1.0
    assert h["ratings"] == {"chesscom": 1300, "lichess": 1520} and h["results"] == {"win": 1, "loss": 1}


def test_backfill_points_start_after_the_baseline_window() -> None:
    ids = list(range(1, 76))  # 75 games, oldest first
    pts = backfill_points(ids, 10, 30)
    assert [p.window[-1] for p in pts] == [50, 60, 70]
    assert pts[0].baseline == tuple(range(1, 51)) and pts[1].baseline == ()
    assert all(len(p.window) == 30 for p in pts)
    assert backfill_points(ids[:49], 10, 30) == []
