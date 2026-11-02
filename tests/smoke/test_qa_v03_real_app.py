"""QA v0.3: the signed-out flow in the real app (WebView2 attached over CDP), on the fixture DB.
Written by the independent QA pass (qa/QA-v0.3.md). Never clicks Sign in (that would open lichess.org).
Screenshots go to tests/e2e/artifacts/qa-v03-real/.
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from tests.smoke.conftest import attach, free_port, launch_app

pytestmark = pytest.mark.smoke
ART = Path(__file__).resolve().parents[1] / "e2e" / "artifacts" / "qa-v03-real"


def shot(page, name: str) -> None:  # type: ignore[no-untyped-def]
    ART.mkdir(parents=True, exist_ok=True)
    page.wait_for_timeout(300)
    page.screenshot(path=str(ART / f"{name}.png"))


def test_signed_out_solve_is_queued_with_its_angle(pw, tmp_path: Path, fixture_puzzles_db: Path) -> None:  # type: ignore[no-untyped-def]
    data_dir = tmp_path / "app-data"
    data_dir.mkdir()
    shutil.copyfile(fixture_puzzles_db, data_dir / "puzzles.db")
    app = launch_app(data_dir, free_port())
    try:
        with attach(pw, app) as page:
            page.reload()  # the startup page shows again on every load
            page.get_by_test_id("startup").wait_for(timeout=30_000)
            assert "Not signed in" in page.get_by_test_id("startup-status").inner_text()
            shot(page, "startup-signed-out")
            page.get_by_test_id("startup-continue").click()
            page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for(timeout=30_000)
            page.get_by_test_id("more-filters").click()
            box = page.get_by_test_id("exclude-played")
            box.wait_for()
            assert box.is_disabled()  # signed out, no history imported
            page.get_by_test_id("more-filters").click()
            page.get_by_label("Puzzles").fill("1")
            page.get_by_role("button", name="Start").click()
            page.get_by_test_id("hint-button").click(timeout=30_000)  # help = a loss, decided at once
            page.get_by_test_id("outcome").filter(has_text="Failed").wait_for()
            page.get_by_test_id("rating-change").filter(has_text="Will sync later").wait_for()
            page.get_by_test_id("sync-chip").filter(has_text="1 solve waiting to sync").wait_for()
            assert page.get_by_test_id("header-rating").count() == 0
            shot(page, "signed-out-result")
        assert app.close() == 0
    finally:
        if app.process.poll() is None:
            app.process.kill()
    conn = sqlite3.connect(data_dir / "user.db")
    try:
        rows = conn.execute("SELECT rated, angle, sync_status, sync_account, help_used FROM attempts").fetchall()
    finally:
        conn.close()
    assert rows == [(1, "mix", "pending", None, "hint")]
    log = (data_dir / "logs" / "weaksquare.log").read_text(encoding="utf-8")
    assert "lichess.org/api" not in log
