"""v0.16 Settings → Your data against the mock (REQUIREMENTS §21): Back up now, Restore from a backup, automatic backups,
and the notice after the restart. The file checks themselves are covered in tests/integration/test_backup.py."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def open_your_data(page: Page, query: str = "") -> None:
    page.goto(page.base_url + "/" + query)  # type: ignore[attr-defined]
    page.get_by_test_id("gear").click()
    page.get_by_test_id("backup-settings").scroll_into_view_if_needed()
    expect(page.get_by_test_id("backup-settings")).to_be_visible()


def calls(page: Page) -> list[str]:
    return page.evaluate("window.__mockApi.calls")


def test_back_up_now_says_it_isnt_encrypted_and_reports_what_it_saved(page: Page) -> None:
    open_your_data(page)
    expect(page.get_by_test_id("backup-last")).to_have_text("No backup made on this PC yet.")
    privacy = page.get_by_test_id("backup-privacy")
    expect(privacy).to_contain_text("isn't encrypted")
    expect(privacy).to_contain_text("sign-in and AI keys are never included")
    page.get_by_test_id("backup-now").click()
    expect(page.get_by_test_id("backup-done")).to_contain_text("Backed up 42 games")
    expect(page.get_by_test_id("backup-last")).to_contain_text("Last backup on this PC: Nov 9, 2026")
    assert "backupNow" in calls(page)


def test_restore_shows_whats_in_it_and_replaces_only_after_you_confirm(page: Page) -> None:
    open_your_data(page)
    page.get_by_test_id("restore-choose").click()
    info = page.get_by_test_id("restore-info")
    expect(info).to_contain_text("Nov 2, 2026")
    expect(info).to_contain_text("WeakSquare 0.16.0")
    expect(info).to_contain_text("42 games, 1,250 puzzle attempts and 3 Coach reports")
    confirm = page.get_by_test_id("restore-confirm")
    expect(confirm).to_contain_text("nothing is merged")
    expect(confirm).to_contain_text("Lichess sign-in, AI keys, the puzzle database and Stockfish")
    assert "restoreBackup" not in calls(page)

    page.get_by_test_id("restore-cancel").click()  # Cancel changes nothing
    expect(confirm).to_have_count(0)
    assert "restoreBackup" not in calls(page)

    page.get_by_test_id("restore-choose").click()
    page.get_by_test_id("restore-replace").click()
    expect(page.get_by_test_id("restore-progress")).to_contain_text("Restarting to finish the restore")
    assert "restoreBackup" in calls(page)


@pytest.mark.parametrize(
    ("kind", "message"),
    [("not_backup", "isn't a WeakSquare backup"), ("newer", "made by a newer version of WeakSquare. Update the app first.")],
)
def test_a_file_that_cant_be_restored_is_refused_with_its_reason(page: Page, kind: str, message: str) -> None:
    open_your_data(page)
    page.evaluate(f"window.__mockBackupNext('{kind}')")
    page.get_by_test_id("restore-choose").click()
    expect(page.get_by_test_id("restore-error")).to_contain_text(message)
    expect(page.get_by_test_id("restore-confirm")).to_have_count(0)


def test_restore_while_a_job_runs_names_it(page: Page) -> None:
    open_your_data(page)
    page.get_by_test_id("restore-choose").click()
    page.evaluate("window.__mockBackupNext('busy')")
    page.get_by_test_id("restore-replace").click()
    expect(page.get_by_test_id("restore-error")).to_contain_text("Wait for the game analysis to finish")
    assert "restoreBackup" not in calls(page)


def test_automatic_backups_ask_for_a_folder_and_show_the_next_one(page: Page) -> None:
    open_your_data(page)
    auto = page.get_by_test_id("backup-auto")
    expect(auto).not_to_be_checked()  # FR-15.3: off by default
    expect(page.get_by_test_id("backup-folder")).to_contain_text("none chosen")
    auto.check(force=True)  # no folder yet: the folder picker opens first
    expect(auto).to_be_checked()
    expect(page.get_by_test_id("backup-folder")).to_contain_text("E:\\WeakSquare backups")
    expect(page.get_by_test_id("backup-next")).to_contain_text("Next automatic backup")
    assert "backupSettings:true:7:5" in calls(page)

    keep = page.get_by_test_id("backup-keep")
    keep.fill("0")
    keep.blur()
    expect(page.get_by_test_id("backup-settings-msg")).to_contain_text("between 1 and 50")
    expect(page.get_by_test_id("backup-keep")).to_have_value("5")  # the box goes back to the saved value


def test_a_missing_folder_is_shown_not_silent(page: Page) -> None:
    page.goto(page.base_url + "/")  # type: ignore[attr-defined]
    page.evaluate("window.__mockApi.getBackupStatus()")
    page.evaluate("window.__mockBackupFolderMissing()")
    page.get_by_test_id("gear").click()
    expect(page.get_by_test_id("backup-error")).to_contain_text("isn't available (is the drive plugged in?)")


@pytest.mark.parametrize(
    ("query", "text"),
    [("restored=1", "Your data was restored from the backup made Nov 2, 2026"), ("restored=failed", "put back as it was")],
)
def test_the_notice_after_the_restart(page: Page, query: str, text: str) -> None:
    page.goto(page.base_url + "/?" + query)  # type: ignore[attr-defined]
    notice = page.get_by_test_id("restore-notice")
    expect(notice).to_contain_text(text)
    if query == "restored=1":
        expect(notice).to_contain_text("Sign in to Lichess again")
    notice.get_by_role("button").click()  # it closes
    expect(notice).to_have_count(0)
    page.goto(page.base_url + "/")  # type: ignore[attr-defined]  # a start with no restore shows nothing
    page.get_by_test_id("gear").wait_for()
    expect(page.get_by_test_id("restore-notice")).to_have_count(0)


def test_the_notice_shows_even_when_the_app_opens_on_the_import_screen(page: Page) -> None:
    page.goto(page.base_url + "/?scenario=empty&restored=1")  # type: ignore[attr-defined]
    page.get_by_test_id("import-view").wait_for()
    expect(page.get_by_test_id("restore-notice")).to_contain_text("Your data was restored")
