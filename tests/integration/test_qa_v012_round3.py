"""QA v0.12 round 3: what the round 2 fixes newly touch, through the real bridge, from real events. A test exposing an
open bug is marked xfail with its ID."""

from __future__ import annotations

import json
import time
from typing import Any

import pytest

from tests.fakes.engine import FakeEngine, plant_managed_install
from tests.helpers import FakeDesktop
from tests.integration.test_coach_run import ANY_GAME, _run
from tests.integration.test_qa_v011_coach import _games
from tests.integration.test_qa_v012_journal_ai import _secret_game
from tests.integration.test_qa_v012_plan import (
    EVERY_DAY,
    _api,
    _ok,
    _plan_with,
    _puzzles_task,
    _real_report,
    _solve_next,
    _svc,
    _task,
)
from tests.integration.test_qa_v012_round2 import _carried, _day, _log_done, _ref, _today_iso, _visit_all, _weak
from weaksquare.bridge.api import Api
from weaksquare.core.plan import LESSON, RETRY, REVIEW, Context, Task, general_task
from weaksquare.core.report_compare import Side, compare, prompt_json, validate_trend


@pytest.fixture(autouse=True)
def _reset() -> None:
    FakeEngine.instances.clear()


@pytest.fixture
def desktop() -> FakeDesktop:
    return FakeDesktop()


@pytest.fixture
def api(paths: Any, clock: Any, desktop: FakeDesktop, fixture_puzzles_db: Any) -> Api:
    return _api(paths, clock, desktop, fixture_puzzles_db)


def _review(gid: int, name: str = "v") -> Task:
    return Task(REVIEW, 10, name, {"game_id": gid})


def _by_id(plan: dict[str, Any], tid: int) -> dict[str, Any]:
    return next(t for d in plan["days"] for t in d["tasks"] if t["id"] == tid)


