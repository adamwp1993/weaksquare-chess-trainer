"""QA v0.12 round 3 in the real app (WebView2 over CDP), a temp data folder, no account, no AI key, nothing sent: Swap and
the checkboxes in the real Plan tab, a reflection's question closed with its tags, the plan-day badge after a plan is
replaced, the search box, and a whole-game weakness that's gone, as Since last report really shows it."""

from __future__ import annotations

import itertools
import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import expect

from tests.smoke.conftest import attach, free_port, launch_app
from tests.smoke.test_qa_v010_real_app import MISSED_MATE, _call, _ok
from tests.smoke.test_qa_v012_round2_real_app import _engine, _pick, _ready, _report, _source

pytestmark = pytest.mark.smoke
ART = Path("tests/e2e/artifacts")
EVERY_DAY = [0, 1, 2, 3, 4, 5, 6]


def _tasks(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [t for d in plan["days"] for t in d["tasks"]]


def _open_plan(page: Any, day_id: int) -> Any:
    """The Plan tab with this day opened, as a scope: the Today card keeps a second copy of the same test ids."""
    page.get_by_test_id("nav-coach").click()
    page.get_by_test_id("coach-tab-plan").click()
    scope = page.get_by_test_id("plan-days")
    scope.wait_for()
    if not scope.get_by_test_id(f"plan-day-{day_id}").is_visible():
        scope.get_by_test_id(f"plan-day-control-{day_id}").click()
    scope.get_by_test_id(f"plan-day-{day_id}").wait_for()
    return scope


def _shot(page: Any, name: str) -> None:
    ART.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(ART / f"qa-v012-r3-{name}.png"), full_page=True)


