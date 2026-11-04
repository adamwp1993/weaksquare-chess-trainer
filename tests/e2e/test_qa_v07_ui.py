"""QA v0.7 (independent) UI checks against the mock client: the Explain panel resets on the next puzzle,
Show me's keyboard stepping, a cleared cap field, the spend indicator's target, and screenshots of the new
screens into tests/e2e/artifacts/ (gitignored) for the visual check."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.e2e.conftest import play
from tests.e2e.test_engine_ui import WRONG, start

pytestmark = pytest.mark.e2e

ART = Path(__file__).resolve().parent / "artifacts"


def _shot(page, name: str) -> None:  # type: ignore[no-untyped-def]
    ART.mkdir(exist_ok=True)
    page.screenshot(path=str(ART / f"qa-v07-{name}.png"), full_page=True)


def _explain(page) -> None:  # type: ignore[no-untyped-def]
    play(page, WRONG, "black")
    page.get_by_test_id("outcome").filter(has_text="Failed").wait_for()
    page.get_by_test_id("answer-button").click()
    page.get_by_text("Explain (≈ $0.0").wait_for()
    page.get_by_test_id("explain-button").click()
    page.get_by_test_id("explanation").wait_for()


def test_qa_explanation_does_not_follow_you_to_the_next_puzzle(page) -> None:  # type: ignore[no-untyped-def]
    start(page, "?ai=on")
    _explain(page)
    _shot(page, "explain")
    page.get_by_test_id("next-button").click()
    page.get_by_test_id("explain-button").wait_for()
    assert page.get_by_test_id("explanation").count() == 0
    assert page.get_by_test_id("explain-button").is_disabled()  # the new puzzle isn't over
    assert page.get_by_test_id("board").get_attribute("data-shapes") == ""


def test_qa_show_me_steps_with_the_arrow_keys(page) -> None:  # type: ignore[no-untyped-def]
    start(page, "?ai=on")
    _explain(page)
    board = page.get_by_test_id("board")
    page.get_by_test_id("line-preview").wait_for()
    first = board.get_attribute("data-shapes")
    page.keyboard.press("ArrowRight")
    page.wait_for_timeout(200)
    assert board.get_attribute("data-shapes") != first
    page.keyboard.press("ArrowLeft")
    page.wait_for_timeout(200)
    assert board.get_attribute("data-shapes") == first
    page.get_by_test_id("line-preview-done").click()
    assert board.get_attribute("data-shapes") == ""


# Regression test for v0.7-B4 (fixed).
def test_qa_clearing_the_cap_field_does_not_silently_set_zero(page) -> None:  # type: ignore[no-untyped-def]
    """Emptying 'Per-run cap ($)' and leaving the field shouldn't quietly save $0 (which blocks every
    Explain); it should keep the old value or say why."""
    start(page, "?ai=on")
    page.get_by_test_id("gear").click()
    cap = page.get_by_test_id("ai-cap")
    cap.scroll_into_view_if_needed()
    cap.fill("")
    cap.blur()
    page.wait_for_timeout(300)
    page.keyboard.press("Escape")
    page.get_by_test_id("gear").click()
    value = page.get_by_test_id("ai-cap").input_value()
    assert value not in ("0", "0.00", ""), f"the cap became {value!r}"


# Regression test for v0.7-B5 (fixed).
def test_qa_spend_indicator_opens_settings_at_the_ai_section(page) -> None:  # type: ignore[no-untyped-def]
    start(page, "?ai=warn")
    page.get_by_test_id("spend-indicator").click()
    page.get_by_test_id("settings").wait_for()
    page.wait_for_timeout(400)
    _shot(page, "spend-click")
    assert page.get_by_test_id("settings-ai").is_visible()
    box = page.get_by_test_id("settings-ai").bounding_box()
    assert box is not None and box["y"] < page.viewport_size["height"], "the AI section is below the fold"


def test_qa_screenshots_of_the_new_screens(page) -> None:  # type: ignore[no-untyped-def]
    start(page, "?ai=over")
    page.get_by_test_id("gear").click()
    page.get_by_test_id("price-table").scroll_into_view_if_needed()
    _shot(page, "settings-ai-over")
    page.keyboard.press("Escape")
    page.goto(page.base_url + "/?startup=show&ai=failed")
    page.get_by_test_id("startup-ai-failed").wait_for()
    _shot(page, "startup-ai-failed")
    page.goto(page.base_url + "/?startup=show")
    page.get_by_test_id("startup-more").click()  # the fast path hides the AI block until Show all options
    page.get_by_test_id("ai-settings").wait_for()
    _shot(page, "startup-all-options")
    page.set_viewport_size({"width": 900, "height": 700})
    start(page, "?ai=on")
    _explain(page)
    _shot(page, "explain-narrow")
