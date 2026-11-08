"""QA v0.14 against the mock client: screenshots of each new screen for the visual check (tests/e2e/artifacts, gitignored),
a narrow window, and UI edges the builder's tests don't cover. A test exposing an open bug is xfail (strict) with its ID."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.e2e
ART = Path("tests/e2e/artifacts")


def _shot(page: Any, name: str) -> None:
    ART.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(ART / f"qa-v014-{name}.png"), full_page=True)


def _studies(page: Any) -> None:
    page.goto(page.base_url + "/")
    page.get_by_test_id("nav-studies").click()
    page.get_by_test_id("studies-view").wait_for()


def _paste(page: Any, text: str) -> None:
    page.get_by_test_id("studies-tab-find").click()
    page.get_by_test_id("study-paste").fill(text)
    page.get_by_test_id("study-paste-add").click()
    page.get_by_test_id("study-page").wait_for()
    page.get_by_test_id("study-reader").wait_for()


def _no_horizontal_overflow(page: Any) -> None:
    assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1")


@pytest.mark.parametrize("size", [(1400, 900), (1024, 700)])
def test_qa14_screenshots_of_every_new_screen(page: Any, size: tuple[int, int]) -> None:
    w, h = size
    page.set_viewport_size({"width": w, "height": h})
    tag = f"{w}x{h}"
    _studies(page)
    page.get_by_test_id("study-card").wait_for()
    _no_horizontal_overflow(page)
    _shot(page, f"my-studies-{tag}")
    page.get_by_test_id("studies-tab-find").click()
    page.get_by_test_id("study-starter").wait_for()
    page.get_by_test_id("study-author").fill("player_author")
    page.get_by_test_id("study-author-search").click()
    page.get_by_test_id("study-author-results").wait_for()
    _no_horizontal_overflow(page)
    _shot(page, f"find-studies-{tag}")
    page.get_by_test_id("study-paste").fill("TestNm02")
    page.get_by_test_id("study-paste-add").click()
    page.get_by_test_id("study-moves").wait_for()
    for _ in range(3):
        page.get_by_test_id("study-forward").click()
    _no_horizontal_overflow(page)
    _shot(page, f"study-normal-{tag}")
    page.get_by_test_id("study-chapter").nth(2).click()
    page.get_by_text("Thanks for studying!").wait_for()
    _shot(page, f"study-text-chapter-{tag}")
    page.get_by_test_id("study-menu").click()
    page.get_by_test_id("study-add-repertoire").click()
    page.get_by_role("dialog").wait_for()
    page.wait_for_timeout(300)
    _shot(page, f"study-repertoire-{tag}")
    page.keyboard.press("Escape")
    page.get_by_test_id("study-back-to-list").click()
    page.get_by_test_id("studies-tab-mine").click()
    page.get_by_test_id("study-card").first.wait_for()
    page.get_by_test_id("study-card").filter(has_text="Invented gamebook").get_by_test_id("study-continue").click()
    page.get_by_test_id("study-reader").wait_for()
    page.wait_for_timeout(900)
    _shot(page, f"study-gamebook-{tag}")
    page.get_by_test_id("nav-games").click()
    page.get_by_test_id("review-1").click()
    page.get_by_test_id("review-strengths").wait_for()
    _shot(page, f"review-three-parts-{tag}")


def test_qa14_b5_hearting_on_the_study_page_keeps_your_move(page: Any) -> None:
    _studies(page)
    _paste(page, "TestNm02")
    for _ in range(3):
        page.get_by_test_id("study-forward").click()
    assert page.get_by_test_id("study-current-move").inner_text().endswith("Nc3")
    page.get_by_test_id("study-heart").click()
    page.wait_for_timeout(600)
    assert page.get_by_test_id("study-current-move").inner_text().endswith("Nc3")


def _board_width(page: Any) -> float:
    box = page.locator("[data-testid=study-reader] [data-testid=board]").bounding_box()
    assert box is not None
    return float(box["width"])


def test_qa14_the_step_through_board_is_a_usable_size(page: Any) -> None:
    page.set_viewport_size({"width": 1400, "height": 900})
    _studies(page)
    _paste(page, "TestNm02")
    page.wait_for_timeout(300)
    assert _board_width(page) >= 240


def test_qa14_b6_the_play_along_board_is_as_big_as_the_step_through_board(page: Any) -> None:
    """The reader's board column is `flex: 0 0 auto` and the board is `width: 100%`, so the board takes the width of the
    buttons under it: four buttons in a normal chapter (~256 px), two in a play-along chapter (~112 px), none in a text
    chapter. In a 1400x900 window there's room for the 560 px maximum."""
    page.set_viewport_size({"width": 1400, "height": 900})
    _studies(page)
    page.get_by_test_id("study-card").filter(has_text="Invented gamebook").get_by_test_id("study-continue").click()
    page.get_by_test_id("study-reader").wait_for()
    page.wait_for_timeout(900)
    assert _board_width(page) >= 240


def test_qa14_a_bad_username_and_an_author_search_error_show_a_message(page: Any) -> None:
    _studies(page)
    page.get_by_test_id("studies-tab-find").click()
    page.get_by_test_id("study-author").fill("not a name!")
    page.get_by_test_id("study-author-search").click()
    err = page.get_by_test_id("study-author-error")
    err.wait_for()
    assert "isn't a Lichess username" in err.inner_text()
