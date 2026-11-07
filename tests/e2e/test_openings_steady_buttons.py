"""Regression (Adam, 2026-11-07): on the Openings page, pressing the step buttons moved the page, so a second
click without moving the mouse missed the button or hit another one.

The learn board sits below the opening's lines, so you're scrolled down to use it. Panels under the buttons
change height from one move to the next (What if…? is there only on the other side's moves, the move's
note panel goes at the end of the line, the engine's lines vary), and when the page got shorter the browser
pulled everything down. These click the same spot on the screen again and again, scrolled to the bottom of
the page, and check each click lands on the same button and steps the line.
"""

from __future__ import annotations

import itertools
from typing import Any

import pytest

from tests.e2e.test_openings_ui import openings, pick

pytestmark = pytest.mark.e2e


def _bold_move(page: Any) -> int:
    """How many moves in, from the move list (the current move is bold); 0 at the start."""
    return int(
        page.evaluate(
            """() => {
                const moves = [...document.querySelectorAll('[data-testid^=learn-move-]')];
                return moves.findIndex((m) => getComputedStyle(m).fontWeight === '700') + 1;
            }"""
        )
    )


def _open_line(page: Any, height: int) -> None:
    page.set_viewport_size({"width": 1280, "height": height})
    openings(page)
    pick(page, "Italian Game")
    page.get_by_test_id("learn-forward").wait_for()


def _scroll_to_bottom(page: Any) -> None:
    page.evaluate("() => window.scrollTo(0, document.documentElement.scrollHeight)")
    page.wait_for_timeout(300)


@pytest.mark.parametrize("height", [700, 900])
def test_forward_stays_under_the_mouse(page: Any, height: int) -> None:
    _open_line(page, height)
    _scroll_to_bottom(page)
    button = page.get_by_test_id("learn-forward")
    box = button.bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    last = int(page.get_by_test_id("learn-moves").locator("[data-testid^=learn-move-]").count())
    for n in range(1, last + 1):
        page.mouse.click(x, y)
        page.wait_for_timeout(250)  # the engine panel and the move note settle
        assert _bold_move(page) == n, f"click {n} didn't step the line"
        now = button.bounding_box()
        assert abs(now["y"] - box["y"]) < 1 and abs(now["x"] - box["x"]) < 1, f"Forward moved after click {n}"


def test_back_stays_under_the_mouse_from_the_end(page: Any) -> None:
    _open_line(page, 700)
    page.get_by_role("button", name="To the end").click()
    _scroll_to_bottom(page)
    button = page.get_by_test_id("learn-back")
    box = button.bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    start = _bold_move(page)
    for n in range(1, start + 1):
        page.mouse.click(x, y)
        page.wait_for_timeout(250)
        assert _bold_move(page) == start - n, f"click {n} didn't step back"
        now = button.bounding_box()
        assert abs(now["y"] - box["y"]) < 1, f"Back moved after click {n}"


def _page_height(page: Any) -> int:
    return int(page.evaluate("() => document.documentElement.scrollHeight"))


def test_the_page_never_gets_shorter_while_you_step(page: Any) -> None:
    """The cause: the What if…? panel is there only on the other side's moves, so the page was 115 px shorter
    every other move in the mock, and more with real notes. A shorter page pulls a scrolled page down."""
    _open_line(page, 700)
    heights = [_page_height(page)]
    forward = page.get_by_test_id("learn-forward")
    while forward.is_enabled():
        forward.click()
        page.wait_for_timeout(150)
        heights.append(_page_height(page))
    back = page.get_by_test_id("learn-back")
    while back.is_enabled():
        back.click()
        page.wait_for_timeout(150)
        heights.append(_page_height(page))
    drops = [(i, a, b) for i, (a, b) in enumerate(itertools.pairwise(heights)) if b < a]
    assert not drops, f"the page got shorter at steps {drops}"


def test_switching_mode_lets_the_column_shrink_again(page: Any) -> None:
    _open_line(page, 700)
    page.get_by_test_id("learn-forward").click()
    page.get_by_test_id("learn-forward").click()
    held = page.get_by_test_id("learn-side").evaluate("(el) => el.style.minHeight")
    assert held.endswith("px")
    page.get_by_test_id("learn-mode").get_by_text("Play along").click()
    page.get_by_test_id("learn-play-status").wait_for()
    side = page.get_by_test_id("learn-side")
    assert float(side.evaluate("(el) => parseFloat(el.style.minHeight || '0')")) <= side.bounding_box()["height"] + 1
