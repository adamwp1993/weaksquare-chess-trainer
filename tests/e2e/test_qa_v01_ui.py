"""QA v0.1: UI edge cases against the mock client, plus screenshots of every v0.1 screen.

Screenshots go to tests/e2e/artifacts/ (gitignored) for visual review. Tests marked
xfail(strict=True) document an open bug by its ID.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.e2e.conftest import play

pytestmark = pytest.mark.e2e
ART = Path(__file__).resolve().parent / "artifacts"


def shot(page, name: str) -> None:  # type: ignore[no-untyped-def]
    ART.mkdir(parents=True, exist_ok=True)
    page.wait_for_timeout(400)
    page.screenshot(path=str(ART / f"qa-v01-{name}.png"), animations="disabled", full_page=True)


def ready(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/")
    page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for()


def your_turn(page) -> None:  # type: ignore[no-untyped-def]
    page.get_by_test_id("trainer-message").filter(has_text="Your turn").wait_for()


def count_text(page) -> str:  # type: ignore[no-untyped-def]
    page.wait_for_timeout(600)  # debounce (250 ms) + round trip
    return page.get_by_test_id("match-count").inner_text()


# ---- FR-3.3: typing a rating -------------------------------------------------------------------


def test_typing_a_minimum_rating_keystroke_by_keystroke(page) -> None:  # type: ignore[no-untyped-def]
    ready(page)
    box = page.get_by_label("Minimum rating")
    box.click()
    box.press("Control+a")
    box.press_sequentially("1200", delay=80)
    box.press("Tab")
    page.wait_for_timeout(400)
    assert box.input_value().replace(",", "") == "1200"


def test_typing_a_maximum_rating_keystroke_by_keystroke(page) -> None:  # type: ignore[no-untyped-def]
    ready(page)
    box = page.get_by_label("Maximum rating")
    box.click()
    box.press("Control+a")
    box.press_sequentially("1600", delay=80)
    box.press("Tab")
    page.wait_for_timeout(400)
    assert box.input_value().replace(",", "") == "1600"


def test_rating_slider_bounds_mean_no_limit(page) -> None:  # type: ignore[no-untyped-def]
    ready(page)
    everything = count_text(page)
    page.get_by_label("Minimum rating").fill("339")  # the mock dataset's minimum
    page.get_by_label("Minimum rating").press("Enter")
    page.get_by_label("Maximum rating").fill("3297")  # and maximum
    page.get_by_label("Maximum rating").press("Enter")
    assert count_text(page) == everything


# ---- FR-3.1 / 3.2: theme picker edges ---------------------------------------------------------


def test_all_with_themes_that_never_co_occur_gives_zero(page) -> None:  # type: ignore[no-untyped-def]
    ready(page)
    page.get_by_test_id("themes-picker").click()
    page.get_by_label("Search themes").fill("one-move")
    page.get_by_role("checkbox", name=re.compile("^One-move")).check()
    page.get_by_label("Search themes").fill("very long")
    page.get_by_role("checkbox", name=re.compile("^Very long")).check()
    page.keyboard.press("Escape")
    any_count = count_text(page)
    assert "0 puzzles match" not in any_count or any_count.startswith("0")
    page.get_by_text("ALL", exact=True).click()
    page.get_by_test_id("match-count").filter(has_text=re.compile(r"^0 puzzles match")).wait_for()
    assert page.get_by_role("button", name="Start").is_disabled()


def test_select_all_ticks_only_the_searched_themes(page) -> None:  # type: ignore[no-untyped-def]
    ready(page)
    page.get_by_test_id("themes-picker").click()
    page.get_by_label("Search themes").fill("mate in")
    page.get_by_role("button", name="Select all").click()
    page.keyboard.press("Escape")
    assert page.get_by_test_id("themes-picker").inner_text().strip() == "2 selected"
    page.get_by_test_id("themes-picker").click()
    page.get_by_role("button", name="Clear").click()
    page.keyboard.press("Escape")
    assert page.get_by_test_id("themes-picker").inner_text().strip() == "All themes"


def test_exclude_everything_included_gives_zero(page) -> None:  # type: ignore[no-untyped-def]
    ready(page)
    page.get_by_test_id("themes-picker").click()
    page.get_by_label("Search themes").fill("fork")
    page.get_by_role("checkbox", name=re.compile("^Fork")).check()
    page.keyboard.press("Escape")
    page.get_by_test_id("exclude-picker").click()
    page.get_by_label("Search exclude themes").fill("fork")
    page.get_by_role("checkbox", name=re.compile("^Fork")).check()
    page.keyboard.press("Escape")
    page.get_by_test_id("match-count").filter(has_text=re.compile(r"^0 puzzles match")).wait_for()


# ---- the trainer --------------------------------------------------------------------------------


def start_mate_in_one(page, queue: str = "5") -> None:  # type: ignore[no-untyped-def]
    ready(page)
    page.get_by_test_id("themes-picker").click()
    page.get_by_label("Search themes").fill("mate in 1")
    page.get_by_role("checkbox", name=re.compile("^Mate in 1")).check()
    page.keyboard.press("Escape")
    page.get_by_label("Puzzles").fill(queue)
    page.get_by_role("button", name="Start").click()
    your_turn(page)


def test_mate_in_one_alternative_mate_is_accepted(page) -> None:  # type: ignore[no-untyped-def]
    start_mate_in_one(page)  # first is 001KR: f1f8 is the solution, d1d8 also mates
    play(page, "d1d8", "white")
    page.get_by_test_id("outcome").filter(has_text="Solved").wait_for()


def test_double_click_next_does_not_fail_an_unseen_puzzle(page) -> None:  # type: ignore[no-untyped-def]
    start_mate_in_one(page)
    play(page, "f1f8", "white")
    page.get_by_test_id("outcome").filter(has_text="Solved").wait_for()
    # Two quick clicks, as a double-click or an impatient second click would send.
    page.evaluate("() => { const b = document.querySelector('[data-testid=next-button]'); b.click(); b.click(); }")
    page.wait_for_timeout(1200)
    shot(page, "after-double-click-next")
    assert page.get_by_test_id("stat-failed").inner_text() == "0"
    assert "Puzzle 2" in page.get_by_test_id("puzzle-header").inner_text()


def test_wrong_move_then_finish_line_counts_once(page) -> None:  # type: ignore[no-untyped-def]
    start_mate_in_one(page)
    play(page, "f1f2", "white")
    page.get_by_test_id("outcome").filter(has_text="Failed").wait_for()
    shot(page, "wrong-move")
    play(page, "f1f8", "white")
    page.get_by_test_id("trainer-message").filter(has_text="full line").wait_for()
    assert page.get_by_test_id("stat-failed").inner_text() == "1"
    assert page.get_by_test_id("stat-solved").inner_text() == "0"
    assert page.get_by_test_id("next-button").inner_text() == "Next puzzle"


def test_themes_hidden_until_decided_and_skip_counts(page) -> None:  # type: ignore[no-untyped-def]
    start_mate_in_one(page)
    assert page.get_by_test_id("outcome").count() == 0
    assert "Mate" not in page.get_by_test_id("puzzle-header").inner_text()
    assert page.get_by_test_id("next-button").inner_text() == "Skip (counts as failed)"
    page.get_by_test_id("next-button").click()
    your_turn(page)
    page.get_by_test_id("stat-failed").filter(has_text="1").wait_for()


def test_endless_session_has_no_total(page) -> None:  # type: ignore[no-untyped-def]
    ready(page)
    page.get_by_label("Endless").check()
    assert page.get_by_label("Puzzles").is_disabled()
    page.get_by_role("button", name="Start").click()
    your_turn(page)
    header = page.get_by_test_id("puzzle-header").inner_text()
    assert header.startswith("Puzzle 1 ·"), header


def test_screens_for_visual_review(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/?scenario=empty")
    page.get_by_test_id("import-view").wait_for()
    shot(page, "first-run")
    ready(page)
    shot(page, "mixer")
    page.get_by_test_id("themes-picker").click()
    shot(page, "theme-picker")
    page.keyboard.press("Escape")
    page.get_by_role("button", name="Menu").click()
    shot(page, "menu")
    page.get_by_role("menuitem", name="About").click()
    page.get_by_role("dialog").get_by_text("Data folder").wait_for()
    shot(page, "about")
    page.keyboard.press("Escape")
    page.get_by_role("button", name="Menu").click()
    page.get_by_role("menuitem", name=re.compile("Update puzzle database")).click()
    page.get_by_role("dialog").wait_for()
    shot(page, "update-db")
    page.keyboard.press("Escape")
    page.set_viewport_size({"width": 1000, "height": 700})  # the window's minimum size
    start_mate_in_one(page, queue="1")
    shot(page, "trainer-min-size")
    play(page, "f1f8", "white")
    page.get_by_test_id("outcome").filter(has_text="Solved").wait_for()
    shot(page, "solved-min-size")
    page.get_by_test_id("next-button").click()
    page.get_by_test_id("session-complete").wait_for()
    shot(page, "session-complete")


# ---- promotion (User Guide: "When a pawn promotes, choose the piece") --------------------------


def start_promotion_puzzle(page) -> None:  # type: ignore[no-untyped-def]
    """04TL9 (rated 485, you play black) ends with a2a1q."""
    ready(page)
    page.get_by_label("Minimum rating").fill("480")
    page.get_by_label("Minimum rating").press("Enter")
    page.get_by_label("Maximum rating").fill("490")
    page.get_by_label("Maximum rating").press("Enter")
    page.get_by_test_id("match-count").filter(has_text=re.compile(r"puzzles match")).wait_for()
    page.get_by_role("button", name="Start").click()
    your_turn(page)
    for uci in ("a5a4", "a4a3", "a3a2"):
        play(page, uci, "black")
        page.get_by_test_id("trainer-message").filter(has_text="Correct").wait_for()
        page.wait_for_timeout(900)
    play(page, "a2a1", "black")
    page.get_by_text("Promote to:").wait_for()


def test_promotion_to_queen_solves(page) -> None:  # type: ignore[no-untyped-def]
    start_promotion_puzzle(page)
    shot(page, "promotion-chooser")
    page.get_by_role("button", name="Queen").click()
    page.get_by_test_id("outcome").filter(has_text="Solved").wait_for()


def test_underpromotion_is_wrong(page) -> None:  # type: ignore[no-untyped-def]
    start_promotion_puzzle(page)
    page.get_by_role("button", name="Knight").click()
    page.get_by_test_id("outcome").filter(has_text="Failed").wait_for()