def test_qa3_the_round_2_fixes_together_in_the_real_app(pw, tmp_path: Path, fixture_puzzles_db: Path) -> None:  # type: ignore[no-untyped-def]
    src = _source()
    data_dir = tmp_path / "app-data"
    data_dir.mkdir()
    shutil.copyfile(fixture_puzzles_db, data_dir / "puzzles.db")
    _engine(src, data_dir)
    facts: dict[str, Any] = {}
    app = launch_app(data_dir, free_port())
    try:
        with attach(pw, app) as page:
            _ready(page)
            gid = _ok(_call(page, "import_game_pgn", MISSED_MATE))["game_id"]
            _report(page, gid)
            plan = _ok(_call(page, "create_plan", {"weeks": 1, "weekdays": EVERY_DAY, "minutes": 40}))
            day = next(d for d in plan["days"] if d["is_today"])

            # Swap from the menu, in the real window, moves on each time and keeps the day's minutes.
            scope = _open_plan(page, day["id"])
            tid = day["tasks"][0]["id"]
            seen = [day["tasks"][0]["title"]]
            for _ in range(5):
                scope.get_by_test_id(f"plan-more-{tid}").click()
                before = {t["id"] for t in _tasks(_ok(_call(page, "get_current_plan")))}
                page.get_by_test_id(f"plan-swap-{tid}").click()
                scope.get_by_test_id(f"plan-task-{tid}").wait_for(state="detached")
                now = _ok(_call(page, "get_current_plan"))
                new = next(t for t in _tasks(now) if t["id"] not in before)
                tid = new["id"]
                seen.append(new["title"])
                today = next(d for d in now["days"] if d["is_today"])
                assert sum(t["minutes"] for t in today["tasks"]) == 40
                assert len({t["title"] for t in today["tasks"]}) == len(today["tasks"])
            facts["swap_chain"] = seen
            assert all(a != b for a, b in itertools.pairwise(seen)), seen
            _shot(page, "plan-after-swaps")

            # B27 and the tags: a reflection's question closed keeps your words and its tags, and Save stores them.
            refl = (
                next(t for t in today["tasks"] if t["type"] == "reflection")
                if any(t["type"] == "reflection" for t in today["tasks"])
                else None
            )
            if refl is None:
                while True:
                    other = next(t for t in today["tasks"] if t["id"] != tid)
                    scope.get_by_test_id(f"plan-more-{other['id']}").click()
                    page.get_by_test_id(f"plan-swap-{other['id']}").click()
                    scope.get_by_test_id(f"plan-task-{other['id']}").wait_for(state="detached")
                    now = _ok(_call(page, "get_current_plan"))
                    today = next(d for d in now["days"] if d["is_today"])
                    refl = next((t for t in today["tasks"] if t["type"] == "reflection"), None)
                    if refl is not None:
                        break
            scope.get_by_test_id(f"plan-start-{refl['id']}").click()
            page.get_by_test_id("journal-prompt").wait_for()
            page.get_by_test_id("journal-tag-day").locator("visible=true").wait_for()
            expect(page.get_by_test_id("journal-tag-day")).not_to_have_value("", timeout=10_000)
            page.get_by_test_id("journal-text").fill("Half a thought, findme.")
            day_tag = page.get_by_test_id("journal-tag-day").input_value()
            page.get_by_test_id("journal-prompt").get_by_role("button").click()
            expect(page.get_by_test_id("journal-prompt")).to_have_count(0)
            expect(page.get_by_test_id("journal-text")).to_have_value("Half a thought, findme.")
            expect(page.get_by_test_id("journal-tag-day")).to_have_value(day_tag)
            _shot(page, "question-closed")
            page.get_by_test_id("journal-save").click()
            entry = page.locator('[data-testid^="journal-entry-"]').filter(has_text="Half a thought")
            entry.wait_for()
            with sqlite3.connect(data_dir / "user.db") as conn:
                row = conn.execute(
                    "SELECT id, kind, plan_day_id, plan_task_id, weakness_key FROM journal_entries ORDER BY id DESC"
                ).fetchone()
            facts["after_closing"] = row
            assert row[2] == today["id"], row
            badge = page.get_by_test_id(f"journal-day-{row[0]}")
            expect(badge).to_contain_text("Plan:")
            badge_text = badge.text_content()
            status = next(t for t in _tasks(_ok(_call(page, "get_current_plan"))) if t["id"] == refl["id"])["status"]
            facts["closed_question_task_status"] = status
            facts["reflection_left_unticked_after_closing"] = status == "left"

            # A word from it, by search; and the badge after the plan is replaced.
            page.get_by_test_id("journal-search").fill("findme")
            entry.wait_for()
            assert page.get_by_test_id("journal-log").count() == 0
            page.get_by_test_id("journal-search").fill("")
            _ok(_call(page, "create_plan", {"weeks": 1, "weekdays": EVERY_DAY, "minutes": 20}, True))
            page.get_by_test_id("coach-tab-report").click()
            page.get_by_test_id("coach-tab-journal").click()
            entry.wait_for()
            expect(page.get_by_test_id(f"journal-day-{row[0]}")).to_have_text(badge_text)
            # The composer offers only the current plan's days, so the old tag can't be picked again by mistake.
            new_plan = _ok(_call(page, "get_current_plan"))
            _pick(page, "journal-tag-day")
            page.get_by_test_id("journal-tag-day").press("Escape")
            facts["badge_after_replacing"] = badge_text
            facts["new_plan_days"] = len(new_plan["days"])
            _shot(page, "badge-after-replacing")

            # A day forward: the checkbox on the row that says "Moved to the next day" is live.
            _ok(_call(page, "set_time_offset", 1))
            moved_plan = _ok(_call(page, "get_current_plan"))
            first_day = moved_plan["days"][0]
            moved = next(t for t in first_day["tasks"] if t["status"] == "carried")
            next_day = next(d for d in moved_plan["days"] if d["is_today"])
            copy = next(t for t in next_day["tasks"] if t["carried"] and t["title"] == moved["title"])
            page.get_by_test_id("coach-tab-report").click()
            scope = _open_plan(page, first_day["id"])
            box = scope.get_by_test_id(f"plan-tick-{moved['id']}")
            expect(box).to_be_enabled()
            box.click()
            scope.locator(f'[data-testid="plan-task-{moved["id"]}"][data-status="done"]').wait_for()
            after = _ok(_call(page, "get_current_plan"))
            facts["hand_tick_on_moved"] = {
                "original": next(t for t in _tasks(after) if t["id"] == moved["id"])["status"],
                "copy": next(t for t in _tasks(after) if t["id"] == copy["id"])["status"],
                "done": after["done"],
            }
            _shot(page, "hand-tick-on-moved")

            # A whole-game weakness that's gone, as the screen shows it: a real second report, its stored numbers set.
            _ok(_call(page, "set_time_offset", 0))
            page.get_by_test_id("coach-tab-report").click()  # QA v0.12-B37: Send to Coach stays on the tab you left
            _report(page, gid)
            for _ in range(300):  # the old report stays on screen while the new run works
                reports = _ok(_call(page, "list_coach_reports"))
                if len(reports) == 2:
                    break
                page.wait_for_timeout(200)
            assert len(reports) == 2
            page.wait_for_timeout(500)
            key = "time:low_clock"
    finally:
        assert app.close() == 0
    with sqlite3.connect(data_dir / "user.db") as conn:
        for rid, gone in ((reports[1]["id"], False), (reports[0]["id"], True)):
            data = json.loads(conn.execute("SELECT report_json FROM coach_reports WHERE id = ?", (rid,)).fetchone()[0])
            data["whole_game"] = [] if gone else [{
                "key": key, "kind": "time", "name": "low_clock", "label": "Mistakes under 10% of your clock",
                "count": 3, "per10": 6.0, "severity": 1, "score": 1.0, "themes": [], "mode": None, "reasons": {},
                "examples": [],
            }]  # fmt: skip
            data["measures"]["time"]["games"] = 6
            conn.execute("UPDATE coach_reports SET report_json = ? WHERE id = ?", (json.dumps(data), rid))
    app = launch_app(data_dir, free_port())
    try:
        with attach(pw, app) as page:
            _ready(page)
            page.get_by_test_id("nav-coach").click()
            page.get_by_test_id("coach-tab-report").click()
            page.get_by_test_id("since-last-report").wait_for(timeout=30_000)
            expect(page.get_by_test_id(f"since-out-{key}")).to_have_text("no longer in the top list")
            expect(page.get_by_test_id(f"since-gone-{key}")).to_be_visible()
            facts["gone_row"] = page.get_by_test_id(f"since-{key}").inner_text()
            assert "—" in facts["gone_row"] and "better" not in facts["gone_row"]
            _shot(page, "whole-game-gone")
    finally:
        ART.mkdir(parents=True, exist_ok=True)
        (ART / "qa-v012-r3-real-facts.json").write_text(json.dumps(facts, indent=2, default=str), encoding="utf-8")
        assert app.close() == 0


