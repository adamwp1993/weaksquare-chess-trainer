"""Regression (Adam, 2026-11-06): the board's file letters and rank numbers were close to unreadable.

chessground drew them at 9px and 80% opacity, and its theme put white numbers on light squares and dark
numbers on dark ones, so on the My games board they looked missing. Every board goes through `Board`, so
these check the labels as drawn: all present, on the right square, large enough, and readable on both square
colors. They run on Puzzles, Game Review and Retry, in both orientations and color schemes.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.e2e.conftest import play
from tests.e2e.test_trainer_v02 import start

pytestmark = pytest.mark.e2e

FILES = "ABCDEFGH"
RANKS = "12345678"
MIN_FONT_PX = 11
MIN_CONTRAST = 4.5  # WCAG AA for small text; every label stays above it on light and dark squares

READ_LABELS = """
() => {
  const board = document.querySelector('[data-testid=board]');
  const box = board.getBoundingClientRect();
  const read = (kind) => [...board.querySelectorAll(`coords.${kind} coord`)].map((el) => {
    const rect = el.getBoundingClientRect();
    const range = document.createRange();
    range.selectNodeContents(el);
    const text = range.getBoundingClientRect();
    const style = getComputedStyle(el);
    let opacity = 1;
    for (let n = el; n && n !== board; n = n.parentElement) opacity *= Number(getComputedStyle(n).opacity);
    return {
      label: el.textContent.trim().toUpperCase(),
      font: parseFloat(style.fontSize),
      color: style.color,
      opacity,
      col: Math.floor(((rect.left + rect.right) / 2 - box.left) / (box.width / 8)),
      row: Math.floor(((rect.top + rect.bottom) / 2 - box.top) / (box.height / 8)),
      inside: text.left >= box.left && text.right <= box.right && text.top >= box.top && text.bottom <= box.bottom,
    };
  });
  return {
    ranks: read('ranks'),
    files: read('files'),
    light: getComputedStyle(board.querySelector('cg-board')).backgroundColor,
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


def check_labels(page: Any, orientation: str) -> None:
    page.locator("[data-testid=board] coords coord").first.wait_for()
    drawn = page.evaluate(READ_LABELS)
    light = rgb(drawn["light"])
    dark = (light[0] * 0.8, light[1] * 0.8, light[2] * 0.8)  # the theme darkens alternate squares by 20%
    white = orientation == "white"

    ranks, files = drawn["ranks"], drawn["files"]
    assert sorted(x["label"] for x in ranks) == list(RANKS)
    assert sorted(x["label"] for x in files) == list(FILES)
    for x in ranks:
        n = RANKS.index(x["label"])
        assert (x["col"], x["row"]) == (0, 7 - n if white else n), f"rank {x['label']} is on the wrong square"
    for x in files:
        n = FILES.index(x["label"])
        assert (x["col"], x["row"]) == (n if white else 7 - n, 7), f"file {x['label']} is on the wrong square"
    for x in ranks + files:
        where = f"{x['label']} ({orientation})"
        assert x["inside"], f"{where} is clipped by the board's edge"
        assert x["font"] >= MIN_FONT_PX, f"{where} is {x['font']}px"
        assert x["opacity"] == 1, f"{where} has opacity {x['opacity']}"
        for name, square in (("light", light), ("dark", dark)):
            ratio = contrast(rgb(x["color"]), square)
            assert ratio >= MIN_CONTRAST, f"{where} has contrast {ratio:.1f} on a {name} square"


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


def test_retry_board(page: Any) -> None:
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


def test_small_board_keeps_each_label_on_its_square(page: Any) -> None:
    page.set_viewport_size({"width": 420, "height": 800})
    open_review(page, 1)
    check_labels(page, "white")


def test_hiding_coordinates_still_hides_them(page: Any) -> None:
    open_review(page, 1)
    labels = page.locator("[data-testid=board] coords")
    assert labels.count() > 0
    page.keyboard.press("c")
    labels.first.wait_for(state="detached")
    assert labels.count() == 0
