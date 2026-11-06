"""QA v0.12 round 2 in the real app (WebView2 over CDP), a temp data folder, no account, no AI key, nothing sent: the
composer's tags and the Game filter through the real bridge, the journal's link, a hand tick in the log, a long word, a
database at 0011, and the plan with no puzzle database through Start."""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import expect

from tests.smoke.conftest import attach, free_port, launch_app
from tests.smoke.test_qa_v010_real_app import MISSED_MATE, _call, _ok
from tests.smoke.test_qa_v012_real_app import _open_plan
from weaksquare import config
from weaksquare.adapters.db.migrate import migrate
from weaksquare.core.clock import FixedClock

pytestmark = pytest.mark.smoke
ART = Path("tests/e2e/artifacts")
EVERY_DAY = [0, 1, 2, 3, 4, 5, 6]


def _ready(page: Any) -> None:
    page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for(timeout=30_000)


def _engine(src: Path, data_dir: Path) -> None:
    shutil.copytree(src, data_dir / "engines" / "sf_19")


def _source() -> Path:
    src = config.default_data_dir(dev=True) / "engines" / "sf_19"
    if not (src / "stockfish.exe").is_file() or not (src / "install.json").is_file():
        pytest.skip(f"no managed Stockfish in {src}")
    return src


def _report(page: Any, gid: int) -> None:
    _ok(_call(page, "set_game_color", gid, "white"))
    for _ in range(100):
        if _ok(_call(page, "get_engine_status"))["state"] == "ready":
            break
        page.wait_for_timeout(200)
    page.get_by_test_id("nav-games").click()
    page.get_by_test_id(f"game-row-{gid}").get_by_role("checkbox").check()
    page.get_by_test_id("send-to-coach").click()
    page.get_by_test_id("coach-sent").filter(has_text="1 game sent").wait_for()
    page.get_by_test_id("coach-run").click()
    page.get_by_test_id("coach-report").wait_for(timeout=180_000)


def _pick(page: Any, testid: str, index: int = 0) -> str:
    page.get_by_test_id(testid).click()
    option = page.get_by_role("option").locator("visible=true").nth(index)
    text = str(option.inner_text())
    option.click()
    return text


def _rows(data_dir: Path) -> list[Any]:
    with sqlite3.connect(data_dir / "user.db") as conn:
        return conn.execute(
            "SELECT text, kind, game_id, ply, plan_day_id, plan_task_id FROM journal_entries ORDER BY id"
        ).fetchall()


