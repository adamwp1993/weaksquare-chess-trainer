"""Regression (Adam, 2026-11-06, and again 2026-11-07): the board's file letters and rank numbers.

First report: chessground drew them inside the edge squares at 9px and 80% opacity, so on the My games board
they looked missing. The rc1 fix made them bold and dark but left them inside the squares, and in the real
app Adam still saw none on Game Review: the numbers were small corner marks, and the bottom row holding the
letters was below the window. Now `Board` draws them itself in strips outside the squares, and the review
boards are sized to fit the window. These check the labels as drawn: all present, lined up with the right
rank or file, outside the squares, large enough, readable on the page in both color schemes, and on screen.
They run on Puzzles, Game Review and Retry, in both orientations.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.e2e.conftest import play
from tests.e2e.test_trainer_v02 import start

pytestmark = pytest.mark.e2e

FILES = "ABCDEFGH"
RANKS = "12345678"
MIN_FONT_PX = 13
MIN_CONTRAST = 4.5  # WCAG AA for normal text

READ_LABELS = """
() => {
  const board = document.querySelector('[data-testid=board]');
  const box = board.getBoundingClientRect();
  const read = (id) => [...document.querySelectorAll(`[data-testid=${id}] span`)].map((el) => {
    const range = document.createRange();
    range.selectNodeContents(el);
    const t = range.getBoundingClientRect();
    const style = getComputedStyle(el);
    let opacity = 1;
    for (let n = el; n; n = n.parentElement) opacity *= Number(getComputedStyle(n).opacity);
    return {
      label: el.textContent.trim().toUpperCase(),
      font: parseFloat(style.fontSize),
      color: style.color,
      visible: el.checkVisibility({ opacityProperty: true, visibilityProperty: true }),
      opacity,
      col: Math.floor(((t.left + t.right) / 2 - box.left) / (box.width / 8)),
      row: Math.floor(((t.top + t.bottom) / 2 - box.top) / (box.height / 8)),
      left: t.left, right: t.right, top: t.top, bottom: t.bottom,
    };
  });
  let bg = 'rgba(0, 0, 0, 0)';
  for (let n = board.parentElement; n && /rgba\\(0, 0, 0, 0\\)|transparent/.test(bg); n = n.parentElement) {
    bg = getComputedStyle(n).backgroundColor;
  }
  if (/rgba\\(0, 0, 0, 0\\)|transparent/.test(bg)) bg = getComputedStyle(document.body).backgroundColor;
  return {
    ranks: read('board-ranks'),
    files: read('board-files'),
    box: { left: box.left, right: box.right, top: box.top, bottom: box.bottom },
    bg,
    inBoard: board.querySelectorAll('coords').length,
    viewport: { width: window.innerWidth, height: window.innerHeight },
  };
}
"""


def rgb(css: str) -> tuple[float, float, float]:
    parts = css[css.index("(") + 1 : css.index(")")].replace(",", " ").split()
    return float(parts[0]), float(parts[1]), float(parts[2])


def luminance(color: tuple[float, float, float]) -> float:
    def channel(v: float) -> float:
        s = v / 255
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(v) for v in color)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def check_labels(page: Any, orientation: str, on_screen: bool = False) -> None:
    page.get_by_test_id("board-files").locator("span").first.wait_for()
    drawn = page.evaluate(READ_LABELS)
    box, white = drawn["box"], orientation == "white"
    ranks, files = drawn["ranks"], drawn["files"]

    assert drawn["inBoard"] == 0, "chessground's own labels are back inside the squares"
    assert [x["label"] for x in ranks] == list(RANKS[::-1] if white else RANKS)
    assert [x["label"] for x in files] == list(FILES if white else FILES[::-1])
    for x in ranks:
        n = RANKS.index(x["label"])
        assert x["row"] == (7 - n if white else n), f"rank {x['label']} isn't level with its rank"
        assert x["right"] <= box["left"], f"rank {x['label']} overlaps the board"
    for x in files:
        n = FILES.index(x["label"])
        assert x["col"] == (n if white else 7 - n), f"file {x['label']} isn't under its file"
        assert x["top"] >= box["bottom"], f"file {x['label']} overlaps the board"
    for x in ranks + files:
        where = f"{x['label']} ({orientation})"
        assert x["visible"], f"{where} is hidden"
        assert x["font"] >= MIN_FONT_PX, f"{where} is {x['font']}px"
        assert x["opacity"] == 1, f"{where} has opacity {x['opacity']}"
        ratio = contrast(rgb(x["color"]), rgb(drawn["bg"]))
        assert ratio >= MIN_CONTRAST, f"{where} has contrast {ratio:.1f} against the page"
        if on_screen:
            assert x["bottom"] <= drawn["viewport"]["height"], f"{where} is below the window"
            assert x["left"] >= 0, f"{where} is off the left of the window"


def open_review(page: Any, game: int, query: str = "") -> None:
    page.goto(page.base_url + "/" + query)
    page.get_by_test_id("nav-games").click()
    page.get_by_test_id(f"review-{game}").click()
    page.get_by_test_id("review-view").wait_for()


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_game_review_board_as_white(page: Any, scheme: str) -> None:
    open_review(page, 1, f"?scheme={scheme}")
    check_labels(page, "white")


def test_game_review_board_as_black(page: Any) -> None:
    page.goto(page.base_url + "/")
    page.get_by_test_id("nav-games").click()
    page.get_by_test_id("review-2").click()  # the mock's game 2: you played black
    page.locator("[data-testid=board].orientation-black").wait_for()
    check_labels(page, "black")


@pytest.mark.parametrize("height", [600, 720, 1000])
def test_game_review_letters_are_in_the_window(page: Any, height: int) -> None:
    """The second report: the letters were drawn but below the bottom of the app's window."""
    page.set_viewport_size({"width": 1280, "height": height})
    open_review(page, 1)
    check_labels(page, "white", on_screen=True)


