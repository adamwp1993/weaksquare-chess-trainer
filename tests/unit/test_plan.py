"""The training plan's pure rules (v0.12, FR-10.61–10.66)."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest

from weaksquare.core.errors import ValidationError
from weaksquare.core.plan import (
    CARRIED,
    DONE,
    GAME_PUZZLES,
    LEFT,
    MISSED,
    PUZZLES,
    REFLECTION,
    RETRY,
    REVIEW,
    SKIPPED,
    TASK_TYPES,
    Context,
    DayRow,
    Facts,
    PlanParams,
    PlanRow,
    Task,
    TaskRow,
    auto_done,
    build_plan,
    first_day,
    is_done,
    plan_progress,
    same_task,
    status_of,
    swap_choices,
    task_spec,
    to_carry,
    training_dates,
)

THURSDAY = date(2026, 11, 5)
CTX = Context(
    rating=1500, engine_ready=True, has_game_puzzles=True, games={1: "game 1", 2: "game 2", 3: "game 3", 4: "game 4"},
    retry_games=frozenset({1, 2, 3}), families=("Sicilian Defense",),
)  # fmt: skip


def weakness(key: str, score: float, *, theme: str | None = None, mode: str | None = None, games: tuple[int, ...] = (1, 2)) -> dict[str, Any]:  # fmt: skip
    kind, name = key.split(":", 1)
    return {
        "key": key, "kind": kind, "name": name, "label": key, "score": score, "themes": [theme] if theme else [],
        "mode": mode, "examples": [{"game_id": g, "ply": 20, "cp_loss": 300} for g in games],
    }  # fmt: skip


REPORT = {
    "weaknesses": [
        weakness("allowed:fork", 9.0, theme="fork", mode="danger_spotting"),
        weakness("missed:pin", 3.0, theme="pin", games=(3,)),
    ],
    "whole_game": [
        weakness("opening:Sicilian Defense", 1.0, games=(4,)),
        weakness("phase:conversion", 1.0, theme="crushing", games=(2,)),
    ],
}


def minutes_by_weakness(plan: Any) -> dict[str | None, int]:
    out: dict[str | None, int] = {}
    for d in plan.days:
        for t in d.tasks:
            out[t.weakness_key] = out.get(t.weakness_key, 0) + t.minutes
    return out


# ---- settings ----


@pytest.mark.parametrize(
    "bad",
    [{"weeks": 0}, {"weeks": 5}, {"minutes": 5}, {"minutes": 121}, {"weekdays": []}, {"weekdays": [7]},
     {"weeks": True}, {"weekdays": "mon"}, {"other": 1}, "x"],
)  # fmt: skip
def test_bad_settings_are_refused(bad: Any) -> None:
    with pytest.raises(ValidationError):
        PlanParams.from_json(bad)


def test_default_settings_are_two_weeks_monday_to_friday_at_20_minutes() -> None:
    p = PlanParams.from_json({})
    assert (p.weeks, p.weekdays, p.minutes) == (2, (0, 1, 2, 3, 4), 20)


# ---- dates: you pick the weekdays (Adam, v0.12 planning) ----


def test_a_plan_starts_today_when_today_is_picked_otherwise_on_the_next_picked_day() -> None:
    assert first_day(THURSDAY, (3,)) == THURSDAY
    assert first_day(THURSDAY, (0, 2)) == date(2026, 11, 9)  # next Monday


@pytest.mark.parametrize("weekdays", [(0,), (0, 2, 4), (0, 1, 2, 3, 4), (0, 1, 2, 3, 4, 5, 6)])
def test_every_week_has_exactly_the_picked_days(weekdays: tuple[int, ...]) -> None:
    start = first_day(THURSDAY, weekdays)
    dates = training_dates(start, weekdays, 3)
    assert len(dates) == 3 * len(weekdays)
    assert all(d.weekday() in weekdays for _, d in dates)
    assert [d for _, d in dates] == sorted({d for _, d in dates})
    for w in (1, 2, 3):
        assert sum(1 for week, _ in dates if week == w) == len(weekdays)


# ---- FR-10.61, 10.62: the plan ----


@pytest.mark.parametrize("minutes", [10, 15, 20, 25, 45, 50, 120])
@pytest.mark.parametrize("weekdays", [(0,), (0, 1, 2, 3, 4), (0, 1, 2, 3, 4, 5, 6)])
def test_each_day_fits_your_minutes_with_2_to_4_tasks(minutes: int, weekdays: tuple[int, ...]) -> None:
    plan = build_plan(REPORT, PlanParams(2, weekdays, minutes), CTX)
    assert len(plan.days) == 2 * len(weekdays)
    for d in plan.days:
        assert 2 <= len(d.tasks) <= 4
        assert sum(t.minutes for t in d.tasks) == minutes


def test_time_follows_the_weakness_score() -> None:
    plan = build_plan(REPORT, PlanParams(4, (0, 1, 2, 3, 4), 30), CTX)
    spent = minutes_by_weakness(plan)
    assert spent["allowed:fork"] > spent["missed:pin"] > spent["phase:conversion"]
    assert spent["allowed:fork"] == max(spent.values())


def test_every_task_is_of_the_closed_list_and_the_plan_uses_each_kind_it_can() -> None:
    plan = build_plan(REPORT, PlanParams(4, (0, 1, 2, 3, 4), 60), CTX)
    used = {t.type for d in plan.days for t in d.tasks}
    assert used <= set(TASK_TYPES)
    assert {PUZZLES, GAME_PUZZLES, RETRY, REVIEW, REFLECTION} <= used


def test_a_plan_is_the_same_every_time() -> None:
    p = PlanParams(2, (0, 2, 4), 30)
    assert json.dumps(build_plan(REPORT, p, CTX).to_json()) == json.dumps(build_plan(REPORT, p, CTX).to_json())


def test_each_week_has_one_reflection() -> None:
    plan = build_plan(REPORT, PlanParams(3, (0, 1, 2), 30), CTX)
    for w in (1, 2, 3):
        assert sum(1 for d in plan.days if d.week == w for t in d.tasks if t.type == REFLECTION) >= 1


def test_no_weaknesses_makes_a_general_mix_not_an_error() -> None:
    plan = build_plan({"weaknesses": [], "whole_game": []}, PlanParams(1, (0, 1), 20), Context())
    assert plan.days
    assert all(t.type in (PUZZLES, REFLECTION) for d in plan.days for t in d.tasks)


def test_a_game_is_never_retried_or_reviewed_twice_in_a_plan() -> None:
    plan = build_plan(REPORT, PlanParams(4, (0, 1, 2, 3, 4, 5, 6), 60), CTX)
    games = [(t.type, t.params["game_id"]) for d in plan.days for t in d.tasks if t.type in (RETRY, REVIEW)]
    assert len(games) == len(set(games))


def test_danger_spotting_is_only_planned_with_stockfish_ready() -> None:
    def modes(ctx: Context) -> set[str]:
        plan = build_plan(REPORT, PlanParams(1, (0, 1, 2, 3, 4), 30), ctx)
        return {t.params["mode"] for d in plan.days for t in d.tasks if t.type == PUZZLES}

    assert "danger_spotting" in modes(CTX)
    assert "danger_spotting" not in modes(Context(engine_ready=False))


def test_game_puzzles_are_planned_only_when_you_have_some() -> None:
    plan = build_plan(REPORT, PlanParams(4, (0, 1, 2, 3, 4), 60), Context(games=CTX.games, has_game_puzzles=False))
    assert GAME_PUZZLES not in {t.type for d in plan.days for t in d.tasks}


def test_a_game_outside_the_library_is_never_planned() -> None:
    report = {"weaknesses": [weakness("missed:pin", 5, theme="pin", games=(99,))], "whole_game": []}
    plan = build_plan(report, PlanParams(1, (0, 1, 2, 3, 4), 60), CTX)
    assert all(t.params.get("game_id") != 99 for d in plan.days for t in d.tasks)


def test_a_plan_survives_json() -> None:
    plan = build_plan(REPORT, PlanParams(1, (1, 3), 20), CTX)
    assert type(plan).from_json(json.loads(json.dumps(plan.to_json()))) == plan


# ---- FR-10.63: a puzzle task is its own filters ----


def test_a_puzzle_task_is_built_from_the_defaults_with_its_own_size() -> None:
    spec, mode = task_spec(PUZZLES, {"themes": ["fork"], "mode": "danger_spotting", "count": 20, "rating_min": 1350, "rating_max": 1650})  # fmt: skip
    assert (spec.themes, spec.queue_size, spec.rating_min, spec.source, mode) == (("fork",), 20, 1350, "lichess", "danger_spotting")  # fmt: skip


def test_a_game_puzzle_task_uses_your_puzzles_at_its_severity() -> None:
    spec, mode = task_spec(GAME_PUZZLES, {"severities": ["blunder"], "kinds": ["missed"], "count": 8})
    assert (spec.source, spec.my_severities, spec.my_kinds, spec.queue_size, mode) == ("my", ("blunder",), ("missed",), 8, "standard")  # fmt: skip


def test_another_task_type_has_no_filters() -> None:
    with pytest.raises(ValidationError):
        task_spec(REVIEW, {"game_id": 1})


# ---- FR-10.64: ticks ----


def row(i: int = 1, type_: str = PUZZLES, *, params: dict[str, Any] | None = None, manual: str | None = None,
        skipped: str | None = None, done: str | None = None, minutes: int = 10, carried_from: int | None = None) -> TaskRow:  # fmt: skip
    return TaskRow(i, 1, i, type_, "missed:pin", minutes, f"task {i}", params if params is not None else {"count": 5},
                   manual, skipped, done, carried_from, None)  # fmt: skip


def test_a_puzzle_task_ticks_when_its_sessions_reach_the_count() -> None:
    t = row()
    assert not auto_done(t, Facts(attempts={1: 4}))
    assert auto_done(t, Facts(attempts={1: 5}))


def test_retry_ticks_only_when_every_mistake_was_tried() -> None:
    t = row(type_=RETRY, params={"game_id": 7})
    need = {7: frozenset({10, 20})}
    assert not auto_done(t, Facts(retry_needed=need, retry_tried={7: frozenset({10})}))
    assert auto_done(t, Facts(retry_needed=need, retry_tried={7: frozenset({10, 20})}))
    assert not auto_done(t, Facts(retry_needed={}, retry_tried={}))


def test_a_review_ticks_from_its_own_pass_or_any_pass_since_the_plan_began() -> None:
    t = row(type_=REVIEW, params={"game_id": 7})
    assert not auto_done(t, Facts())
    assert auto_done(t, Facts(reviewed_tasks=frozenset({1})))
    assert auto_done(t, Facts(reviewed_games=frozenset({7})))


def test_a_reflection_ticks_when_its_entry_is_saved() -> None:
    t = row(type_=REFLECTION, params={"prompt": "p"})
    assert not auto_done(t, Facts())
    assert auto_done(t, Facts(entry_tasks=frozenset({1})))


def test_a_hand_tick_counts_whatever_the_app_saw() -> None:
    assert is_done(row(manual="done"), Facts())


def test_a_box_you_unticked_stays_unticked_even_when_the_app_sees_it_done() -> None:
    assert not is_done(row(manual="undone"), Facts(attempts={1: 5}))
    assert is_done(row(manual=None), Facts(attempts={1: 5}))


def test_statuses() -> None:
    day = "2026-11-05"
    assert status_of(row(manual="done"), day, THURSDAY, Facts(), frozenset()) == DONE
    assert status_of(row(skipped="t"), day, THURSDAY, Facts(), frozenset()) == SKIPPED
    assert status_of(row(), day, THURSDAY, Facts(), frozenset({1})) == CARRIED
    assert status_of(row(), day, THURSDAY, Facts(), frozenset()) == LEFT
    assert status_of(row(), "2026-11-04", THURSDAY, Facts(), frozenset()) == MISSED


# ---- swap ----


def test_swap_gives_a_different_task_for_the_same_weakness_first() -> None:
    plan = build_plan(REPORT, PlanParams(1, (0,), 20), CTX)
    first = plan.days[0].tasks[0]
    new = next(t for t in swap_choices(first, REPORT, CTX) if not same_task(t, first))
    assert new.weakness_key == first.weakness_key
    assert (new.type, new.params) != (first.type, first.params)
    assert new.minutes == first.minutes


def test_swap_is_deterministic_and_always_finds_something() -> None:
    t = Task(PUZZLES, 10, "x", {"themes": [], "mode": "standard", "count": 5}, None)
    empty = {"weaknesses": [], "whole_game": []}
    choices = swap_choices(t, empty, Context())
    assert choices == swap_choices(t, empty, Context())
    assert any(not same_task(c, t) for c in choices)


def test_same_task_ignores_the_size_and_rating_band_only() -> None:
    a = Task(
        PUZZLES,
        10,
        "6 puzzles",
        {"themes": ["fork"], "mode": "standard", "count": 6, "rating_min": 1000, "rating_max": 1400},
    )
    bigger = Task(
        PUZZLES,
        10,
        "30 puzzles",
        {"themes": ["fork"], "mode": "standard", "count": 30, "rating_min": 800, "rating_max": 1600},
    )
    other_mode = Task(
        PUZZLES,
        10,
        "6 puzzles",
        {"themes": ["fork"], "mode": "commit_line", "count": 6, "rating_min": 1000, "rating_max": 1400},
    )
    assert same_task(a, bigger)
    assert not same_task(a, other_mode)


# ---- carry-over ----


def plan_with(days: list[DayRow], minutes: int = 20) -> PlanRow:
    return PlanRow(1, "t", None, "deterministic", None, PlanParams(1, (0, 1, 2, 3, 4), minutes), days[0].date, "current", None, tuple(days))  # fmt: skip


def day(i: int, iso: str, tasks: list[TaskRow]) -> DayRow:
    return DayRow(i, 1, 1, i, iso, tuple(tasks))


def test_yesterdays_unfinished_tasks_carry_to_today() -> None:
    plan = plan_with([day(1, "2026-11-04", [row(1), row(2, manual="done")]), day(2, "2026-11-05", [row(3)])])
    found = to_carry(plan, THURSDAY, Facts())
    assert found is not None
    assert found[0].id == 2
    assert [t.id for t in found[1]] == [1]


def test_carry_over_is_at_most_one_days_worth() -> None:
    tasks = [row(1, minutes=10), row(2, minutes=10), row(3, minutes=10)]
    plan = plan_with([day(1, "2026-11-04", tasks), day(2, "2026-11-05", [row(4)])], minutes=20)
    found = to_carry(plan, THURSDAY, Facts())
    assert found is not None
    assert [t.id for t in found[1]] == [1, 2]


def test_carry_over_is_safe_to_repeat() -> None:
    plan = plan_with([day(1, "2026-11-04", [row(1)]), day(2, "2026-11-05", [row(2, carried_from=1)])])
    assert to_carry(plan, THURSDAY, Facts()) is None


def test_nothing_carries_on_a_rest_day_but_it_does_on_the_next_training_day() -> None:
    plan = plan_with([day(1, "2026-11-04", [row(1)]), day(2, "2026-11-06", [row(2)])])
    assert to_carry(plan, THURSDAY, Facts()) is None
    found = to_carry(plan, date(2026, 11, 6), Facts())
    assert found is not None
    assert [t.id for t in found[1]] == [1]


def test_only_the_last_training_day_carries_older_ones_are_missed() -> None:
    plan = plan_with([day(1, "2026-11-03", [row(1)]), day(2, "2026-11-04", [row(2)]), day(3, "2026-11-05", [row(3)])])
    found = to_carry(plan, THURSDAY, Facts())
    assert found is not None
    assert [t.id for t in found[1]] == [2]


def test_skipped_and_done_tasks_do_not_carry() -> None:
    plan = plan_with([day(1, "2026-11-04", [row(1, skipped="t"), row(2, manual="done")]), day(2, "2026-11-05", [row(3)])])  # fmt: skip
    assert to_carry(plan, THURSDAY, Facts()) is None


# ---- FR-10.66: progress is aggregates only ----


def test_progress_holds_aggregates_only() -> None:
    secret_prompt = "My secret plan against Opponent"
    tasks = [
        row(1, params={"count": 5}, manual="done"),
        row(2, REVIEW, params={"game_id": 12345}, skipped="t"),
        row(3, REFLECTION, params={"prompt": secret_prompt}),
    ]
    plan = plan_with([day(1, "2026-11-05", tasks)])
    out = plan_progress(plan, THURSDAY, Facts(seconds={1: 300}), {"fork": (10, 7)})
    assert out["tasks_by_type"][PUZZLES] == {DONE: 1}
    assert out["tasks_by_type"][REVIEW] == {SKIPPED: 1}
    assert out["puzzle_first_try_by_theme"]["fork"] == {"attempts": 10, "first_try": 7}
    assert out["minutes_spent"] == 5
    text = json.dumps(out)
    assert secret_prompt not in text
    assert "12345" not in text
    assert "task 1" not in text
