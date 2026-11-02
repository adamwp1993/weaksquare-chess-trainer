"""QA v0.2: the version's main flows in the real app (WebView2 attached over CDP), on the fixture DB.
Written by the independent QA pass (qa/QA-v0.2.md). Screenshots go to tests/e2e/artifacts/qa-v02-real/.

- A ratio preset saved, loaded from the Preset menu, played with Hint and Show answer; Stats show the
  attempts; preset, Stats and settings (coordinates, sounds off) survive a relaunch.
- A v1 puzzles.db: the app shows the upgrade screen, upgrades with no download, and returns to the mixer
  with the opening filter available.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tests.smoke.conftest import attach, free_port, launch_app

pytestmark = pytest.mark.smoke
ART = Path(__file__).resolve().parents[1] / "e2e" / "artifacts" / "qa-v02-real"


def shot(page, name: str) -> None:  # type: ignore[no-untyped-def]
    ART.mkdir(parents=True, exist_ok=True)
    page.wait_for_timeout(300)
    page.screenshot(path=str(ART / f"{name}.png"))


@pytest.fixture
def data_dir(tmp_path: Path, fixture_puzzles_db: Path) -> Path:
    d = tmp_path / "app-data"
    d.mkdir()
    shutil.copyfile(fixture_puzzles_db, d / "puzzles.db")
    return d


RATIO = {
    "ratios": [{"themes": ["middlegame"], "weight": 50}, {"themes": ["endgame"], "weight": 30},
               {"themes": ["fork", "pin"], "weight": 20}],
    "min_popularity": None, "min_plays": None, "exclude_solved_here": False, "queue_size": 15,
}  # fmt: skip


def test_preset_hint_answer_stats_and_settings_survive_relaunch(pw, data_dir: Path) -> None:  # type: ignore[no-untyped-def]
    app = launch_app(data_dir, free_port())
    try:
        with attach(pw, app) as page:
            page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for(timeout=30_000)
            saved = page.evaluate("s => window.pywebview.api.save_preset('Combo night', s, false)", RATIO)
            assert saved["ok"], saved
            page.reload()
            page.get_by_test_id("startup-continue").click(timeout=30_000)  # v0.3: the startup page again
            page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for(timeout=30_000)
            page.get_by_test_id("preset-select").click()
            page.get_by_role("option", name="Combo night").click()
            page.get_by_test_id("ratio-editor").wait_for()
            page.get_by_test_id("ratio-total").filter(has_text="Total 100%").wait_for()
            shot(page, "preset-loaded")

            page.get_by_role("button", name="Start").click()
            page.get_by_test_id("trainer-message").filter(has_text="Your turn").wait_for(timeout=15_000)
            page.get_by_test_id("hint-button").click()
            page.get_by_test_id("outcome").filter(has_text="Failed").wait_for()
            assert page.get_by_test_id("board").get_attribute("data-hint")
            page.get_by_test_id("answer-button").click()
            page.get_by_test_id("answer-player").wait_for()
            page.get_by_role("button", name="Forward").click()
            shot(page, "answer")
            page.get_by_test_id("next-button").click()
            page.get_by_test_id("trainer-message").filter(has_text="Your turn").wait_for(timeout=15_000)
            page.get_by_test_id("next-button").click()  # skip: a second loss
            page.get_by_test_id("stat-failed").filter(has_text="2").wait_for()

            page.get_by_role("button", name="Menu").click()
            page.get_by_role("menuitem", name="Stats").click()
            page.get_by_test_id("stats-view").filter(has_text="Puzzles played").wait_for()
            stats = page.get_by_test_id("stats-view").inner_text()
            shot(page, "stats")
            assert "2" in stats and "0%" in stats, stats
            page.keyboard.press("Escape")

            page.get_by_role("button", name="Menu").click()
            page.get_by_role("menuitem", name="Settings…").click()
            page.get_by_test_id("coordinates-switch").click()
            page.get_by_test_id("sounds-switch").click()
            page.wait_for_timeout(500)
            page.keyboard.press("Escape")
        assert app.close() == 0
    finally:
        if app.process.poll() is None:
            app.process.kill()

    app = launch_app(data_dir, free_port())
    try:
        with attach(pw, app) as page:
            page.get_by_test_id("match-count").wait_for(timeout=30_000)
            settings = page.evaluate("window.pywebview.api.get_settings()")["data"]
            assert settings["coordinates"] is False and settings["sounds"]["on"] is False, settings
            presets = page.evaluate("window.pywebview.api.list_presets()")["data"]
            assert [p["name"] for p in presets] == ["Combo night"]
            report = page.evaluate("window.pywebview.api.get_stats()")
            assert report["ok"], report
        assert app.close() == 0
    finally:
        if app.process.poll() is None:
            app.process.kill()

    import sqlite3

    with sqlite3.connect(data_dir / "user.db") as conn:
        rows = conn.execute("SELECT win, help_used, puzzle_rating FROM attempts ORDER BY id").fetchall()
    assert [(w, h) for w, h, _ in rows] == [(0, "hint"), (0, "none")]
    assert all(r is not None for _, _, r in rows)  # puzzle_rating recorded (Stats rating bands)


def test_v1_puzzles_db_is_upgraded_in_the_real_app(pw, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from tests.integration.test_puzzle_db_v2 import make_v1_db
    from weaksquare.core.clock import FixedClock

    d = tmp_path / "app-data"
    d.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    make_v1_db(d / "puzzles.db", FixedClock(), work)
    app = launch_app(d, free_port())
    try:
        with attach(pw, app) as page:
            # On the 337-puzzle fixture the upgrade can finish before Playwright attaches, so the
            # upgrade screen itself isn't asserted here (the e2e suite covers it against the mock).
            page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for(timeout=120_000)
            catalog = page.evaluate("window.pywebview.api.get_opening_catalog()")
            assert catalog["ok"] and len(catalog["data"]) > 0, catalog
            shot(page, "after-upgrade")
        assert app.close() == 0
    finally:
        if app.process.poll() is None:
            app.process.kill()
    assert not (d / "puzzles.new.db").exists()
    import sqlite3

    with sqlite3.connect(d / "puzzles.db") as conn:
        assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] >= 2
        assert conn.execute("SELECT COUNT(*) FROM openings").fetchone()[0] > 0


def test_enter_after_mouse_clicks_is_next_in_the_real_app(pw, data_dir: Path) -> None:  # type: ignore[no-untyped-def]
    """v0.2-B1 in the real window (round 2): click Start, then Hint, with the mouse; Enter must go to
    puzzle 2 of the same session, not press Start or Hint again."""
    app = launch_app(data_dir, free_port())
    try:
        with attach(pw, app) as page:
            page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for(timeout=30_000)
            page.get_by_role("button", name="Start").click()
            page.get_by_test_id("trainer-message").filter(has_text="Your turn").wait_for(timeout=15_000)
            page.keyboard.press("Enter")  # focus is still on Start: this is Skip (counts as failed)
            page.get_by_test_id("puzzle-header").filter(has_text="Puzzle 2 of").wait_for(timeout=15_000)
            # the session bar refreshes one bridge call after the new puzzle shows (QA v0.4 r2: the
            # header can render with the previous stats for a moment, so wait, don't read at once)
            page.wait_for_function(
                "() => document.querySelector('[data-testid=stat-failed]').innerText === '1'", timeout=10_000
            )
            page.get_by_test_id("trainer-message").filter(has_text="Your turn").wait_for(timeout=15_000)
            page.get_by_test_id("hint-button").click()
            page.get_by_test_id("outcome").filter(has_text="Failed").wait_for()
            page.keyboard.press("Enter")
            page.get_by_test_id("puzzle-header").filter(has_text="Puzzle 3 of").wait_for(timeout=15_000)
            page.wait_for_function(
                "() => document.querySelector('[data-testid=stat-failed]').innerText === '2'", timeout=10_000
            )
        assert app.close() == 0
    finally:
        if app.process.poll() is None:
            app.process.kill()
