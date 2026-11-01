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
    # Regression for v0.1-B7: with a long path (this temp folder), the Open buttons stay inside the dialog.
    app_page.set_viewport_size({"width": 1000, "height": 700})
    content = dialog.bounding_box()
    for button in dialog.get_by_role("button", name="Open").all():
        box = button.bounding_box()
        assert box is not None and content is not None
        assert box["x"] + box["width"] <= content["x"] + content["width"] + 1


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


def test_session_runs_and_attempts_persist_across_restart(pw, with_puzzles) -> None:  # type: ignore[no-untyped-def]
    from tests.smoke.conftest import attach

    def run(check_all_time: str | None) -> None:
        app = launch_app(with_puzzles, free_port())
        try:
            with attach(pw, app) as page:
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


def test_dark_scheme_survives_relaunch(pw, with_puzzles) -> None:  # type: ignore[no-untyped-def]
    """FR-1.12 Done when: the color scheme is saved through the bridge and applied on relaunch."""
    from tests.smoke.conftest import attach

    def scheme(page) -> str:  # type: ignore[no-untyped-def]
        return page.evaluate("document.documentElement.getAttribute('data-mantine-color-scheme')")

    app = launch_app(with_puzzles, free_port())
    try:
        with attach(pw, app) as page:
            page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for(timeout=30_000)
            assert scheme(page) == "light"
            page.get_by_role("button", name="Menu").click()
            page.get_by_role("menuitem", name="Settings…").click()
            page.get_by_test_id("color-scheme").get_by_text("Dark", exact=True).click()
            assert scheme(page) == "dark"
            page.wait_for_timeout(300)  # the save is a bridge call
    finally:
        assert app.close() == 0

    app = launch_app(with_puzzles, free_port())
    try:
        with attach(pw, app) as page:
            page.get_by_test_id("match-count").wait_for(timeout=30_000)
            assert scheme(page) == "dark"  # from the first render on
            assert page.evaluate("[localStorage.length, sessionStorage.length]") == [0, 0]
    finally:
        assert app.close() == 0


def test_sounds_may_play_without_a_click(app_page) -> None:  # type: ignore[no-untyped-def]
    """FR-1.13: the opponent's first move plays a sound before you've clicked anything, so WebView2's
    autoplay policy must allow audio without a user gesture. Playwright's evaluate isn't a gesture."""
    app_page.get_by_test_id("import-view").wait_for(timeout=30_000)  # no puzzle DB in this data folder
    result = app_page.evaluate(
        """async () => {
            const a = new Audio('/sounds/sfx/Move.ogg');
            a.volume = 0;
            try { await a.play(); return 'played'; } catch (e) { return e.name; }
        }"""
    )
    assert result == "played"