def test_qa2_the_new_tags_filter_link_and_hand_tick_in_the_real_app(
    pw, tmp_path: Path, fixture_puzzles_db: Path
) -> None:  # type: ignore[no-untyped-def]
    src = _source()
    data_dir = tmp_path / "app-data"
    data_dir.mkdir()
    shutil.copyfile(fixture_puzzles_db, data_dir / "puzzles.db")
    _engine(src, data_dir)
    ART.mkdir(parents=True, exist_ok=True)
    app = launch_app(data_dir, free_port())
    try:
        with attach(pw, app) as page:
            _ready(page)
            gid = _ok(_call(page, "import_game_pgn", MISSED_MATE))["game_id"]
            _report(page, gid)
            report = _ok(_call(page, "list_coach_reports"))[0]["id"]
            plan = _ok(_call(page, "create_plan", {"weeks": 1, "weekdays": EVERY_DAY, "minutes": 40}))
            today = next(d for d in plan["days"] if d["is_today"])

            # The composer's tags, as you'd use them.
            page.get_by_test_id("coach-tab-journal").click()
            page.get_by_test_id("journal-tab").wait_for()
            label = _pick(page, "journal-tag-game")
            assert "player_a" in label and "opponent_b" in label
            day_label = _pick(page, "journal-tag-day")
            assert "Week 1" in day_label
            page.get_by_test_id("journal-text").fill("A note with tags, https://example.org/x in it.")
            page.screenshot(path=str(ART / "qa-v012-r2-real-composer.png"), full_page=True)
            page.get_by_test_id("journal-save").click()
            entry = page.locator('[data-testid^="journal-entry-"]').filter(has_text="A note with tags")
            entry.wait_for()
            row = _rows(data_dir)[-1]
            assert row[1] == "reflection" and row[2] == gid and row[3] is None
            assert row[4] == plan["days"][0]["id"] and row[5] is None

            # Another note, on nothing: the Game filter tells them apart, and hides the log.
            page.get_by_test_id("journal-text").fill("A note on nothing.")
            page.get_by_test_id("journal-save").click()
            page.get_by_text("A note on nothing.").wait_for()
            page.get_by_test_id("journal-log").first.wait_for()
            assert _pick(page, "journal-filter-game").startswith("player_a")
            page.get_by_text("A note on nothing.").wait_for(state="detached")
            entry.wait_for()
            assert page.get_by_test_id("journal-log").count() == 0
            assert page.get_by_test_id("journal-older").count() == 0
            page.screenshot(path=str(ART / "qa-v012-r2-real-filter.png"), full_page=True)
            page.get_by_test_id("journal-filter-game").locator(
                "xpath=ancestor::*[contains(@class,'InputWrapper-root')]"
            ).locator("button").last.click()
            page.get_by_text("A note on nothing.").wait_for()

            # What the tags send: the preview in the real panel, and the prompt's own lines through the bridge.
            preview = _ok(_call(page, "get_coach_journal_preview", report))
            tagged = next(p for p in preview if p["text"].startswith("A note with tags"))
            assert tagged["game"] == "G1" and "example.org" not in tagged["text"]
            blob = json.dumps(preview)
            assert "player_a" not in blob and "opponent_b" not in blob and "plan_day" not in blob

            # B3: a note on a move opens that very move, also the first move of the game.
            for ply in (0, 4):
                page.get_by_test_id("nav-games").click()
                page.get_by_test_id(f"game-row-{gid}").get_by_role("button", name="Review", exact=True).click()
                page.get_by_test_id(f"move-{ply}").click()
                page.get_by_test_id("game-note-add").click()
                page.get_by_test_id("game-note-text").fill(f"Note on ply {ply}.")
                page.get_by_test_id("game-note-save").click()
                page.get_by_test_id(f"move-note-{ply}").wait_for()
                page.get_by_test_id("review-back").click()
                page.get_by_test_id("nav-coach").click()
                page.get_by_test_id("coach-tab-journal").click()
                note = page.locator('[data-testid^="journal-entry-"]').filter(has_text=f"Note on ply {ply}.")
                note.locator('[data-testid^="journal-open-"]').click()
                page.get_by_test_id(f"move-note-{ply}").wait_for()
                page.wait_for_timeout(300)
                filled = page.locator('[data-testid^="move-"][data-variant="filled"]')
                assert filled.first.get_attribute("data-testid") == f"move-{ply}"
                page.get_by_test_id("review-back").click()

            # B14: one long word.
            page.get_by_test_id("nav-coach").click()
            page.get_by_test_id("coach-tab-journal").click()
            page.get_by_test_id("journal-text").fill("w" * 5000)
            page.get_by_test_id("journal-save").click()
            page.get_by_text("wwwww").first.wait_for()
            assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")
            page.screenshot(path=str(ART / "qa-v012-r2-real-long-word.png"), full_page=True)

            # B6: a hand tick and untick, in the real log.
            log = lambda: next(  # noqa: E731
                (
                    i["log"]
                    for i in _ok(_call(page, "get_journal", {}))["items"]
                    if i["log"] and i["date"] == today["date"]
                ),
                None,
            )
            before = (log() or {}).get("plan_tasks_done", 0)
            page.get_by_test_id("coach-tab-plan").click()
            t = today["tasks"][-1]
            box = page.get_by_test_id(f"plan-tick-{t['id']}").locator("visible=true")
            box.click()
            page.locator(f'[data-testid="plan-task-{t["id"]}"][data-status="done"]').first.wait_for()
            assert log()["plan_tasks_done"] == before + 1
            box.click()
            page.locator(f'[data-testid="plan-task-{t["id"]}"][data-status="left"]').first.wait_for()
            assert (log() or {}).get("plan_tasks_done", 0) == before

            # A reflection task from the real plan: its day comes filled in, and saving ticks it.
            all_tasks = [(d, x) for d in plan["days"] for x in d["tasks"]]
            found = next(((d, x) for d, x in all_tasks if x["type"] == "reflection"), None)
            if found is not None:
                d, r = found
                if not d["is_today"]:
                    _open_plan(page, d["id"])
                page.get_by_test_id(f"plan-start-{r['id']}").locator("visible=true").click()
                page.get_by_test_id("journal-prompt").wait_for()
                # The task's day comes filled in, once the day list has loaded.
                expect(page.get_by_test_id("journal-tag-day")).not_to_have_value("", timeout=10_000)
                page.get_by_test_id("journal-text").fill("From the reflection task.")
                page.get_by_test_id("journal-save").click()
                page.get_by_text("From the reflection task.").first.wait_for()
                row = _rows(data_dir)[-1]
                assert row[4] == d["id"] and row[5] == r["id"]
                now = next(
                    x for dd in _ok(_call(page, "get_current_plan"))["days"] for x in dd["tasks"] if x["id"] == r["id"]
                )
                assert now["status"] == "done"
    finally:
        assert app.close() == 0


