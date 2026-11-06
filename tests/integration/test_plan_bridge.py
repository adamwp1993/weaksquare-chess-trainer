"""v0.12 through the real bridge: every DTO the plan, the journal and Since last report send (FR-10.61–10.73)."""

from __future__ import annotations

import shutil
from datetime import timedelta
from typing import Any

import pytest

from tests.fakes.engine import FakeEngine, plant_managed_install
from tests.helpers import FakeDesktop, build_api
from tests.integration.test_game_puzzles import Recorder
from tests.unit.test_digest import make_rows
from weaksquare.adapters.db.connection import Database
from weaksquare.adapters.db.migrate import migrate
from weaksquare.adapters.db.repos.coach import CoachReportsRepo
from weaksquare.adapters.db.repos.game_analysis import GameAnalysisRepo
from weaksquare.adapters.db.repos.plans import PlansRepo
from weaksquare.bridge.api import Api
from weaksquare.config import MIGRATIONS_DIR
from weaksquare.core.filters import FilterSpec
from weaksquare.core.plan import LESSON, PUZZLES, REFLECTION, RETRY, REVIEW, Day, PlanDraft, PlanParams, Task


@pytest.fixture(autouse=True)
def _reset() -> None:
    FakeEngine.instances.clear()


@pytest.fixture
def desktop() -> FakeDesktop:
    return FakeDesktop()


@pytest.fixture
def api(paths: Any, clock: Any, desktop: FakeDesktop, fixture_puzzles_db: Any) -> Api:
    shutil.copyfile(fixture_puzzles_db, paths.puzzles_db)
    migrate(paths.user_db, MIGRATIONS_DIR / "user", clock)
    return build_api(paths, clock, desktop)


def _ok(result: Any) -> Any:
    """Bridge calls answer {"ok": true, "data": ...} or {"ok": false, "error": ...}."""
    assert result.get("ok") is True, result
    return result["data"]


def _db(api: Api) -> Database:
    return api._plan._plans._db  # type: ignore[no-any-return]


def _report(
    api: Api, *, day: int = 5, games: list[int] | None = None, per10: float = 3.0, key: str = "missed:fork"
) -> int:
    w = {
        "key": key, "kind": key.split(":")[0], "name": key.split(":")[1], "label": "Forks", "count": 3, "per10": per10,
        "severity": 200, "score": 5.0, "themes": ["fork"], "mode": None, "reasons": {},
        "examples": [{"game_id": g, "ply": 4, "cp_loss": 300} for g in games or []],
    }  # fmt: skip
    return int(
        CoachReportsRepo(_db(api)).add(
            f"2026-11-{day:02d}T10:00:00+00:00", "me", "You", "games", {"detail": "summary"},
            {"source": "games", "games": 10, "per10": {"blunders": 1.0}, "weaknesses": [w], "missed": [w], "whole_game": []},
            games or list(range(1000 + day * 100, 1010 + day * 100)),
        )
    )  # fmt: skip


def _game(api: Api) -> int:
    api._game_puzzles._engine = Recorder()  # type: ignore[attr-defined]
    sans = ["Nf3", "Nf6", "Ng1", "Ng8", "e4", "e5", "Qh5", "Nc6", "Bc4", "Nf6", "Qxf7#"]
    pgn = '[White "player_a"]\n[Black "opponent_b"]\n[Result "1-0"]\n\n1. Nf3 Nf6 2. Ng1 Ng8 3. e4 e5 4. Qh5 Nc6 5. Bc4 Nf6 6. Qxf7# 1-0\n'
    gid = int(api._games.import_pgn(pgn).game_id)
    api._games.set_user_color(gid, "white")
    evals = [0] * 5 + [-350] * (len(sans) - 4)
    GameAnalysisRepo(_db(api)).replace(gid, make_rows(sans, evals), "analyzed", 0.3, "Stockfish 19")
    return gid


