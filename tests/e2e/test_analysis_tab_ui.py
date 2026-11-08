"""v0.15 UI against the mock: the Analysis tab (REQUIREMENTS §20, FR-14.1-14.6). Invented data only
(web/src/api/mockAnalysisTab.ts)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.e2e.conftest import click_square, play
from tests.e2e.test_engine_ui import solve
from tests.e2e.test_engine_ui import start as start_puzzle
from tests.e2e.test_v010_ui import review
from tests.e2e.test_v012_tooltips import _assert_all_have_tips

pytestmark = pytest.mark.e2e

START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
PGN = """[Event "Invented Open"]
[White "Player A"]
[Black "Player B"]
[Result "1-0"]

1. e4 {A comment with https://example.org/x} e5 2. Nf3 Nc6 3. Bb5 1-0
"""
SECOND = """[White "Player C"]
[Black "Player D"]

1. d4 d5 *
"""


def analysis(page: Any, query: str = "") -> None:
    page.goto(page.base_url + "/" + query)
    page.get_by_test_id("nav-analysis").click()
    page.get_by_test_id("analysis-view").wait_for()


def calls(page: Any) -> list[str]:
    return list(page.evaluate("() => window.__mockApi.calls"))


def board(page: Any) -> Any:
    """The board on screen: the trainer stays mounted, hidden, with its own board while another tab shows."""
    return page.locator("[data-testid=board]:visible")


def fen(page: Any) -> str:
    return str(board(page).get_attribute("data-fen"))


def same(a: str, b: str) -> bool:
    return a.split()[:4] == b.split()[:4]


def wait_fen(page: Any, prefix: str) -> None:
    page.wait_for_function(
        "(p) => [...document.querySelectorAll('[data-testid=board]')].some((b) => b.offsetParent !== null"
        " && b.getAttribute('data-fen').startsWith(p))",
        arg=prefix,
    )


# ---- FR-14.1, 14.4: the tab, moves for either side, lines as branches ----------------------------------------


def test_the_tab_opens_at_the_start_and_keeps_two_lines_from_one_position(page: Any) -> None:
    analysis(page)
    assert fen(page) == START
    play(page, "e2e4", "white")
    play(page, "e7e5", "white")  # either side moves
    page.get_by_test_id("analysis-move").filter(has_text="1… e5").wait_for()
    page.get_by_test_id("analysis-back").click()
    play(page, "c7c5", "white")  # a different reply: a new line
    variation = page.get_by_test_id("analysis-variation")
    variation.wait_for()
    assert "c5" in variation.inner_text()
    page.get_by_test_id("analysis-main-line").click()
    wait_fen(page, "rnbqkbnr/pppppppp/8/8/4P3")  # back where the side line left the main line, after 1. e4
    page.get_by_test_id("analysis-moves").get_by_text("c5").click()
    wait_fen(page, "rnbqkbnr/pp1ppppp/8/2p5/4P3")
    page.keyboard.press("ArrowLeft")
    wait_fen(page, "rnbqkbnr/pppppppp/8/8/4P3")


def test_the_engine_and_its_arrow_follow_the_board(page: Any) -> None:
    analysis(page)
    play(page, "e2e4", "white")
    page.get_by_test_id("engine-line").first.wait_for()
    page.wait_for_function(
        "() => document.querySelector('[data-testid=analysis-view] [data-testid=board]').getAttribute('data-arrows')"
    )
    assert any(c.startswith("analyzeBoard:") for c in calls(page))


def test_lines_survive_switching_tabs(page: Any) -> None:
    analysis(page)
    play(page, "d2d4", "white")
    page.get_by_test_id("nav-studies").click()
    page.get_by_test_id("nav-analysis").click()
    page.get_by_test_id("analysis-move").filter(has_text="1. d4").wait_for()


# ---- FR-14.2: set up a position --------------------------------------------------------------------------------


def test_set_up_a_position_by_picking_pieces_and_clicking_squares(page: Any) -> None:
    analysis(page)
    page.get_by_test_id("analysis-setup").click()
    page.get_by_test_id("analysis-setup-panel").wait_for()
    page.get_by_test_id("setup-clear").click()
    page.get_by_test_id("spare-white-king").click()
    click_square(page, "e1", "white")
    page.get_by_test_id("spare-white-rook").click()
    click_square(page, "a1", "white")
    page.get_by_test_id("spare-black-king").click()
    click_square(page, "e8", "white")
    page.get_by_test_id("setup-done").click()
    page.get_by_test_id("analysis-setup-panel").wait_for(state="detached")
    assert fen(page) == "4k3/8/8/8/8/8/8/R3K3 w Q - 0 1"  # castling only where king and rook still stand


def test_an_impossible_position_gets_a_message_and_never_reaches_the_engine(page: Any) -> None:
    analysis(page)
    page.get_by_test_id("analysis-setup").click()
    page.get_by_test_id("setup-clear").click()
    page.get_by_test_id("spare-white-king").click()
    click_square(page, "e1", "white")
    before = [c for c in calls(page) if c.startswith("analyzeBoard:")]
    page.get_by_test_id("setup-done").click()
    problems = page.get_by_test_id("setup-problems")
    problems.wait_for()
    assert "Black has no king." in problems.inner_text()
    page.get_by_test_id("analysis-setup-panel").wait_for()  # still setting up
    page.wait_for_timeout(500)
    assert [c for c in calls(page) if c.startswith("analyzeBoard:")] == before


def test_castling_boxes_follow_the_pieces(page: Any) -> None:
    analysis(page)
    page.get_by_test_id("analysis-setup").click()
    assert page.get_by_test_id("setup-castle-K").is_enabled()
    page.get_by_test_id("spare-trash").click()
    click_square(page, "h1", "white")
    page.wait_for_function("() => document.querySelector('[data-testid=setup-castle-K]').disabled")
    assert page.get_by_test_id("setup-castle-Q").is_enabled()


def test_paste_a_fen_or_be_told_why_not(page: Any) -> None:
    analysis(page)
    page.get_by_test_id("analysis-setup").click()
    page.get_by_test_id("setup-fen").fill("not a fen")
    page.get_by_test_id("setup-fen-use").click()
    page.get_by_test_id("setup-problems").filter(has_text="isn't a FEN").wait_for()
    page.get_by_test_id("setup-fen").fill("4k3/8/8/8/8/8/4P3/4K3 b - - 0 1")
    page.get_by_test_id("setup-fen-use").click()
    page.get_by_test_id("analysis-setup-panel").wait_for(state="detached")
    assert fen(page) == "4k3/8/8/8/8/8/4P3/4K3 b - - 0 1"


def test_cancel_leaves_the_board_as_it_was(page: Any) -> None:
    analysis(page)
    play(page, "e2e4", "white")
    page.get_by_test_id("analysis-setup").click()
    page.get_by_test_id("setup-clear").click()
    page.get_by_test_id("setup-cancel").click()
    page.get_by_test_id("analysis-move").filter(has_text="1. e4").wait_for()


# ---- FR-14.3: import a PGN -------------------------------------------------------------------------------------


def test_a_pasted_pgn_opens_with_its_comment_as_text(page: Any) -> None:
    analysis(page)
    page.get_by_test_id("analysis-import-pgn").click()
    page.get_by_test_id("analysis-pgn-text").fill(PGN)
    page.get_by_test_id("analysis-pgn-read").click()
    page.get_by_test_id("analysis-pgn-text").wait_for(state="detached")
    moves = page.get_by_test_id("analysis-moves")
    moves.get_by_text("Bb5").wait_for()
    assert "Bb5" in moves.inner_text() and "https://example.org/x" in moves.inner_text()
    assert page.locator("[data-testid=analysis-moves] a").count() == 0  # never a link
    assert fen(page) == START  # opens at the start; step through it
    page.keyboard.press("ArrowRight")
    wait_fen(page, "rnbqkbnr/pppppppp/8/8/4P3")


def test_a_bad_pgn_says_why_and_changes_nothing(page: Any) -> None:
    analysis(page)
    play(page, "e2e4", "white")
    page.get_by_test_id("analysis-import-pgn").click()
    page.get_by_test_id("analysis-pgn-text").fill("1. e4 e5 2. Qxf7")
    page.get_by_test_id("analysis-pgn-read").click()
    page.get_by_test_id("analysis-pgn-error").wait_for()
    page.keyboard.press("Escape")
    page.get_by_test_id("analysis-move").filter(has_text="1. e4").wait_for()


def test_a_pgn_with_several_games_lets_you_pick_and_asks_before_replacing(page: Any) -> None:
    analysis(page)
    play(page, "g1f3", "white")
    page.get_by_test_id("analysis-import-pgn").click()
    page.get_by_test_id("analysis-pgn-text").fill(PGN + "\n" + SECOND)
    page.get_by_test_id("analysis-pgn-read").click()
    games = page.get_by_test_id("analysis-pgn-games")
    games.wait_for()
    assert "Player A – Player B" in games.inner_text() and "Player C – Player D" in games.inner_text()
    _assert_all_have_tips(page, "PGN pick list")
    games.get_by_text("Player C").click()
    page.get_by_test_id("analysis-pgn-open").click()
    page.get_by_test_id("analysis-confirm-keep").click()  # keep: Nf3 stays
    page.get_by_test_id("analysis-move").filter(has_text="1. Nf3").wait_for()
    page.get_by_test_id("analysis-import-pgn").click()
    page.get_by_test_id("analysis-pgn-text").fill(SECOND)
    page.get_by_test_id("analysis-pgn-read").click()
    page.get_by_test_id("analysis-confirm-replace").click()
    assert "d5" in page.get_by_test_id("analysis-moves").inner_text()


# ---- FR-14.4: popular replies ----------------------------------------------------------------------------------


def test_popular_replies_when_signed_in_and_a_click_plays_one(page: Any) -> None:
    analysis(page)
    rows = page.get_by_test_id("popular-move")
    rows.first.wait_for()
    assert rows.first.get_attribute("data-uci") == "e2e4"
    rows.first.click()
    wait_fen(page, "rnbqkbnr/pppppppp/8/8/4P3")
    page.locator("[data-testid=popular-move][data-uci=c7c5]").wait_for()


def test_popular_replies_say_sign_in_when_signed_out(page: Any) -> None:
    analysis(page, "?account=signed_out")
    page.get_by_test_id("popular-signed-out").wait_for()
    assert page.get_by_test_id("popular-move").count() == 0


# ---- FR-14.6: Open in Analysis tab -----------------------------------------------------------------------------


def test_open_in_analysis_tab_from_a_finished_puzzle(page: Any) -> None:
    start_puzzle(page)
    solve(page)
    page.get_by_test_id("analyze-button").click()
    page.get_by_test_id("analysis-controls").wait_for()
    here = fen(page)
    page.get_by_test_id("analysis-open-tab").click()
    page.get_by_test_id("analysis-view").wait_for()
    assert same(fen(page), here)
    # The puzzle's moves from its start come with it: you can step back through them.
    assert page.get_by_test_id("analysis-moves").locator("[data-move-id]").count() >= 3
    page.get_by_test_id("analysis-back").click()
    assert not same(fen(page), here)


def test_open_in_analysis_tab_from_game_review_with_its_moves(page: Any) -> None:
    review(page)
    page.get_by_test_id("review-next").click()
    page.get_by_test_id("review-next").click()
    page.get_by_test_id("review-analyze-here").click()
    page.get_by_test_id("review-free").wait_for()
    here = fen(page)
    page.get_by_test_id("analysis-open-tab").click()
    page.get_by_test_id("analysis-view").wait_for()
    assert same(fen(page), here)
    assert page.get_by_test_id("analysis-moves").locator("[data-move-id]").count() >= 2
    page.get_by_test_id("analysis-move").filter(has_text="1…").wait_for()  # after the game's second move


def test_open_in_analysis_tab_asks_before_replacing_your_lines(page: Any) -> None:
    analysis(page)
    play(page, "b2b3", "white")
    page.get_by_test_id("nav-games").click()  # not review(): a page load would start the app afresh
    page.get_by_test_id("review-1").click()
    page.get_by_test_id("review-analyze-here").click()
    page.get_by_test_id("analysis-open-tab").click()
    page.get_by_test_id("analysis-confirm-keep").click()
    page.get_by_test_id("analysis-move").filter(has_text="1. b3").wait_for()


# ---- FR-10.72: tooltips ----------------------------------------------------------------------------------------


def test_analysis_options_have_tooltips(page: Any) -> None:
    analysis(page)
    _assert_all_have_tips(page, "Analysis tab")
    page.get_by_test_id("analysis-setup").click()
    page.get_by_test_id("analysis-setup-panel").wait_for()
    _assert_all_have_tips(page, "Set up a position")
    page.get_by_test_id("setup-cancel").click()
    page.get_by_test_id("analysis-import-pgn").click()
    page.get_by_test_id("analysis-pgn-text").wait_for()
    _assert_all_have_tips(page, "Import a PGN")
