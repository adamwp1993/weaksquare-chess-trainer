"""v1.0 the Coach's Progress tab against the mock (REQUIREMENTS §10.8, FR-10.38): the empty state and Run checkpoint now,
the cards and charts (statuses, the flat baseline, hollow "not enough data yet" points, the rebuilt stretch, lower is
better), the checkpoint history and its report links, the settings, the main page's status notice and the Stats link.
The rules themselves are covered in tests/unit/test_fix_tracking.py and tests/integration/test_checkpoints.py."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def open_progress(page: Page, query: str = "") -> None:
    page.goto(page.base_url + "/" + query)  # type: ignore[attr-defined]
    page.get_by_test_id("nav-coach").click()
    page.get_by_test_id("coach-tab-progress").click()
    page.get_by_test_id("progress-tab").wait_for()


def calls(page: Page) -> list[str]:
    return page.evaluate("window.__mockApi.calls")


def test_before_any_checkpoint_it_says_what_runs_one(page: Page) -> None:
    open_progress(page)
    empty = page.get_by_test_id("progress-empty")
    expect(empty).to_contain_text("No checkpoints yet")
    expect(empty).to_contain_text("after every 10 new games")
    expect(page.get_by_test_id("checkpoint-next")).to_contain_text("after 10 more eligible games")
    page.get_by_test_id("checkpoint-run-now").click()
    expect(page.get_by_test_id("checkpoint-done")).to_contain_text("Checkpoint #1 saved")
    expect(page.get_by_test_id("progress-empty")).to_have_count(0)
    expect(page.get_by_test_id("progress-checkpoint-1")).to_contain_text("you ran it")
    expect(page.get_by_test_id("progress-card-allowed:fork")).to_be_visible()
    assert "runCheckpointNow" in calls(page)


def test_each_weakness_has_its_status_and_trend(page: Page) -> None:
    open_progress(page, "?progress=history")
    expected = {
        "missed:pin": "Regressed", "allowed:fork": "Improving", "missed:mateIn2": "Training",
        "time:low_clock": "New", "habit:hungPiece": "Fixed",
    }  # fmt: skip
    for key, status in expected.items():
        expect(page.get_by_test_id(f"progress-card-{key}").get_by_test_id("progress-status")).to_have_text(status)
    fork = page.get_by_test_id("progress-card-allowed:fork")
    expect(fork).to_contain_text("Started at 4.0 per 10 games · now 2.3")
    expect(fork.get_by_test_id("progress-rate-chart")).to_contain_text("Per 10 games (lower is better)")
    expect(fork.get_by_test_id("progress-rate-chart")).to_contain_text("Start 4.0")  # the frozen baseline line
    expect(fork.get_by_test_id("progress-accuracy-chart")).to_contain_text("Shaded: rebuilt from past games")
    expect(fork.get_by_test_id("progress-accuracy-chart")).to_contain_text("higher is better")
    expect(fork).to_contain_text("70% didn't look, 20% miscalculated, 10% rushed")


def test_not_enough_data_is_said_and_drawn_hollow(page: Page) -> None:
    open_progress(page, "?progress=history")
    clock = page.get_by_test_id("progress-card-time:low_clock")
    expect(clock.get_by_test_id("progress-guarded")).to_have_text("(not enough data yet)")
    expect(clock.locator("circle[data-guarded=true]")).to_have_count(1)
    expect(clock.get_by_test_id("progress-accuracy-chart")).to_have_count(0)  # no puzzle theme trains time use
    expect(page.get_by_test_id("progress-card-allowed:fork").locator("circle[data-guarded=true]")).to_have_count(0)


def test_game_health_charts_and_history_table(page: Page) -> None:
    open_progress(page, "?progress=history")
    health = page.get_by_test_id("progress-health")
    expect(health.get_by_test_id("progress-errors-chart")).to_contain_text(
        "Blunders, mistakes and inaccuracies per 10 games (lower is better)"
    )
    for name in ("Blunders", "Mistakes", "Inaccuracies"):
        expect(health.get_by_test_id("progress-errors-chart")).to_contain_text(name)  # legend and direct labels
    expect(health.get_by_test_id("progress-acpl-chart")).to_contain_text("Average centipawn loss (lower is better)")
    latest = page.get_by_test_id("progress-checkpoint-6")
    expect(latest).to_contain_text("2.3")  # the table carries the charts' numbers
    expect(latest).to_contain_text("Missed: Pin: Improving → Regressed")
    rebuilt = page.get_by_test_id("progress-checkpoint-2")
    expect(rebuilt).to_contain_text("rebuilt from past games")
    expect(rebuilt.get_by_test_id("progress-open-report")).to_have_count(0)  # no report for a rebuilt one


def test_a_checkpoints_report_opens_in_the_report_tab(page: Page) -> None:
    open_progress(page, "?progress=history")
    page.get_by_test_id("progress-checkpoint-5").get_by_test_id("progress-open-report").click()
    expect(page.get_by_test_id("coach-report")).to_contain_text("Checkpoint #5")
    expect(page.get_by_test_id("coach-history")).to_contain_text("Checkpoint #6")


def test_get_ai_take_and_ai_summary_lead_to_the_report(page: Page) -> None:
    open_progress(page, "?progress=history")
    expect(page.get_by_test_id("progress-checkpoint-6").get_by_test_id("progress-ai-summary")).to_be_visible()
    page.get_by_test_id("progress-checkpoint-5").get_by_test_id("progress-get-ai-take").click()
    expect(page.get_by_test_id("coach-report")).to_contain_text("Checkpoint #5")
    expect(page.get_by_test_id("coach-ai")).to_be_visible()  # Get AI coaching, with its estimate and Confirm


def test_settings_are_saved_and_bad_ones_refused(page: Page) -> None:
    open_progress(page, "?progress=history")
    page.get_by_test_id("checkpoint-settings-toggle").click()
    panel = page.get_by_test_id("checkpoint-settings")
    expect(panel.get_by_test_id("checkpoint-auto-ai")).to_be_checked()  # on by default (FR-10.37)
    panel.get_by_test_id("checkpoint-every").fill("50")
    panel.get_by_test_id("checkpoint-schedule").get_by_text("On a weekday").click()
    panel.get_by_test_id("checkpoint-save").click()
    expect(panel.get_by_test_id("checkpoint-saved")).to_be_visible()
    assert "checkpointSettings:50:30:weekday:true:true" in calls(page)
    expect(page.get_by_test_id("checkpoint-next")).to_contain_text("(every 50)")
    expect(page.get_by_test_id("checkpoint-next")).to_contain_text("Also on Sundays.")
    panel.get_by_test_id("checkpoint-fixed").fill("80")
    panel.get_by_test_id("checkpoint-save").click()
    expect(panel.get_by_test_id("checkpoint-settings-error")).to_contain_text("Fixed < Improving < Regressed")


def test_a_status_change_is_shown_once_on_the_main_page(page: Page) -> None:
    page.goto(page.base_url + "/?progress=history")  # type: ignore[attr-defined]
    notice = page.get_by_test_id("status-notices")
    expect(notice).to_contain_text("Checkpoint #6: Missed: Pin: Improving → Regressed")
    notice.get_by_test_id("status-notices-open").click()
    expect(page.get_by_test_id("progress-tab")).to_be_visible()
    page.get_by_test_id("nav-puzzles").click()
    expect(page.get_by_test_id("status-notices")).to_have_count(0)


def test_stats_links_to_progress(page: Page) -> None:
    page.goto(page.base_url + "/?progress=history")  # type: ignore[attr-defined]
    page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for()
    page.get_by_role("button", name="Menu").click()
    page.get_by_role("menuitem", name="Stats").click()
    page.get_by_test_id("stats-open-progress").click()
    expect(page.get_by_test_id("progress-tab")).to_be_visible()
