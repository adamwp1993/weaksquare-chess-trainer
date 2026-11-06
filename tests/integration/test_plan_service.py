"""The training plan against a real database and the real services (v0.12, FR-10.61–10.66)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.integration.test_qa_v011_coach import _games
from weaksquare.adapters.db.repos.coach import CoachReportsRepo
from weaksquare.adapters.db.repos.custom_puzzles import RetryRepo
from weaksquare.adapters.db.repos.plans import PlansRepo
from weaksquare.adapters.db.repos.user_data import SettingsRepo
from weaksquare.core.errors import ConflictError, NotFoundError, ValidationError
from weaksquare.core.plan import (
    GAME_PUZZLES,
    LESSON,
    PUZZLES,
    REFLECTION,
    RETRY,
    REVIEW,
    Day,
    PlanDraft,
    PlanParams,
    Task,
    training_dates,
)

EVERY_DAY = (0, 1, 2, 3, 4, 5, 6)


def _weakness(key: str, score: float, theme: str, games: list[int]) -> dict[str, Any]:
    kind, name = key.split(":", 1)
    return {
        "key": key, "kind": kind, "name": name, "label": key, "count": 3, "per10": 2.0, "severity": 200,
        "score": score, "themes": [theme], "mode": None, "reasons": {},
        "examples": [{"game_id": g, "ply": 8, "cp_loss": 300} for g in games],
    }  # fmt: skip


def _report(services: Any, subject: str = "me", games: list[int] | None = None) -> int:
    weak = [_weakness("missed:fork", 5.0, "fork", games or [])]
    return int(
        CoachReportsRepo(services.db).add(
            "2026-11-05T10:00:00+00:00", subject, "You", "games", {"detail": "summary"},
            {"source": "games", "games": 10, "weaknesses": weak, "missed": weak, "whole_game": []}, games or [],
        )
    )  # fmt: skip


def _plan(services: Any, tasks: list[Task], *, days: int = 1, minutes: int = 20) -> Any:
    """A plan with these tasks on its first day, stored directly, so each test controls exactly what's in it."""
    day_tasks = [tuple(tasks), *[(Task(REFLECTION, 5, "later", {"prompt": "later"}),) for _ in range(days - 1)]]
    draft = PlanDraft(
        PlanParams(1, EVERY_DAY[:days], minutes),
        tuple(Day(1, i + 1, t) for i, t in enumerate(day_tasks)),
    )
    today = services.plan._today()
    dates = [d for _, d in training_dates(today, tuple(sorted({(today.weekday() + i) % 7 for i in range(days)})), 1)]
    PlansRepo(services.db).add(
        draft, sorted(dates)[:days], services.plan._now(), report_id=None, source="deterministic"
    )
    return services.plan.current()


def _first(view: Any) -> Any:
    return view.days[0].tasks[0]


def _puzzle_task(count: int = 3) -> Task:
    return Task(PUZZLES, 10, f"{count} puzzles", {"themes": [], "mode": "standard", "count": count, "rating_min": None, "rating_max": None})  # fmt: skip


def _settings(services: Any) -> list[Any]:
    with services.db.session() as conn:
        return [tuple(r) for r in conn.execute("SELECT key, value FROM settings ORDER BY key").fetchall()]


# ---- building ----


def test_a_plan_needs_a_report_of_yours(services) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValidationError):
        services.plan.preview({})
    _report(services, subject="lichess:someone")
    with pytest.raises(ValidationError):  # another player's report never makes your plan (§10.1)
        services.plan.preview({})


def test_a_preview_saves_nothing_and_create_starts_on_a_picked_day(services) -> None:  # type: ignore[no-untyped-def]
    _report(services)
    pv = services.plan.preview({"weeks": 1, "weekdays": [0, 2], "minutes": 20})
    assert services.plan.current() is None
    assert pv.dates == ("2026-01-05", "2026-01-07")  # the clock's today, a Thursday, isn't picked: next Monday
    services.plan.create({"weeks": 1, "weekdays": [0, 2], "minutes": 20})
    assert [d.day.date for d in services.plan.current().days] == list(pv.dates)
    assert services.plan.params() == PlanParams(1, (0, 2), 20)


def test_a_new_plan_replaces_the_current_one_only_when_you_confirm(services) -> None:  # type: ignore[no-untyped-def]
    _report(services)
    first = services.plan.create({"weeks": 1})
    with pytest.raises(ConflictError):
        services.plan.create({"weeks": 2})
    assert services.plan.current().plan.id == first
    second = services.plan.create({"weeks": 2}, confirmed=True)
    assert services.plan.current().plan.id == second
    plans = {p.plan.id: p.plan.status for p in services.plan.history()}
    assert plans == {first: "replaced", second: "current"}


