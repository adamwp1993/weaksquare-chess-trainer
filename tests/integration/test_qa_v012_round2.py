"""QA v0.12 round 2: what the round 1 fixes newly touch, through the real bridge, from real events. A test exposing an
open bug is marked xfail with its ID."""

from __future__ import annotations

import itertools
import json
import shutil
import sqlite3
from dataclasses import asdict, replace
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from tests.fakes.engine import FakeEngine, plant_managed_install
from tests.helpers import FakeDesktop, build_api
from tests.integration.test_coach_run import ANY_GAME, _my_games, _run
from tests.integration.test_game_explain import configure, fake
from tests.integration.test_qa_v011_coach import _games
from tests.integration.test_qa_v012_journal_ai import _journal_lines, _secret_game, _wait, _with
from tests.integration.test_qa_v012_plan import (
    EVERY_DAY,
    _api,
    _ok,
    _plan_with,
    _puzzles_task,
    _real_report,
    _svc,
    _task,
)
from tests.unit.test_game_measures import _clock, dg, games
from tests.unit.test_game_measures import m as moment
from weaksquare.adapters.db.migrate import migrate
from weaksquare.bridge.api import Api
from weaksquare.config import MIGRATIONS_DIR
from weaksquare.core.clock import FixedClock
from weaksquare.core.game_measures import build_measures, game_weaknesses
from weaksquare.core.plan import GAME_PUZZLES, REFLECTION, REVIEW, Task
from weaksquare.core.report_compare import Side, compare, validate_trend


@pytest.fixture(autouse=True)
def _reset() -> None:
    FakeEngine.instances.clear()


@pytest.fixture
def desktop() -> FakeDesktop:
    return FakeDesktop()


@pytest.fixture
def api(paths: Any, clock: Any, desktop: FakeDesktop, fixture_puzzles_db: Any) -> Api:
    return _api(paths, clock, desktop, fixture_puzzles_db)


def _ref(name: str, minutes: int = 10) -> Task:
    return Task(REFLECTION, minutes, name, {"prompt": name})


def _day(plan: dict[str, Any], i: int) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = plan["days"][i]["tasks"]
    return tasks


def _carried(plan: dict[str, Any], i: int) -> list[dict[str, Any]]:
    return [t for t in _day(plan, i) if t["carried"]]


def _today_iso(api: Api) -> str:
    return api._plan._today().isoformat()


def _log_done(api: Api, day: str) -> int:
    got = _ok(api.get_journal({"date_from": day, "date_to": day, "kinds": ["log"]}))
    logs = [i["log"] for i in got["items"] if i["log"]]
    return int(logs[0]["plan_tasks_done"]) if logs else 0


# ---- FR-10.64: the carry-over limit, several missed days in a row ----


def test_qa2_the_limit_holds_every_day_of_a_run_of_missed_days(api: Api, clock: Any) -> None:
    days = [[_ref(f"d{d}-{i}") for i in range(3)] for d in range(5)]
    _plan_with(api, days)
    for d in range(1, 5):
        clock.advance(days=1)
        for _ in range(3):
            plan = _ok(api.get_current_plan())
            _ok(api.get_today_plan())
        assert sum(t["minutes"] for t in _carried(plan, d)) <= 20, (d, [t["title"] for t in _day(plan, d)])
        assert len(_day(plan, d)) == 5
    # Nothing piles up behind, and each thing left is counted once.
    assert plan["left"] == 5


def test_qa2_a_carried_task_can_be_carried_again(api: Api, clock: Any) -> None:
    _plan_with(api, [[_ref("a")], [_ref("b")], [_ref("c")]])
    clock.advance(days=1)
    _ok(api.get_current_plan())
    clock.advance(days=1)
    plan = _ok(api.get_current_plan())
    assert sorted(t["title"] for t in _carried(plan, 2)) == ["a", "b"]
    assert plan["left"] == 3


@pytest.mark.parametrize("how", ["tick", "skip"])
def test_qa2_a_carried_task_done_or_skipped_still_uses_up_the_limit(api: Api, clock: Any, how: str) -> None:
    plan = _plan_with(api, [[_ref(f"a{i}") for i in range(3)], [_ref("b")]])
    clock.advance(days=1)
    plan = _ok(api.get_current_plan())
    first = _carried(plan, 1)[0]
    if how == "tick":
        _ok(api.set_plan_task_tick(first["id"], True))
    else:
        _ok(api.skip_plan_task(first["id"]))
    for _ in range(3):
        plan = _ok(api.get_current_plan())
    assert sum(t["minutes"] for t in _carried(plan, 1)) == 20
    assert [t["title"] for t in _carried(plan, 1)] == ["a0", "a1"]


def test_qa2_done_or_skipped_carried_tasks_do_not_carry_again(api: Api, clock: Any) -> None:
    _plan_with(api, [[_ref("a"), _ref("b")], [_ref("c")], [_ref("d")]])
    clock.advance(days=1)
    plan = _ok(api.get_current_plan())
    a, b = _carried(plan, 1)
    _ok(api.set_plan_task_tick(a["id"], True))
    _ok(api.skip_plan_task(b["id"]))
    clock.advance(days=1)
    plan = _ok(api.get_current_plan())
    assert [t["title"] for t in _carried(plan, 2)] == ["c"]


def test_qa2_swapping_a_carried_task_never_lets_more_in_past_the_limit(api: Api, paths: Any, clock: Any) -> None:
    _real_report(api, paths, 6)
    _plan_with(api, [[_ref(f"a{i}") for i in range(3)], [_ref("b")]])
    clock.advance(days=1)
    plan = _ok(api.get_current_plan())
    first = _carried(plan, 1)[0]
    _ok(api.swap_plan_task(first["id"]))
    for _ in range(3):
        plan = _ok(api.get_current_plan())
    titles = [t["title"] for t in _day(plan, 1)]
    assert "a2" not in titles, titles
    assert "a0" not in titles, titles  # the copy you swapped away stays gone
    assert sum(t["minutes"] for t in _day(plan, 1)) == 30, titles


