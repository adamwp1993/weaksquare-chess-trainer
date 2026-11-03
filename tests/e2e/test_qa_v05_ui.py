"""QA v0.5 (independent) against the mock client: mode switch mid-puzzle, Show move count cap,
double Submit, switching to Spaced repetition with nothing due mid-session, collapsed-panel layout,
and screenshots of every v0.5 screen into tests/e2e/artifacts/ (gitignored)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.e2e.conftest import play
from tests.e2e.test_modes import LINE, calls, choose_mode, enter, open_app, start_session

pytestmark = pytest.mark.e2e

ART = Path(__file__).resolve().parent / "artifacts"


def shot(page, name: str) -> None:  # type: ignore[no-untyped-def]
    ART.mkdir(exist_ok=True)
    page.screenshot(path=str(ART / f"qa-v05-{name}.png"), full_page=True)


def all_time_failed(page) -> int:  # type: ignore[no-untyped-def]
    return int(page.evaluate("window.__mockApi.allTime.failed"))


def test_mode_switch_mid_puzzle_records_nothing_for_the_puzzle_in_progress(page) -> None:  # type: ignore[no-untyped-def]
    open_app(page)
    start_session(page)
    play(page, "d5c3", "black")  # first move right, puzzle still in progress
    page.get_by_test_id("trainer-message").filter(has_text="Correct").wait_for()
    before = all_time_failed(page)
    choose_mode(page, "Commit the line")
    page.get_by_test_id("session-mode").filter(has_text="Commit the line").wait_for()
    page.get_by_test_id("commit-controls").wait_for()
    assert all_time_failed(page) == before
    assert page.get_by_test_id("stat-failed").inner_text() == "0"


def test_switching_to_spaced_repetition_with_nothing_due_mid_session(page) -> None:  # type: ignore[no-untyped-def]
    open_app(page, "?srs=none")
    start_session(page)
    choose_mode(page, "Spaced repetition")
    page.wait_for_timeout(500)
    shot(page, "switch-to-srs-nothing-due")
    # Whatever happens, the trainer must not keep a Standard session running under an SRS label silently:
    # record what the UI shows for the report.
    mode_badge = page.get_by_test_id("session-mode").inner_text()
    start_disabled = page.get_by_role("button", name="Start").is_disabled()
    errors = page.get_by_role("alert").all_inner_texts()
    print(f"QA-OBS session-mode={mode_badge!r} start_disabled={start_disabled} alerts={errors!r}")
    assert any("Nothing is due" in e for e in errors), errors
    # Regression v0.5-B1: the mode stays Standard, matching the session that keeps running.
    assert mode_badge == "Standard"
    assert page.get_by_test_id("mode-control").locator("input:checked").get_attribute("value") == "standard"
    assert page.get_by_test_id("filters-fieldset").get_attribute("disabled") is None
    assert not [c for c in page.evaluate("window.__mockApi.calls") if c.startswith("setting:trainer.mode")]


def test_show_move_count_stops_entry_at_the_solution_length(page) -> None:  # type: ignore[no-untyped-def]
    open_app(page, "?mode=commit_line")
    page.get_by_test_id("show-length-switch").click()
    start_session(page)
    enter(page, LINE)
    assert "3 of 3 entered" in page.get_by_test_id("commit-count").inner_text()
    play(page, "b5b1", "black")  # a 4th ply (any legal-looking move) is refused
    page.wait_for_timeout(200)
    assert "3 of 3 entered" in page.get_by_test_id("commit-count").inner_text()
    shot(page, "commit-show-count-full")


def test_double_clicking_submit_submits_once(page) -> None:  # type: ignore[no-untyped-def]
    open_app(page, "?mode=commit_line")
    start_session(page)
    enter(page, LINE)
    page.get_by_test_id("commit-submit").dblclick()
    page.get_by_test_id("outcome").filter(has_text="Solved").wait_for()
    assert sum(1 for c in calls(page) if c.startswith("submitLine:")) == 1


def test_hint_before_submit_then_submit_shows_the_line_as_failed(page) -> None:  # type: ignore[no-untyped-def]
    open_app(page, "?mode=commit_line")
    start_session(page)
    page.get_by_test_id("hint-button").click()
    page.get_by_test_id("outcome").filter(has_text="Failed").wait_for()
    shot(page, "commit-after-hint")
    controls = page.get_by_test_id("commit-controls")
    print(f"QA-OBS commit controls visible after Hint: {controls.count() and controls.is_visible()}")


def test_screens_for_visual_review(page) -> None:  # type: ignore[no-untyped-def]
    # Commit entry and result
    open_app(page, "?mode=commit_line")
    start_session(page)
    enter(page, LINE[:2])
    shot(page, "commit-entry")
    enter(page, LINE[2:])
    page.get_by_test_id("commit-submit").click()
    page.get_by_test_id("outcome").wait_for()
    page.wait_for_timeout(500)
    shot(page, "commit-result")
    # Collapsed panel while playing
    page.get_by_test_id("hide-filters").click()
    page.get_by_test_id("filters-strip").wait_for()
    page.wait_for_timeout(300)
    shot(page, "collapsed-playing")
    page.get_by_test_id("show-filters").click()
    # SRS panel
    choose_mode(page, "Spaced repetition")
    page.get_by_test_id("srs-due").wait_for()
    page.wait_for_timeout(300)
    shot(page, "srs-panel")
    # Depth ladder
    choose_mode(page, "Standard")
    page.get_by_label("Order").get_by_text("Depth ladder").click()
    page.get_by_test_id("ladder-status").wait_for()
    shot(page, "ladder-panel")
    # Settings (Training + Debug in a dev run)
    open_app(page, "?dev=1")
    page.get_by_test_id("gear").click()
    page.get_by_test_id("training-settings").wait_for()
    page.get_by_test_id("debug-settings").scroll_into_view_if_needed()
    shot(page, "settings-training-debug")
    page.get_by_test_id("time-offset").fill("3")
    page.get_by_test_id("time-offset-apply").click()
    page.keyboard.press("Escape")
    page.get_by_test_id("time-offset-banner").wait_for()
    shot(page, "dev-banner")
    # Stats by mode
    page.get_by_role("button", name="Menu").click()
    page.get_by_role("menuitem", name="Stats").click()
    page.get_by_test_id("stats-mode-tab").click()
    page.get_by_test_id("stats-by-mode").wait_for()
    shot(page, "stats-by-mode")
    # Dark scheme, collapsed
    open_app(page, "?scheme=dark&mode=commit_line")
    start_session(page)
    page.get_by_test_id("hide-filters").click()
    page.get_by_test_id("filters-strip").wait_for()
    page.wait_for_timeout(300)
    shot(page, "collapsed-dark")