def test_a_puzzle_task_widens_until_it_has_enough_puzzles(services) -> None:  # type: ignore[no-untyped-def]
    _report(services)
    ctx = services.plan.context(services.plan.latest_report())
    narrow = {"themes": [], "mode": "standard", "rating_min": 3000, "rating_max": 3100}
    assert services.plan.fit_task(Task(PUZZLES, 10, "t", {**narrow, "count": 2}), ctx).params["rating_min"] == 2800
    too_many = services.plan.fit_task(Task(PUZZLES, 10, "t", {**narrow, "count": 500}), ctx)
    assert too_many.params["rating_min"] is None and too_many.params["rating_max"] is None


def test_a_game_puzzle_task_with_no_puzzles_becomes_general_puzzles(services) -> None:  # type: ignore[no-untyped-def]
    _report(services)
    ctx = services.plan.context(services.plan.latest_report())
    t = Task(GAME_PUZZLES, 10, "t", {"severities": ["blunder"], "kinds": [], "count": 5})
    assert services.plan.fit_task(t, ctx).type == PUZZLES


# ---- FR-10.63: Start ----


def test_a_puzzle_task_never_changes_your_filters_mode_presets_or_suggestion(services) -> None:  # type: ignore[no-untyped-def]
    filters = {"themes": ["pin"], "rating_min": 800, "rating_max": 900}
    repo = SettingsRepo(services.db)
    repo.set("mixer.filters", filters)
    repo.set("trainer.mode", "commit_line")
    repo.set("mixer.suggested_applied", filters)
    view = _plan(services, [_puzzle_task(3)])
    before = _settings(services)
    presets_before = services.presets.list()
    action = services.plan.start_task(_first(view).task.id)
    assert action.kind == "session" and action.remaining == 3
    services.sessions.next_puzzle(action.session.session_id)
    services.plan.current()
    assert _settings(services) == before
    assert services.presets.list() == presets_before


def test_each_task_type_opens_where_it_happens(services) -> None:  # type: ignore[no-untyped-def]
    gid = _games(services, 1)[0]
    view = _plan(
        services,
        [
            Task(RETRY, 5, "r", {"game_id": gid}),
            Task(REVIEW, 5, "v", {"game_id": gid}),
            Task(LESSON, 5, "l", {"topic": "theme:fork"}),
            Task(REFLECTION, 5, "x", {"prompt": "why?", "game_id": gid}, "missed:fork"),
        ],
    )
    got = [services.plan.start_task(t.task.id) for t in view.days[0].tasks]
    assert [a.kind for a in got] == [RETRY, REVIEW, LESSON, REFLECTION]
    assert got[0].game_id == gid and got[1].game_id == gid
    assert got[2].topic == "theme:fork"
    assert got[3].prompt == "why?" and got[3].weakness_key == "missed:fork" and got[3].game_id == gid


def test_a_task_whose_game_is_gone_says_so(services) -> None:  # type: ignore[no-untyped-def]
    view = _plan(services, [Task(REVIEW, 5, "v", {"game_id": 999})])
    with pytest.raises(NotFoundError):
        services.plan.start_task(_first(view).task.id)


# ---- FR-10.64: each task type ticks from the real events ----


def test_a_puzzle_task_ticks_when_its_sessions_reach_the_count_across_sessions(services) -> None:  # type: ignore[no-untyped-def]
    view = _plan(services, [_puzzle_task(2)])
    tid = _first(view).task.id
    a = services.plan.start_task(tid, rated=False)
    sid = a.session.session_id
    services.sessions.next_puzzle(sid)
    services.sessions.next_puzzle(sid)  # moving on from an undecided puzzle records it as a loss
    assert _first(services.plan.current()).progress == 1
    assert _first(services.plan.current()).status == "left"
    again = services.plan.start_task(tid, rated=False)  # stop and resume: only what's left
    assert again.remaining == 1
    s2 = again.session.session_id
    services.sessions.next_puzzle(s2)
    services.sessions.next_puzzle(s2)
    assert _first(services.plan.current()).status == "done"


def test_puzzles_outside_the_task_do_not_tick_it(services) -> None:  # type: ignore[no-untyped-def]
    from weaksquare.core.filters import FilterSpec

    view = _plan(services, [_puzzle_task(1)])
    info = services.sessions.start(FilterSpec(queue_size=5), False, "standard", False)
    services.sessions.next_puzzle(info.session_id)
    services.sessions.next_puzzle(info.session_id)
    assert _first(services.plan.current()).status == "left"
    assert view.plan.id == services.plan.current().plan.id