def _all_tasks(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [t for d in plan["days"] for t in d["tasks"]]


def _passes(api: Api) -> list[tuple[Any, ...]]:
    with _svc(api).db.session() as conn:
        rows = conn.execute("SELECT game_id, plan_task_id, plies_json, completed_at FROM review_passes ORDER BY id")
        return [tuple(r) for r in rows]


# ---- PlansRepo.add deletes unfinished passes (QA v0.12-B20's fix) ----


def test_qa3_a_new_plan_keeps_finished_passes_and_what_the_daily_log_says(api: Api, paths: Any, clock: Any) -> None:
    plant_managed_install(paths)
    done_game, open_game = _games(_svc(api), 2)
    _visit_all(api, done_game)
    rev = _ok(api.get_review(open_game))
    _ok(api.mark_review_ply(open_game, rev["key_moments"][0]))
    day = _today_iso(api)

    def reviewed() -> int:
        got = _ok(api.get_journal({"date_from": day, "date_to": day, "kinds": ["log"]}))
        return int(next(i["log"] for i in got["items"] if i["log"])["games_reviewed"])

    assert reviewed() == 1
    clock.advance(hours=1)
    _plan_with(api, [[_review(open_game)], [_ref("y")]])
    assert reviewed() == 1, "a new plan must not change the log of a day already gone"
    assert [p[0] for p in _passes(api)] == [done_game]


def test_qa3_a_replaced_plans_finished_review_stays_done_and_its_half_review_stays_undone(
    api: Api, paths: Any, clock: Any
) -> None:
    plant_managed_install(paths)
    finished, half = _games(_svc(api), 2)
    old = _plan_with(api, [[_review(finished, "f"), _review(half, "h")], [_ref("y")]])
    a, b = _task(old, 0, 0)["id"], _task(old, 0, 1)["id"]
    clock.advance(minutes=1)
    _ok(api.start_plan_task(a))
    _visit_all(api, finished)
    _ok(api.start_plan_task(b))
    rev = _ok(api.get_review(half))
    for m in rev["key_moments"]:
        _ok(api.mark_review_ply(half, m))
    clock.advance(minutes=1)
    new = _plan_with(api, [[_review(half, "again")], [_ref("y")]])
    # The rest of the half-reviewed game, after the replacement, counts for neither plan: the plan began after them.
    clock.advance(minutes=1)
    _ok(api.mark_review_ply(half, len(rev["moves"]) - 1))
    history = _ok(api.list_plans())
    was = next(p for p in history if p["id"] == old["id"])
    assert _by_id(was, a)["status"] == "done"
    assert _by_id(was, b)["status"] != "done"
    assert _task(_ok(api.get_current_plan()))["status"] == "left"
    # Going through the whole game for the new plan ticks it, with no Start.
    _visit_all(api, half)
    assert _task(_ok(api.get_current_plan()))["id"] == _task(new)["id"]
    assert _task(_ok(api.get_current_plan()))["status"] == "done"
    was = next(p for p in _ok(api.list_plans()) if p["id"] == old["id"])
    assert _by_id(was, b)["status"] != "done", "an ended plan stays as it was"


def test_qa3_a_second_plan_in_the_same_second_as_the_visits_does_not_break_the_review(api: Api, paths: Any) -> None:
    """The clock doesn't move at all here: a pass and a plan with one timestamp."""
    plant_managed_install(paths)
    gid = _games(_svc(api), 1)[0]
    _plan_with(api, [[_review(gid)], [_ref("y")]])
    rev = _ok(api.get_review(gid))
    _ok(api.mark_review_ply(gid, rev["key_moments"][0]))
    _plan_with(api, [[_review(gid)], [_ref("y")]])
    assert _passes(api) == []
    _visit_all(api, gid)
    assert _task(_ok(api.get_current_plan()))["status"] == "done"


# ---- Facts.carried: a task with a copy no longer ticks itself (QA v0.12-B26's fix) ----


def _carried_pair(api: Api, clock: Any, first: Task) -> tuple[dict[str, Any], int, int]:
    plan = _plan_with(api, [[first], [_ref("b")], [_ref("c")]])
    original = _task(plan)["id"]
    clock.advance(days=1)
    plan = _ok(api.get_current_plan())
    copy = _carried(plan, 1)[0]["id"]
    return plan, original, copy


def test_qa3_a_chain_of_copies_keeps_its_progress_and_finishes_once(api: Api, paths: Any, clock: Any) -> None:
    plan = _plan_with(api, [[_puzzles_task(3, 10)], [_ref("b")], [_ref("c")], [_ref("d")]])
    t0 = _task(plan)["id"]
    sid = _ok(api.start_plan_task(t0, False))["session"]["session_id"]
    assert _solve_next(api, paths, sid)
    _ok(api.next_puzzle(sid))  # the first attempt is decided
    clock.advance(days=1)
    plan = _ok(api.get_current_plan())
    t1 = _carried(plan, 1)[0]["id"]
    assert _by_id(plan, t1)["progress"] == 1 and _by_id(plan, t1)["status"] == "left"
    assert _by_id(plan, t0)["status"] == "carried"
    clock.advance(days=1)
    plan = _ok(api.get_current_plan())
    t2 = next(t["id"] for t in _carried(plan, 2) if t["type"] == "puzzles")
    assert _by_id(plan, t2)["progress"] == 1
    assert _by_id(plan, t1)["status"] == "carried"
    # The middle copy's own Start isn't what's offered: the newest is. It needs the 2 puzzles left.
    a = _ok(api.start_plan_task(t2, False))
    assert a["remaining"] == 2
    sid = a["session"]["session_id"]
    assert _solve_next(api, paths, sid)
    assert _solve_next(api, paths, sid)
    _ok(api.next_puzzle(sid))
    plan = _ok(api.get_current_plan())
    assert [t["id"] for t in _all_tasks(plan) if t["status"] == "done"] == [t2]
    assert plan["done"] == 1
    assert _log_done(api, _today_iso(api)) == 1
    prog = _ok(api.get_current_plan())
    assert prog["left"] == sum(1 for t in _all_tasks(prog) if t["status"] == "left")


@pytest.mark.xfail(
    strict=True, reason="QA v0.12-B32: a hand tick on the original leaves the copy open, so it counts twice"
)
def test_qa3_a_hand_tick_on_a_task_moved_to_the_next_day_settles_the_one_task(api: Api, clock: Any) -> None:
    plan, original, copy = _carried_pair(api, clock, _ref("a"))
    _ok(api.set_plan_task_tick(original, True))
    plan = _ok(api.get_current_plan())
    # The box is live on the row that says "Moved to the next day": however it's settled, this is one task.
    states = (_by_id(plan, original)["status"], _by_id(plan, copy)["status"])
    assert states.count("left") == 0 or plan["done"] == 0, states
    _ok(api.set_plan_task_tick(copy, True))
    plan = _ok(api.get_current_plan())
    assert plan["done"] == 1, [(t["title"], t["status"]) for t in _all_tasks(plan)]
    assert _log_done(api, _today_iso(api)) <= 1


def test_qa3_a_hand_tick_on_the_copy_leaves_the_original_moved(api: Api, clock: Any) -> None:
    plan, original, copy = _carried_pair(api, clock, _ref("a"))
    _ok(api.set_plan_task_tick(copy, True))
    plan = _ok(api.get_current_plan())
    assert _by_id(plan, original)["status"] == "carried"
    assert _by_id(plan, copy)["status"] == "done"
    assert plan["done"] == 1
    _ok(api.set_plan_task_tick(copy, False))
    plan = _ok(api.get_current_plan())
    assert _by_id(plan, copy)["status"] == "left" and plan["done"] == 0


@pytest.mark.parametrize("kind", ["puzzles", "review", "retry"])
@pytest.mark.xfail(strict=True, reason="QA v0.12-B33: a task you unticked comes back ticked as soon as it's copied")
def test_qa3_a_task_you_unticked_stays_unticked_when_it_carries(api: Api, paths: Any, clock: Any, kind: str) -> None:
    plant_managed_install(paths)
    gid = _games(_svc(api), 1)[0]
    first = {
        "puzzles": _puzzles_task(1, 10),
        "review": _review(gid),
        "retry": Task(RETRY, 10, "r", {"game_id": gid}),
    }[kind]
    plan = _plan_with(api, [[first], [_ref("b")]])
    tid = _task(plan)["id"]
    clock.advance(minutes=1)
    if kind == "puzzles":
        sid = _ok(api.start_plan_task(tid, False))["session"]["session_id"]
        assert _solve_next(api, paths, sid)
        _ok(api.next_puzzle(sid))
    elif kind == "review":
        _ok(api.start_plan_task(tid))
        _visit_all(api, gid)
    else:
        rev = _ok(api.get_review(gid))
        for ply in rev["retry_plies"]:
            move = rev["moves"][ply]
            _ok(api.retry_move(gid, ply, move["best_move"] or move["uci"]))
    assert _task(_ok(api.get_current_plan()))["status"] == "done"
    _ok(api.set_plan_task_tick(tid, False))  # I didn't really do it
    assert _task(_ok(api.get_current_plan()))["status"] == "left"
    clock.advance(days=1)
    plan = _ok(api.get_current_plan())
    copy = _carried(plan, 1)[0]
    assert copy["status"] == "left", "FR-10.64: a hand choice always wins"
    assert plan["done"] == 0


@pytest.mark.parametrize("kind", ["reflection", "lesson"])
@pytest.mark.xfail(
    strict=True, reason="QA v0.12-B34: what you finish from the original past midnight does not reach the copy"
)
def test_qa3_a_reflection_or_lesson_started_before_midnight_ticks_after_it(
    api: Api, paths: Any, clock: Any, kind: str
) -> None:
    """Same case as B26, for the two types that tick by task id, not by game or by inherited attempts."""
    _real_report(api, paths, 6)
    first = _ref("a") if kind == "reflection" else Task(LESSON, 10, "Lesson", {"topic": "theme:fork"})
    plan = _plan_with(api, [[first], [_ref("b")]])
    tid = _task(plan)["id"]
    _ok(api.start_plan_task(tid))
    clock.advance(days=1)
    plan = _ok(api.get_current_plan())  # the copy is made while the question is open, or the lesson card up
    copy = _carried(plan, 1)[0]["id"]
    if kind == "reflection":
        _ok(api.add_journal_entry({"text": "words", "plan_task_id": tid}))
    else:
        _ok(api.open_plan_lesson(tid, "curated:0"))
    plan = _ok(api.get_current_plan())
    # One task: it ends up done once, and nothing of it is still left to do.
    assert plan["done"] == 1, [(t["title"], t["status"]) for t in _all_tasks(plan)]
    assert _by_id(plan, copy)["status"] == "done"


def test_qa3_the_ai_part_and_the_screen_add_up_the_same_with_copies_and_swaps(api: Api, paths: Any, clock: Any) -> None:
    _real_report(api, paths, 6)
    plan = _plan_with(api, [[_puzzles_task(5, 10), _ref("a")], [_ref("b")], [_ref("c")]])
    pid = _task(plan)["id"]
    sid = _ok(api.start_plan_task(pid, False))["session"]["session_id"]
    assert _solve_next(api, paths, sid)
    _ok(api.next_puzzle(sid))
    with _svc(api).db.transaction() as conn:
        conn.execute("UPDATE attempts SET time_ms = 300000 WHERE session_id = ?", (sid,))
    clock.advance(days=1)
    plan = _ok(api.get_current_plan())
    copies = _carried(plan, 1)
    assert len(copies) == 2
    _ok(api.set_plan_task_tick(next(t["id"] for t in copies if t["type"] == "reflection"), True))
    _ok(api.swap_plan_task(next(t["id"] for t in copies if t["type"] == "puzzles")))
    plan = _ok(api.get_current_plan())
    prog = api._plan.progress()
    assert prog is not None
    assert prog["minutes_spent"] == plan["minutes_spent"] == 15  # 5 solving on the swapped task, 10 for the ticked one
    statuses: dict[str, int] = {}
    for s in prog["tasks_by_type"].values():
        for k, v in s.items():
            statuses[k] = statuses.get(k, 0) + v
    assert statuses.get("done", 0) == plan["done"]
    assert statuses.get("left", 0) == plan["left"]
    assert sum(statuses.values()) == len(_all_tasks(plan))


def test_qa3_swapping_a_copy_does_not_carry_the_original_again_on_later_days(api: Api, paths: Any, clock: Any) -> None:
    _real_report(api, paths, 6)
    plan = _plan_with(api, [[_ref("a")], [_ref("b")], [_ref("c")]])
    clock.advance(days=1)
    plan = _ok(api.get_current_plan())
    copy = _carried(plan, 1)[0]["id"]
    new = _ok(api.swap_plan_task(copy))
    for _ in range(2):
        plan = _ok(api.get_current_plan())
    titles = [t["title"] for t in _day(plan, 1)]
    assert titles.count("a") == 0, titles
    assert _task(plan)["status"] == "missed"  # with its copy swapped away, the original no longer says it moved
    clock.advance(days=1)
    plan = _ok(api.get_current_plan())
    assert [t["title"] for t in _carried(plan, 2)].count("a") == 0
    # What it was swapped for carries on as a normal unfinished task.
    assert _by_id(plan, new)["status"] == "carried"


# ---- swap_choices and _swap_in (QA v0.12-B22's fix) ----


def _weak_report(api: Api, paths: Any) -> dict[str, Any]:
    _real_report(api, paths, 6)
    return _ok(api.create_plan({"weeks": 1, "weekdays": EVERY_DAY, "minutes": 30}))


@pytest.mark.xfail(
    strict=True, reason="QA v0.12-B31: Swap compares titles only, so a new puzzle count is 'another' task"
)
def test_qa3_swap_is_not_fooled_by_a_new_puzzle_count_after_your_speed_changes(api: Api, paths: Any) -> None:
    _real_report(api, paths, 6)
    plan = _plan_with(api, [[general_task(Context(), 10), _ref("x")]])
    general, other = _task(plan, 0, 0), _task(plan, 0, 1)
    assert general["title"] == "6 puzzles: any theme"
    # You solve a puzzle at your own speed, as anyone does: the same task now has another count, so another title.
    sid = _ok(api.start_plan_task(general["id"], False))["session"]["session_id"]
    assert _solve_next(api, paths, sid)
    _ok(api.next_puzzle(sid))
    with _svc(api).db.transaction() as conn:
        conn.execute("UPDATE attempts SET time_ms = 20000")
        for _ in range(49):  # the average needs your last 50 attempts
            conn.execute(
                "INSERT INTO attempts (puzzle_source, puzzle_id, session_id, mode, started_at, finished_at, win, help_used,"
                " first_move_correct, line_correct, time_ms) SELECT puzzle_source, puzzle_id, NULL, mode, started_at,"
                " finished_at, win, help_used, first_move_correct, line_correct, time_ms FROM attempts LIMIT 1"
            )
    assert api._plan._puzzle_minutes() != 1.5
    tid = other["id"]
    for _ in range(12):
        tid = _ok(api.swap_plan_task(tid))
        titles = [t["title"] for t in _day(_ok(api.get_current_plan()), 0)]
        same = [x for x in titles if x.endswith("puzzles: any theme")]
        assert len(same) <= 1, titles  # FR-10.64 and swap_for: never one already on the day


@pytest.mark.xfail(strict=True, reason="QA v0.12-B35: Swap offers a game already used elsewhere in the plan")
def test_qa3_swap_does_not_offer_a_game_another_day_of_the_plan_already_has(api: Api, paths: Any) -> None:
    plan = _weak_report(api, paths)
    current = api._plan._plans.current()
    used = {(t.type, t.params.get("game_id")) for d in current.days for t in d.tasks if t.type in (REVIEW, RETRY)}
    assert used
    last = plan["days"][-1]["tasks"][0]["id"]
    first_seen: list[Any] = []
    tid = last
    for _ in range(25):
        tid = _ok(api.swap_plan_task(tid))
        place = api._plan._plans.place(tid)
        assert place is not None
        if place.task.type in (REVIEW, RETRY):
            first_seen.append((place.task.type, place.task.params["game_id"]))
    assert not set(first_seen) & used, (first_seen, used)


@pytest.mark.xfail(
    strict=True, reason="QA v0.12-B35: Swap offers a game you already reviewed, and it ticks itself at once"
)
def test_qa3_swap_never_gives_a_task_that_is_already_done(api: Api, paths: Any, clock: Any) -> None:
    plan = _weak_report(api, paths)
    current = api._plan._plans.current()
    games = [t.params["game_id"] for d in current.days for t in d.tasks if t.type == REVIEW]
    assert games
    clock.advance(minutes=1)
    for g in games:
        _visit_all(api, g)
    plan = _ok(api.get_current_plan())
    done = plan["done"]
    tid = next(t["id"] for t in _all_tasks(plan) if t["status"] == "left")
    for _ in range(25):
        tid = _ok(api.swap_plan_task(tid))
        plan = _ok(api.get_current_plan())
        assert _by_id(plan, tid)["status"] != "done", _by_id(plan, tid)["title"]
    assert plan["done"] == done


def test_qa3_every_pool_task_can_start_and_keeps_the_minutes_and_a_full_day(api: Api, paths: Any) -> None:
    plan = _weak_report(api, paths)
    today = _day(plan, 0)
    tid = today[0]["id"]
    minutes = today[0]["minutes"]
    others = [t["id"] for t in today[1:]]
    kinds: set[str] = set()
    modes: set[Any] = set()
    for _ in range(30):
        tid = _ok(api.swap_plan_task(tid))
        plan = _ok(api.get_current_plan())
        now = _day(plan, 0)
        assert sum(t["minutes"] for t in now) == 30 and len(now) == len(today)
        assert next(t for t in now if t["id"] == tid)["minutes"] == minutes
        assert [t["id"] for t in now if t["id"] != tid] == others
        titles = [t["title"] for t in now]
        assert len(titles) == len(set(titles)), titles
        got = _ok(api.start_plan_task(tid, False))
        kinds.add(got["kind"])
        modes.add(got.get("mode"))
    assert "reflection" in kinds and {"standard", "commit_line", "name_idea"} <= modes, (kinds, modes)


def test_qa3_a_pool_question_ticks_when_answered_and_the_tag_it_brings_is_accepted(api: Api, paths: Any) -> None:
    plan = _weak_report(api, paths)
    tid = _day(plan, 0)[0]["id"]
    for _ in range(30):
        tid = _ok(api.swap_plan_task(tid))
        t = _by_id(_ok(api.get_current_plan()), tid)
        if t["type"] == "reflection" and "one thing to remember" in t["title"]:
            break
    else:
        raise AssertionError("no pool question")
    a = _ok(api.start_plan_task(tid))
    _ok(api.add_journal_entry({"text": "w", "weakness_key": a["weakness_key"], "plan_day_id": a["plan_day_id"], "plan_task_id": tid}))  # fmt: skip
    assert _by_id(_ok(api.get_current_plan()), tid)["status"] == "done"


# ---- the unknown rate of a whole-game weakness that's gone (QA v0.12-B16's fix) ----


def _edit_report(api: Api, report_id: int, change: Any) -> None:
    with _svc(api).db.transaction() as conn:
        data = json.loads(
            conn.execute("SELECT report_json FROM coach_reports WHERE id = ?", (report_id,)).fetchone()[0]
        )
        change(data)
        conn.execute("UPDATE coach_reports SET report_json = ? WHERE id = ?", (json.dumps(data), report_id))
    api._coach._comparisons.clear()


def test_qa3_a_whole_game_weakness_gone_through_the_real_report_read_and_the_prompt(
    api: Api, paths: Any, clock: Any
) -> None:
    plant_managed_install(paths)
    svc = _svc(api)
    _games(svc, 6)
    first = _run(svc, {"source": "games", **ANY_GAME})
    clock.advance(days=4)
    _games(svc, 12)
    second = _run(svc, {"source": "games", **ANY_GAME})
    key = "time:low_clock"

    def add(data: dict[str, Any]) -> None:
        data["whole_game"] = [_weak(key, 6.0)]
        data.setdefault("measures", {}).setdefault("time", {})["games"] = 6

    def gone(data: dict[str, Any]) -> None:
        data["whole_game"] = []
        data.setdefault("measures", {}).setdefault("time", {})["games"] = 6

    _edit_report(api, first, add)
    _edit_report(api, second, gone)
    report = _ok(api.get_coach_report(second))
    row = next(w for w in report["comparison"]["weaknesses"] if w["key"] == key)
    assert row["now"] is None and row["delta"] is None and row["flag"] == "gone"
    assert row["verdict"] == "not_enough" and row["then"] == 6.0 and row["series"][-1] is None
    # Worst first, what's gone at the end: a None must sort without a crash.
    assert report["comparison"]["weaknesses"][-1]["flag"] == "gone"
    # It isn't in the report's own tables, so `_weakness_dto` can't show it as a change.
    assert all(w["key"] != key for w in report["whole_game"])
    # The prompt part the AI gets.
    c = api._coach.comparison(second)
    assert c is not None
    part = prompt_json(c, [4, 0])
    sent = next(w for w in part["weaknesses"] if w["key"] == key)
    assert sent["change"] == "not_enough" and sent["rates"]["this report"] is None
    json.dumps(part)
    for claim in ("improved", "worse", "same"):
        notes, dropped = validate_trend([{"key": key, "change": claim, "comment": "x"}], c)
        assert not notes and dropped == 1


def test_qa3_a_five_report_series_with_a_whole_game_weakness_coming_and_going() -> None:
    key = "opening:Sicilian"

    def side(i: int, in_list: bool, per10: float = 4.0) -> Side:
        data = {
            "source": "games", "games": 20, "whole_game": [_weak(key, per10)] if in_list else [], "weaknesses": [],
            "measures": {"openings": [{"family": "Sicilian", "games": 8, "score": 0.5}]},
        }  # fmt: skip
        return Side(i, f"2026-01-{i:02d}T10:00:00+00:00", data, frozenset(range(i * 100, i * 100 + 20)))

    chain = [side(1, True, 6.0), side(2, False), side(3, True, 5.0), side(4, False)]
    c = compare(side(5, True, 3.0), chain)
    assert c is not None
    row = next(w for w in c.weaknesses if w.key == key)
    # Back after a report out of the list: there's no last rate to compare, so no verdict, and the series shows the gaps.
    assert row.series == (6.0, None, 5.0, None, 3.0)
    assert row.flag == "new" and row.verdict == "not_enough" and row.then is None and row.now == 3.0
    part = prompt_json(c, [4, 3, 2, 1, 0])
    assert len(part["reports"]) == 5
    c2 = compare(side(5, False), [*chain[:-1], side(4, True, 2.0)])
    assert c2 is not None
    gone = next(w for w in c2.weaknesses if w.key == key)
    assert gone.now is None and gone.series[-1] is None and gone.verdict == "not_enough"
    assert validate_trend([{"key": key, "change": "improved", "comment": "x"}], c2)[0] == []


def test_qa3_a_tactical_weakness_gone_is_still_better_and_the_ai_sees_one_number() -> None:
    """The rule for a whole-game weakness must not have touched a tactical one: every one found is stored."""

    def side(i: int, rows: list[dict[str, Any]]) -> Side:
        data = {"source": "games", "games": 20, "missed": rows, "weaknesses": rows, "whole_game": []}
        return Side(i, f"2026-01-{i:02d}T10:00:00+00:00", data, frozenset(range(i * 100, i * 100 + 20)))

    old = side(1, [_weak("missed:fork", 4.0)])
    c = compare(side(2, []), [old])
    assert c is not None
    row = c.weaknesses[0]
    assert row.now == 0.0 and row.flag == "gone" and row.verdict == "better"


@pytest.mark.xfail(
    strict=True, reason="QA v0.12-B36: a tactical weakness gone says Now 0 but its series and prompt say no rate"
)
def test_qa3_a_tactical_weakness_gone_has_the_same_number_in_its_series_and_the_prompt() -> None:
    def side(i: int, rows: list[dict[str, Any]]) -> Side:
        data = {"source": "games", "games": 20, "missed": rows, "weaknesses": rows, "whole_game": []}
        return Side(i, f"2026-01-{i:02d}T10:00:00+00:00", data, frozenset(range(i * 100, i * 100 + 20)))

    c = compare(side(3, []), [side(1, [_weak("missed:fork", 4.0)]), side(2, [_weak("missed:fork", 3.0)])])
    assert c is not None
    row = c.weaknesses[0]
    assert row.now == 0.0 and row.series[-1] == row.now, row.series
    assert prompt_json(c, [2, 1, 0])["weaknesses"][0]["rates"]["this report"] == 0.0


# ---- uncapped search, the plan-day badge, the timeline's edges ----


def test_qa3_search_with_thousands_of_entries_finds_all_and_stays_quick(api: Api) -> None:
    today = _today_iso(api)
    with _svc(api).db.transaction() as conn:
        conn.executemany(
            "INSERT INTO journal_entries (created_at, updated_at, entry_date, kind, text) VALUES (?,?,?,?,?)",
            [(f"{today}T10:00:00+00:00", f"{today}T10:00:00+00:00", today, "note", f"needle {i} " + "x" * 200) for i in range(5000)],
        )  # fmt: skip
    start = time.perf_counter()
    got = _ok(api.get_journal({"query": "needle"}))
    took = time.perf_counter() - start
    assert len(got["items"]) == 5000
    assert got["older"] is False
    assert took < 3.0, took


def test_qa3_the_day_badge_stays_right_after_the_plan_is_replaced_and_an_edit(api: Api, clock: Any) -> None:
    plan = _plan_with(api, [[_ref("a")], [_ref("b")]])
    day = plan["days"][1]
    entry = _ok(api.add_journal_entry({"text": "note", "plan_day_id": day["id"]}))
    assert entry["plan_day_date"] == day["date"]
    clock.advance(days=3)
    _plan_with(api, [[_ref("c")], [_ref("d")]])
    got = _ok(api.get_journal({"query": "note"}))["items"][0]["entry"]
    assert got["plan_day_date"] == day["date"] and got["plan_day_id"] == day["id"]
    edited = _ok(api.edit_journal_entry(entry["id"], "note again"))
    assert edited["plan_day_date"] == day["date"]


def test_qa3_the_timeline_with_a_window_wholly_ahead_or_back_to_front(api: Api, clock: Any) -> None:
    today = _today_iso(api)
    _ok(api.add_journal_entry({"text": "today"}))
    far = "2099-01-01"
    got = _ok(api.get_journal({"date_from": far, "date_to": far}))
    assert got["items"] == [] and got["older"] is False
    got = _ok(api.get_journal({"date_from": far}))
    assert got["items"] == [] and got["older"] is False
    got = _ok(api.get_journal({"date_from": today, "date_to": "2000-01-01"}))
    assert got["items"] == []
    got = _ok(api.get_journal({"date_to": far, "query": "today"}))
    assert [i["entry"]["text"] for i in got["items"]] == ["today"]


# ---- round 2's list again, by what the requirement says ----


def test_qa3_b21_a_hand_tick_then_the_app_then_an_untick_and_a_retick(api: Api, clock: Any) -> None:
    plan = _plan_with(api, [[_ref("a"), _ref("b")], [_ref("c")], [_ref("d")]])
    tid = _task(plan)["id"]
    day1 = _today_iso(api)
    _ok(api.set_plan_task_tick(tid, True))
    assert _log_done(api, day1) == 1
    clock.advance(days=1)
    day2 = _today_iso(api)
    _ok(api.add_journal_entry({"text": "w", "plan_task_id": tid}))
    _ok(api.get_current_plan())
    assert (_log_done(api, day1), _log_done(api, day2)) == (1, 0)
    _ok(api.set_plan_task_tick(tid, False))
    assert (_log_done(api, day1), _log_done(api, day2)) == (0, 0)
    _ok(api.set_plan_task_tick(tid, True))
    assert (_log_done(api, day1), _log_done(api, day2)) == (0, 1) or (_log_done(api, day1), _log_done(api, day2)) == (
        1,
        0,
    )


def test_qa3_b23_minutes_stay_over_a_chain_of_swaps_with_time_on_each(api: Api, paths: Any) -> None:
    _real_report(api, paths, 6)
    plan = _plan_with(api, [[_puzzles_task(5, 10), _ref("x")]])
    tid = _task(plan)["id"]
    total = 0
    for _ in range(4):
        task = _by_id(_ok(api.get_current_plan()), tid)
        if task["type"] in ("puzzles", "game_puzzles"):
            sid = _ok(api.start_plan_task(tid, False))["session"]["session_id"]
            assert _solve_next(api, paths, sid)
            _ok(api.next_puzzle(sid))
            with _svc(api).db.transaction() as conn:
                conn.execute("UPDATE attempts SET time_ms = 120000 WHERE session_id = ?", (sid,))
            total += 2
        tid = _ok(api.swap_plan_task(tid))
    assert total >= 2
    assert _ok(api.get_current_plan())["minutes_spent"] == total


def test_qa3_b26_nothing_doubles_for_a_retry_or_a_review_over_midnight(api: Api, paths: Any, clock: Any) -> None:
    plant_managed_install(paths)
    a, b = _games(_svc(api), 2)
    plan = _plan_with(api, [[_review(a), Task(RETRY, 10, "r", {"game_id": b})], [_ref("c")], [_ref("d")]])
    _ok(api.start_plan_task(_task(plan, 0, 0)["id"]))
    clock.advance(days=1)
    plan = _ok(api.get_current_plan())
    assert len(_carried(plan, 1)) == 2
    clock.advance(minutes=1)
    _visit_all(api, a)
    rev = _ok(api.get_review(b))
    for ply in rev["retry_plies"]:
        move = rev["moves"][ply]
        _ok(api.retry_move(b, ply, move["best_move"] or move["uci"]))
    plan = _ok(api.get_current_plan())
    assert plan["done"] == 2, [(t["title"], t["status"]) for t in _all_tasks(plan)]
    assert [t["status"] for t in _day(plan, 0)] == ["carried", "carried"]
    assert _log_done(api, _today_iso(api)) == 2


def test_qa3_b28_two_games_on_one_day_against_one_opponent_still_differ(api: Api) -> None:
    g1, g2 = _secret_game(api, 0), _secret_game(api, 1)
    with _svc(api).db.transaction() as conn:
        same = conn.execute("SELECT white, black, played_at FROM games WHERE id = ?", (g1,)).fetchone()
        conn.execute("UPDATE games SET white = ?, black = ?, played_at = ? WHERE id = ?", (*same, g2))
    _ok(api.add_journal_entry({"text": "one", "game_id": g1}))
    _ok(api.add_journal_entry({"text": "two", "game_id": g2}))
    labels = [g["label"] for g in _ok(api.get_journal({}))["games"]]
    assert len(labels) == 2 and len(set(labels)) == 2, labels