def test_settings_preview_create_and_read_a_plan(api: Api) -> None:
    st = _ok(api.get_plan_settings())
    assert st["weeks"] == 2 and st["weekdays"] == [0, 1, 2, 3, 4] and st["has_report"] is False
    assert api.preview_plan({"weeks": 1})["ok"] is False  # no report yet
    _report(api)
    assert _ok(api.get_plan_settings())["has_report"] is True
    pv = _ok(api.preview_plan({"weeks": 1, "weekdays": [0, 2], "minutes": 20}))
    assert pv["start_date"] == "2026-01-05" and pv["replaces"] is False and pv["days"][0]["date"] == "2026-01-05"
    assert pv["days"][0]["tasks"][0]["title"]
    assert _ok(api.get_current_plan()) is None
    plan = _ok(api.create_plan({"weeks": 1, "weekdays": [0, 2], "minutes": 20}))
    assert plan["status"] == "current" and plan["source"] == "deterministic" and len(plan["days"]) == 2
    task = plan["days"][0]["tasks"][0]
    assert {"id", "type", "title", "status", "auto", "manual", "progress", "count", "minutes_spent", "carried"} <= set(
        task
    )


def test_replacing_needs_the_confirm_and_history_lists_both(api: Api) -> None:
    _report(api)
    _ok(api.create_plan({"weeks": 1}))
    refused = api.create_plan({"weeks": 2})
    assert refused["ok"] is False and "Confirm" in refused["error"]["message"]
    _ok(api.create_plan({"weeks": 2}, True))
    assert [p["status"] for p in _ok(api.list_plans())] == ["current", "replaced"]


def _today_plan(api: Api, tasks: list[Any]) -> list[dict[str, Any]]:
    draft = PlanDraft(
        PlanParams(1, (0, 1, 2, 3, 4, 5, 6), 20), tuple(Day(1, i + 1, tuple(tasks) if i == 0 else ()) for i in range(7))
    )
    today = api._plan._today()
    PlansRepo(_db(api)).add(
        draft, [today + timedelta(days=i) for i in range(7)], api._plan._now(), report_id=None, source="deterministic"
    )
    return list(_ok(api.get_current_plan())["days"][0]["tasks"])


def test_ticks_skip_and_the_today_card(api: Api) -> None:
    tid = _today_plan(api, [Task(REFLECTION, 5, "x", {"prompt": "why?"})])[0]["id"]
    _ok(api.set_plan_task_tick(tid, True))
    today = _ok(api.get_today_plan())
    assert today["day"]["tasks"][0]["status"] == "done" and today["day"]["tasks"][0]["manual"] == "done"
    assert today["day"]["is_today"] is True
    _ok(api.set_plan_task_tick(tid, False))
    _ok(api.skip_plan_task(tid, True))
    assert _ok(api.get_current_plan())["days"][0]["tasks"][0]["status"] == "skipped"
    assert api.set_plan_task_tick(99999, True)["ok"] is False


def test_each_start_action_crosses_the_bridge(api: Api) -> None:
    gid = _game(api)
    _report(api, games=[gid])
    tasks = _today_plan(
        api,
        [
            Task(
                PUZZLES, 5, "p", {"themes": [], "mode": "standard", "count": 2, "rating_min": None, "rating_max": None}
            ),
            Task(RETRY, 5, "r", {"game_id": gid}),
            Task(REVIEW, 5, "v", {"game_id": gid}),
            Task(LESSON, 5, "l", {"topic": "theme:fork"}),
            Task(REFLECTION, 5, "x", {"prompt": "why?", "game_id": gid}, "missed:fork"),
        ],
    )
    got = [_ok(api.start_plan_task(t["id"], False)) for t in tasks]
    assert [a["kind"] for a in got] == ["session", "retry", "review", "lesson", "reflection"]
    assert got[0]["session"]["session_id"] > 0 and got[0]["remaining"] == 2 and got[0]["mode"] == "standard"
    assert got[1]["game_id"] == gid and got[2]["game_id"] == gid
    assert got[3]["lesson"]["topic"] == "theme:fork" and "url" not in str(got[3]["lesson"]).lower()
    assert got[4]["prompt"] == "why?" and got[4]["plan_day_id"] is not None


def test_a_lesson_link_is_built_by_the_backend_and_ticks_the_task(api: Api, desktop: FakeDesktop) -> None:
    _report(api)
    tid = _today_plan(api, [Task(LESSON, 5, "l", {"topic": "theme:fork"})])[0]["id"]
    _ok(api.open_plan_lesson(tid, "curated:0"))
    assert any("lichess.org/practice" in u for u in desktop.urls)
    assert _ok(api.get_current_plan())["days"][0]["tasks"][0]["status"] == "done"
    assert api.open_plan_lesson(tid, "https://evil.example")["ok"] is False


def test_the_review_ply_mark_crosses_the_bridge(api: Api) -> None:
    gid = _game(api)
    assert _ok(api.mark_review_ply(gid, 0)) is False
    assert api.mark_review_ply(gid, -1)["ok"] is False