def test_retry_ticks_when_every_mistake_was_tried(services) -> None:  # type: ignore[no-untyped-def]
    gid = _games(services, 2)[1]
    plies = services.review.retry_plies(gid)
    assert len(plies) >= 1
    view = _plan(services, [Task(RETRY, 5, "r", {"game_id": gid})])
    repo = RetryRepo(services.db)
    for ply in plies[:-1]:
        repo.add(gid, ply, "e2e4", False, 100, services.plan._now())
    assert _first(services.plan.current()).status == "left"
    repo.add(gid, plies[-1], "e2e4", True, 0, services.plan._now())
    assert _first(services.plan.current()).status == "done"
    assert view.plan.id


def test_a_retry_from_before_the_plan_does_not_count(services, clock) -> None:  # type: ignore[no-untyped-def]
    gid = _games(services, 1)[0]
    for ply in services.review.retry_plies(gid):
        RetryRepo(services.db).add(gid, ply, "e2e4", True, 0, services.plan._now())
    clock.advance(hours=1)
    _plan(services, [Task(RETRY, 5, "r", {"game_id": gid})])
    assert _first(services.plan.current()).status == "left"


def test_a_review_ticks_at_every_key_moment_and_the_final_move(services) -> None:  # type: ignore[no-untyped-def]
    gid = _games(services, 1)[0]
    view = _plan(services, [Task(REVIEW, 5, "v", {"game_id": gid})])
    services.plan.start_task(_first(view).task.id)
    review = services.review.review(gid)
    last = len(review.moves) - 1
    for ply in review.key_moments:
        services.review.mark_visited(gid, ply)
    assert last not in review.key_moments
    assert _first(services.plan.current()).status == "left"  # the final move is still to come
    assert services.review.mark_visited(gid, last) is True
    assert _first(services.plan.current()).status == "done"


def test_jumping_to_the_last_move_alone_does_not_tick_a_review(services) -> None:  # type: ignore[no-untyped-def]
    gid = _games(services, 1)[0]
    view = _plan(services, [Task(REVIEW, 5, "v", {"game_id": gid})])
    services.plan.start_task(_first(view).task.id)
    services.review.mark_visited(gid, len(services.review.review(gid).moves) - 1)
    assert _first(services.plan.current()).status == "left"


def test_a_reflection_ticks_when_its_entry_is_saved(services) -> None:  # type: ignore[no-untyped-def]
    view = _plan(services, [Task(REFLECTION, 5, "x", {"prompt": "why?"})])
    tid = _first(view).task.id
    services.journal.add("Something I noticed.")  # not from this task
    assert _first(services.plan.current()).status == "left"
    services.journal.add("What I noticed.", plan_task_id=tid)
    assert _first(services.plan.current()).status == "done"


def test_a_lesson_ticks_when_you_open_it(services) -> None:  # type: ignore[no-untyped-def]
    view = _plan(services, [Task(LESSON, 5, "l", {"topic": "theme:fork"})])
    services.plan.start_task(_first(view).task.id)
    assert _first(services.plan.current()).status == "left"  # starting isn't opening a link
    services.plan.lesson_opened(_first(view).task.id)
    assert _first(services.plan.current()).status == "done"


def test_a_lesson_drill_starts_a_session_without_touching_your_filters(services) -> None:  # type: ignore[no-untyped-def]
    view = _plan(services, [Task(LESSON, 5, "l", {"topic": "theme:fork"})])
    before = _settings(services)
    action = services.plan.start_lesson_drill(_first(view).task.id, rated=False)
    assert action.kind == "session"
    assert _first(services.plan.current()).status == "done"
    assert _settings(services) == before


# ---- FR-10.64: by hand ----


def test_tick_untick_skip_and_a_hand_choice_beats_the_app(services) -> None:  # type: ignore[no-untyped-def]
    view = _plan(services, [Task(REFLECTION, 5, "x", {"prompt": "why?"})])
    tid = _first(view).task.id
    services.plan.set_tick(tid, True)
    t = _first(services.plan.current())
    assert t.status == "done" and t.auto is False
    services.plan.set_tick(tid, False)
    assert _first(services.plan.current()).status == "left"
    services.journal.add("Saved from the task.", plan_task_id=tid)  # the app now sees it done…
    t = _first(services.plan.current())
    assert t.auto is True and t.status == "left"  # …but you unticked it
    services.plan.set_tick(tid, True)
    assert _first(services.plan.current()).status == "done"
    services.plan.skip(tid)
    assert _first(services.plan.current()).status == "done"  # done beats skipped
    services.plan.set_tick(tid, False)
    services.plan.skip(tid)
    assert _first(services.plan.current()).status == "skipped"
    services.plan.skip(tid, False)
    assert _first(services.plan.current()).status == "left"


def test_a_tick_shows_in_both_the_today_card_and_the_plan(services) -> None:  # type: ignore[no-untyped-def]
    view = _plan(services, [Task(REFLECTION, 5, "x", {"prompt": "why?"})])
    tid = _first(view).task.id
    services.plan.set_tick(tid, True)
    assert services.plan.today().day.tasks[0].status == "done"
    services.plan.set_tick(tid, False)
    assert _first(services.plan.current()).status == "left"
    assert services.plan.today().day.tasks[0].status == "left"


