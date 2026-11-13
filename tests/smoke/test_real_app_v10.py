"""v1.0 in the real app (WebView2 over CDP), on temp data folders:
- a fresh data folder (no puzzle database, no data) opens on the first-run wizard, not the startup page (NFR-8);
- Start fresh is remembered: closing and reopening comes back at the puzzle-database step, decided from what's
  installed (core/setup.py);
- a first launch whose puzzle database setup.py already imported still shows it (Restore must be offered), and it
  finishes into the app;
- the checkpoint backfill (v1.0b) finishes at launch on a folder with nothing to replay."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from tests.smoke.conftest import attach, finish_wizard, free_port, launch_app

pytestmark = pytest.mark.smoke


def _setting(db: Path, key: str) -> str | None:
    conn = sqlite3.connect(db)
    try:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    finally:
        conn.close()
    return None if row is None else str(row[0])


def test_a_fresh_data_folder_opens_on_the_wizard_and_resumes_after_a_restart(pw, prepare_data_dir: Path) -> None:  # type: ignore[no-untyped-def]
    app = launch_app(prepare_data_dir, free_port())
    try:
        with attach(pw, app, keep_wizard=True) as page:
            wizard = page.get_by_test_id("wizard")
            assert wizard.get_attribute("data-step") == "welcome"
            assert page.get_by_test_id("startup").count() == 0
            page.get_by_test_id("wizard-fresh").click()
            page.get_by_test_id("wizard-puzzles").wait_for(timeout=10_000)
        assert app.close() == 0
    finally:
        if app.process.poll() is None:
            app.process.kill()
    assert _setting(prepare_data_dir / "user.db", "setup.choice") == '"fresh"'
    assert _setting(prepare_data_dir / "user.db", "checkpoints.backfill_version") == "1"  # nothing to replay: done

    again = launch_app(prepare_data_dir, free_port())
    try:
        with attach(pw, again, keep_wizard=True) as page:
            page.get_by_test_id("wizard-puzzles").wait_for(timeout=30_000)  # resumed at the same step
            assert page.get_by_test_id("wizard").get_attribute("data-step") == "puzzles"
        assert again.close() == 0
    finally:
        if again.process.poll() is None:
            again.process.kill()


def test_after_setup_imported_the_puzzles_it_still_offers_restore_then_opens_the_app(  # type: ignore[no-untyped-def]
    pw, prepare_data_dir: Path, fixture_puzzles_db: Path
) -> None:
    shutil.copyfile(fixture_puzzles_db, prepare_data_dir / "puzzles.db")
    app = launch_app(prepare_data_dir, free_port())
    try:
        with attach(pw, app, keep_wizard=True) as page:
            assert page.get_by_test_id("wizard").get_attribute("data-step") == "welcome"
            assert page.get_by_test_id("wizard-restore").is_visible()
            finish_wizard(page)
            page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for(timeout=30_000)
        assert app.close() == 0
    finally:
        if app.process.poll() is None:
            app.process.kill()
    assert _setting(prepare_data_dir / "user.db", "setup.finished") == "true"

    again = launch_app(prepare_data_dir, free_port())
    try:
        with attach(pw, again) as page:  # finished: the startup page again, as on every later launch
            page.get_by_test_id("match-count").wait_for(timeout=30_000)
            assert page.get_by_test_id("wizard").count() == 0
        assert again.close() == 0
    finally:
        if again.process.poll() is None:
            again.process.kill()