@pytest.mark.parametrize("height", [720, 820])
def test_an_unanalyzed_game_still_shows_the_letters(page: Any, height: int) -> None:
    """The Analyze panel above the board pushed it down, so the bottom row fell out of the window."""
    page.set_viewport_size({"width": 1280, "height": height})
    page.goto(page.base_url + "/")
    page.get_by_test_id("nav-games").click()
    page.get_by_test_id("review-2").click()
    page.get_by_test_id("review-not-analyzed").wait_for()
    page.locator("[data-testid=board].orientation-black").wait_for()
    check_labels(page, "black", on_screen=True)


def test_the_board_grows_back_when_the_window_does(page: Any) -> None:
    page.set_viewport_size({"width": 1280, "height": 600})
    open_review(page, 1)
    page.get_by_test_id("board-files").wait_for()
    small = page.get_by_test_id("board").bounding_box()["width"]
    page.set_viewport_size({"width": 1280, "height": 1000})
    for _ in range(50):  # the app's CSP forbids wait_for_function's eval
        if page.get_by_test_id("board").bounding_box()["width"] > small + 50:
            break
        page.wait_for_timeout(100)
    assert page.get_by_test_id("board").bounding_box()["width"] > small + 50


def test_retry_board(page: Any) -> None:
    page.set_viewport_size({"width": 1280, "height": 820})
    open_review(page, 1)
    page.get_by_test_id("retry-start").click()
    page.get_by_test_id("retry-mode").wait_for()
    check_labels(page, "white")
    play(page, "f3d4", "white")
    page.get_by_test_id("retry-result").wait_for()
    check_labels(page, "white")


def test_puzzle_board(page: Any) -> None:
    page.goto(page.base_url + "/")
    start(page)  # the mock's first puzzle: you play black
    check_labels(page, "black")


def test_small_board_keeps_each_label_by_its_square(page: Any) -> None:
    page.set_viewport_size({"width": 420, "height": 800})
    open_review(page, 1)
    check_labels(page, "white")


def test_hiding_coordinates_still_hides_them(page: Any) -> None:
    open_review(page, 1)
    labels = page.locator("[data-testid=board-ranks], [data-testid=board-files]")
    assert labels.count() == 2
    page.keyboard.press("c")
    labels.first.wait_for(state="detached")
    assert labels.count() == 0
    page.keyboard.press("c")
    labels.first.wait_for()
    assert labels.count() == 2


# ---- every other board (Adam, 2026-11-07: "puzzles doesnt have them") ----------------------------------------
# The Puzzles board was a fixed 560 px under the session bar, so in a shorter window its file letters were
# below the bottom edge, as on Game Review before. Every board at the top of its page now fits the window.


@pytest.mark.parametrize("height", [600, 720, 1000])
def test_puzzle_letters_are_in_the_window(page: Any, height: int) -> None:
    page.set_viewport_size({"width": 1280, "height": height})
    page.goto(page.base_url + "/")
    start(page)
    check_labels(page, "black", on_screen=True)


@pytest.mark.parametrize("height", [600, 720])
def test_puzzle_letters_are_in_the_window_with_filters_hidden(page: Any, height: int) -> None:
    page.set_viewport_size({"width": 1280, "height": height})
    page.goto(page.base_url + "/")
    start(page)
    page.get_by_test_id("hide-filters").click()
    page.get_by_test_id("filters-strip").wait_for()
    page.wait_for_timeout(300)
    check_labels(page, "black", on_screen=True)


@pytest.mark.parametrize("height", [600, 720])
def test_opening_practice_letters_are_in_the_window(page: Any, height: int) -> None:
    from tests.e2e.test_openings_ui import start_practice

    page.set_viewport_size({"width": 1280, "height": height})
    start_practice(page)
    orientation = page.get_by_test_id("board").evaluate(
        "(el) => el.classList.contains('orientation-black') ? 'black' : 'white'"
    )
    check_labels(page, orientation, on_screen=True)


def test_opening_learn_board_has_the_labels_once_scrolled_to(page: Any) -> None:
    """The learn board sits under the opening's lines, so you scroll to it; its labels are then all in view."""
    from tests.e2e.test_openings_ui import openings, pick

    page.set_viewport_size({"width": 1280, "height": 720})
    openings(page)
    pick(page, "Italian Game")
    page.get_by_test_id("board").scroll_into_view_if_needed()
    page.get_by_test_id("board-files").scroll_into_view_if_needed()
    check_labels(page, "white", on_screen=True)