def test_qa3_the_user_guide_sections_step_by_step_in_the_real_app(pw, tmp_path: Path, fixture_puzzles_db: Path) -> None:  # type: ignore[no-untyped-def]
    """*Your training plan*, *Your training journal*, *Finding out what an option does*, by the guide's own words."""
    src = _source()
    data_dir = tmp_path / "app-data"
    data_dir.mkdir()
    shutil.copyfile(fixture_puzzles_db, data_dir / "puzzles.db")
    _engine(src, data_dir)
    app = launch_app(data_dir, free_port())
    try:
        with attach(pw, app) as page:
            _ready(page)
            # Step 1: "Run the Coach at least once."
            page.get_by_test_id("nav-coach").click()
            page.get_by_test_id("coach-tab-plan").click()
            expect(page.get_by_test_id("plan-no-report")).to_be_visible()
            page.get_by_test_id("coach-tab-report").click()
            gid = _ok(_call(page, "import_game_pgn", MISSED_MATE))["game_id"]
            _report(page, gid)
            # Step 2: Weeks, Minutes per day, Training days. Defaults are 2 weeks, 20 minutes, carry over on.
            page.get_by_test_id("coach-tab-plan").click()
            builder = page.get_by_test_id("plan-builder")
            for words in ("Weeks", "Minutes per day", "Training days", "Carry over missed tasks"):
                expect(builder).to_contain_text(words)
            expect(page.get_by_test_id("plan-weeks")).to_have_value("2")
            expect(page.get_by_test_id("plan-minutes")).to_have_value("20")
            for d in "56":
                page.get_by_test_id(
                    f"plan-weekday-{d}"
                ).click()  # every day, so today is a training day whenever this runs
            # Step 3: "Press Preview the plan. Nothing is saved yet."
            builder.get_by_role("button", name="Preview the plan").click()
            page.get_by_test_id("plan-preview-list").wait_for()
            assert _ok(_call(page, "get_current_plan")) is None
            # Step 4: "Press Start this plan. It starts today if today is one of your training days."
            builder.get_by_role("button", name="Start this plan").click()
            page.get_by_test_id("plan-current").wait_for()
            plan = _ok(_call(page, "get_current_plan"))
            assert plan["days"][0]["is_today"]
            # "A day has 2 to 4 tasks that add up to your minutes, and each week has one reflection."
            for week in (1, 2):
                days_of = [d for d in plan["days"] if d["week"] == week]
                assert sum(t["type"] == "reflection" for d in days_of for t in d["tasks"]) >= 1
            assert all(2 <= len(d["tasks"]) <= 4 and sum(t["minutes"] for t in d["tasks"]) == 20 for d in plan["days"])
            # "A new plan replaces the current one only when you confirm. The old one stays under Earlier plans."
            builder.get_by_role("button", name="Preview the plan").click()
            page.get_by_test_id("plan-create").click()
            dialog = page.get_by_role("dialog", name="Replace your current plan?")
            dialog.wait_for()
            dialog.get_by_role("button").last.click()
            page.get_by_test_id("plan-history").wait_for()
            expect(page.get_by_test_id("plan-history")).to_contain_text("Earlier plans")
            plan = _ok(_call(page, "get_current_plan"))
            # "Ticking in either place updates both": the Today card on the main page and the Plan tab.
            tid = plan["days"][0]["tasks"][0]["id"]
            page.get_by_test_id("nav-puzzles").click()
            card = page.get_by_test_id("today-card")
            card.get_by_test_id(f"plan-tick-{tid}").click()
            card.locator(f'[data-testid="plan-task-{tid}"][data-status="done"]').wait_for()
            page.get_by_test_id("nav-coach").click()
            page.get_by_test_id("coach-tab-plan").click()
            days = page.get_by_test_id("plan-days")
            days.locator(f'[data-testid="plan-task-{tid}"][data-status="done"]').wait_for()
            expect(page.get_by_test_id("plan-totals")).to_contain_text("1 done")
            # "a box you unticked stays unticked"
            days.get_by_test_id(f"plan-tick-{tid}").click()
            days.locator(f'[data-testid="plan-task-{tid}"][data-status="left"]').wait_for()
            # "skips a task or swaps it": the words on the menu.
            days.get_by_test_id(f"plan-more-{tid}").click()
            expect(page.get_by_test_id(f"plan-skip-{tid}").locator("visible=true")).to_have_text("Skip")
            expect(page.get_by_test_id(f"plan-swap-{tid}").locator("visible=true")).to_have_text(
                "Swap for another task"
            )
            page.keyboard.press("Escape")
            # Your training journal: Save, Edit, Delete, Search, Show, the log.
            page.get_by_test_id("coach-tab-journal").click()
            page.get_by_test_id("journal-text").fill("A word to look for.")
            page.get_by_test_id("journal-save").click()
            entry = page.locator('[data-testid^="journal-entry-"]').filter(has_text="A word to look for.")
            entry.wait_for()
            entry = page.get_by_test_id(str(entry.get_attribute("data-testid")))  # its text leaves it while you edit
            entry.get_by_role("button", name="Edit").click()
            entry.locator('[data-testid^="journal-edit-text-"]').fill("A word to look for, edited.")
            entry.get_by_role("button", name="Save").click()
            page.get_by_text("A word to look for, edited.").wait_for()
            expect(page.get_by_test_id("journal-log").first).to_contain_text("Daily log")
            page.wait_for_timeout(1000)  # QA v0.12-B38: let the journal's answers land before asking for another
            page.get_by_test_id("journal-search").fill("edited")
            expect(page.get_by_test_id("journal-log")).to_have_count(0)
            page.get_by_test_id("journal-search").fill("")
            page.get_by_test_id("journal-log").first.wait_for()
            page.get_by_test_id("journal-filter-log").click()
            page.get_by_text("A word to look for, edited.").wait_for(state="detached")
            page.get_by_test_id("journal-filter-log").click()
            edited = page.locator('[data-testid^="journal-entry-"]').filter(has_text="edited")
            edited.get_by_role("button", name="Delete").click()
            edited.wait_for(state="detached")
            # B28: a game with no date has no empty brackets in Tag a game; the same words in the Game filter.
            label = _pick(page, "journal-tag-game")
            assert "player_a" in label and "()" not in label, label
            # Finding out what an option does: hover. (Tab is in the e2e test: a window driven over CDP has no OS focus.)
            mark = page.locator('[data-option-info="journal.show"]')
            mark.hover()
            expect(page.get_by_role("tooltip")).to_contain_text("Which kinds of entry")
            page.mouse.move(0, 0)
            expect(page.get_by_role("tooltip")).to_have_count(0)
            _shot(page, "guide-walk-end")
    finally:
        assert app.close() == 0


