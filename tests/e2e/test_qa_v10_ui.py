"""QA v1.0 against the mock client: the first-run wizard's edges and a screenshot of each new screen in
tests/e2e/artifacts/ (gitignored) for the visual check (light and dark). A test exposing an open bug is xfail (strict)
with its ID.

- v1.0-B1: a restore that's refused (something is running) must not leave "restore" recorded as your choice: the
  next start would skip the welcome step and the puzzle step would say "Your data is restored"."""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

ART = Path(__file__).parent / "artifacts"


def shot(page: Page, name: str) -> None:
    ART.mkdir(exist_ok=True)
    page.screenshot(path=str(ART / f"qa-v10-{name}.png"), full_page=True)


def fresh(page: Page, extra: str = "") -> None:
    page.goto(page.base_url + "/?scenario=fresh" + extra)  # type: ignore[attr-defined]
    expect(page.get_by_test_id("wizard")).to_have_attribute("data-step", "welcome")


def setup_state(page: Page) -> dict:  # type: ignore[type-arg]
    return page.evaluate("window.__mockApi.getSetupState()")  # type: ignore[no-any-return]


@pytest.mark.xfail(strict=True, reason="v1.0-B1: the choice is recorded before the restore is accepted")
def test_qa_b1_a_refused_restore_leaves_no_restore_choice_behind(page: Page) -> None:
    fresh(page)
    page.get_by_test_id("wizard-restore").click()
    expect(page.get_by_test_id("wizard-restore-info")).to_contain_text("42 games")
    page.evaluate("window.__mockBackupNext('busy')")
    page.get_by_test_id("wizard-restore-go").click()
    expect(page.get_by_test_id("wizard-error")).to_contain_text("Wait for the game analysis to finish")
    st = setup_state(page)
    # Nothing was restored, so nothing may say it was: the welcome step (Start fresh / Restore) must still be next.
    assert st["choice"] is None and st["step"] == "welcome", st


def test_qa_restore_choice_cancelled_changes_nothing(page: Page) -> None:
    fresh(page)
    page.get_by_test_id("wizard-restore").click()
    page.get_by_test_id("wizard-restore-confirm").get_by_role("button", name="Cancel").click()
    expect(page.get_by_test_id("wizard-restore-confirm")).to_have_count(0)
    assert setup_state(page)["choice"] is None
    expect(page.get_by_test_id("wizard")).to_have_attribute("data-step", "welcome")


def test_qa_a_file_that_isnt_a_backup_is_refused_on_the_welcome_step(page: Page) -> None:
    fresh(page)
    page.evaluate("window.__mockBackupNext('not_backup')")
    page.get_by_test_id("wizard-restore").click()
    expect(page.get_by_test_id("wizard-error")).to_contain_text("isn't a WeakSquare backup")
    assert setup_state(page)["choice"] is None
    page.get_by_test_id("wizard-fresh").click()  # Start fresh still works after it
    expect(page.get_by_test_id("wizard")).to_have_attribute("data-step", "puzzles")


def test_qa_finish_is_refused_until_every_step_is_done(page: Page) -> None:
    fresh(page)
    out = page.evaluate("window.__mockApi.finishSetup().then(() => 'ok', e => e.message)")
    assert out != "ok"
    expect(page.get_by_test_id("wizard")).to_have_attribute("data-step", "welcome")


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_qa_screenshots_of_every_wizard_step(page: Page, scheme: str) -> None:
    fresh(page, f"&scheme={scheme}")
    shot(page, f"wizard-welcome-{scheme}")
    page.get_by_test_id("wizard-restore").click()
    expect(page.get_by_test_id("wizard-restore-info")).to_be_visible()
    shot(page, f"wizard-restore-confirm-{scheme}")
    page.get_by_test_id("wizard-restore-confirm").get_by_role("button", name="Cancel").click()
    page.get_by_test_id("wizard-fresh").click()
    expect(page.get_by_test_id("wizard")).to_have_attribute("data-step", "puzzles")
    shot(page, f"wizard-puzzles-{scheme}")
    page.get_by_role("button", name="Download from Lichess").click()
    expect(page.get_by_test_id("wizard")).to_have_attribute("data-step", "engine", timeout=10_000)
    shot(page, f"wizard-engine-{scheme}")
    page.get_by_test_id("wizard-skip-engine").click()
    expect(page.get_by_test_id("wizard")).to_have_attribute("data-step", "lichess")
    shot(page, f"wizard-lichess-{scheme}")
    page.get_by_test_id("wizard-skip-lichess").click()
    expect(page.get_by_test_id("wizard")).to_have_attribute("data-step", "done")
    shot(page, f"wizard-done-{scheme}")
    for step in ("Welcome", "Puzzles", "Stockfish", "Lichess"):
        expect(page.get_by_test_id("wizard-stepper")).to_contain_text(step)


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_qa_screenshots_of_the_progress_tab(page: Page, scheme: str) -> None:
    page.goto(page.base_url + f"/?progress=history&scheme={scheme}")  # type: ignore[attr-defined]
    expect(page.get_by_test_id("status-notices")).to_be_visible()
    shot(page, f"status-notice-{scheme}")
    page.get_by_test_id("nav-coach").click()
    page.get_by_test_id("coach-tab-progress").click()
    page.get_by_test_id("progress-tab").wait_for()
    page.get_by_test_id("progress-card-allowed:fork").wait_for()
    shot(page, f"progress-history-{scheme}")
    page.get_by_test_id("checkpoint-settings-toggle").click()
    page.get_by_test_id("checkpoint-settings").wait_for()
    expect(page.get_by_test_id("checkpoint-save")).to_be_visible()
    page.wait_for_timeout(600)  # the panel opens with an animation
    shot(page, f"progress-settings-{scheme}")
    page.goto(page.base_url + f"/?scheme={scheme}")  # type: ignore[attr-defined]
    page.get_by_test_id("nav-coach").click()
    page.get_by_test_id("coach-tab-progress").click()
    page.get_by_test_id("progress-empty").wait_for()
    shot(page, f"progress-empty-{scheme}")


