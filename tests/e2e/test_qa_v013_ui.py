"""QA v0.13: the Openings page's state against the mock (FR-12.6, 12.8-12.10, 12.15, 12.16): the what-if preview and the board
behind it, what's kept across a change of step, line or color, and screenshots. A test exposing an open bug is xfail with its ID."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.e2e.conftest import play

pytestmark = pytest.mark.e2e
ART = Path("tests/e2e/artifacts")
READY = "?openings=ready&engine=ready"
AI = READY + "&ai=on"


def openings(page: Any, query: str = READY) -> None:
    page.goto(page.base_url + "/" + query)
    page.get_by_test_id("nav-openings").click()
    page.get_by_test_id("openings-view").wait_for()


def pick(page: Any, name: str = "Italian Game") -> None:
    page.locator(f"[data-testid=opening-family][data-name='{name}']").click()
    page.get_by_test_id("opening-lines").wait_for()


def shot(page: Any, name: str) -> None:
    ART.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(ART / f"qa-v013-{name}.png"), full_page=True)


def pieces(page: Any) -> dict[str, str]:
    """What chessground is really drawing: square -> piece class. `data-fen` is only what React last asked for."""
    return page.evaluate(
        """() => Object.fromEntries([...document.querySelectorAll('[data-testid=board] cg-board piece')]
            .filter((p) => !p.classList.contains('ghost')).map((p) => [p.cgKey, p.className]))"""
    )


def fen(page: Any) -> str:
    return page.get_by_test_id("board").get_attribute("data-fen") or ""


# ---- what if: the preview and the board ---------------------------------------------------------------------------


def test_clear_puts_the_board_back_after_a_typed_move(page: Any) -> None:
    openings(page)
    pick(page)
    page.get_by_test_id("learn-forward").click()
    at = fen(page)
    page.get_by_test_id("what-if-move").fill("a6")
    page.get_by_test_id("what-if-go").click()
    page.get_by_test_id("what-if-replies").wait_for()
    assert fen(page) != at
    page.get_by_test_id("what-if-clear").click()
    page.get_by_test_id("what-if-replies").wait_for(state="detached")
    assert fen(page) == at
    page.wait_for_timeout(350)
    assert "a6" not in pieces(page) and "a7" in pieces(page)


def test_clear_puts_the_board_back_after_a_move_on_the_board(page: Any) -> None:
    openings(page)
    pick(page)
    page.get_by_test_id("learn-forward").click()
    at = fen(page)
    play(page, "a7a6", "white")
    page.get_by_test_id("what-if-replies").wait_for()
    page.get_by_test_id("what-if-clear").click()
    page.wait_for_timeout(1000)
    assert page.get_by_test_id("what-if-replies").count() == 0
    assert fen(page) == at


def test_stepping_away_clears_the_preview(page: Any) -> None:
    openings(page)
    pick(page)
    page.get_by_test_id("learn-forward").click()
    at = fen(page)
    page.get_by_test_id("what-if-move").fill("a6")
    page.get_by_test_id("what-if-go").click()
    page.get_by_test_id("what-if-replies").wait_for()
    assert fen(page) != at
    page.get_by_test_id("learn-back").click()
    page.wait_for_timeout(300)
    assert " w " in fen(page) and "/p" not in fen(page).split()[0].split("/")[2]


def test_changing_color_starts_the_line_over_with_no_preview(page: Any) -> None:
    openings(page)
    pick(page)
    page.get_by_test_id("learn-forward").click()
    page.get_by_test_id("what-if-move").fill("a6")
    page.get_by_test_id("what-if-go").click()
    page.get_by_test_id("what-if-replies").wait_for()
    page.get_by_test_id("opening-color").get_by_text("As Black").click()
    page.locator("[data-testid=board].orientation-black").wait_for()
    assert page.get_by_test_id("what-if-replies").count() == 0
    assert fen(page).startswith("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w")


def test_changing_line_starts_it_over(page: Any) -> None:
    openings(page)
    pick(page)
    page.get_by_test_id("learn-forward").click()
    page.get_by_test_id("opening-line-1").click()
    page.wait_for_timeout(200)
    assert fen(page).startswith("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w")


def test_switching_to_play_along_clears_a_preview(page: Any) -> None:
    openings(page)
    pick(page)
    page.get_by_test_id("learn-forward").click()
    page.get_by_test_id("what-if-move").fill("a6")
    page.get_by_test_id("what-if-go").click()
    page.get_by_test_id("what-if-replies").wait_for()
    page.get_by_test_id("learn-mode").get_by_text("Play along").click()
    page.get_by_test_id("learn-play-status").wait_for()
    assert page.get_by_test_id("what-if").count() == 0
    # The preview is cleared by an effect just after this render, so wait for it (QA round 2: a full run caught it mid-way).
    page.wait_for_function(
        "() => document.querySelector('[data-testid=board]').dataset.fen.startsWith('rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w')"
    )


def test_a_refused_what_if_on_the_board_puts_the_piece_back(page: Any) -> None:
    openings(page, "?openings=ready&engine=missing")  # no engine: the backend refuses every what-if
    pick(page)
    page.get_by_test_id("learn-forward").click()
    play(page, "a7a6", "white")
    page.get_by_test_id("what-if-error").wait_for()
    page.wait_for_timeout(350)
    assert "a7" in pieces(page) and "a6" not in pieces(page)


def test_adding_a_board_played_what_if_keeps_the_message_and_your_reply(page: Any) -> None:
    openings(page)
    pick(page)
    page.get_by_test_id("learn-forward").click()
    play(page, "a7a6", "white")
    page.get_by_test_id("what-if-replies").wait_for()
    page.get_by_test_id("what-if-reply").nth(1).click()
    page.get_by_test_id("what-if-add").click()
    page.get_by_test_id("what-if-saved").wait_for()
    page.wait_for_timeout(500)
    assert page.get_by_test_id("what-if-saved").count() == 1
    assert page.get_by_test_id("what-if-reply").nth(1).is_checked()


def test_adding_a_typed_what_if_keeps_the_message(page: Any) -> None:
    openings(page)
    pick(page)
    page.get_by_test_id("learn-forward").click()
    page.get_by_test_id("what-if-move").fill("a6")
    page.get_by_test_id("what-if-go").click()
    page.get_by_test_id("what-if-replies").wait_for()
    page.get_by_test_id("what-if-add").click()
    page.get_by_test_id("what-if-saved").wait_for()
    page.wait_for_timeout(500)
    assert page.get_by_test_id("what-if-saved").count() == 1


def test_jumping_to_another_of_their_turns_drops_the_old_replies(page: Any) -> None:
    openings(page)
    pick(page)
    page.get_by_test_id("learn-forward").click()  # after 1.e4: their move
    page.get_by_test_id("what-if-move").fill("a6")
    page.get_by_test_id("what-if-go").click()
    page.get_by_test_id("what-if-replies").wait_for()
    page.get_by_test_id("learn-move-2").click()  # after 2.Nf3: their move again, with no step between
    page.wait_for_timeout(200)
    assert page.get_by_test_id("what-if-replies").count() == 0


def test_a_wrong_move_in_play_along_redraws_the_right_position(page: Any) -> None:
    openings(page)
    pick(page)
    page.get_by_test_id("learn-mode").get_by_text("Play along").click()
    play(page, "d2d4", "white")
    page.locator("[data-testid=learn-board][data-tries='1']").wait_for()
    page.wait_for_timeout(350)
    assert "d2" in pieces(page) and "d4" not in pieces(page)
    page.get_by_test_id("learn-nudge").wait_for()
    play(page, "e2e4", "white")
    page.wait_for_timeout(600)
    assert "e4" in pieces(page) and "e5" in pieces(page)  # the app replied
    assert page.get_by_test_id("learn-nudge").count() == 0


def test_their_side_cant_be_moved_in_play_along(page: Any) -> None:
    openings(page)
    pick(page)
    page.get_by_test_id("learn-mode").get_by_text("Play along").click()
    play(page, "e7e5", "white")
    page.wait_for_timeout(300)
    assert "e7" in pieces(page) and page.locator("[data-testid=learn-board][data-tries='0']").count() == 1


def test_your_side_is_read_only_in_step_through_on_your_turn(page: Any) -> None:
    openings(page)
    pick(page)
    play(page, "e2e4", "white")
    page.wait_for_timeout(300)
    assert "e2" in pieces(page) and page.get_by_test_id("what-if").count() == 0


# ---- Practice ---------------------------------------------------------------------------------------------------------


def _start_practice(page: Any) -> None:
    pick(page)
    page.get_by_test_id("opening-add-0").click()
    page.get_by_test_id("opening-added").wait_for()
    page.get_by_test_id("openings-tab-practice").click()
    page.get_by_test_id("practice-begin").click()
    page.get_by_test_id("practice-session").wait_for()


def test_a_session_can_be_limited_to_one_branch_from_the_screen(page: Any) -> None:
    openings(page)
    pick(page)
    page.get_by_test_id("opening-add-0").click()
    page.get_by_test_id("opening-added").wait_for()
    page.get_by_test_id("openings-tab-practice").click()
    page.get_by_test_id("practice-begin").wait_for()
    assert page.get_by_test_id("practice-branch").count() == 1


def test_a_miss_shows_the_refutation_not_only_a_score(page: Any) -> None:
    openings(page)
    _start_practice(page)
    play(page, "d2d4", "white")
    page.get_by_test_id("practice-refutation").wait_for()
    text = page.get_by_test_id("practice-refutation").inner_text()
    assert any(ch in text for ch in "abcdefgh" if f"{ch}" and any(f"{ch}{n}" in text for n in "12345678"))


def test_an_engine_only_note_says_so(page: Any) -> None:
    openings(page, AI)
    pick(page)
    page.get_by_test_id("opening-wikibooks").click()
    page.get_by_test_id("overview-note-button").click()
    block = page.get_by_test_id("overview-note").get_by_test_id("opening-note")
    block.wait_for()
    assert block.get_by_test_id("opening-note-credit").count() == 0
    assert page.get_by_test_id("opening-note-engine-only").count() >= 1


# ---- screenshots -------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_screenshots_of_every_screen(page: Any, scheme: str) -> None:
    openings(page, f"{AI}&scheme={scheme}")
    pick(page)
    shot(page, f"book-{scheme}")
    page.get_by_test_id("learn-forward").click()
    page.get_by_test_id("what-if-move").fill("a6")
    page.get_by_test_id("what-if-go").click()
    page.get_by_test_id("what-if-replies").wait_for()
    shot(page, f"what-if-{scheme}")
    page.get_by_test_id("what-if-clear").click()
    page.get_by_test_id("opening-prefetch").click()
    page.get_by_test_id("prefetch-plan").wait_for()
    shot(page, f"prefetch-{scheme}")
    page.keyboard.press("Escape")
    page.get_by_test_id("prefetch-plan").wait_for(state="detached")
    page.get_by_test_id("opening-build").click()
    page.get_by_test_id("build-start").wait_for()
    page.get_by_test_id("build-start").click()
    page.get_by_test_id("build-save").wait_for()
    shot(page, f"build-{scheme}")
    page.get_by_test_id("build-save").click()
    page.get_by_test_id("build-saved").wait_for()
    page.keyboard.press("Escape")
    page.get_by_test_id("openings-tab-repertoire").click()
    page.get_by_test_id("repertoire-rows").wait_for()
    shot(page, f"repertoire-{scheme}")
    page.get_by_test_id("openings-tab-practice").click()
    page.get_by_test_id("practice-begin").click()
    page.get_by_test_id("practice-session").wait_for()
    shot(page, f"practice-{scheme}")
    play(page, "a2a3", "white")
    page.get_by_test_id("practice-missed").wait_for()
    shot(page, f"practice-wrong-{scheme}")
    page.get_by_test_id("openings-tab-stats").click()
    page.get_by_test_id("opening-stats").wait_for()
    shot(page, f"stats-{scheme}")
