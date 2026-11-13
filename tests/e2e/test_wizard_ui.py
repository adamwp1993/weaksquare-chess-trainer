"""v1.0 the first-run wizard against the mock (NFR-8, FR-15.4): a fresh install goes Welcome → puzzle database →
Stockfish → Lichess → the app; each step can be skipped where the requirement allows; Restore from a backup marks it
pending and restarts (the choice is recorded once the swap succeeds, v1.0-B1/B7); an existing install never sees it. The step rule itself is tested in
tests/unit/test_setup_core.py and tests/integration/test_setup_wizard.py."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def calls(page: Page) -> list[str]:
    return page.evaluate("window.__mockApi.calls")


def fresh(page: Page) -> None:
    page.goto(page.base_url + "/?scenario=fresh")  # type: ignore[attr-defined]
    expect(page.get_by_test_id("wizard")).to_have_attribute("data-step", "welcome")


def test_a_fresh_install_goes_through_every_step_into_the_app(page: Page) -> None:
    fresh(page)
    expect(page.get_by_test_id("startup")).to_have_count(0)  # the wizard comes before the startup page
    page.get_by_test_id("wizard-fresh").click()
    expect(page.get_by_test_id("wizard")).to_have_attribute("data-step", "puzzles")
    page.get_by_role("button", name="Download from Lichess").click()
    expect(page.get_by_test_id("wizard")).to_have_attribute("data-step", "engine", timeout=10_000)
    page.get_by_test_id("engine-install").click()
    expect(page.get_by_test_id("wizard")).to_have_attribute("data-step", "lichess", timeout=10_000)
    page.get_by_test_id("wizard-skip-lichess").click()
    expect(page.get_by_test_id("wizard")).to_have_attribute("data-step", "done")
    page.get_by_test_id("wizard-finish").click()
    expect(page.get_by_test_id("wizard")).to_have_count(0)
    page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for()
    assert {"setupChoice:fresh", "engineInstall:false", "setupSkip:lichess", "setupFinish"} <= set(calls(page))


def test_an_older_puzzle_database_is_upgraded_at_the_puzzle_step(page: Page) -> None:
    """v1.0 self-check regression: the puzzle step upgrades an older puzzles.db, it never asks for a download."""
    page.goto(page.base_url + "/?scenario=fresh-upgrade")  # type: ignore[attr-defined]
    page.get_by_test_id("wizard-fresh").click()
    expect(page.get_by_test_id("wizard")).to_have_attribute("data-step", "puzzles")
    expect(page.get_by_text("Upgrading your puzzle database")).to_be_visible()
    expect(page.get_by_role("button", name="Download from Lichess")).to_have_count(0)
    expect(page.get_by_test_id("wizard")).to_have_attribute("data-step", "engine", timeout=10_000)
    assert "upgrade" in calls(page)


def test_stockfish_can_be_skipped_and_the_end_says_so(page: Page) -> None:
    fresh(page)
    page.get_by_test_id("wizard-fresh").click()
    page.get_by_role("button", name="Download from Lichess").click()
    expect(page.get_by_test_id("wizard")).to_have_attribute("data-step", "engine", timeout=10_000)
    page.get_by_test_id("wizard-skip-engine").click()
    page.get_by_test_id("wizard-skip-lichess").click()
    expect(page.get_by_test_id("wizard-done")).to_contain_text("Stockfish isn't installed yet")


def test_restore_marks_it_pending_then_restarts(page: Page) -> None:
    fresh(page)
    page.get_by_test_id("wizard-restore").click()
    expect(page.get_by_test_id("wizard-restore-info")).to_contain_text("42 games")
    page.get_by_test_id("wizard-restore-go").click()
    expect(page.get_by_test_id("wizard-restore-progress")).to_contain_text("Restarting to finish the restore")
    log = calls(page)
    assert log.index("setupChoice:restore") < log.index("restoreBackup")  # marked pending, carried through the swap
    assert page.evaluate("window.__mockApi.getSetupState()")["choice"] is None  # recorded only once it swapped in (B1)


def test_an_existing_install_never_sees_it(page: Page) -> None:
    page.goto(page.base_url + "/?startup=show")  # type: ignore[attr-defined]
    expect(page.get_by_test_id("startup")).to_be_visible()
    expect(page.get_by_test_id("wizard")).to_have_count(0)


def test_a_missing_puzzle_database_on_an_existing_install_goes_to_the_importer(page: Page) -> None:
    page.goto(page.base_url + "/?scenario=empty")  # type: ignore[attr-defined]
    page.get_by_test_id("import-view").wait_for()
    expect(page.get_by_test_id("wizard")).to_have_count(0)
