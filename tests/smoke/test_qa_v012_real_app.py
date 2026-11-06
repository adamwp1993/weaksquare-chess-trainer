"""QA v0.12 in the real app (WebView2 over CDP), a temp data folder, no account, no AI key, nothing sent.

Real Stockfish copied in (read-only source), a real game, a real Coach run. Then the version's main flow through the
real window: build a plan in the Plan tab, solve a puzzle task from the Today card (the Mixer's settings stay
byte-identical), review a game with best moves hidden, retry, write a reflection, add a note on a move, follow the
journal's link back, move a day forward with the dev time offset (carry-over), run the Coach again, read Since last
report, tick Include my journal and read its preview, restart, and check it all stayed. What it finds is kept in
`tests/e2e/artifacts/qa-v012-real-facts.json`.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from tests.smoke.conftest import attach, free_port, launch_app
from tests.smoke.test_qa_v010_real_app import MISSED_MATE, _call, _ok
from weaksquare import config

pytestmark = pytest.mark.smoke
ART = Path("tests/e2e/artifacts")


def _ready(page: Any) -> None:
    page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for(timeout=30_000)


def _snapshot(data_dir: Path) -> tuple[list[Any], list[Any]]:
    with sqlite3.connect(data_dir / "user.db") as conn:
        return (
            conn.execute("SELECT key, value FROM settings WHERE key NOT LIKE 'plan.%' ORDER BY key").fetchall(),
            conn.execute("SELECT * FROM presets ORDER BY 1").fetchall(),
        )


def _plan(page: Any) -> Any:
    return _ok(_call(page, "get_current_plan"))


def _find(plan: Any, kind: str) -> tuple[Any, Any] | None:
    for day in plan["days"]:
        for t in day["tasks"]:
            if t["type"] == kind:
                return day, t
    return None


def _status(page: Any, tid: int) -> str:
    for day in _plan(page)["days"]:
        for t in day["tasks"]:
            if t["id"] == tid:
                return str(t["status"])
    raise AssertionError(tid)


def _open_plan(page: Any, day_id: int) -> None:
    """The Plan tab, with this day opened."""
    page.get_by_test_id("nav-coach").click()
    page.get_by_test_id("coach-tab-plan").click()
    page.get_by_test_id("plan-current").wait_for()
    if not page.get_by_test_id(f"plan-day-{day_id}").is_visible():
        page.get_by_test_id(f"plan-day-control-{day_id}").click()
        page.get_by_test_id(f"plan-day-{day_id}").wait_for()


def test_qa_v012_the_main_flow_in_the_real_app(pw, tmp_path: Path, fixture_puzzles_db: Path) -> None:  # type: ignore[no-untyped-def]
    src = config.default_data_dir(dev=True) / "engines" / "sf_19"
    if not (src / "stockfish.exe").is_file() or not (src / "install.json").is_file():
        pytest.skip(f"no managed Stockfish in {src}")
    data_dir = tmp_path / "app-data"
    data_dir.mkdir()
    shutil.copyfile(fixture_puzzles_db, data_dir / "puzzles.db")
    shutil.copytree(src, data_dir / "engines" / "sf_19")
    ART.mkdir(parents=True, exist_ok=True)
    facts: dict[str, Any] = {}
    app = launch_app(data_dir, free_port())
    try:
        with attach(pw, app) as page:
            _ready(page)
            assert page.get_by_test_id("today-card").count() == 0  # no plan, no card
            gid = _ok(_call(page, "import_game_pgn", MISSED_MATE))["game_id"]
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
            first_report = _ok(_call(page, "list_coach_reports"))[0]["id"]
            assert page.get_by_test_id("since-last-report").count() == 0  # a first report has nothing to compare

            # Your own filters and mode, and a preset, before the plan.
            _ok(_call(page, "save_preset", "Mine", {"themes": ["pin"], "rating_min": 800, "rating_max": 900}))

            # Build it in the Plan tab, on every weekday so today is a training day.
            page.get_by_test_id("coach-tab-plan").click()
            page.get_by_test_id("plan-tab").wait_for()
            for d in "56":
                page.get_by_test_id(f"plan-weekday-{d}").click()  # Mon-Fri are on by default
            page.get_by_test_id("plan-minutes").fill("50")
            page.get_by_test_id("plan-preview").click()
            page.get_by_test_id("plan-preview-list").wait_for()
            page.screenshot(path=str(ART / "qa-v012-real-plan-preview.png"), full_page=True)
            assert _ok(_call(page, "get_current_plan")) is None  # a preview saves nothing
            page.get_by_test_id("plan-create").click()
            page.get_by_test_id("plan-current").wait_for()
            plan = _plan(page)
            assert len(plan["days"]) == 14
            assert all(sum(t["minutes"] for t in d["tasks"]) == 50 for d in plan["days"])
            facts["types"] = sorted({t["type"] for d in plan["days"] for t in d["tasks"]})
            page.screenshot(path=str(ART / "qa-v012-real-plan.png"), full_page=True)
            before = _snapshot(data_dir)

            # A puzzle task from the Today card, played in the real trainer.
            page.get_by_test_id("nav-puzzles").click()
            card = page.get_by_test_id("today-card")
            card.wait_for()
            page.screenshot(path=str(ART / "qa-v012-real-today.png"), full_page=True)
            found = _find(plan, "puzzles")
            assert found is not None
            day, task = found
            if not day["is_today"]:
                _open_plan(page, day["id"])
            page.get_by_test_id(f"plan-start-{task['id']}").locator("visible=true").click()
            page.get_by_test_id("plan-session-banner").wait_for(timeout=10_000)
            page.screenshot(path=str(ART / "qa-v012-real-plan-session.png"), full_page=True)
            for _ in range(600):  # Hint, Show answer, Next, as a person would; a button that's busy is tried again
                if _status(page, task["id"]) == "done":
                    break
                if page.get_by_test_id("hint-button").is_enabled():
                    page.get_by_test_id("hint-button").click()
                elif (
                    page.get_by_test_id("answer-button").is_enabled() and page.get_by_text("The solution").count() == 0
                ):
                    page.get_by_test_id("answer-button").click()
                elif page.get_by_test_id("next-button").is_enabled():
                    page.get_by_test_id("next-button").click()
                page.wait_for_timeout(150)
            assert _status(page, task["id"]) == "done"
            assert _snapshot(data_dir) == before  # mixer.filters, trainer.mode, presets, everything
            page.get_by_test_id("today-count").wait_for()
            facts["today_count"] = page.get_by_test_id("today-count").inner_text()

            # A review task: opens with best moves hidden, your setting untouched; visits tick it.
            found = _find(plan, "review")
            assert found is not None
            day, task = found
            _open_plan(page, day["id"])
            page.get_by_test_id(f"plan-start-{task['id']}").click()
            page.get_by_test_id("review-view").wait_for()
            page.get_by_test_id("move-list").wait_for(timeout=30_000)
            assert not page.get_by_test_id("review-show-best").is_checked()
            page.get_by_test_id("review-show-best").check(force=True)  # on for this task only
            page.get_by_test_id("review-show-best").uncheck(force=True)
            rev = _ok(_call(page, "get_review", gid))
            assert _status(page, task["id"]) == "left"
            for ply in [*rev["key_moments"], len(rev["moves"]) - 1]:
                page.get_by_test_id(f"move-{ply}").click()
                page.wait_for_timeout(150)
            page.wait_for_timeout(300)
            assert _status(page, task["id"]) == "done"
            assert _snapshot(data_dir) == before  # review.show_best too

            # A note on a move: the marker, then the journal's link back.
            ply = rev["key_moments"][0]
            page.get_by_test_id(f"move-{ply}").click()
            page.get_by_test_id("game-note-add").click()
            page.get_by_test_id("game-note-text").fill("I rushed this. See https://example.org/x")
            page.get_by_test_id("game-note-save").click()
            page.get_by_test_id(f"move-note-{ply}").wait_for()
            page.screenshot(path=str(ART / "qa-v012-real-review-note.png"), full_page=True)
            page.get_by_test_id("review-back").click()
            page.get_by_test_id("coach-tab-journal").click()
            page.get_by_test_id("journal-tab").wait_for()
            page.screenshot(path=str(ART / "qa-v012-real-journal.png"), full_page=True)
            page.locator('[data-testid^="journal-open-"]').first.click()
            page.get_by_test_id(f"move-note-{ply}").wait_for()
            page.wait_for_timeout(200)
            filled = page.locator('[data-testid^="move-"][data-variant="filled"]')
            facts["note_ply"] = ply
            facts["journal_link_shows"] = filled.first.get_attribute("data-testid") if filled.count() else None
            page.get_by_test_id("review-back").click()

            # A Retry task through the real path.
            found = _find(plan, "retry")
            if found is not None:
                day, task = found
                _open_plan(page, day["id"])
                page.get_by_test_id(f"plan-start-{task['id']}").click()
                page.get_by_test_id("retry-mode").wait_for(timeout=30_000)
                for p in rev["retry_plies"]:
                    _ok(_call(page, "retry_move", gid, p, rev["moves"][p]["best_move"] or rev["moves"][p]["uci"]))
                assert _status(page, task["id"]) == "done"
                page.get_by_test_id("retry-exit").click()
                page.get_by_test_id("review-back").click()

            # A reflection: Start opens the journal with the question; saving ticks it.
            found = _find(plan, "reflection")
            assert found is not None
            day, task = found
            _open_plan(page, day["id"])
            page.get_by_test_id(f"plan-start-{task['id']}").click()
            page.get_by_test_id("journal-prompt").wait_for()
            page.get_by_test_id("journal-text").fill("My reflection from the task.")
            page.get_by_test_id("journal-save").click()
            page.get_by_text("My reflection from the task.").first.wait_for()
            assert _status(page, task["id"]) == "done"
            assert _snapshot(data_dir) == before

            # A hand tick and the totals, and the Plan tab against the Today card.
            today = _ok(_call(page, "get_today_plan"))
            left = [t for t in today["day"]["tasks"] if t["status"] == "left"]
            if left:
                _open_plan(page, today["day"]["id"])
                page.get_by_test_id(f"plan-tick-{left[0]['id']}").click(force=True)
                page.wait_for_timeout(300)
                assert _status(page, left[0]["id"]) == "done"
            plan = _plan(page)
            facts["totals"] = page.get_by_test_id("plan-totals").first.inner_text()
            assert f"{plan['done']} done" in facts["totals"]

            # Daily log against Stats: everything so far is on one day.
            log = next(i["log"] for i in _ok(_call(page, "get_journal", {}))["items"] if i["log"])
            stats = _ok(_call(page, "get_stats"))
            assert log["overall"]["attempts"] == stats["overall"]["attempts"]
            assert log["overall"]["solved"] == stats["overall"]["solved"]
            assert log["games_reviewed"] >= 1 and log["games_analyzed"] == 1 and log["coach_runs"]
            facts["log"] = {
                k: log[k] for k in ("games_synced", "games_analyzed", "games_reviewed", "retries", "plan_tasks_done")
            }

            # The next day, by the dev time offset: unfinished tasks carry, the Today card moves.
            left_day1 = [t["title"] for t in plan["days"][0]["tasks"] if t["status"] == "left"]
            _ok(_call(page, "set_time_offset", 1))
            page.get_by_test_id("nav-puzzles").click()
            card.wait_for()
            today2 = _ok(_call(page, "get_today_plan"))
            assert today2["day"]["position"] == 2
            facts["carried"] = [t["title"] for t in today2["day"]["tasks"] if t["carried"]]
            assert set(facts["carried"]) <= set(left_day1)
            page.screenshot(path=str(ART / "qa-v012-real-today-day2.png"), full_page=True)

            # The Coach again: Since last report, with its guard, and the journal's preview.
            page.get_by_test_id("nav-coach").click()
            page.get_by_test_id("coach-tab-report").click()
            page.get_by_test_id("coach-run").click()
            for _ in range(600):
                second = _ok(_call(page, "list_coach_reports"))[0]["id"]
                if second != first_report:
                    break
                page.wait_for_timeout(300)
            assert second != first_report
            page.get_by_test_id("coach-report").wait_for()
            comparison = _ok(_call(page, "get_coach_report", second))["comparison"]
            assert comparison["earlier_id"] == first_report and comparison["settings"] == "same"
            assert (
                comparison["days_between"] == 1
                and comparison["new_games"] == 0
                and comparison["enough_new_games"] is False
            )
            assert all(w["verdict"] == "not_enough" for w in comparison["weaknesses"])
            page.screenshot(path=str(ART / "qa-v012-real-since-last.png"), full_page=True)
            box = page.get_by_test_id("coach-ai-journal")
            box.scroll_into_view_if_needed()
            assert not box.is_checked()
            box.check()
            page.get_by_test_id("coach-journal-warning").wait_for()
            lines = page.get_by_test_id("coach-journal-line")
            lines.first.wait_for()
            text = " ".join(lines.all_inner_texts())
            assert "I rushed this. See [link removed]" in text and "example.org" not in text
            # This fixture game has no date, so the report has no first day: only entries tagged to its game go.
            assert "My reflection from the task." not in text
            page.screenshot(path=str(ART / "qa-v012-real-journal-preview.png"))
            page.get_by_test_id("coach-notes-ok").click()
            q = _ok(_call(page, "get_coach_ai_quote", second, {"include_journal": True}))
            assert q["quote"]["state"] not in ("ok", "cached")  # no key: blocked, nothing sent
            done_before_restart = _plan(page)["done"]
    finally:
        assert app.close() == 0
    with sqlite3.connect(data_dir / "user.db") as conn:
        blob = repr(conn.execute("SELECT key, value FROM settings").fetchall())
        assert "include_journal" not in blob
        assert conn.execute("SELECT COUNT(*) FROM llm_usage").fetchone()[0] == 0
    (ART / "qa-v012-real-facts.json").write_text(json.dumps(facts, indent=1), encoding="utf-8")

    app = launch_app(data_dir, free_port())
    try:
        with attach(pw, app) as page:
            _ready(page)
            page.get_by_test_id("today-card").wait_for()
            assert _plan(page)["done"] == done_before_restart
            page.get_by_test_id("nav-coach").click()
            page.get_by_test_id("coach-tab-journal").click()
            page.get_by_text("My reflection from the task.").first.wait_for()
            page.get_by_test_id("journal-log").first.wait_for()
            page.get_by_test_id("coach-tab-report").click()
            box = page.get_by_test_id("coach-ai-journal")
            if box.count():
                assert not box.is_checked()  # off every time (FR-10.71)
    finally:
        assert app.close() == 0
