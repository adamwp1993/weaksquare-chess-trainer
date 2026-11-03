"""v0.6 against the mock client: Name the idea first (FR-4.3), Danger spotting (FR-4.4), the mistake-reason chips
(§7.3, FR-5.6–5.10), the reason settings, and the Stats additions (FR-9.3, 9.7)."""

from __future__ import annotations

import pytest

from tests.e2e.conftest import play
from tests.e2e.test_engine_ui import no_engine_output
from tests.e2e.test_modes import calls, choose_mode, open_app

pytestmark = pytest.mark.e2e


def start(page, wait_ms: int = 700) -> None:  # type: ignore[no-untyped-def]
    page.get_by_role("button", name="Start").click()
    page.get_by_test_id("trainer-message").wait_for()
    page.wait_for_timeout(wait_ms)


# ---- Name the idea first ----------------------------------------------------------------------------


def test_name_the_idea_tags_first_then_solves_and_shows_the_tag_score(page) -> None:  # type: ignore[no-untyped-def]
    open_app(page)
    choose_mode(page, "Name the idea first")
    start(page)
    assert "Name the idea first" in page.get_by_test_id("trainer-message").inner_text()
    start_button = page.get_by_test_id("idea-start")
    assert start_button.is_disabled()  # at least one tag
    page.get_by_test_id("idea-payoff").click()
    page.get_by_role("option", name="Fork", exact=True).click()
    page.keyboard.press("Escape")
    start_button.click()
    page.get_by_test_id("idea-tags").wait_for(state="detached")
    assert "tags:fork" in calls(page)
    play(page, "d5c3", "black")
    page.wait_for_timeout(500)  # the reply
    play(page, "c3d1", "black")
    page.get_by_test_id("outcome").filter(has_text="Solved").wait_for()
    result = page.get_by_test_id("idea-result").inner_text()
    assert "Ideas found 1 of 2" in result and "Fork" in result
    assert "Hanging piece" in page.get_by_test_id("idea-missed").inner_text()


# ---- Danger spotting --------------------------------------------------------------------------------


def test_danger_spotting_safe_then_blunder_with_the_punishing_move(page) -> None:  # type: ignore[no-untyped-def]
    open_app(page, "?mode=danger_spotting")
    assert page.get_by_test_id("rated-switch").is_disabled()  # stays on this PC
    start(page, 200)
    page.get_by_test_id("danger-call").wait_for()
    assert page.get_by_test_id("hint-button").is_disabled()  # no Hint before the call
    no_engine_output(page)  # FR-7.3
    page.keyboard.press("s")  # the first mock candidate is safe
    page.get_by_test_id("outcome").filter(has_text="Solved").wait_for()
    assert "was safe" in page.get_by_test_id("danger-verdict").inner_text()
    page.get_by_test_id("next-button").click()

    page.get_by_test_id("danger-call").wait_for()
    page.get_by_test_id("danger-unsafe").click()  # the second is the real blunder (black's g2g1)
    msg = page.get_by_test_id("trainer-message")
    msg.filter(has_text="punish it").wait_for()
    play(page, "d4e2", "white")  # the board turned to the punishing side
    page.get_by_test_id("outcome").filter(has_text="Solved").wait_for()
    assert "was the blunder" in page.get_by_test_id("danger-verdict").inner_text()
    assert [c for c in calls(page) if c.startswith("danger:")] == ["danger:safe", "danger:unsafe"]


def test_danger_spotting_wrong_call_asks_why_with_missed_resource_suggested(page) -> None:  # type: ignore[no-untyped-def]
    open_app(page, "?mode=danger_spotting")
    start(page, 200)
    page.get_by_test_id("danger-safe").click()
    page.get_by_test_id("next-button").click()
    page.get_by_test_id("danger-call").wait_for()
    page.get_by_test_id("danger-safe").click()  # the blunder, called safe
    page.get_by_test_id("outcome").filter(has_text="Failed").wait_for()
    chip = page.get_by_test_id("reason-missedResource")
    chip.wait_for()
    assert "Suggested" in chip.inner_text()


def test_danger_spotting_needs_the_engine(page) -> None:  # type: ignore[no-untyped-def]
    open_app(page, "?mode=danger_spotting&engine=missing")
    page.get_by_test_id("danger-needs-engine").wait_for()
    assert page.get_by_test_id("start").is_disabled()


