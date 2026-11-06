"""v0.13a UI against the mock: the Openings page (FR-12.1-12.6, 12.13, 12.16)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.e2e.conftest import play
from tests.e2e.test_v012_tooltips import _assert_all_have_tips

pytestmark = pytest.mark.e2e


def openings(page: Any, query: str = "?openings=ready&engine=ready") -> None:
    page.goto(page.base_url + "/" + query)
    page.get_by_test_id("nav-openings").click()
    page.get_by_test_id("openings-view").wait_for()


def pick(page: Any, name: str) -> None:
    page.locator(f"[data-testid=opening-family][data-name='{name}']").click()
    page.get_by_test_id("opening-lines").wait_for()


def test_the_first_visit_imports_the_book(page: Any) -> None:
    page.goto(page.base_url + "/")
    page.get_by_test_id("nav-openings").click()
    page.get_by_test_id("openings-view").wait_for()
    assert page.get_by_test_id("opening-family").count() == 3


def test_search_narrows_the_list(page: Any) -> None:
    openings(page)
    page.get_by_test_id("openings-search").fill("caro")
    page.locator("[data-testid=opening-family]").filter(has_text="Caro-Kann").wait_for()
    page.get_by_test_id("openings-search").fill("nothing like this")
    page.get_by_text("No opening matches that.").wait_for()


def test_presets_change_how_many_lines_show(page: Any) -> None:
    openings(page)
    pick(page, "Italian Game")
    assert page.get_by_test_id("opening-lines").locator("[data-testid^=opening-line-]").count() == 4
    page.get_by_test_id("opening-preset").get_by_text("Light").click()
    page.get_by_test_id("opening-line-2").wait_for(state="detached")
    assert page.get_by_test_id("opening-lines").locator("[data-testid^=opening-line-]").count() == 2
    page.get_by_test_id("opening-preset").get_by_text("Custom").click()
    page.get_by_test_id("opening-sub-lines").wait_for()


def test_extending_labels_stockfish_moves_and_stop_removes_them(page: Any) -> None:
    openings(page)
    pick(page, "Italian Game")
    page.get_by_test_id("opening-extend-run").click()
    page.locator("[data-testid=learn-moves] [data-source=engine]").first.wait_for()
    assert "Stockfish" in page.get_by_test_id("learn-moves").inner_text()
    page.get_by_test_id("opening-extend").get_by_text("Stop at the book's end").click()
    page.locator("[data-testid=learn-moves] [data-source=engine]").first.wait_for(state="detached")
    assert page.get_by_test_id("opening-extend-offer").count() == 0


def test_step_through_moves_the_board_forward_and_back(page: Any) -> None:
    openings(page)
    pick(page, "Italian Game")
    board = page.get_by_test_id("board")
    start = board.get_attribute("data-fen")
    page.get_by_test_id("learn-forward").click()
    assert board.get_attribute("data-fen") != start
    page.get_by_test_id("learn-back").click()
    assert board.get_attribute("data-fen") == start


def test_play_along_replies_nudges_and_never_scores(page: Any) -> None:
    openings(page)
    pick(page, "Italian Game")
    page.get_by_test_id("learn-mode").get_by_text("Play along").click()
    page.get_by_text("Your move.").wait_for()
    board = page.get_by_test_id("board")
    start = board.get_attribute("data-fen")
    play(page, "d2d4", "white")  # the line plays e4
    page.locator("[data-testid=learn-board][data-tries='1']").wait_for()
    page.get_by_test_id("learn-nudge").filter(has_text="e2").wait_for()
    assert board.get_attribute("data-fen") == start
    play(page, "d2d4", "white")  # the same wrong move again still snaps back
    page.locator("[data-testid=learn-board][data-tries='2']").wait_for()
    assert board.get_attribute("data-fen") == start
    play(page, "e2e4", "white")
    page.wait_for_function("() => document.querySelector('[data-testid=board]').dataset.fen.includes('/4p3/4P3/')")
    page.get_by_test_id("learn-play-status").filter(has_text="Your move.").wait_for()
    assert page.get_by_test_id("learn-nudge").count() == 0


def test_play_along_hides_the_moves_still_to_come(page: Any) -> None:
    openings(page)
    pick(page, "Italian Game")
    assert "Bc4" in page.get_by_test_id("learn-moves").inner_text()
    page.get_by_test_id("learn-mode").get_by_text("Play along").click()
    assert "Bc4" not in page.get_by_test_id("learn-moves").inner_text()


def test_as_black_turns_the_board_and_the_app_moves_first(page: Any) -> None:
    openings(page)
    pick(page, "Caro-Kann Defense")
    page.get_by_test_id("opening-color").get_by_text("As Black").click()
    page.locator("[data-testid=board].orientation-black").wait_for()
    page.get_by_test_id("learn-mode").get_by_text("Play along").click()
    page.get_by_text("Your move.").wait_for()  # after the app's 1.e4
    assert " b " in (page.get_by_test_id("board").get_attribute("data-fen") or "")


def test_lines_join_your_repertoire_and_can_be_removed(page: Any) -> None:
    openings(page)
    pick(page, "Italian Game")
    page.get_by_test_id("opening-add-0").click()
    page.get_by_test_id("opening-added").filter(has_text="Added").wait_for()
    page.get_by_test_id("opening-add-0").click()
    page.get_by_test_id("opening-added").filter(has_text="already have").wait_for()
    page.get_by_test_id("opening-add-1").click()
    page.get_by_test_id("opening-added").filter(has_text="stayed as they were").wait_for()
    page.get_by_test_id("openings-tab-repertoire").click()
    page.get_by_test_id("repertoire-rows").wait_for()
    assert "Italian Game (C50)" in page.get_by_test_id("repertoire-openings").inner_text()
    rows = page.get_by_test_id("repertoire-row")
    total = rows.count()
    nf6 = rows.filter(has_text="Nf6").last
    nf6.get_by_test_id("repertoire-remove").click()
    page.get_by_test_id("repertoire-confirm").wait_for()
    page.get_by_test_id("repertoire-confirm-remove").click()
    page.get_by_test_id("repertoire-confirm").wait_for(state="detached")
    assert 0 < rows.count() < total


def test_your_color_is_kept_separate(page: Any) -> None:
    openings(page)
    pick(page, "Italian Game")
    page.get_by_test_id("opening-add-0").click()
    page.get_by_test_id("opening-added").wait_for()
    page.get_by_test_id("openings-tab-repertoire").click()
    page.get_by_test_id("repertoire-rows").wait_for()
    page.get_by_test_id("repertoire-color").get_by_text("Black").click()
    page.get_by_test_id("repertoire-empty").wait_for()


def test_every_option_has_a_tooltip(page: Any) -> None:
    openings(page)
    pick(page, "Italian Game")
    page.get_by_test_id("opening-preset").get_by_text("Custom").click()
    page.get_by_test_id("opening-sub-lines").wait_for()
    _assert_all_have_tips(page, "Openings")
    page.get_by_test_id("openings-tab-repertoire").click()
    page.get_by_test_id("repertoire-tab").wait_for()
    _assert_all_have_tips(page, "My repertoire")


def test_coordinates_show_here_too(page: Any) -> None:
    openings(page)
    pick(page, "Italian Game")
    assert page.locator("[data-testid=board] coords").count() > 0