def test_qa2_carry_off_then_on_keeps_the_limit(api: Api, clock: Any) -> None:
    _plan_with(api, [[_ref(f"a{i}") for i in range(3)], [_ref("b")]])
    settings = _ok(api.get_plan_settings())
    assert settings["carry_over"] is True
    clock.advance(days=1)
    plan = _ok(api.get_current_plan())
    assert sum(t["minutes"] for t in _carried(plan, 1)) == 20


def test_qa2_a_session_running_past_midnight_does_not_finish_a_task_twice(api: Api, paths: Any, clock: Any) -> None:
    plan = _plan_with(api, [[_puzzles_task(2, 10), _ref("x")], [_ref("b")]])
    tid = _task(plan)["id"]
    a = _ok(api.start_plan_task(tid, False))
    sid = a["session"]["session_id"]
    _ok(api.next_puzzle(sid))
    clock.advance(days=1)
    plan = _ok(api.get_current_plan())  # the copy is made while the session runs
    assert len(_carried(plan, 1)) == 2
    for _ in range(3):
        _ok(api.next_puzzle(sid))
    plan = _ok(api.get_current_plan())
    done = [t for d in plan["days"] for t in d["tasks"] if t["status"] == "done"]
    assert len(done) <= 1, [(t["title"], t["carried"]) for t in done]
    assert plan["done"] <= 1


# ---- FR-10.65: minutes spent ----


def test_qa2_minutes_spent_stay_after_a_swap(api: Api, paths: Any, clock: Any) -> None:
    _real_report(api, paths, 6)
    plan = _plan_with(api, [[_puzzles_task(5, 10), _ref("x")]])
    tid = _task(plan)["id"]
    sid = _ok(api.start_plan_task(tid, False))["session"]["session_id"]
    _ok(api.next_puzzle(sid))
    clock.advance(minutes=10)
    _ok(api.next_puzzle(sid))
    with _svc(api).db.transaction() as conn:
        conn.execute("UPDATE attempts SET time_ms = 600000 WHERE session_id = ?", (sid,))
    assert _ok(api.get_current_plan())["minutes_spent"] == 10
    _ok(api.swap_plan_task(tid))
    assert _ok(api.get_current_plan())["minutes_spent"] == 10


# ---- FR-10.64: Swap, again and again ----


def test_qa2_a_long_swap_chain_moves_on_and_never_doubles_a_task_on_the_day(api: Api, paths: Any) -> None:
    plant_managed_install(paths)
    _my_games(_svc(api), 1)
    _run(_svc(api), {"source": "games", **ANY_GAME})
    _ok(api.create_plan({"weeks": 1, "weekdays": EVERY_DAY, "minutes": 40}))
    plan = _ok(api.get_current_plan())
    tid = _task(plan)["id"]
    seen = [_task(plan)["title"]]
    for _ in range(12):
        tid = _ok(api.swap_plan_task(tid))
        plan = _ok(api.get_current_plan())
        titles = [t["title"] for t in _day(plan, 0)]
        assert len(titles) == len(set(titles)), titles
        assert sum(t["minutes"] for t in _day(plan, 0)) == 40
        now = next(t for t in _day(plan, 0) if t["id"] == tid)
        seen.append(now["title"])
    # It must reach several tasks first, and each Swap must give you another task.
    assert len(set(seen[:4])) == 4, seen
    assert all(a != b for a, b in itertools.pairwise(seen)), seen


def test_qa2_a_swapped_task_can_start_and_the_new_task_ticks(api: Api, paths: Any) -> None:
    _real_report(api, paths, 6)
    _ok(api.create_plan({"weeks": 1, "weekdays": EVERY_DAY, "minutes": 30}))
    plan = _ok(api.get_current_plan())
    tid = _task(plan)["id"]
    for _ in range(4):
        tid = _ok(api.swap_plan_task(tid))
        assert api.start_plan_task(tid, False)["ok"]


def test_qa2_a_swap_keeps_ticks_of_the_others_and_is_refused_on_an_ended_plan(api: Api, paths: Any, clock: Any) -> None:
    _real_report(api, paths, 6)
    old = _ok(api.create_plan({"weeks": 1, "weekdays": EVERY_DAY, "minutes": 30}))
    a, b = _task(old, 0, 0), _task(old, 0, 1)
    _ok(api.set_plan_task_tick(b["id"], True))
    _ok(api.swap_plan_task(a["id"]))
    assert next(t for t in _day(_ok(api.get_current_plan()), 0) if t["id"] == b["id"])["status"] == "done"
    clock.advance(hours=1)
    _ok(api.create_plan({"weeks": 1, "weekdays": EVERY_DAY, "minutes": 30}, True))
    assert api.swap_plan_task(b["id"])["ok"] is False


# ---- FR-10.64, 10.68: hand ticks and unticks in the daily log ----


def test_qa2_ticks_and_unticks_by_hand_day_by_day(api: Api, clock: Any) -> None:
    plan = _plan_with(api, [[_ref("a"), _ref("b")], [_ref("c")]])
    a, b = _day(plan, 0)
    day1 = _today_iso(api)
    _ok(api.set_plan_task_tick(a["id"], True))
    assert _log_done(api, day1) == 1
    _ok(api.set_plan_task_tick(b["id"], True))
    assert _log_done(api, day1) == 2
    _ok(api.set_plan_task_tick(a["id"], False))
    assert _log_done(api, day1) == 1
    clock.advance(days=1)
    day2 = _today_iso(api)
    _ok(api.set_plan_task_tick(a["id"], True))  # a day late, on yesterday's task
    assert _log_done(api, day1) == 1
    assert _log_done(api, day2) == 1


def test_qa2_an_app_seen_task_unticked_and_ticked_again_counts_once(api: Api) -> None:
    plan = _plan_with(api, [[_ref("a"), _ref("b")]])
    a = _day(plan, 0)[0]
    day = _today_iso(api)
    _ok(api.add_journal_entry({"text": "done from the task", "plan_task_id": a["id"]}))
    _ok(api.get_current_plan())
    assert _log_done(api, day) == 1
    _ok(api.set_plan_task_tick(a["id"], False))
    _ok(api.get_current_plan())
    assert _log_done(api, day) == 0
    _ok(api.set_plan_task_tick(a["id"], True))
    _ok(api.get_current_plan())
    assert _log_done(api, day) == 1


