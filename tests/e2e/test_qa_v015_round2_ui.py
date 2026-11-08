"""QA v0.15 round 2 (independent), against the mock: B2 at other sizes and orientations, B3 on a failed line, B4 across
window widths. Invented data only."""

from __future__ import annotations

from typing import Any

import pytest

from tests.e2e.test_analysis_tab_ui import analysis, board, fen, same
from tests.e2e.test_modes import enter, open_app, start_session
from tests.e2e.test_qa_v015_ui import _drag, moves_in_tab, open_in_tab

pytestmark = pytest.mark.e2e


def _centre(page: Any, square: str, orientation: str) -> tuple[float, float]:
    box = board(page).bounding_box()
    size = box["width"] / 8
    col = "abcdefgh".index(square[0])
    row = 8 - int(square[1])
    if orientation == "black":
        col, row = 7 - col, 7 - row
    return box["x"] + (col + 0.5) * size, box["y"] + (row + 0.5) * size


def _drag_spare(page: Any, testid: str, square: str, orientation: str) -> None:
    page.get_by_test_id(testid).scroll_into_view_if_needed()
    spare = page.get_by_test_id(testid).bounding_box()
    _drag(page, (spare["x"] + spare["width"] / 2, spare["y"] + spare["height"] / 2), _centre(page, square, orientation))


@pytest.mark.parametrize(
    ("width", "height", "flip"),
    [(1280, 900, False), (1280, 900, True), (1920, 1080, False), (1024, 768, False), (900, 700, False)],
)
def test_qa_r2_b2_the_first_palette_drag_lands_on_its_square(page: Any, width: int, height: int, flip: bool) -> None:
    page.set_viewport_size({"width": width, "height": height})
    analysis(page)
    orientation = "white"
    if flip:
        page.get_by_test_id("analysis-flip").click()
        orientation = "black"
    page.get_by_test_id("analysis-setup").click()
    page.get_by_test_id("analysis-setup-panel").wait_for()
    page.get_by_test_id("spare-white-queen").scroll_into_view_if_needed()
    _drag_spare(page, "spare-white-queen", "d4", orientation)  # no press on the board before this
    page.wait_for_timeout(300)  # a person can't start the next drag within a frame of the last
    _drag_spare(page, "spare-black-knight", "f5", orientation)  # a second drag, from the other row
    page.get_by_test_id("setup-done").click()
    page.get_by_test_id("analysis-setup-panel").wait_for(state="detached")
    assert fen(page) == "rnbqkbnr/pppppppp/8/5n2/3Q4/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def test_qa_r2_b2_a_drag_after_the_window_changes_size_still_lands(page: Any) -> None:
    analysis(page)
    page.get_by_test_id("analysis-setup").click()
    page.get_by_test_id("analysis-setup-panel").wait_for()
    page.get_by_test_id("setup-clear").click()  # the alert-free path: the board doesn't move
    page.set_viewport_size({"width": 1100, "height": 900})
    page.wait_for_timeout(200)
    _drag_spare(page, "spare-white-king", "e1", "white")
    page.wait_for_timeout(300)
    _drag_spare(page, "spare-black-king", "e8", "white")
    page.get_by_test_id("setup-done").click()
    page.get_by_test_id("analysis-setup-panel").wait_for(state="detached")
    assert fen(page) == "4k3/8/8/8/8/8/8/4K3 w - - 0 1"


def test_qa_r2_b3_a_failed_committed_line_comes_with_its_moves(page: Any) -> None:
    open_app(page, "?mode=commit_line")
    start_session(page)
    enter(page, ["h7h6"])
    page.get_by_test_id("commit-submit").click()
    page.get_by_test_id("outcome").filter(has_text="Failed").wait_for()
    here = open_in_tab(page)
    assert same(fen(page), here)
    assert moves_in_tab(page) >= 2  # the opponent's move and your h6
    page.get_by_test_id("analysis-back").click()
    assert not same(fen(page), here)


@pytest.mark.parametrize("width", [900, 1000, 1199, 1200, 1280, 1440])
def test_qa_r2_b4_the_header_fits_at_every_width(page: Any, width: int) -> None:
    page.set_viewport_size({"width": width, "height": 700})
    analysis(page)
    header = page.locator("header")
    assert header.locator("> div").first.evaluate(
        "e => e.scrollHeight <= e.clientHeight + 1 && e.scrollWidth <= e.clientWidth + 1"
    )
    title = header.locator("h3")
    if title.is_visible():
        assert title.inner_text() == "WeakSquare Chess Trainer"
        assert title.evaluate("e => e.scrollWidth <= e.clientWidth + 1")
        tb = title.bounding_box()
        nav = page.get_by_test_id("nav-puzzles").bounding_box()
        assert tb["x"] + tb["width"] <= nav["x"]  # no overlap with the nav
    else:
        assert width < 1200
    for nav in ("puzzles", "games", "coach", "openings", "studies", "analysis"):
        box = page.get_by_test_id(f"nav-{nav}").bounding_box()
        assert box is not None and box["y"] + box["height"] <= 56 and box["x"] + box["width"] <= width
