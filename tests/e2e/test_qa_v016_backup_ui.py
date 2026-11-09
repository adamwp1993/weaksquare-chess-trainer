"""QA v0.16: Settings → Your data beyond the builder's e2e tests. Screenshots go to tests/e2e/artifacts/ (gitignored)."""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

ART = Path(__file__).parent / "artifacts"


def open_your_data(page: Page, query: str = "") -> None:
    page.goto(page.base_url + "/" + query)  # type: ignore[attr-defined]
    page.get_by_test_id("gear").click()
    page.get_by_test_id("backup-settings").scroll_into_view_if_needed()
    expect(page.get_by_test_id("backup-settings")).to_be_visible()


def shot(page: Page, name: str) -> None:
    ART.mkdir(exist_ok=True)
    page.get_by_test_id("backup-settings").screenshot(path=str(ART / name))


def calls(page: Page) -> list[str]:
    return page.evaluate("window.__mockApi.calls")


def test_qa_a_restore_that_fails_its_full_check_shows_the_reason_and_lets_you_choose_again(page: Page) -> None:
    """The mock never fails the restore job, so the `restore-failed` branch is otherwise untested."""
    open_your_data(page)
    page.evaluate(
        """() => {
          const m = window.__mockApi;
          m.restoreBackup = async () => {
            const id = "job-qa-fail";
            m.emit({ id, kind: "backup_restore", state: "running", progress: null, message: "Checking the backup…", error_code: null });
            setTimeout(() => m.emit({ id, kind: "backup_restore", state: "failed", progress: null,
              message: "This backup is damaged and can't be restored. Nothing was changed.", error_code: "damaged" }), 200);
            return id;
          };
        }"""
    )
    page.get_by_test_id("restore-choose").click()
    shot(page, "qa-v016-restore-confirm.png")
    page.get_by_test_id("restore-replace").click()
    expect(page.get_by_test_id("restore-failed")).to_contain_text("damaged and can't be restored. Nothing was changed.")
    expect(page.get_by_test_id("restore-progress")).to_have_count(0)
    expect(page.get_by_test_id("restore-confirm")).to_have_count(0)
    expect(page.get_by_test_id("restore-choose")).to_be_enabled()
    shot(page, "qa-v016-restore-failed.png")
    page.get_by_test_id("restore-choose").click()  # choosing again clears the old failure
    expect(page.get_by_test_id("restore-failed")).to_have_count(0)
    expect(page.get_by_test_id("restore-confirm")).to_be_visible()


def test_qa_restore_choose_is_disabled_while_the_restore_runs_and_replace_fires_once(page: Page) -> None:
    open_your_data(page)
    page.get_by_test_id("restore-choose").click()
    page.get_by_test_id("restore-replace").dblclick()
    expect(page.get_by_test_id("restore-progress")).to_be_visible()
    expect(page.get_by_test_id("restore-choose")).to_be_disabled()
    expect(page.get_by_test_id("restore-progress")).to_contain_text("Restarting to finish the restore")
    assert calls(page).count("restoreBackup") == 1


def test_qa_cancelling_the_open_dialog_changes_nothing(page: Page) -> None:
    open_your_data(page)
    page.evaluate("() => { window.__mockApi.chooseBackupToRestore = async () => null; }")
    page.get_by_test_id("restore-choose").click()
    expect(page.get_by_test_id("restore-confirm")).to_have_count(0)
    expect(page.get_by_test_id("restore-error")).to_have_count(0)


def test_qa_your_data_screens_for_the_visual_check(page: Page) -> None:
    page.set_viewport_size({"width": 1000, "height": 700})  # the app's minimum window
    open_your_data(page)
    shot(page, "qa-v016-your-data-min-window.png")
    page.get_by_test_id("backup-auto").check(force=True)
    expect(page.get_by_test_id("backup-next")).to_be_visible()
    page.evaluate("window.__mockBackupFolderMissing()")
    page.get_by_test_id("backup-folder-choose").click()  # reloads the status through the settings call
    shot(page, "qa-v016-your-data-auto-on.png")
    box = page.get_by_test_id("backup-settings").bounding_box()
    assert box is not None and box["width"] <= 1000
    for tid in ("backup-now", "restore-choose", "backup-folder-choose", "backup-interval", "backup-keep"):
        el = page.get_by_test_id(tid).bounding_box()
        assert el is not None and el["x"] >= box["x"] and el["x"] + el["width"] <= box["x"] + box["width"] + 1, tid