def test_qa2_a_hand_tick_stays_on_its_day_when_the_app_sees_it_done_later(api: Api, clock: Any) -> None:
    plan = _plan_with(api, [[_ref("a"), _ref("b")], [_ref("c")]])
    a = _day(plan, 0)[0]
    day1 = _today_iso(api)
    _ok(api.set_plan_task_tick(a["id"], True))
    assert _log_done(api, day1) == 1
    clock.advance(days=1)
    day2 = _today_iso(api)
    _ok(api.add_journal_entry({"text": "written the day after", "plan_task_id": a["id"]}))
    _ok(api.get_current_plan())
    assert (_log_done(api, day1), _log_done(api, day2)) == (1, 0)


def test_qa2_a_hand_tick_on_a_carried_copy_counts_once(api: Api, clock: Any) -> None:
    _plan_with(api, [[_ref("a")], [_ref("b")]])
    clock.advance(days=1)
    plan = _ok(api.get_current_plan())
    _ok(api.set_plan_task_tick(_carried(plan, 1)[0]["id"], True))
    assert _log_done(api, _today_iso(api)) == 1
    plan = _ok(api.get_current_plan())
    assert plan["done"] == 1


def test_qa2_ticking_a_skipped_task_counts_and_a_swapped_away_tick_does_not(api: Api, paths: Any) -> None:
    _real_report(api, paths, 6)
    plan = _plan_with(api, [[_ref("a"), _ref("b")]])
    a, b = _day(plan, 0)
    day = _today_iso(api)
    _ok(api.skip_plan_task(a["id"]))
    _ok(api.set_plan_task_tick(a["id"], True))
    assert _log_done(api, day) == 1
    _ok(api.set_plan_task_tick(b["id"], True))
    _ok(api.swap_plan_task(b["id"]))
    assert _log_done(api, day) == 1


# ---- FR-10.64: a review task and your passes ----


def _visit_all(api: Api, gid: int) -> None:
    rev = _ok(api.get_review(gid))
    for m in [*rev["key_moments"], len(rev["moves"]) - 1]:
        _ok(api.mark_review_ply(gid, m))


def _review_plan(api: Api, gid: int) -> dict[str, Any]:
    return _plan_with(api, [[Task(REVIEW, 10, "v", {"game_id": gid}), _ref("x")], [_ref("y")]])


def test_qa2_a_whole_review_since_the_plan_began_ticks_with_an_old_pass_left_open(
    api: Api, paths: Any, clock: Any
) -> None:
    plant_managed_install(paths)
    gid = _games(_svc(api), 1)[0]
    rev = _ok(api.get_review(gid))
    _ok(api.mark_review_ply(gid, rev["key_moments"][0]))  # a look at the game last week
    clock.advance(days=7)
    _review_plan(api, gid)
    clock.advance(hours=1)
    _visit_all(api, gid)  # from My games, not Start: FR-10.64 only says you visited them
    assert _task(_ok(api.get_current_plan()))["status"] == "done"


def test_qa2_a_review_task_ticks_without_start_when_no_pass_is_open(api: Api, paths: Any, clock: Any) -> None:
    plant_managed_install(paths)
    gid = _games(_svc(api), 1)[0]
    _review_plan(api, gid)
    clock.advance(hours=1)
    _visit_all(api, gid)
    assert _task(_ok(api.get_current_plan()))["status"] == "done"


def test_qa2_a_carried_review_task_keeps_the_moves_you_already_visited(api: Api, paths: Any, clock: Any) -> None:
    plant_managed_install(paths)
    gid = _games(_svc(api), 1)[0]
    rev = _ok(api.get_review(gid))
    plan = _review_plan(api, gid)
    _ok(api.start_plan_task(_task(plan)["id"]))
    for m in rev["key_moments"]:
        _ok(api.mark_review_ply(gid, m))
    clock.advance(days=1)
    plan = _ok(api.get_current_plan())
    copy = next(t for t in _carried(plan, 1) if t["type"] == "review")
    _ok(api.start_plan_task(copy["id"]))
    _ok(api.mark_review_ply(gid, len(rev["moves"]) - 1))  # only the final move was left
    plan = _ok(api.get_current_plan())
    assert next(t for t in _day(plan, 1) if t["id"] == copy["id"])["status"] == "done"


def test_qa2_resuming_a_review_task_keeps_its_own_visits(api: Api, paths: Any, clock: Any) -> None:
    plant_managed_install(paths)
    gid = _games(_svc(api), 1)[0]
    rev = _ok(api.get_review(gid))
    plan = _review_plan(api, gid)
    tid = _task(plan)["id"]
    _ok(api.start_plan_task(tid))
    for m in rev["key_moments"]:
        _ok(api.mark_review_ply(gid, m))
    clock.advance(hours=1)
    _ok(api.start_plan_task(tid))
    _ok(api.mark_review_ply(gid, len(rev["moves"]) - 1))
    assert _task(_ok(api.get_current_plan()))["status"] == "done"


# ---- FR-10.65: an ended plan, with a session still running ----


def test_qa2_a_session_still_running_when_the_plan_ends(api: Api, paths: Any, clock: Any) -> None:
    _real_report(api, paths, 6)
    old = _plan_with(api, [[_puzzles_task(3, 10), _ref("x")]])
    tid = _task(old)["id"]
    sid = _ok(api.start_plan_task(tid, False))["session"]["session_id"]
    _ok(api.next_puzzle(sid))
    clock.advance(minutes=5)
    _ok(api.next_puzzle(sid))  # one decided before the plan ends
    with _svc(api).db.session() as conn:
        before = conn.execute("SELECT COUNT(*) FROM attempts WHERE session_id = ?", (sid,)).fetchone()[0]
    clock.advance(hours=1)
    new = _ok(api.create_plan({"weeks": 1, "weekdays": EVERY_DAY, "minutes": 30}, True))
    clock.advance(minutes=5)
    for _ in range(5):
        got = api.next_puzzle(sid)  # the session carries on, whatever the plan did
        assert got["ok"], got
        clock.advance(minutes=1)
    ended = next(p for p in _ok(api.list_plans()) if p["id"] == old["id"])
    t = ended["days"][0]["tasks"][0]
    assert ended["status"] == "replaced"
    assert t["status"] != "done" and t["progress"] == before, t
    assert _ok(api.get_current_plan())["id"] == new["id"]
    assert _ok(api.get_current_plan())["done"] == 0


