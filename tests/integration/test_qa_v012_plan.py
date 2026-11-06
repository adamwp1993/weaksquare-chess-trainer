"""QA v0.12: the training plan through the real bridge, from real events (FR-10.61-10.65).

Every tick here comes from what the app really records: `submit_move` on a real session, `retry_move`,
`mark_review_ply`, `add_journal_entry`, `open_plan_lesson`. Days pass on a real clock path (`FixedClock.advance`, and
`OffsetClock` for the dev time offset). A test exposing an open bug is marked xfail with its ID.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from tests.fakes.engine import FakeEngine, plant_managed_install
from tests.helpers import FakeDesktop, build_api
from tests.integration.test_coach_run import ANY_GAME, _my_games, _run
from tests.integration.test_qa_v011_coach import _games
from weaksquare.adapters.db.migrate import migrate
from weaksquare.adapters.db.repos.plans import PlansRepo
from weaksquare.adapters.system_clock import OffsetClock
from weaksquare.bridge.api import Api
from weaksquare.config import MIGRATIONS_DIR
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
)

EVERY_DAY = [0, 1, 2, 3, 4, 5, 6]


@pytest.fixture(autouse=True)
def _reset() -> None:
    FakeEngine.instances.clear()


@pytest.fixture
def desktop() -> FakeDesktop:
    return FakeDesktop()


def _api(paths: Any, clock: Any, desktop: FakeDesktop, puzzles: Any) -> Api:
    if puzzles is not None:
        shutil.copyfile(puzzles, paths.puzzles_db)
    migrate(paths.user_db, MIGRATIONS_DIR / "user", clock)
    return build_api(paths, clock, desktop)


@pytest.fixture
def api(paths: Any, clock: Any, desktop: FakeDesktop, fixture_puzzles_db: Any) -> Api:
    return _api(paths, clock, desktop, fixture_puzzles_db)


def _ok(result: Any) -> Any:
    assert result.get("ok") is True, result
    return result["data"]


def _svc(api: Api) -> SimpleNamespace:
    """The services behind this bridge, for the shared helpers that make games and reports."""
    return SimpleNamespace(
        coach=api._coach, games=api._games, db=api._plan._plans._db, game_puzzles=api._game_puzzles,
        llm_settings=api._llm_settings, plan=api._plan, journal=api._journal, review=api._review,
    )  # fmt: skip


def _real_report(api: Api, paths: Any, n: int = 6) -> tuple[int, list[int]]:
    """A report from a real Coach run on n analyzed games of yours."""
    plant_managed_install(paths)
    ids = _games(_svc(api), n)
    return _run(_svc(api), {"source": "games", **ANY_GAME}), ids


def _plan_with(api: Api, days: list[list[Task]], minutes: int = 20) -> dict[str, Any]:
    """A plan with these tasks, one training day per calendar day from today."""
    today = api._plan._today()
    params = PlanParams(1, tuple(sorted({(today.weekday() + i) % 7 for i in range(len(days))})), minutes)
    draft = PlanDraft(params, tuple(Day(1, i + 1, tuple(t)) for i, t in enumerate(days)))
    PlansRepo(_svc(api).db).add(
        draft, [today + timedelta(days=i) for i in range(len(days))], api._plan._now(), report_id=None,
        source="deterministic",
    )  # fmt: skip
    plan: dict[str, Any] = _ok(api.get_current_plan())
    return plan


def _puzzles_task(count: int = 2, minutes: int = 10, mode: str = "standard") -> Task:
    return Task(
        PUZZLES, minutes, f"{count} puzzles",
        {"themes": [], "mode": mode, "count": count, "rating_min": None, "rating_max": None},
    )  # fmt: skip


def _solution(paths: Any, puzzle_id: str) -> list[str]:
    conn = sqlite3.connect(paths.puzzles_db)
    try:
        row = conn.execute("SELECT moves FROM puzzles WHERE id = ?", (puzzle_id,)).fetchone()
    finally:
        conn.close()
    return str(row[0]).split()


def _solve_next(api: Api, paths: Any, sid: int) -> bool:
    """Play the next puzzle of a real session through the bridge, correctly. False when the queue has ended."""
    view = _ok(api.next_puzzle(sid))
    if view is None:
        return False
    for uci in _solution(paths, view["puzzle_id"])[1::2]:
        if _ok(api.submit_move(sid, uci))["finished"]:
            break
    return True


def _settings_and_presets(api: Api) -> tuple[list[Any], list[Any]]:
    with _svc(api).db.session() as conn:
        settings = [tuple(r) for r in conn.execute("SELECT key, value FROM settings ORDER BY key")]
        presets = [tuple(r) for r in conn.execute("SELECT * FROM presets ORDER BY 1")]
    return settings, presets


def _task(plan: dict[str, Any], day: int = 0, n: int = 0) -> dict[str, Any]:
    t: dict[str, Any] = plan["days"][day]["tasks"][n]
    return t


# ---- FR-10.61, 10.62, 10.63: a real plan from a real report ----


def test_qa_every_task_of_a_real_plan_from_a_real_report_can_start(api: Api, paths: Any) -> None:
    plant_managed_install(paths)
    svc = _svc(api)
    _my_games(svc, 1)  # a missed mate and an allowed one, so tactical weaknesses with their game and puzzles
    _run(svc, {"source": "games", **ANY_GAME})
    plan = _ok(api.create_plan({"weeks": 4, "weekdays": EVERY_DAY, "minutes": 120}))
    seen: set[str] = set()
    for day in plan["days"]:
        assert 2 <= len(day["tasks"]) <= 4
        assert sum(t["minutes"] for t in day["tasks"]) == 120
        for t in day["tasks"]:
            seen.add(t["type"])
            got = api.start_plan_task(t["id"], False)
            assert got["ok"], (t, got)
    # Puzzles from your games appear only when you have enough of them: this one game has too few (see the next test).
    assert {"puzzles", "retry", "review", "lesson", "reflection"} == seen, seen


def test_qa_a_task_of_puzzles_from_your_games_starts_and_ticks(api: Api, paths: Any) -> None:
    plant_managed_install(paths)
    svc = _svc(api)
    _my_games(svc, 1)
    _run(svc, {"source": "games", **ANY_GAME})
    assert any(s == "active" for *_, s in api._plan._game_puzzles.coach_puzzles())
    task = Task(GAME_PUZZLES, 10, "from your games", {"severities": ["blunder"], "kinds": ["missed"], "count": 1})
    plan = _plan_with(api, [[task, Task(REFLECTION, 10, "x", {"prompt": "x"})]])
    a = _ok(api.start_plan_task(_task(plan)["id"], False))
    sid = a["session"]["session_id"]
    view = _ok(api.next_puzzle(sid))
    assert view["source"] == "my"
    _ok(api.next_puzzle(sid))  # moving on decides it
    assert _task(_ok(api.get_current_plan()))["status"] == "done"


def test_qa_a_real_puzzle_history_report_makes_a_plan(api: Api) -> None:
    conn_rows = _svc(api)
    # 15 real, first-try-wrong attempts make puzzle weaknesses in a puzzle-history report.
    info = _ok(api.start_session({"queue_size": 20}, False, "standard", False))
    sid = info["session_id"]
    for _ in range(15):
        if _ok(api.next_puzzle(sid)) is None:
            break
    rid = _run(conn_rows, {"source": "puzzles"})
    plan = _ok(api.create_plan({"weeks": 1, "weekdays": [0, 1], "minutes": 20}))
    assert len(plan["days"]) == 2
    for day in plan["days"]:
        for t in day["tasks"]:
            assert t["type"] in ("puzzles", "lesson", "reflection"), t  # a puzzle-history report has no games
            assert api.start_plan_task(t["id"], False)["ok"]
    assert _ok(api.get_coach_report(rid))["comparison"] is None


def test_qa_the_plan_works_without_a_puzzle_database(paths: Any, clock: Any, desktop: FakeDesktop) -> None:
    api = _api(paths, clock, desktop, None)
    with _svc(api).db.transaction() as conn:
        conn.execute(
            "INSERT INTO coach_reports (created_at, subject, subject_label, source_kind, params_json, report_json,"
            " game_ids_json) VALUES ('2026-01-01T10:00:00+00:00','me','You','games','{}',?, '[]')",
            (json.dumps({"source": "games", "games": 10, "weaknesses": [], "whole_game": []}),),
        )
    assert _ok(api.get_today_plan()) is None  # the Today card's read must never fail
    got = api.preview_plan({"weeks": 1})
    assert got["ok"] or got["error"]["message"]  # a plain answer either way, never a crash
    assert got["ok"] or got["error"].get("code") != "internal"


# ---- FR-10.63: a puzzle task never touches your Mixer ----


def test_qa_every_session_from_a_task_leaves_every_setting_and_preset_byte_identical(api: Api, paths: Any) -> None:
    _real_report(api, paths)
    mine = {"themes": ["pin"], "rating_min": 800, "rating_max": 900}
    _ok(api.set_setting("mixer.filters", mine))
    _ok(api.set_setting("trainer.mode", "commit_line"))
    _ok(api.save_preset("My preset", mine))
    plan = _plan_with(
        api,
        [
            [
                _puzzles_task(1),
                _puzzles_task(1, mode="commit_line"),
                _puzzles_task(1, mode="name_idea"),
                _puzzles_task(1, mode="danger_spotting"),
                Task(LESSON, 5, "lesson", {"topic": "theme:fork"}),
            ]
        ],
    )
    before = _settings_and_presets(api)
    assert any(r[0] == "mixer.filters" for r in before[0]) and len(before[1]) == 1
    for t in _ok(api.get_current_plan())["days"][0]["tasks"]:
        got = (
            _ok(api.start_plan_lesson_drill(t["id"], False))
            if t["type"] == "lesson"
            else _ok(api.start_plan_task(t["id"], False))
        )
        sid = got["session"]["session_id"]
        _ok(api.next_puzzle(sid))
        _ok(api.next_puzzle(sid))
        _ok(api.get_today_plan())
        _ok(api.get_current_plan())
        assert _settings_and_presets(api) == before, t["type"]
    assert plan["id"]


# ---- FR-10.64: every type ticks from the real event ----


def test_qa_a_puzzle_task_ticks_from_really_solved_puzzles_across_stop_and_resume(api: Api, paths: Any) -> None:
    plan = _plan_with(api, [[_puzzles_task(3), Task(REFLECTION, 10, "x", {"prompt": "?"})]])
    tid = _task(plan)["id"]
    a = _ok(api.start_plan_task(tid, False))
    assert a["remaining"] == 3 and a["session"]["queue_size"] == 3
    assert _solve_next(api, paths, a["session"]["session_id"])
    assert _task(_ok(api.get_current_plan()))["progress"] == 1
    b = _ok(api.start_plan_task(tid, False))  # stop and resume
    assert b["remaining"] == 2
    assert _solve_next(api, paths, b["session"]["session_id"])
    assert _solve_next(api, paths, b["session"]["session_id"])
    assert _task(_ok(api.get_current_plan()))["status"] == "done"
    today = _ok(api.get_today_plan())["day"]["tasks"][0]
    assert today["status"] == "done" and today["auto"] is True


def test_qa_retry_ticks_from_real_retry_moves_and_a_review_from_real_visits(api: Api, paths: Any) -> None:
    plant_managed_install(paths)
    gid = _games(_svc(api), 1)[0]
    plan = _plan_with(api, [[Task(RETRY, 10, "r", {"game_id": gid}), Task(REVIEW, 10, "v", {"game_id": gid})]])
    retry, review = plan["days"][0]["tasks"]
    rev = _ok(api.get_review(gid))
    assert _ok(api.start_plan_task(retry["id"]))["kind"] == "retry"
    for ply in rev["retry_plies"]:
        move = rev["moves"][ply]
        _ok(api.retry_move(gid, ply, move["best_move"] or move["uci"]))
    assert _task(_ok(api.get_current_plan()), 0, 0)["status"] == "done"

    assert _ok(api.start_plan_task(review["id"]))["kind"] == "review"
    assert _task(_ok(api.get_current_plan()), 0, 1)["status"] == "left"
    for m in rev["key_moments"]:
        _ok(api.mark_review_ply(gid, m))
    last = len(rev["moves"]) - 1
    assert _ok(api.mark_review_ply(gid, last)) is True
    t = _task(_ok(api.get_current_plan()), 0, 1)
    assert t["status"] == "done" and t["auto"] is True


def test_qa_a_reflection_and_a_lesson_tick_from_the_real_calls(api: Api, desktop: FakeDesktop, paths: Any) -> None:
    _real_report(api, paths, 1)
    plan = _plan_with(
        api, [[Task(REFLECTION, 10, "x", {"prompt": "?"}), Task(LESSON, 10, "l", {"topic": "theme:fork"})]]
    )
    refl, lesson = plan["days"][0]["tasks"]
    action = _ok(api.start_plan_task(refl["id"]))
    _ok(api.add_journal_entry({"text": "Thought.", "plan_day_id": action["plan_day_id"], "plan_task_id": refl["id"]}))
    assert _task(_ok(api.get_current_plan()))["status"] == "done"
    assert _ok(api.start_plan_task(lesson["id"]))["kind"] == "lesson"
    assert _task(_ok(api.get_current_plan()), 0, 1)["status"] == "left"
    _ok(api.open_plan_lesson(lesson["id"], "curated:0"))
    assert _task(_ok(api.get_current_plan()), 0, 1)["status"] == "done" and desktop.urls


def test_qa_a_hand_choice_always_wins_over_a_later_real_event(api: Api, paths: Any) -> None:
    plan = _plan_with(api, [[_puzzles_task(1), Task(REFLECTION, 10, "x", {"prompt": "?"})]])
    tid = _task(plan)["id"]
    _ok(api.set_plan_task_tick(tid, False))  # unticked before the app saw anything
    a = _ok(api.start_plan_task(tid, False))
    assert _solve_next(api, paths, a["session"]["session_id"])
    t = _task(_ok(api.get_current_plan()))
    assert t["status"] != "done" and t["auto"] is True and t["manual"] == "undone"
    _ok(api.set_plan_task_tick(tid, True))
    assert _task(_ok(api.get_current_plan()))["status"] == "done"


def test_qa_the_totals_never_count_a_task_twice_when_it_is_carried(api: Api, clock: Any) -> None:
    plan = _plan_with(
        api,
        [[Task(REFLECTION, 10, "x", {"prompt": "a"}), _puzzles_task(5)], [Task(REFLECTION, 10, "y", {"prompt": "b"})]],
    )
    assert plan["left"] == 3
    clock.advance(days=1)
    after = _ok(api.get_current_plan())
    assert after["left"] == 3  # today's 1 plus the 2 carried; the originals say "carried" and aren't counted


def test_qa_minutes_spent_do_not_double_when_a_puzzle_task_is_carried(api: Api, clock: Any) -> None:
    plan = _plan_with(
        api,
        [[_puzzles_task(5), Task(REFLECTION, 10, "x", {"prompt": "a"})], [Task(REFLECTION, 10, "y", {"prompt": "b"})]],
    )
    tid = _task(plan)["id"]
    a = _ok(api.start_plan_task(tid, False))
    sid = a["session"]["session_id"]
    _ok(api.next_puzzle(sid))
    clock.advance(minutes=10)
    _ok(api.next_puzzle(sid))  # one attempt of 10 minutes
    with _svc(api).db.transaction() as conn:
        conn.execute("UPDATE attempts SET time_ms = 600000 WHERE session_id = ?", (sid,))
    assert _ok(api.get_current_plan())["minutes_spent"] == 10
    clock.advance(days=1)
    assert _ok(api.get_current_plan())["minutes_spent"] == 10  # the same 10 minutes


# ---- carry-over, day by day ----


def _three_missed(api: Api) -> None:
    day1 = [Task(REFLECTION, 10, f"a{i}", {"prompt": f"a{i}"}) for i in range(3)]
    _plan_with(api, [day1, [Task(REFLECTION, 10, "b", {"prompt": "b"})], [Task(REFLECTION, 10, "c", {"prompt": "c"})]])


def test_qa_the_first_read_of_a_new_day_carries_a_days_worth(api: Api, clock: Any) -> None:
    _three_missed(api)
    clock.advance(days=1)
    p = _ok(api.get_current_plan())
    carried = [t for t in p["days"][1]["tasks"] if t["carried"]]
    assert len(carried) == 2 and sum(t["minutes"] for t in carried) == 20  # 3 x 10 missed, 20 a day


def test_qa_reading_the_plan_again_never_carries_more_than_a_days_worth(api: Api, clock: Any) -> None:
    _three_missed(api)
    clock.advance(days=1)
    for _ in range(3):  # the Today card and the Plan tab read it again after every change
        p = _ok(api.get_current_plan())
    carried = [t for t in p["days"][1]["tasks"] if t["carried"]]
    assert sum(t["minutes"] for t in carried) <= 20, [t["title"] for t in carried]


def test_qa_only_the_last_training_day_carries_when_you_were_away(api: Api, clock: Any) -> None:
    plan = _plan_with(
        api,
        [[Task(REFLECTION, 10, f"d{d}", {"prompt": f"d{d}"})] for d in range(4)],
    )
    clock.advance(days=3)  # opened again on day 4: days 1 and 2 are missed, day 3 carries
    p = _ok(api.get_current_plan())
    assert [t["status"] for t in p["days"][0]["tasks"]] == ["missed"]
    assert [t["status"] for t in p["days"][1]["tasks"]] == ["missed"]
    assert [t["status"] for t in p["days"][2]["tasks"]] == ["carried"]
    assert [t["title"] for t in p["days"][3]["tasks"]] == ["d3", "d2"]
    assert plan["id"] == p["id"]


def test_qa_carry_over_off_drops_them_and_a_rest_day_carries_nothing(api: Api, clock: Any) -> None:
    _plan_with(api, [[Task(REFLECTION, 10, "a", {"prompt": "a"})], [Task(REFLECTION, 10, "b", {"prompt": "b"})]])
    _ok(api.set_setting("plan.carry_over", False))
    clock.advance(days=1)
    p = _ok(api.get_current_plan())
    assert len(p["days"][1]["tasks"]) == 1 and p["days"][0]["tasks"][0]["status"] == "missed"
    clock.advance(days=1)  # past the end: a rest day with nothing to carry to
    today = _ok(api.get_today_plan())
    assert today["day"] is None and today["finished"] is True


def test_qa_done_and_skipped_tasks_never_carry(api: Api, clock: Any, paths: Any) -> None:
    plan = _plan_with(
        api,
        [
            [_puzzles_task(1), Task(REFLECTION, 5, "s", {"prompt": "s"}), Task(REFLECTION, 5, "h", {"prompt": "h"})],
            [Task(REFLECTION, 10, "b", {"prompt": "b"})],
        ],
    )
    done, skipped, ticked = plan["days"][0]["tasks"]
    a = _ok(api.start_plan_task(done["id"], False))
    assert _solve_next(api, paths, a["session"]["session_id"])
    _ok(api.skip_plan_task(skipped["id"]))
    _ok(api.set_plan_task_tick(ticked["id"], True))
    clock.advance(days=1)
    p = _ok(api.get_current_plan())
    assert len(p["days"][1]["tasks"]) == 1
    assert [t["status"] for t in p["days"][0]["tasks"]] == ["done", "skipped", "done"]


def test_qa_a_carried_task_can_be_finished_and_its_session_counts_on_the_copy(api: Api, clock: Any, paths: Any) -> None:
    plan = _plan_with(
        api,
        [[_puzzles_task(2), Task(REFLECTION, 10, "x", {"prompt": "x"})], [Task(REFLECTION, 10, "b", {"prompt": "b"})]],
    )
    a = _ok(api.start_plan_task(_task(plan)["id"], False))
    assert _solve_next(api, paths, a["session"]["session_id"])  # 1 of 2 on day 1
    clock.advance(days=1)
    p = _ok(api.get_current_plan())
    copy = next(t for t in p["days"][1]["tasks"] if t["carried"] and t["type"] == "puzzles")
    assert copy["progress"] == 1
    b = _ok(api.start_plan_task(copy["id"], False))
    assert b["remaining"] == 1
    assert _solve_next(api, paths, b["session"]["session_id"])
    p = _ok(api.get_current_plan())
    assert next(t for t in p["days"][1]["tasks"] if t["id"] == copy["id"])["status"] == "done"


def test_qa_swapping_a_carried_task_does_not_bring_it_back(api: Api, clock: Any, paths: Any) -> None:
    _real_report(api, paths, 1)
    _plan_with(
        api,
        [[_puzzles_task(2), Task(REFLECTION, 10, "x", {"prompt": "x"})], [Task(REFLECTION, 10, "b", {"prompt": "b"})]],
    )
    clock.advance(days=1)
    p = _ok(api.get_current_plan())
    copies = [t for t in p["days"][1]["tasks"] if t["carried"]]
    _ok(api.swap_plan_task(copies[0]["id"]))
    for _ in range(2):
        again = _ok(api.get_current_plan())
        assert len(again["days"][1]["tasks"]) == len(p["days"][1]["tasks"])


def test_qa_the_dev_time_offset_moves_the_plan_day(paths: Any, desktop: FakeDesktop, fixture_puzzles_db: Any) -> None:
    clock = OffsetClock(0)
    api = _api(paths, clock, desktop, fixture_puzzles_db)
    _plan_with(api, [[Task(REFLECTION, 10, "a", {"prompt": "a"})], [Task(REFLECTION, 10, "b", {"prompt": "b"})]])
    first = _ok(api.get_today_plan())
    assert first["day"]["position"] == 1
    _ok(api.set_time_offset(1))
    second = _ok(api.get_today_plan())
    assert second["day"]["position"] == 2 and [t["title"] for t in second["day"]["tasks"]] == ["b", "a"]
    assert second["day"]["tasks"][1]["carried"] is True
    _ok(api.set_time_offset(5))
    assert _ok(api.get_today_plan())["finished"] is True


# ---- swap, history, odd inputs ----


def test_qa_swap_keeps_moving_to_the_next_task(api: Api, paths: Any) -> None:
    _real_report(api, paths, 6)
    plan = _ok(api.create_plan({"weeks": 1, "weekdays": EVERY_DAY, "minutes": 30}))
    tid = _task(plan)["id"]
    titles = [_task(plan)["title"]]
    for _ in range(3):
        tid = _ok(api.swap_plan_task(tid))
        now = _ok(api.get_current_plan())
        titles.append(next(t["title"] for t in now["days"][0]["tasks"] if t["id"] == tid))
    assert len(set(titles)) >= 3, titles


def test_qa_an_old_plans_completion_stops_when_it_is_replaced(api: Api, paths: Any, clock: Any) -> None:
    plant_managed_install(paths)
    gid = _games(_svc(api), 1)[0]
    rid = _run(_svc(api), {"source": "games", **ANY_GAME})
    old = _plan_with(api, [[Task(REVIEW, 10, "v", {"game_id": gid}), Task(REFLECTION, 10, "x", {"prompt": "x"})]])
    clock.advance(hours=1)
    _ok(api.create_plan({"weeks": 1, "weekdays": EVERY_DAY}, True))
    clock.advance(hours=1)
    rev = _ok(api.get_review(gid))
    for m in [*rev["key_moments"], len(rev["moves"]) - 1]:
        _ok(api.mark_review_ply(gid, m))
    ended = next(p for p in _ok(api.list_plans()) if p["id"] == old["id"])
    assert ended["status"] == "replaced" and ended["done"] == 0, ended
    assert rid


def test_qa_a_review_task_needs_visits_since_the_plan_began(api: Api, paths: Any, clock: Any) -> None:
    plant_managed_install(paths)
    gid = _games(_svc(api), 1)[0]
    rev = _ok(api.get_review(gid))
    for m in rev["key_moments"]:
        _ok(api.mark_review_ply(gid, m))  # a look at the game last week: the pass stays open
    clock.advance(days=7)
    plan = _plan_with(api, [[Task(REVIEW, 10, "v", {"game_id": gid}), Task(REFLECTION, 10, "x", {"prompt": "x"})]])
    _ok(api.start_plan_task(_task(plan)["id"]))
    _ok(api.mark_review_ply(gid, len(rev["moves"]) - 1))  # only the final move, today
    assert _task(_ok(api.get_current_plan()))["status"] == "left"


def test_qa_a_task_that_cannot_start_says_why_and_the_plan_still_reads(api: Api) -> None:
    plan = _plan_with(api, [[_puzzles_task(1, mode="danger_spotting"), Task(RETRY, 10, "r", {"game_id": 987654})]])
    danger, retry = plan["days"][0]["tasks"]
    got = api.start_plan_task(danger["id"], False)  # Stockfish isn't installed here
    assert got["ok"] is False and got["error"]["message"]
    assert api.start_plan_task(retry["id"], False)["ok"] is False
    assert _ok(api.get_today_plan())["day"]["tasks"][0]["status"] == "left"


@pytest.mark.parametrize(
    "bad",
    [
        {"weeks": 0},
        {"weeks": 5},
        {"weeks": True},
        {"minutes": 9},
        {"minutes": 121},
        {"minutes": 20.5},
        {"weekdays": []},
        {"weekdays": [7]},
        {"weekdays": [-1]},
        {"weekdays": ["1"]},
        {"evil": 1},
    ],
)
def test_qa_plan_settings_are_refused_outside_their_bounds(api: Api, paths: Any, bad: dict[str, Any]) -> None:
    _real_report(api, paths, 1)
    assert api.create_plan(bad)["ok"] is False
    assert api.preview_plan(bad)["ok"] is False
    assert api.set_setting("plan.params", bad)["ok"] is False
    assert _ok(api.get_current_plan()) is None


@pytest.mark.parametrize(
    "params", [{"weeks": 1, "weekdays": [0], "minutes": 10}, {"weeks": 4, "weekdays": EVERY_DAY, "minutes": 120}]
)
def test_qa_plan_settings_at_both_bounds_make_a_plan(api: Api, paths: Any, params: dict[str, Any]) -> None:
    _real_report(api, paths, 1)
    plan = _ok(api.create_plan(params))
    assert len(plan["days"]) == params["weeks"] * len(params["weekdays"])
    for d in plan["days"]:
        assert sum(t["minutes"] for t in d["tasks"]) == params["minutes"] and 2 <= len(d["tasks"]) <= 4