def test_the_depth_ladder_is_not_offered_in_the_new_modes(page) -> None:  # type: ignore[no-untyped-def]
    open_app(page)
    page.get_by_text("Depth ladder", exact=True).click()
    choose_mode(page, "Name the idea first")
    page.get_by_test_id("ladder-mode-note").wait_for()
    assert page.get_by_test_id("start").is_disabled()


# ---- mistake reasons -------------------------------------------------------------------------------


def _lose_first_puzzle(page) -> None:  # type: ignore[no-untyped-def]
    open_app(page)
    start(page)
    play(page, "f7f6", "black")  # legal, not the solution
    page.get_by_test_id("outcome").filter(has_text="Failed").wait_for()
    page.get_by_test_id("answer-button").click()  # free now; ends the puzzle


def test_reason_chips_keys_note_change_and_misclick(page) -> None:  # type: ignore[no-untyped-def]
    _lose_first_puzzle(page)
    page.get_by_test_id("reason-chips").wait_for()
    assert page.get_by_test_id("reason-chips").get_by_role("button").filter(has_text="1. Didn't look").count() == 1
    assert page.get_by_test_id("reason-didntLook").get_attribute("title") == "Didn't look for it"
    page.keyboard.press("1")
    page.get_by_test_id("reason-saved").wait_for()
    assert page.get_by_test_id("reason-didntLook").get_attribute("aria-pressed") == "true"
    page.get_by_test_id("reason-add-note").click()
    page.get_by_test_id("reason-note").fill("  saw it too late ")
    page.get_by_test_id("reason-note-save").click()
    page.wait_for_timeout(100)
    page.keyboard.press("6")  # changed my mind: a misclick
    page.get_by_test_id("stat-misclicks").filter(has_text="1 misclick").wait_for()
    assert page.get_by_test_id("stat-failed").inner_text() == "0"
    reasons = [c for c in calls(page) if c.startswith("reason:")]
    assert reasons == ["reason:1=didntLook", "reason:1=didntLook:saw it too late", "reason:1=misclick"]


def test_skip_hides_the_chips_and_next_still_works(page) -> None:  # type: ignore[no-untyped-def]
    _lose_first_puzzle(page)
    page.get_by_test_id("reason-skip").click()
    assert page.get_by_test_id("reason-chips").count() == 0
    page.keyboard.press("2")  # nothing to answer now
    assert not [c for c in calls(page) if c.startswith("reason:")]
    page.get_by_test_id("next-button").click()
    page.get_by_test_id("puzzle-header").filter(has_text="Puzzle 2").wait_for()


def test_reasons_off_in_settings_round_trips_through_the_bridge(page) -> None:  # type: ignore[no-untyped-def]
    open_app(page)
    page.get_by_role("button", name="Menu").click()
    page.get_by_role("menuitem", name="Settings").click()
    page.get_by_test_id("reasons-ask").get_by_text("Off", exact=True).click()
    page.wait_for_timeout(100)
    assert 'setting:reasons.ask="off"' in calls(page)
    page.keyboard.press("Escape")
    start(page)
    play(page, "f7f6", "black")
    page.get_by_test_id("outcome").filter(has_text="Failed").wait_for()
    page.get_by_test_id("answer-button").click()
    page.wait_for_timeout(300)
    assert page.get_by_test_id("reason-chips").count() == 0


# ---- Stats -------------------------------------------------------------------------------------------


def test_stats_reason_breakdown_and_mode_details(page) -> None:  # type: ignore[no-untyped-def]
    open_app(page)
    page.get_by_role("button", name="Menu").click()
    page.get_by_role("menuitem", name="Stats").click()
    page.get_by_test_id("stats-mode-tab").click()
    details = page.get_by_test_id("stats-mode-details").inner_text()
    assert "Calculation accuracy" in details and "Ideas found" in details and "Safe moves called Safe" in details
    page.get_by_test_id("stats-reasons-tab").click()
    table = page.get_by_test_id("reasons-table")
    table.wait_for()
    assert "Didn't look for it" in table.inner_text() and "Misclick" not in table.inner_text()
    assert "Misclicks: 1" in page.get_by_test_id("reasons-misclicks").inner_text()
    page.get_by_test_id("reasons-trend-table").wait_for()
    page.get_by_test_id("reasons-mode").click()
    page.get_by_role("option", name="Danger spotting").click()
    page.wait_for_timeout(100)
    assert "reasonStats:all:danger_spotting" in calls(page)