def test_qa2_what_happened_before_the_end_still_counts_after_it(api: Api, paths: Any, clock: Any) -> None:
    plant_managed_install(paths)
    gid = _games(_svc(api), 1)[0]
    _run(_svc(api), {"source": "games", **ANY_GAME})
    old = _plan_with(api, [[_puzzles_task(1, 10), Task(REVIEW, 10, "v", {"game_id": gid}), _ref("x")]])
    p, r, x = _day(old, 0)
    sid = _ok(api.start_plan_task(p["id"], False))["session"]["session_id"]
    _ok(api.next_puzzle(sid))
    clock.advance(minutes=1)
    _ok(api.next_puzzle(sid))
    _ok(api.start_plan_task(r["id"]))
    _visit_all(api, gid)
    _ok(api.add_journal_entry({"text": "from the task", "plan_task_id": x["id"]}))
    clock.advance(minutes=1)
    _ok(api.create_plan({"weeks": 1, "weekdays": EVERY_DAY, "minutes": 30}, True))
    clock.advance(days=2)
    ended = next(q for q in _ok(api.list_plans()) if q["id"] == old["id"])
    assert ended["done"] == 3, ended["days"][0]["tasks"]


def test_qa2_an_ended_plan_refuses_hand_changes_and_a_note_saved_later_does_not_tick_it(
    api: Api, paths: Any, clock: Any
) -> None:
    _real_report(api, paths, 6)
    old = _plan_with(api, [[_ref("a"), _ref("b")]])
    a = _day(old, 0)[0]
    clock.advance(minutes=1)
    _ok(api.create_plan({"weeks": 1, "weekdays": EVERY_DAY, "minutes": 30}, True))
    clock.advance(minutes=1)
    assert api.set_plan_task_tick(a["id"], True)["ok"] is False
    assert api.skip_plan_task(a["id"])["ok"] is False
    assert api.start_plan_task(a["id"])["ok"] is False
    _ok(api.add_journal_entry({"text": "late", "plan_task_id": a["id"]}))  # a Journal tab left open from the task
    ended = next(q for q in _ok(api.list_plans()) if q["id"] == old["id"])
    assert ended["done"] == 0


# ---- FR-10.70: timeline paging, older, mixed filters ----


def _texts(t: dict[str, Any]) -> list[str]:
    return [i["entry"]["text"] for i in t["items"] if i["entry"]]


def _logs(t: dict[str, Any]) -> int:
    return sum(1 for i in t["items"] if i["log"])


def test_qa2_an_empty_journal_has_no_older_page(api: Api) -> None:
    t = _ok(api.get_journal({}))
    assert t["items"] == [] and t["older"] is False and t["games"] == []


def test_qa2_paging_back_reaches_an_old_note_and_stops(api: Api, clock: Any) -> None:
    _ok(api.add_journal_entry({"text": "old"}))
    clock.advance(days=100)
    _ok(api.add_journal_entry({"text": "new"}))
    t = _ok(api.get_journal({}))
    assert _texts(t) == ["new"] and t["older"] is True
    seen = list(_texts(t))
    pages = 0
    while t["older"]:
        t = _ok(api.get_journal({"before": t["window_start"]}))
        seen += _texts(t)
        pages += 1
        assert pages < 10
    assert seen == ["new", "old"]


def test_qa2_older_stops_at_from_and_to_moves_the_window(api: Api, clock: Any) -> None:
    _ok(api.add_journal_entry({"text": "first"}))
    start = _today_iso(api)
    clock.advance(days=100)
    today = _today_iso(api)
    _ok(api.add_journal_entry({"text": "last"}))
    t = _ok(api.get_journal({"date_from": (clock.now() - timedelta(days=10)).date().isoformat()}))
    assert _texts(t) == ["last"] and t["older"] is False
    t = _ok(api.get_journal({"date_to": start}))
    assert _texts(t) == ["first"] and t["older"] is False
    t = _ok(api.get_journal({"date_from": today, "date_to": start}))  # From after To
    assert t["items"] == [] and t["older"] is False


def test_qa2_a_to_date_after_today_still_shows_today(api: Api, clock: Any) -> None:
    _ok(api.add_journal_entry({"text": "today's"}))
    later = (clock.now() + timedelta(days=200)).date().isoformat()
    assert _texts(_ok(api.get_journal({"date_to": later}))) == ["today's"]


@pytest.mark.parametrize("field", ["query", "weakness_key", "game_id"])
def test_qa2_show_daily_log_with_a_search_or_filter_lists_no_entries(api: Api, field: str) -> None:
    gid = _secret_game(api, 0)
    _ok(api.add_journal_entry({"text": "pins", "game_id": gid, "weakness_key": "missed:pin"}))
    value = {"query": "pins", "weakness_key": "missed:pin", "game_id": gid}[field]
    t = _ok(api.get_journal({"kinds": ["log"], field: value}))
    assert _texts(t) == []