def test_qa3_the_journal_shows_what_the_newest_search_asked_for(pw, tmp_path: Path, fixture_puzzles_db: Path) -> None:  # type: ignore[no-untyped-def]
    """The bridge answers on its own threads: an older answer must not replace a newer one, here with a long journal."""
    data_dir = tmp_path / "app-data"
    data_dir.mkdir()
    shutil.copyfile(fixture_puzzles_db, data_dir / "puzzles.db")
    app = launch_app(data_dir, free_port())
    try:
        with attach(pw, app) as page:
            _ready(page)
            for i in range(300):
                _ok(_call(page, "add_journal_entry", {"text": f"needle {i} " + "x" * 300}))
            _ok(_call(page, "add_journal_entry", {"text": "the only other word"}))
            page.get_by_test_id("nav-coach").click()
            page.get_by_test_id("coach-tab-journal").click()
            box = page.get_by_test_id("journal-search")
            entries = page.locator('[data-testid^="journal-entry-"]')
            wrong = 0
            for _ in range(12):
                box.fill("")
                box.press_sequentially("other", delay=0)  # each letter asks; n, ne, ... aren't what's wanted
                page.wait_for_timeout(1200)
                if entries.count() != 1:
                    wrong += 1
                box.fill("needle")
                box.fill("other")
                page.wait_for_timeout(1200)
                if entries.count() != 1:
                    wrong += 1
            assert wrong == 0, wrong
    finally:
        assert app.close() == 0