def test_swap_replaces_the_task_in_place_and_keeps_the_minutes(services) -> None:  # type: ignore[no-untyped-def]
    gid = _games(services, 1)[0]
    _report(services, games=[gid])
    view = _plan(services, [_puzzle_task(3), Task(REFLECTION, 5, "x", {"prompt": "p"})])
    old = _first(view).task
    new_id = services.plan.swap(old.id)
    now = services.plan.current().days[0].tasks
    assert now[0].task.id == new_id and all(t.task.id != old.id for t in now)
    assert now[0].task.swapped_from == old.id and now[0].task.minutes == old.minutes
    with pytest.raises(NotFoundError):  # the old task is gone from the plan
        services.plan.set_tick(old.id, True)


def test_an_old_plan_is_read_only(services) -> None:  # type: ignore[no-untyped-def]
    _report(services)
    view = _plan(services, [Task(REFLECTION, 5, "x", {"prompt": "p"})])
    services.plan.create({"weeks": 1}, confirmed=True)
    with pytest.raises(ConflictError):
        services.plan.set_tick(_first(view).task.id, True)


# ---- FR-10.64: carry-over ----


def test_a_missed_days_tasks_carry_over_by_default_once(services, clock) -> None:  # type: ignore[no-untyped-def]
    _plan(services, [Task(REFLECTION, 5, "first", {"prompt": "first"})], days=2)
    clock.advance(days=1)
    view = services.plan.current()
    assert view.days[0].tasks[0].status == "carried"
    titles = [t.task.title for t in view.days[1].tasks]
    assert titles == ["later", "first"]
    services.plan.current()  # safe to repeat
    assert [t.task.title for t in services.plan.current().days[1].tasks] == titles


def test_with_carry_over_off_a_missed_task_is_just_missed(services, clock) -> None:  # type: ignore[no-untyped-def]
    SettingsRepo(services.db).set("plan.carry_over", False)
    _plan(services, [Task(REFLECTION, 5, "first", {"prompt": "first"})], days=2)
    clock.advance(days=1)
    view = services.plan.current()
    assert view.days[0].tasks[0].status == "missed"
    assert [t.task.title for t in view.days[1].tasks] == ["later"]


def test_a_carried_puzzle_task_keeps_its_progress(services, clock) -> None:  # type: ignore[no-untyped-def]
    view = _plan(services, [_puzzle_task(2)], days=2)
    a = services.plan.start_task(_first(view).task.id, rated=False)
    services.sessions.next_puzzle(a.session.session_id)
    services.sessions.next_puzzle(a.session.session_id)
    clock.advance(days=1)
    copy = services.plan.current().days[1].tasks[-1]
    assert copy.task.carried_from == _first(view).task.id
    assert copy.progress == 1


# ---- the Today card ----


def test_today_on_a_rest_day_names_the_next_training_day(services) -> None:  # type: ignore[no-untyped-def]
    _report(services)
    services.plan.create({"weeks": 1, "weekdays": [0], "minutes": 20})  # the clock's today isn't a Monday
    t = services.plan.today()
    assert t.day is None and t.next_date == "2026-01-05" and t.finished is False


def test_today_says_when_the_plan_has_finished(services, clock) -> None:  # type: ignore[no-untyped-def]
    _plan(services, [Task(REFLECTION, 5, "x", {"prompt": "p"})])
    clock.advance(days=30)
    t = services.plan.today()
    assert t.day is None and t.next_date is None and t.finished is True


# ---- FR-10.66: progress ----


def test_progress_is_aggregates_only(services) -> None:  # type: ignore[no-untyped-def]
    gid = _games(services, 1)[0]
    view = _plan(services, [_puzzle_task(1), Task(REVIEW, 5, "Review your game against Secret", {"game_id": gid})])
    a = services.plan.start_task(_first(view).task.id, rated=False)
    services.sessions.next_puzzle(a.session.session_id)
    services.sessions.next_puzzle(a.session.session_id)
    out = services.plan.progress()
    assert out["tasks_by_type"][PUZZLES] == {"done": 1}
    text = json.dumps(out)
    assert "Secret" not in text and f'"{gid}"' not in text and "game_id" not in text


def test_no_plan_no_progress(services) -> None:  # type: ignore[no-untyped-def]
    assert services.plan.progress() is None
    assert services.plan.current() is None and services.plan.today() is None


def test_a_move_past_the_end_of_the_game_never_completes_a_review(services) -> None:  # type: ignore[no-untyped-def]
    gid = _games(services, 1)[0]
    assert services.review.mark_visited(gid, 10_000) is False