def test_journal_entries_and_the_timeline_cross_the_bridge(api: Api) -> None:
    gid = _game(api)
    note = _ok(api.add_journal_entry({"text": "A note.", "weakness_key": "missed:fork"}))
    assert note["kind"] == "note" and note["game_label"] is None
    refl = _ok(api.add_journal_entry({"text": "On a move.", "game_id": gid, "ply": 4}))
    assert refl["kind"] == "reflection" and refl["game_label"] == "player_a – opponent_b"
    assert refl["move"]  # the SAN of that move, from your own analysis
    assert [n["id"] for n in _ok(api.get_game_notes(gid))] == [refl["id"]]
    t = _ok(api.get_journal({}))
    assert {i["entry"]["id"] for i in t["items"] if i["entry"]} == {note["id"], refl["id"]}
    assert _ok(api.edit_journal_entry(note["id"], "Edited."))["text"] == "Edited."
    _ok(api.delete_journal_entry(note["id"]))
    assert api.add_journal_entry({"text": "x", "secret": 1})["ok"] is False


def test_the_daily_log_crosses_the_bridge(api: Api) -> None:
    info = api._sessions.start(FilterSpec(queue_size=5), False, "standard", False)
    api._sessions.next_puzzle(info.session_id)
    api._sessions.next_puzzle(info.session_id)
    logs = [i["log"] for i in _ok(api.get_journal({}))["items"] if i["log"]]
    assert logs[0]["overall"]["attempts"] == 1 and logs[0]["by_mode"][0]["key"] == "standard"
    assert logs[0]["by_source"][0]["label"] == "Lichess puzzles"


def test_since_last_report_crosses_the_bridge_and_the_table_follows_its_guard(api: Api) -> None:
    _report(api, day=1, per10=4.0)
    second = _report(api, day=11, per10=3.0)
    rep = _ok(api.get_coach_report(second))
    c = rep["comparison"]
    assert c["days_between"] == 10 and c["new_games"] == 10 and c["settings"] == "unknown"
    assert c["weaknesses"][0]["verdict"] == "better" and c["weaknesses"][0]["series"] == [4.0, 3.0]
    assert rep["missed"][0]["change"] == "better" and rep["missed"][0]["trend"] == -1.0


def test_the_table_says_new_and_not_enough_rather_than_worse(api: Api) -> None:
    _report(api, day=1, games=list(range(1, 11)), per10=1.0)
    few = _report(api, day=2, games=[*range(4, 11), 100, 101, 102], per10=9.0)  # 3 new games
    assert _ok(api.get_coach_report(few))["missed"][0]["change"] == "not_enough"
    fresh = _report(api, day=3, games=list(range(200, 210)), per10=1.0, key="missed:pin")
    assert _ok(api.get_coach_report(fresh))["missed"][0]["change"] == "new"


def test_a_first_report_has_no_comparison(api: Api) -> None:
    rep = _ok(api.get_coach_report(_report(api)))
    assert rep["comparison"] is None and rep["missed"][0]["change"] is None and rep["missed"][0]["trend"] is None


def test_the_plan_settings_go_through_the_validators(api: Api) -> None:
    _ok(api.set_setting("plan.params", {"weeks": 3, "weekdays": [1], "minutes": 30}))
    assert _ok(api.get_plan_settings())["weeks"] == 3
    assert api.set_setting("plan.params", {"weeks": 9})["ok"] is False
    _ok(api.set_setting("plan.carry_over", False))
    assert _ok(api.get_plan_settings())["carry_over"] is False
    assert api.set_setting("plan.carry_over", "no")["ok"] is False


def test_the_journal_preview_crosses_the_bridge(api: Api, paths: Any) -> None:
    plant_managed_install(paths)
    gid = _game(api)
    rid = _report(api, games=[gid])
    with _db(api).transaction() as conn:
        conn.execute(
            "UPDATE coach_reports SET report_json = json_set(report_json, '$.first_played', '2020-01-01') WHERE id = ?",
            (rid,),
        )
    _ok(api.add_journal_entry({"text": "On a move.", "game_id": gid, "ply": 4}))
    lines = _ok(api.get_coach_journal_preview(rid))
    assert lines == [
        {"text": "On a move.", "kind": "reflection", "game": "G1", "ply": 5, "move": lines[0]["move"], "weakness": None}
    ]
    assert lines[0]["move"]
