"""FR-2.5 in the UI, against the mock: the banner's wording and buttons, Check for updates, the exact
numbers after the update, and the daily-check switch."""

from __future__ import annotations

import pytest

from tests.e2e.test_qa_v01_ui import ready

pytestmark = pytest.mark.e2e


def calls(page) -> list[str]:  # type: ignore[no-untyped-def]
    return page.evaluate("window.__mockApi.calls")


def open_update(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/?scenario=update")
    page.get_by_test_id("update-banner").wait_for()


def test_no_banner_when_up_to_date(page) -> None:  # type: ignore[no-untyped-def]
    ready(page)
    page.wait_for_timeout(500)
    assert page.get_by_test_id("update-banner").count() == 0
    assert "check:false" in calls(page)  # the automatic check ran (not forced)


def test_banner_wording(page) -> None:  # type: ignore[no-untyped-def]
    open_update(page)
    text = page.get_by_test_id("update-banner").inner_text()
    assert "exported 2026-11-01, yours is from 2026-10-02" in text
    assert "Download about 295 MB?" in text
    assert "About 6,193,530 puzzles (+36,189)" in page.get_by_test_id("update-count").inner_text()


def test_not_now_and_skip(page) -> None:  # type: ignore[no-untyped-def]
    open_update(page)
    page.get_by_test_id("update-not-now").click()
    page.get_by_test_id("update-banner").wait_for(state="hidden")
    assert "dismiss:not_now" in calls(page)
    open_update(page)
    page.get_by_test_id("update-skip").click()
    page.get_by_test_id("update-banner").wait_for(state="hidden")
    assert "dismiss:skip" in calls(page)


def test_update_now_imports_and_reports_the_exact_numbers(page) -> None:  # type: ignore[no-untyped-def]
    open_update(page)
    page.get_by_test_id("update-now").click()
    page.get_by_test_id("import-done").filter(has_text="44,112 new, 7,923 removed").wait_for(timeout=10_000)
    assert page.get_by_test_id("update-banner").count() == 0
    assert "import:download" in calls(page)


def test_check_for_updates_button(page) -> None:  # type: ignore[no-untyped-def]
    ready(page)
    page.get_by_role("button", name="Menu").click()
    page.get_by_role("menuitem", name="Update puzzle database…").click()
    page.get_by_test_id("check-updates").click()
    page.get_by_test_id("check-result").filter(has_text="up to date").wait_for()
    assert "check:true" in calls(page)  # forced: runs even if checked today


def test_daily_check_switch_is_saved(page) -> None:  # type: ignore[no-untyped-def]
    ready(page)
    page.get_by_role("button", name="Menu").click()
    page.get_by_role("menuitem", name="Settings…").click()
    switch = page.get_by_test_id("auto-check-switch")
    assert switch.is_checked()
    switch.click()
    assert "setting:puzzle_db.auto_check=false" in calls(page)