def test_qa2_filters_combine(api: Api, clock: Any) -> None:
    g1, g2 = _secret_game(api, 0), _secret_game(api, 1)
    _ok(api.add_journal_entry({"text": "pins one", "game_id": g1, "weakness_key": "missed:pin"}))
    _ok(api.add_journal_entry({"text": "pins two", "game_id": g2, "weakness_key": "missed:pin"}))
    _ok(api.add_journal_entry({"text": "forks one", "game_id": g1, "weakness_key": "missed:fork"}))
    _ok(api.add_journal_entry({"text": "pins note", "weakness_key": "missed:pin"}))
    start = _today_iso(api)
    clock.advance(days=60)
    _ok(api.add_journal_entry({"text": "pins late", "game_id": g1, "weakness_key": "missed:pin"}))
    q = {"game_id": g1, "query": "pins"}
    assert _texts(_ok(api.get_journal(q))) == ["pins late", "pins one"]
    assert _texts(_ok(api.get_journal({**q, "date_to": start}))) == ["pins one"]
    assert _texts(_ok(api.get_journal({**q, "date_from": _today_iso(api)}))) == ["pins late"]
    assert _texts(_ok(api.get_journal({"weakness_key": "missed:fork", "game_id": g1}))) == ["forks one"]
    assert _texts(_ok(api.get_journal({"weakness_key": "missed:pin", "kinds": ["note"]}))) == ["pins note"]
    assert _texts(_ok(api.get_journal({"game_id": g2, "query": "forks"}))) == []
    t = _ok(api.get_journal({"kinds": ["reflection"]}))
    assert _texts(t) == ["pins late", "forks one", "pins two", "pins one"]
    assert t["older"] is False and _logs(t) == 0
    assert {g["id"] for g in t["games"]} == {g1, g2}  # the Game filter's choices don't narrow with the filter


def test_qa2_search_reaches_every_entry_past_500(api: Api) -> None:
    with _svc(api).db.transaction() as conn:
        conn.executemany(
            "INSERT INTO journal_entries (created_at, updated_at, entry_date, kind, text) VALUES (?,?,?,?,?)",
            [("2020-01-01T10:00:00+00:00", "2020-01-01T10:00:00+00:00", "2020-01-01", "note", "pins again")] * 501,
        )
    t = _ok(api.get_journal({"query": "pins"}))
    shown = len(_texts(t))
    assert shown == 501 or t["older"] is True, shown


def test_qa2_older_is_true_for_a_local_day_the_utc_date_hides(
    paths: Any, desktop: FakeDesktop, fixture_puzzles_db: Any
) -> None:
    west = timezone(timedelta(hours=-5))
    clock = FixedClock(datetime(2026, 3, 1, 23, 0, tzinfo=UTC), west)
    api = _api(paths, clock, desktop, fixture_puzzles_db)
    sid = _ok(api.start_session({"queue_size": 5}, False, "standard", False))["session_id"]
    _ok(api.next_puzzle(sid))
    clock.advance(hours=2)  # 02 Mar 01:00 UTC, still 1 Mar, 20:00 at home
    _ok(api.next_puzzle(sid))
    # Page back so that the window starts exactly on 2 Mar: the attempt's local day is 1 Mar.
    clock.advance(days=30)
    today = api._plan._today().isoformat()
    t = _ok(api.get_journal({}))
    assert t["window_start"] == (date.fromisoformat(today) - timedelta(days=29)).isoformat()
    assert _logs(t) == 0
    assert t["older"] is True


def test_qa2_the_game_filter_tells_apart_two_games_against_one_opponent(api: Api) -> None:
    g1, g2 = _secret_game(api, 0), _secret_game(api, 1)
    _ok(api.add_journal_entry({"text": "one", "game_id": g1}))
    _ok(api.add_journal_entry({"text": "two", "game_id": g2}))
    labels = [g["label"] for g in _ok(api.get_journal({}))["games"]]
    assert len(labels) == 2 and len(set(labels)) == 2, labels


# ---- FR-10.67, FR-8.16: the composer's tags and what they send ----


def test_qa2_a_game_and_a_day_tag_are_stored_and_send_no_id_url_or_day(api: Api, paths: Any, clock: Any) -> None:
    plant_managed_install(paths)
    svc = _svc(api)
    ids = [_secret_game(api, k) for k in range(6)]
    rid = _run(svc, {"source": "games", **ANY_GAME})
    outside = _secret_game(api, 7)
    plan = _ok(api.create_plan({"weeks": 1, "weekdays": EVERY_DAY, "minutes": 30}))
    day = plan["days"][0]["id"]
    clock.advance(days=1500)  # after the games' dates
    inside = _ok(api.add_journal_entry({"text": "Tagged inside.", "game_id": ids[1], "plan_day_id": day}))
    out = _ok(api.add_journal_entry({"text": "Tagged outside.", "game_id": outside, "plan_day_id": day}))
    only_day = _ok(api.add_journal_entry({"text": "Tagged a day.", "plan_day_id": day}))
    assert inside["kind"] == "reflection" and out["kind"] == "reflection" and only_day["kind"] == "note"
    preview = _ok(api.get_coach_journal_preview(rid))
    by_text = {p["text"]: p for p in preview}
    assert by_text["Tagged inside."]["game"]
    assert by_text["Tagged outside."]["game"] is None and by_text["Tagged a day."]["game"] is None
    configure(svc)
    fake(svc).queue(_with())
    _wait(api, api.start_coach_ai(rid, {"include_journal": True}))
    req = fake(svc).requests[-1]
    blob = req.user + req.system
    sent = _journal_lines(req.user)
    assert {x["note"] for x in sent} == {"Tagged inside.", "Tagged outside.", "Tagged a day."}
    for x in sent:
        assert set(x) <= {"note", "kind", "game", "ply", "weakness"}, x
    assert next(x for x in sent if x["note"] == "Tagged inside.")["game"].startswith("G")
    assert "game" not in next(x for x in sent if x["note"] == "Tagged outside.")
    for bad in (
        "plan_day",
        "plan_task",
        '"game_id"',
        "SecretWhiteName",
        "SecretBlackName",
        "ZZSECRETGAME",
        "lichess",
        "2019",
    ):
        assert bad not in blob, bad


def test_qa2_every_key_a_real_report_can_have_is_a_tag(api: Api, paths: Any) -> None:
    plant_managed_install(paths)
    svc = _svc(api)
    _my_games(svc, 1)
    rid = _run(svc, {"source": "games", **ANY_GAME})
    r = _ok(api.get_coach_report(rid))
    keys = {w["key"] for g in ("weaknesses", "whole_game", "missed", "allowed", "habits") for w in r.get(g) or []}
    assert keys
    for k in keys:
        assert api.add_journal_entry({"text": "t", "weakness_key": k})["ok"], k


