"""Done-when: set filters -> solve 3 puzzles via the mock -> session stats update.

The mock serves its fixed puzzles in order (web/src/api/mockPuzzles.ts). With Fork + ALL, rating
1100-1700 and 2-move puzzles, the first three are DtKOy (you play black), IRypK and UjLNn (white).
"""

from __future__ import annotations

import re

import pytest

from tests.e2e.conftest import play

pytestmark = pytest.mark.e2e


def your_turn(page) -> None:  # type: ignore[no-untyped-def]
    page.get_by_test_id("trainer-message").filter(has_text="Your turn").wait_for()


def test_filters_then_solve_three(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/")
    count = page.get_by_test_id("match-count")
    count.filter(has_text="615,730 puzzles match").wait_for()  # all 10 mock puzzles, scaled
    everything = count.inner_text()

    # Themes: Fork, match ALL.
    page.get_by_test_id("themes-picker").click()
    page.get_by_label("Search themes").fill("fork")
    page.get_by_role("checkbox", name=re.compile("^Fork")).check()
    page.keyboard.press("Escape")
    page.get_by_text("ALL", exact=True).click()
    # Rating 1100-1700, 2-move puzzles, a queue of 3.
    page.get_by_label("Minimum rating").fill("1100")
    page.get_by_label("Maximum rating").fill("1700")
    page.get_by_label("2 moves").check()
    page.get_by_label("Puzzles").fill("3")
    count.filter(has_text="307,865 puzzles match").wait_for()  # 5 mock puzzles
    assert count.inner_text() != everything

    page.get_by_role("button", name="Start").click()

    # 1: DtKOy, solved.
    your_turn(page)
    assert not page.get_by_test_id("outcome").is_visible()  # themes hidden while solving (FR-3.14)
    play(page, "d5c3", "black")
    page.get_by_test_id("trainer-message").filter(has_text="Correct").wait_for()
    your_turn_after_reply(page)
    play(page, "c3d1", "black")
    page.get_by_test_id("outcome").filter(has_text="Solved").wait_for()
    assert "Fork" in page.get_by_test_id("outcome-themes").inner_text()
    page.get_by_test_id("stat-solved").filter(has_text="1").wait_for()
    page.get_by_test_id("next-button").click()

    # 2: IRypK, a wrong move = failed.
    your_turn(page)
    play(page, "g4g3", "white")
    page.get_by_test_id("outcome").filter(has_text="Failed").wait_for()
    page.get_by_test_id("stat-failed").filter(has_text="1").wait_for()
    page.get_by_test_id("next-button").click()

    # 3: UjLNn, solved.
    your_turn(page)
    play(page, "d4c6", "white")
    page.get_by_test_id("trainer-message").filter(has_text="Correct").wait_for()
    your_turn_after_reply(page)
    play(page, "c6b4", "white")
    page.get_by_test_id("outcome").filter(has_text="Solved").wait_for()

    page.get_by_test_id("stat-solved").filter(has_text="2").wait_for()
    assert page.get_by_test_id("stat-failed").inner_text() == "1"
    assert page.get_by_test_id("stat-accuracy").inner_text() == "67%"

    page.get_by_test_id("next-button").click()
    page.get_by_test_id("session-complete").wait_for()


def your_turn_after_reply(page) -> None:  # type: ignore[no-untyped-def]
    """Wait until the opponent's reply has been played and the board is ours again."""
    page.wait_for_timeout(900)  # the reply is played 300 ms after the answer, animated over 250 ms


def test_no_matches_disables_start(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/")
    page.get_by_label("Minimum rating").fill("3200")
    page.get_by_test_id("match-count").filter(has_text="0 puzzles match").wait_for()
    assert page.get_by_role("button", name="Start").is_disabled()


def test_first_run_import_flow(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/?scenario=empty")
    page.get_by_role("button", name="Download from Lichess").click()
    page.get_by_test_id("import-message").wait_for()
    page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for(timeout=10_000)


def test_cancel_import(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/?scenario=empty")
    page.get_by_role("button", name="Download from Lichess").click()
    page.get_by_role("button", name="Cancel").click()
    page.get_by_role("button", name="Download from Lichess").wait_for()
