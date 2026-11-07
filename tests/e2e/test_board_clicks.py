"""The board takes a click anywhere inside a square, not only near its centre, including after the
layout around it changes size (regression: chessground kept stale board bounds, v0.5 post-sign-off)."""

from __future__ import annotations

import pytest

from tests.e2e.test_modes import open_app, start_session

pytestmark = pytest.mark.e2e


def click_near_corner(page, square: str, orientation: str, fx: float, fy: float) -> None:  # type: ignore[no-untyped-def]
    """Click inside `square` at fraction (fx, fy) of its width/height from its top-left corner."""
    board = page.get_by_test_id("board")
    board.scroll_into_view_if_needed()
    box = board.bounding_box()
    size = box["width"] / 8
    file = "abcdefgh".index(square[0])
    rank = int(square[1]) - 1
    col = file if orientation == "white" else 7 - file
    row = 7 - rank if orientation == "white" else rank
    page.mouse.click(box["x"] + (col + fx) * size, box["y"] + (row + fy) * size)


def move_by_corners(page) -> None:  # type: ignore[no-untyped-def]
    # The mock's first puzzle: you play black, d5c3. Click each square near opposite corners.
    click_near_corner(page, "d5", "black", 0.1, 0.1)
    click_near_corner(page, "c3", "black", 0.9, 0.9)
    page.get_by_test_id("trainer-message").filter(has_text="Correct").wait_for(timeout=3000)


def test_click_near_square_corner_moves_the_piece(page) -> None:  # type: ignore[no-untyped-def]
    open_app(page)
    start_session(page)
    move_by_corners(page)


def test_click_near_square_corner_after_hiding_filters(page) -> None:  # type: ignore[no-untyped-def]
    open_app(page)
    start_session(page)
    page.get_by_test_id("hide-filters").click()
    page.get_by_test_id("filters-strip").wait_for()
    page.wait_for_timeout(300)
    move_by_corners(page)


def test_click_near_square_corner_after_the_board_moves_down(page) -> None:  # type: ignore[no-untyped-def]
    """Content above the board (a notice, the session bar wrapping, the filters panel in a narrow window)
    can push the board down without resizing it or scrolling; clicks must follow the board."""
    open_app(page)
    start_session(page)
    page.get_by_test_id("board").hover()  # chessground has measured the board here
    page.evaluate(
        """() => {
            // The whole board with its coordinate strips (a grid: a spacer inside it would be a grid cell).
            const wrap = document.querySelector('[data-testid="board"]').closest('.ws-board-frame');
            const spacer = document.createElement('div');
            spacer.style.height = '30px';
            wrap.parentElement.insertBefore(spacer, wrap);
        }"""
    )
    move_by_corners(page)


def test_click_near_square_corner_after_showing_filters_again(page) -> None:  # type: ignore[no-untyped-def]
    open_app(page)
    start_session(page)
    page.get_by_test_id("hide-filters").click()
    page.get_by_test_id("filters-strip").wait_for()
    page.get_by_test_id("show-filters").click()
    page.get_by_test_id("mixer-column").wait_for(state="visible")
    page.wait_for_timeout(300)
    move_by_corners(page)