@pytest.mark.parametrize("level", ["0011"])
def test_qa2_a_database_at_0011_opens_in_the_real_app(pw, tmp_path: Path, fixture_puzzles_db: Path, level: str) -> None:  # type: ignore[no-untyped-def]
    data_dir = tmp_path / "app-data"
    data_dir.mkdir()
    shutil.copyfile(fixture_puzzles_db, data_dir / "puzzles.db")
    with tempfile.TemporaryDirectory() as td:
        old = Path(td)
        for f in sorted((config.MIGRATIONS_DIR / "user").glob("00*.sql")):
            if f.name[:4] <= level:
                shutil.copy(f, old / f.name)
        migrate(data_dir / "user.db", old, FixedClock())
    now = "2020-01-01T10:00:00+00:00"
    with sqlite3.connect(data_dir / "user.db") as conn:
        assert "manual_at" not in {r[1] for r in conn.execute("PRAGMA table_info(plan_tasks)")}
        pid = conn.execute(
            "INSERT INTO training_plans (created_at, source, weeks, weekdays_json, minutes_per_day, start_date, status)"
            " VALUES (?, 'deterministic', 1, ?, 20, '2020-01-01', 'current')",
            (now, json.dumps(EVERY_DAY)),
        ).lastrowid
        day = conn.execute(
            "INSERT INTO plan_days (plan_id, week, position, date) VALUES (?,1,1,'2020-01-01')", (pid,)
        ).lastrowid
        conn.execute(
            "INSERT INTO plan_tasks (day_id, position, type, minutes, title, params_json, manual_state)"
            " VALUES (?,1,'reflection',10,'t','{\"prompt\": \"x\"}','done')",
            (day,),
        )
    app = launch_app(data_dir, free_port())
    try:
        with attach(pw, app) as page:
            _ready(page)
            plan = _ok(_call(page, "get_current_plan"))
            assert plan["done"] == 1
            page.get_by_test_id("nav-coach").click()
            page.get_by_test_id("coach-tab-journal").click()
            page.get_by_test_id("journal-tab").wait_for()
    finally:
        assert app.close() == 0
    with sqlite3.connect(data_dir / "user.db") as conn:
        assert "manual_at" in {r[1] for r in conn.execute("PRAGMA table_info(plan_tasks)")}


def test_qa2_the_plan_with_no_puzzle_database_through_start_in_the_real_app(pw, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """With no puzzle DB the window shows only *Get the puzzle database*: no nav, no Coach. So the plan's no-database
    answers can only be reached through the bridge. Here, that real bridge in the real window."""
    data_dir = tmp_path / "app-data"
    data_dir.mkdir()
    migrate(data_dir / "user.db", config.MIGRATIONS_DIR / "user", FixedClock())
    weak = {"key": "missed:fork", "label": "Missed: Fork", "kind": "missed", "name": "fork", "per10": 6.0, "count": 3,
            "severity": 300, "score": 1.0, "themes": ["fork"], "mode": None, "reasons": {}, "examples": []}  # fmt: skip
    report = {"source": "games", "games": 10, "weaknesses": [weak], "missed": [weak], "whole_game": []}
    with sqlite3.connect(data_dir / "user.db") as conn:
        conn.execute(
            "INSERT INTO coach_reports (created_at, subject, subject_label, source_kind, params_json, report_json,"
            " game_ids_json) VALUES ('2026-01-01T10:00:00+00:00','me','You','games','{}',?, '[]')",
            (json.dumps(report),),
        )
    ART.mkdir(parents=True, exist_ok=True)
    app = launch_app(data_dir, free_port())
    try:
        with attach(pw, app) as page:
            page.get_by_text("Get the puzzle database").wait_for(timeout=30_000)
            assert page.get_by_test_id("nav-coach").count() == 0
            page.screenshot(path=str(ART / "qa-v012-r2-real-nodb-start.png"), full_page=True)
            assert _ok(_call(page, "get_puzzle_db_status"))["installed"] is False
            assert _ok(_call(page, "preview_plan", {"weeks": 1, "weekdays": EVERY_DAY, "minutes": 40}))["days"]
            plan = _ok(_call(page, "create_plan", {"weeks": 1, "weekdays": EVERY_DAY, "minutes": 40}))
            assert _ok(_call(page, "get_today_plan")) is not None
            tasks = [t for d in plan["days"] for t in d["tasks"]]
            puzzle = next(t for t in tasks if t["type"] == "puzzles")
            got = _call(page, "start_plan_task", puzzle["id"], False)
            assert got["ok"] is False and "puzzle database" in got["error"]["message"], got
            assert _ok(_call(page, "swap_plan_task", puzzle["id"]))
    finally:
        assert app.close() == 0