@pytest.mark.xfail(strict=True, reason="QA v0.12-B38: a slow, older journal answer replaces the newer one on screen")
def test_qa3_a_slow_older_answer_does_not_replace_the_search_you_asked_for(
    pw, tmp_path: Path, fixture_puzzles_db: Path
) -> None:  # type: ignore[no-untyped-def]
    """The whole journal (with its daily log) takes longer than a search. Here that's made certain by holding back the
    answer to the request without a search, as a busy PC can: the real bridge still answers it."""
    data_dir = tmp_path / "app-data"
    data_dir.mkdir()
    shutil.copyfile(fixture_puzzles_db, data_dir / "puzzles.db")
    app = launch_app(data_dir, free_port())
    try:
        with attach(pw, app) as page:
            _ready(page)
            _ok(_call(page, "add_journal_entry", {"text": "a word to find"}))
            _ok(_call(page, "add_journal_entry", {"text": "something else"}))
            page.get_by_test_id("nav-coach").click()
            page.get_by_test_id("coach-tab-journal").click()
            entries = page.locator('[data-testid^="journal-entry-"]')
            page.get_by_text("something else").wait_for()
            page.evaluate(
                """() => {
                    const real = window.pywebview.api.get_journal;
                    window.pywebview.api.get_journal = async (f) => {
                        const answer = await real(f);
                        if (!f || !f.query) await new Promise((r) => setTimeout(r, 1500));
                        return answer;
                    };
                }"""
            )
            box = page.get_by_test_id("journal-search")
            box.fill("find")
            page.get_by_test_id("journal-search").wait_for()
            expect(entries).to_have_count(1)
            box.fill("")  # the slow one
            box.fill("find")  # the one you want, answered first
            page.wait_for_timeout(2500)
            assert box.input_value() == "find"
            assert entries.count() == 1, "the screen shows the whole journal under a search for one word"
    finally:
        assert app.close() == 0