def test_qa_run_checkpoint_now_twice_quickly_starts_one(page: Page) -> None:
    page.goto(page.base_url + "/")  # type: ignore[attr-defined]
    page.get_by_test_id("nav-coach").click()
    page.get_by_test_id("coach-tab-progress").click()
    button = page.get_by_test_id("checkpoint-run-now")
    button.click()
    if button.is_enabled():  # a second click while it runs must not start a second checkpoint
        button.click(timeout=2_000)
    expect(page.get_by_test_id("checkpoint-done")).to_contain_text("Checkpoint #1 saved")
    calls = page.evaluate("window.__mockApi.calls")
    assert calls.count("runCheckpointNow") == 1, calls


def test_qa_two_checkpoints_on_the_same_day_are_two_points(page: Page) -> None:
    """Run checkpoint now twice in a day: the charts' x axis is the day, so both points must still be drawn. The mock
    adds card points only at its first checkpoint, so the second point (same day) is added to its data directly."""
    page.goto(page.base_url + "/")  # type: ignore[attr-defined]
    page.get_by_test_id("nav-coach").click()
    page.get_by_test_id("coach-tab-progress").click()
    for n in (1, 2):
        page.get_by_test_id("checkpoint-run-now").click()
        expect(page.get_by_test_id("checkpoint-done")).to_contain_text(f"Checkpoint #{n} saved")
    page.evaluate(
        """() => { const c = window.__mockApi.progress.cards[0];
        c.points.push({...c.points[0], checkpoint: 2, per10: 2.0}); c.current_per10 = 2.0; }"""
    )
    page.get_by_test_id("coach-tab-report").click()
    page.get_by_test_id("coach-tab-progress").click()
    card = page.get_by_test_id("progress-card-allowed:fork")
    expect(card).to_contain_text("now 2.0")
    shot(page, "progress-same-day")
    expect(card.get_by_test_id("progress-rate-chart").locator("circle")).to_have_count(2)


@pytest.mark.xfail(strict=True, reason="v1.0-B3: a weakness no puzzle trains says 'Puzzles: — first try over 0 tries'")
def test_qa_b3_a_weakness_no_puzzle_trains_has_no_puzzle_line(page: Page) -> None:
    page.goto(page.base_url + "/?progress=history")  # type: ignore[attr-defined]
    page.get_by_test_id("nav-coach").click()
    page.get_by_test_id("coach-tab-progress").click()
    card = page.get_by_test_id("progress-card-time:low_clock")
    expect(card.get_by_test_id("progress-accuracy-chart")).to_have_count(0)  # nothing trains time use with puzzles
    expect(card).not_to_contain_text("over 0 tries", timeout=2_000)


def _last_point_x(chart) -> float:  # type: ignore[no-untyped-def]
    circles = chart.locator("circle")
    box = circles.nth(circles.count() - 1).bounding_box()
    assert box is not None
    return float(box["x"] + box["width"] / 2)


@pytest.mark.xfail(strict=True, reason="v1.0-B4: the card's two charts don't share their x positions")
def test_qa_b4_a_cards_two_charts_put_each_checkpoint_at_the_same_x(page: Page) -> None:
    """FR-10.38 (v1.0 build): game rate and puzzle accuracy are two charts "sharing the time axis". The same checkpoint
    should sit at the same horizontal position in both, so the shaded rebuilt stretch and the dates line up."""
    page.goto(page.base_url + "/?progress=history")  # type: ignore[attr-defined]
    page.get_by_test_id("nav-coach").click()
    page.get_by_test_id("coach-tab-progress").click()
    card = page.get_by_test_id("progress-card-allowed:fork")
    card.get_by_test_id("progress-accuracy-chart").locator("circle").first.wait_for()
    rate = _last_point_x(card.get_by_test_id("progress-rate-chart"))
    acc = _last_point_x(card.get_by_test_id("progress-accuracy-chart"))
    assert abs(rate - acc) <= 2, (rate, acc)
