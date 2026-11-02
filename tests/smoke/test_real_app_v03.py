"""v0.3 in the real app: a test launch starts signed out (its own keyring entry), the startup page
shows, and nothing about the account crosses the bridge except status (SR-1)."""

from __future__ import annotations

import pytest

from tests.smoke.conftest import RunningApp

pytestmark = pytest.mark.smoke


def test_test_launch_is_signed_out_and_reaches_the_main_page(app_page, real_app: RunningApp) -> None:  # type: ignore[no-untyped-def]
    status = app_page.evaluate("pywebview.api.get_account_status()")
    assert status == {
        "ok": True,
        "data": {"state": "signed_out", "username": None, "rating": None, "provisional": False},
    }
    sync = app_page.evaluate("pywebview.api.get_sync_status()")
    assert sync["ok"] and sync["data"]["state"] == "signed_out" and sync["data"]["pending"] == 0
    assert app_page.get_by_test_id("header-rating").count() == 0
    app_page.get_by_test_id("gear").click()
    app_page.get_by_test_id("settings").get_by_text("Not signed in").wait_for()
    log = (real_app.data_dir / "logs" / "weaksquare.log").read_text(encoding="utf-8")
    assert "lichess.org/api" not in log  # no Lichess call without a sign-in
