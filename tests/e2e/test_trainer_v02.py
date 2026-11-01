"""v0.2 trainer UI against the mock: Hint, Show answer (§7.2, FR-5.2, FR-5.4).

The mock serves DtKOy first: you play black, the solution is d5c3 (then b1b5) c3d1.
"""

from __future__ import annotations

import pytest

from tests.e2e.conftest import play
from tests.e2e.test_qa_v01_ui import ready, your_turn

pytestmark = pytest.mark.e2e


def start(page) -> None:  # type: ignore[no-untyped-def]
    ready(page)
    page.get_by_role("button", name="Start").click()
    your_turn(page)


def test_show_answer_unlocks_after_a_hint(page) -> None:  # type: ignore[no-untyped-def]
    start(page)
    assert page.get_by_test_id("answer-button").is_disabled()
    page.get_by_test_id("hint-button").click()
    page.get_by_test_id("trainer-message").filter(has_text="counts as failed").wait_for()
    assert page.get_by_test_id("board").get_attribute("data-hint") == "d5"
    page.get_by_test_id("outcome").filter(has_text="Failed").wait_for()  # a hint is a loss (FR-5.2)
    assert page.get_by_test_id("answer-button").is_enabled()


def test_hint_then_finish_the_line_counts_once(page) -> None:  # type: ignore[no-untyped-def]
    start(page)
    page.get_by_test_id("hint-button").click()
    page.get_by_test_id("outcome").filter(has_text="Failed").wait_for()
    play(page, "d5c3", "black")
    page.get_by_test_id("trainer-message").filter(has_text="Correct").wait_for()
    assert page.get_by_test_id("board").get_attribute("data-hint") == ""  # cleared by the move
    page.wait_for_timeout(700)
    play(page, "c3d1", "black")
    page.get_by_test_id("trainer-message").filter(has_text="full line").wait_for()
    page.get_by_test_id("session-bar").filter(has_text="Failed 1").wait_for()


def test_answer_steps_back_and_forward_and_ends_the_puzzle(page) -> None:  # type: ignore[no-untyped-def]
    start(page)
    page.get_by_test_id("hint-button").click()
    page.get_by_test_id("answer-button").click()
    player = page.get_by_test_id("answer-player")
    player.wait_for()
    step = page.get_by_test_id("answer-step")
    assert step.inner_text() == "Start"
    page.get_by_role("button", name="Forward").click()
    assert step.inner_text().startswith("1/3: N")  # d5c3 is a knight move
    page.get_by_role("button", name="Forward").click()
    page.get_by_role("button", name="Forward").click()
    assert step.inner_text().startswith("3/3:")
    assert page.get_by_role("button", name="Forward").is_disabled()
    page.get_by_role("button", name="Back").click()
    assert step.inner_text().startswith("2/3:")
    assert page.get_by_test_id("hint-button").is_disabled()
    assert page.get_by_test_id("next-button").inner_text() == "Next puzzle"
    page.get_by_test_id("session-bar").filter(has_text="Failed 1").wait_for()


def test_answer_after_solving_is_free(page) -> None:  # type: ignore[no-untyped-def]
    start(page)
    play(page, "d5c3", "black")
    page.get_by_test_id("trainer-message").filter(has_text="Correct").wait_for()
    page.wait_for_timeout(700)
    play(page, "c3d1", "black")
    page.get_by_test_id("outcome").filter(has_text="Solved").wait_for()
    assert page.get_by_test_id("hint-button").is_disabled()
    page.get_by_test_id("answer-button").click()
    page.get_by_test_id("answer-step").filter(has_text="Start").wait_for()
    page.get_by_test_id("session-bar").filter(has_text="Solved 1").wait_for()  # still solved (FR-5.4)
    assert "Failed 0" in page.get_by_test_id("session-bar").inner_text()


def open_stats(page) -> None:  # type: ignore[no-untyped-def]
    page.get_by_role("button", name="Menu").click()
    page.get_by_role("menuitem", name="Stats").click()
    page.get_by_test_id("stats-view").wait_for()


def test_stats_page(page) -> None:  # type: ignore[no-untyped-def]
    ready(page)
    open_stats(page)
    assert page.get_by_test_id("stats-played").inner_text() == "58"
    assert page.get_by_test_id("stats-accuracy").inner_text() == "71%"
    assert page.get_by_test_id("stats-line-wrong").inner_text() == "16%"  # 8 of 49
    assert "Fork" in page.get_by_test_id("stats-by-theme").inner_text()
    page.get_by_role("tab", name="By length").click()
    assert "4+ moves" in page.get_by_test_id("stats-by-length").inner_text()
    page.get_by_role("tab", name="By rating").click()
    assert "1200–1399" in page.get_by_test_id("stats-by-rating").inner_text()


# ---- keyboard shortcuts, coordinates, auto-orient ----------------------------------------------
def test_keyboard_hint_answer_steps_and_next(page) -> None:  # type: ignore[no-untyped-def]
    start(page)
    page.keyboard.press("a")  # Show answer is locked before a hint: nothing happens
    page.wait_for_timeout(300)
    assert page.get_by_test_id("answer-player").count() == 0
    page.keyboard.press("h")
    page.get_by_test_id("trainer-message").filter(has_text="Hint").wait_for()
    page.keyboard.press("a")
    page.get_by_test_id("answer-step").filter(has_text="Start").wait_for()
    page.keyboard.press("ArrowRight")
    page.keyboard.press("ArrowRight")
    page.get_by_test_id("answer-step").filter(has_text="2/3").wait_for()
    page.keyboard.press("ArrowLeft")
    page.get_by_test_id("answer-step").filter(has_text="1/3").wait_for()
    page.keyboard.press("n")
    page.get_by_test_id("puzzle-header").filter(has_text="Puzzle 2").wait_for()


def test_shortcuts_ignored_while_typing(page) -> None:  # type: ignore[no-untyped-def]
    start(page)
    page.get_by_test_id("preset-save").click()
    page.get_by_test_id("preset-name").type("hn")  # a dialog is open and focus is in a field
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    assert page.get_by_test_id("board").get_attribute("data-hint") == ""
    assert "Puzzle 1" in page.get_by_test_id("puzzle-header").inner_text()


def test_shortcut_list(page) -> None:  # type: ignore[no-untyped-def]
    ready(page)
    page.keyboard.press("?")
    assert "Show answer" in page.get_by_test_id("shortcuts-list").inner_text()


def test_coordinates_toggle_by_key_and_menu_is_saved(page) -> None:  # type: ignore[no-untyped-def]
    start(page)
    coords = page.locator("[data-testid=board] coords")
    assert coords.count() > 0
    page.keyboard.press("c")
    page.wait_for_timeout(200)
    assert coords.count() == 0
    page.get_by_role("button", name="Menu").click()
    page.get_by_test_id("menu-coordinates").filter(has_text="Show board coordinates").click()
    page.wait_for_timeout(200)
    assert coords.count() > 0  # saving through the bridge is covered by tests/integration/test_ui_settings.py


def test_board_faces_the_side_you_play(page) -> None:  # type: ignore[no-untyped-def]
    """Auto-orient (v0.1, tested in v0.2): you play black in DtKOy, white in IRypK."""
    start(page)
    wrap = page.locator(".cg-wrap")
    assert "orientation-black" in (wrap.get_attribute("class") or "")
    page.get_by_test_id("next-button").click()  # skip
    page.get_by_test_id("puzzle-header").filter(has_text="you play white").wait_for()
    assert "orientation-white" in (wrap.get_attribute("class") or "")