@pytest.mark.parametrize(
    "key",
    [
        "opening:Sicilian Defense", "opening:King's Indian Attack", "opening:St. George Defense", "opening:Réti Opening",
        "opening:Nimzo-Larsen Attack", "opening:Bird's Opening", "opening:Queen's Gambit Declined", "opening:Ruy Lopez",
        "opening:Scandinavian Defense", "opening:Pterodactyl Defense", "opening:Caro-Kann Defense", "opening:Ware Opening",
        "opening:Van't Kruijs Opening", "opening:Saragossa Opening", "opening:Mieses Opening", "opening:Benko Gambit",
        "endgame:rook", "endgame:pawn", "phase:conversion", "time:low_clock", "habit:castledLate", "habit:hungPiece",
        "missed:mateIn1", "allowed:fork", "puzzle:pin",
    ],
)  # fmt: skip
def test_qa2_real_weakness_keys_pass_the_tag_check(api: Api, key: str) -> None:
    assert api.add_journal_entry({"text": "t", "weakness_key": key})["ok"], key
    assert _ok(api.get_journal({"weakness_key": key}))["items"]


@pytest.mark.parametrize(
    "key",
    [
        "https://evil.example/u", "opening:https://evil.example/u", "opening:see evil.example/u now", "missed:www.evil.example",
        "habit:http://1.2.3.4/x", "opening://evil.example/a", "time:evil.com", "phase:1.2.3.4", "other:thing", "opening:", ":x",
    ],
)  # fmt: skip
def test_qa2_a_tag_can_not_be_a_web_address_on_add_or_on_edit(api: Api, key: str) -> None:
    assert api.add_journal_entry({"text": "t", "weakness_key": key})["ok"] is False
    e = _ok(api.add_journal_entry({"text": "t"}))
    assert api.edit_journal_entry(e["id"], "t", key)["ok"] is False


def test_qa2_a_reflection_tasks_weakness_from_an_ai_plan_can_be_saved(api: Api, paths: Any) -> None:
    """The plan's own weakness keys come from the report, so a task's tag always passes the journal's check."""
    plant_managed_install(paths)
    _my_games(_svc(api), 1)
    _run(_svc(api), {"source": "games", **ANY_GAME})
    plan = _ok(api.create_plan({"weeks": 4, "weekdays": EVERY_DAY, "minutes": 60}))
    tasks = [t for d in plan["days"] for t in d["tasks"]]
    keys = {t["weakness_key"] for t in tasks if t["weakness_key"]}
    assert keys
    for k in keys:
        assert api.add_journal_entry({"text": "t", "weakness_key": k})["ok"], k


def test_qa2_a_note_on_each_move_of_a_game_and_none_past_it(api: Api) -> None:
    gid = _secret_game(api, 0)
    moves = _ok(api.get_review(gid))
    n = len(moves["moves"]) if "moves" in moves else 0
    assert api.add_journal_entry({"text": "first", "game_id": gid, "ply": 0})["ok"]
    if n:
        assert api.add_journal_entry({"text": "last", "game_id": gid, "ply": n - 1})["ok"]
        assert api.add_journal_entry({"text": "past", "game_id": gid, "ply": n})["ok"] is False
    assert api.add_journal_entry({"text": "neg", "game_id": gid, "ply": -1})["ok"] is False


# ---- FR-10.73: the group guard for each whole-game kind ----


def _weak(key: str, per10: float) -> dict[str, Any]:
    return {"key": key, "label": key, "per10": per10, "count": 3, "games": 3, "game_ids": [], "score": 1.0,
            "themes": [], "mode": None, "reasons": {}, "examples": []}  # fmt: skip


def _measures(key: str, n: int) -> dict[str, Any]:
    if key.startswith("opening:"):
        return {"openings": [{"family": key.split(":", 1)[1], "games": n, "score": 0.5}]}
    if key.startswith("endgame:"):
        return {"endgames": [{"type": key.split(":", 1)[1], "games": n}]}
    group = {"phase:conversion": "conversion", "time:low_clock": "time", "habit:castledLate": "king"}[key]
    return {group: {"games": n}}


def _sides(key: str, old_n: int | None, new_n: int | None, *, in_new: bool = False) -> Any:
    old: dict[str, Any] = {"source": "games", "games": 20, "whole_game": [_weak(key, 6.0)], "weaknesses": []}
    new: dict[str, Any] = {
        "source": "games",
        "games": 20,
        "whole_game": [_weak(key, 2.0)] if in_new else [],
        "weaknesses": [],
    }
    if old_n is not None:
        old["measures"] = _measures(key, old_n)
    if new_n is not None:
        new["measures"] = _measures(key, new_n)
    a = Side(1, "2026-01-01T10:00:00+00:00", old, frozenset(range(20)))
    b = Side(2, "2026-01-10T10:00:00+00:00", new, frozenset(range(100, 120)))
    return compare(b, [a])


ALL_KINDS = ["opening:Sicilian", "endgame:rook", "phase:conversion", "time:low_clock", "habit:castledLate"]


@pytest.mark.parametrize("key", ALL_KINDS)
@pytest.mark.parametrize("old_n,new_n", [(8, 2), (2, 8), (4, 4), (8, 0), (5, 4), (4, 5)])
@pytest.mark.parametrize("in_new", [False, True])
def test_qa2_each_whole_game_kind_needs_5_games_each_side(key: str, old_n: int, new_n: int, in_new: bool) -> None:
    c = _sides(key, old_n, new_n, in_new=in_new)
    w = next(x for x in c.weaknesses if x.key == key)
    assert w.verdict == "not_enough"


@pytest.mark.parametrize("key", ALL_KINDS)
def test_qa2_each_whole_game_kind_with_5_games_each_side_gets_a_verdict(key: str) -> None:
    w = next(x for x in _sides(key, 5, 5, in_new=True).weaknesses if x.key == key)
    assert w.verdict == "better"


