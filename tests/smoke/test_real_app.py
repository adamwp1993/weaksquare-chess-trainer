"""Real-app smoke: the actual pywebview window, driven over CDP (`uv run pytest -m smoke`)."""

from __future__ import annotations

import subprocess
import sys

import pytest

from tests.smoke.conftest import RunningApp, free_port, launch_app

pytestmark = pytest.mark.smoke


def test_about_screen_shows_the_data_folder(app_page, real_app: RunningApp) -> None:  # type: ignore[no-untyped-def]
    app_page.get_by_role("button", name="Menu").click()
    app_page.get_by_role("menuitem", name="About").click()
    dialog = app_page.get_by_role("dialog")
    dialog.get_by_text("Data folder").wait_for()
    assert str(real_app.data_dir) in dialog.inner_text()
    assert "AGPL-3.0-or-later" in dialog.inner_text()


def test_first_run_shows_the_import_screen(app_page) -> None:  # type: ignore[no-untyped-def]
    app_page.get_by_test_id("import-view").wait_for()
    assert app_page.get_by_role("button", name="Download from Lichess").is_visible()


def test_no_browser_storage_and_csp_active(app_page) -> None:  # type: ignore[no-untyped-def]
    csp = app_page.evaluate(
        "() => document.querySelector('meta[http-equiv=\"Content-Security-Policy\"]')?.content ?? ''"
    )
    assert "default-src 'self'" in csp
    assert app_page.evaluate("() => localStorage.length") == 0


def test_closes_cleanly_and_releases_the_lock(real_app: RunningApp, app_page) -> None:  # type: ignore[no-untyped-def]
    assert real_app.close() == 0
    log = (real_app.data_dir / "logs" / "weaksquare.log").read_text(encoding="utf-8")
    assert "Shutting down" in log


def test_second_launch_exits_and_first_keeps_running(real_app: RunningApp, app_page) -> None:  # type: ignore[no-untyped-def]
    second = launch_app(real_app.data_dir, free_port())
    assert second.process.wait(30) == 0
    assert real_app.process.poll() is None


def test_debug_port_refused_without_dev(tmp_path) -> None:  # type: ignore[no-untyped-def]
    import os

    env = dict(os.environ, WEAKSQUARE_DATA_DIR=str(tmp_path))
    env["WEAKSQUARE_NO_DIALOGS"] = "1"
    env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = f"--remote-debugging-port={free_port()}"
    env.pop("PYTEST_CURRENT_TEST", None)
    proc = subprocess.run([sys.executable, "-m", "weaksquare"], env=env, capture_output=True, timeout=30)
    assert proc.returncode == 2
    assert b"refuses to start" in proc.stderr


@pytest.fixture
def with_puzzles(prepare_data_dir, fixture_puzzles_db):  # type: ignore[no-untyped-def]
    import shutil

    shutil.copyfile(fixture_puzzles_db, prepare_data_dir / "puzzles.db")
    return prepare_data_dir


def test_session_runs_and_attempts_persist_across_restart(with_puzzles, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from playwright.sync_api import sync_playwright

    from tests.smoke.conftest import attach

    def run(check_all_time: str | None) -> None:
        app = launch_app(with_puzzles, free_port())
        try:
            with sync_playwright() as pw, attach(pw, app) as page:
                page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for(timeout=30_000)
                if check_all_time is None:
                    page.get_by_role("button", name="Start").click()
                    page.get_by_test_id("trainer-message").filter(has_text="Your turn").wait_for()
                    page.get_by_test_id("next-button").click()  # skip = a recorded loss
                    page.get_by_test_id("stat-failed").filter(has_text="1").wait_for()
                else:
                    page.get_by_role("button", name="Start").click()
                    page.get_by_test_id("stat-all-time").filter(has_text=check_all_time).wait_for()
        finally:
            assert app.close() == 0

    run(None)
    run("0 solved, 1 failed")