@pytest.mark.parametrize("key", ALL_KINDS)
@pytest.mark.parametrize("old_n,new_n", [(None, None), (None, 8), (8, None)])
def test_qa2_a_report_with_no_measures_never_gets_a_verdict(key: str, old_n: Any, new_n: Any) -> None:
    c = _sides(key, old_n, new_n, in_new=True)
    assert next(x for x in c.weaknesses if x.key == key).verdict == "not_enough"


@pytest.mark.parametrize("key", ALL_KINDS)
def test_qa2_a_measures_that_is_not_a_mapping_or_has_odd_rows_does_not_crash(key: str) -> None:
    old = {"source": "games", "games": 20, "whole_game": [_weak(key, 6.0)], "weaknesses": [], "measures": "odd"}
    new = {
        "source": "games",
        "games": 20,
        "whole_game": [],
        "weaknesses": [],
        "measures": {"openings": ["x", None], "endgames": None, "king": 3},
    }
    c = compare(
        Side(2, "2026-01-10T10:00:00+00:00", new, frozenset(range(100, 120))),
        [Side(1, "2026-01-01T10:00:00+00:00", old, frozenset(range(20)))],
    )
    assert c is not None and c.weaknesses[0].verdict == "not_enough"


def test_qa2_real_reports_have_the_groups_the_guard_reads(api: Api, paths: Any) -> None:
    plant_managed_install(paths)
    svc = _svc(api)
    _games(svc, 6)
    rid = _run(svc, {"source": "games", **ANY_GAME})
    with svc.db.session() as conn:
        data = json.loads(conn.execute("SELECT report_json FROM coach_reports WHERE id = ?", (rid,)).fetchone()[0])
    ms = data["measures"]
    for group in ("conversion", "time", "king"):
        assert "games" in ms[group], (group, ms[group])
    for row in ms["openings"]:
        assert "family" in row and "games" in row, row
    for row in ms["endgames"]:
        assert "type" in row and "games" in row, row


def test_qa2_the_ai_is_told_not_enough_and_a_better_claim_is_dropped_for_each_kind() -> None:
    for key in ALL_KINDS:
        c = _sides(key, 8, 2)
        notes, dropped = validate_trend([{"key": key, "change": "improved", "comment": "Well done."}], c)
        assert notes == [] and dropped == 1, key


def test_qa2_a_group_with_5_games_gone_from_the_list_because_others_are_worse_is_not_better() -> None:
    """A weakness pushed out of the capped list (or below its gate) still has games in its group: its rate isn't 0."""
    key = "opening:Sicilian"
    w = next(x for x in _sides(key, 8, 8).weaknesses if x.key == key)
    assert w.flag == "gone"
    assert w.verdict != "better", (w.then, w.now, w.verdict)


def test_qa2_low_clock_mistakes_unchanged_but_gone_from_the_list_are_not_better() -> None:
    """Built by the real measures from digests: as many low-clock mistakes as before, but mistakes elsewhere rose, so
    the weakness's gate (low-clock rate above the rest) closes. Its rate hasn't improved."""

    def report(ds: list[tuple[int, Any]]) -> dict[str, Any]:
        ms = build_measures(ds)
        return {"source": "games", "games": len(ds), "weaknesses": [], "measures": ms.to_json(),
                "whole_game": [asdict(w) for w in game_weaknesses(ds, ms)]}  # fmt: skip

    hurried = dg(time=_clock(5, 1), moments=(moment(70, swing=500, clock_pct=4),))
    calm = dg(time=_clock(5, 0))
    before = games(hurried, hurried, calm, calm, calm)
    after = games(*[replace(d, time=_clock(5, 1 if i < 2 else 0, 30, 10)) for i, (_, d) in enumerate(before)])
    a, b = report(before), report(after)
    assert [w["key"] for w in a["whole_game"]] == ["time:low_clock"] and b["whole_game"] == []
    assert a["measures"]["time"]["low_error_rate"] == b["measures"]["time"]["low_error_rate"]
    c = compare(
        Side(2, "2026-01-10T10:00:00+00:00", b, frozenset(range(100, 105))),
        [Side(1, "2026-01-01T10:00:00+00:00", a, frozenset(range(5)))],
    )
    assert c is not None
    w = next(x for x in c.weaknesses if x.key == "time:low_clock")
    assert w.flag == "gone"
    assert w.verdict != "better", (w.then, w.now, w.verdict)


# ---- user/0012: from a v0.11 database, and from one at 0011 ----


def _upto(tmp: Path, last: str) -> Path:
    old = tmp / f"mig{last}"
    old.mkdir()
    for f in sorted((MIGRATIONS_DIR / "user").glob("00*.sql")):
        if f.name[:4] <= last:
            shutil.copy(f, old / f.name)
    return old


def test_qa2_a_v011_database_migrates_and_its_rows_stay(
    paths: Any, clock: Any, desktop: FakeDesktop, fixture_puzzles_db: Any, tmp_path: Path
) -> None:
    migrate(paths.user_db, _upto(tmp_path, "0010"), clock)
    with sqlite3.connect(paths.user_db) as conn:
        assert "plan_tasks" not in {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
        conn.execute(
            "INSERT INTO sessions (started_at, mode, filters_json) VALUES ('2026-01-01T10:00:00+00:00', 'standard', '{}')"
        )
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone() == (1,)
    api = _api(paths, clock, desktop, fixture_puzzles_db)
    with sqlite3.connect(paths.user_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone() == (1,)
        assert "manual_at" in {r[1] for r in conn.execute("PRAGMA table_info(plan_tasks)")}
        assert conn.execute("PRAGMA user_version").fetchone()[0] >= 0
    plan = _plan_with(api, [[_ref("a"), _ref("b")]])
    _ok(api.set_plan_task_tick(_day(plan, 0)[0]["id"], True))
    assert _log_done(api, _today_iso(api)) == 1


def test_qa2_a_database_at_0011_with_a_plan_keeps_its_ticks(
    paths: Any, clock: Any, desktop: FakeDesktop, fixture_puzzles_db: Any, tmp_path: Path
) -> None:
    migrate(paths.user_db, _upto(tmp_path, "0011"), clock)
    with sqlite3.connect(paths.user_db) as conn:
        assert "manual_at" not in {r[1] for r in conn.execute("PRAGMA table_info(plan_tasks)")}
    now = clock.now().isoformat()
    day = clock.now().date().isoformat()
    with sqlite3.connect(paths.user_db) as conn:
        cur = conn.execute(
            "INSERT INTO training_plans (created_at, report_id, source, weeks, weekdays_json, minutes_per_day, start_date, status)"
            " VALUES (?, NULL, 'deterministic', 1, ?, 20, ?, 'current')",
            (now, json.dumps(EVERY_DAY), day),
        )
        pid = cur.lastrowid
        dcur = conn.execute("INSERT INTO plan_days (plan_id, week, position, date) VALUES (?,1,1,?)", (pid, day))
        for i, state in enumerate(("done", "undone", None)):
            conn.execute(
                "INSERT INTO plan_tasks (day_id, position, type, minutes, title, params_json, manual_state)"
                " VALUES (?,?,?,?,?,?,?)",
                (dcur.lastrowid, i, "reflection", 10, f"t{i}", '{"prompt": "x"}', state),
            )
    api = _api(paths, clock, desktop, fixture_puzzles_db)
    plan = _ok(api.get_current_plan())
    assert [t["status"] for t in _day(plan, 0)] == ["done", "left", "left"]
    with sqlite3.connect(paths.user_db) as conn:
        assert conn.execute("SELECT manual_at FROM plan_tasks").fetchall() == [(None,)] * 3
    assert _log_done(api, day) == 0  # no time was recorded for that tick: nothing to file it under, and no crash
    _ok(api.set_plan_task_tick(_day(plan, 0)[2]["id"], True))
    assert _log_done(api, day) == 1
    # Migrating again changes nothing.
    migrate(paths.user_db, MIGRATIONS_DIR / "user", clock)
    assert _ok(api.get_current_plan())["done"] == 2


def test_qa2_a_real_data_folder_restart_keeps_the_hand_tick(
    paths: Any, clock: Any, desktop: FakeDesktop, fixture_puzzles_db: Any
) -> None:
    api = _api(paths, clock, desktop, fixture_puzzles_db)
    plan = _plan_with(api, [[_ref("a"), _ref("b")]])
    _ok(api.set_plan_task_tick(_day(plan, 0)[0]["id"], True))
    again = build_api(paths, clock, desktop)
    assert _ok(again.get_current_plan())["done"] == 1
    assert _log_done(again, _today_iso(again)) == 1


# ---- FR-10.61-10.64 with no puzzle database, through Start ----


@pytest.fixture
def nodb(paths: Any, clock: Any, desktop: FakeDesktop) -> Api:
    return _api(paths, clock, desktop, None)


def test_qa2_the_whole_plan_with_no_puzzle_database_through_start(nodb: Api, paths: Any) -> None:
    api = nodb
    assert _ok(api.get_puzzle_db_status())["installed"] is False
    plant_managed_install(paths)
    _my_games(_svc(api), 1)
    _run(_svc(api), {"source": "games", **ANY_GAME})
    prev = _ok(api.preview_plan({"weeks": 2, "weekdays": EVERY_DAY, "minutes": 60}))
    assert prev["days"]
    plan = _ok(api.create_plan({"weeks": 2, "weekdays": EVERY_DAY, "minutes": 60}))
    _ok(api.get_today_plan())
    seen: dict[str, int] = {}
    for d in plan["days"]:
        for t in d["tasks"]:
            seen[t["type"]] = seen.get(t["type"], 0) + 1
            got = api.start_plan_task(t["id"], False)
            if not got["ok"]:
                assert got["error"].get("code") != "internal", (t["type"], got)
                assert "went wrong" not in got["error"]["message"], (t["type"], got)
    assert seen
    first = plan["days"][0]["tasks"]
    got = api.swap_plan_task(first[0]["id"])
    assert got["ok"], got
    assert api.skip_plan_task(first[1]["id"])["ok"]
    assert api.set_plan_task_tick(first[2 if len(first) > 2 else 1]["id"], True)["ok"]
    assert _ok(api.get_current_plan())["days"]
    assert _ok(api.get_journal({}))


def test_qa2_a_lessons_drill_with_no_puzzle_database(nodb: Api, paths: Any) -> None:
    api = nodb
    plant_managed_install(paths)
    _my_games(_svc(api), 1)
    _run(_svc(api), {"source": "games", **ANY_GAME})
    plan = _ok(api.create_plan({"weeks": 2, "weekdays": EVERY_DAY, "minutes": 60}))
    lessons = [t for d in plan["days"] for t in d["tasks"] if t["type"] == "lesson"]
    assert lessons
    for t in lessons:
        got = api.start_plan_lesson_drill(t["id"], False)
        assert got["ok"] or got["error"].get("code") != "internal", (t["title"], got)


def test_qa2_a_game_puzzle_task_with_no_puzzle_database(nodb: Api, paths: Any) -> None:
    """Your own puzzles live in user.db: is it refused with a plain message, or does it play?"""
    api = nodb
    plant_managed_install(paths)
    _my_games(_svc(api), 1)
    _run(_svc(api), {"source": "games", **ANY_GAME})
    task = Task(GAME_PUZZLES, 10, "from your games", {"severities": ["blunder"], "kinds": ["missed"], "count": 1})
    plan = _plan_with(api, [[task, _ref("x")]])
    got = api.start_plan_task(_task(plan)["id"], False)
    assert got["ok"] or "went wrong" not in got["error"]["message"]


def test_qa2_the_ai_run_with_no_puzzle_database_and_a_plan(nodb: Api, paths: Any) -> None:
    api = nodb
    plant_managed_install(paths)
    svc = _svc(api)
    _my_games(svc, 1)
    rid = _run(svc, {"source": "games", **ANY_GAME})
    _ok(api.create_plan({"weeks": 1, "weekdays": EVERY_DAY, "minutes": 60}))
    configure(svc)
    fake(svc).queue(_with())
    _wait(api, api.start_coach_ai(rid))
    assert "plan" in fake(svc).requests[-1].user.lower()
