"""v0.14 UI against the mock: the Studies tab (FR-13.1-13.10). Invented studies only (web/src/api/mockStudies.ts)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.e2e.conftest import play
from tests.e2e.test_v012_tooltips import _assert_all_have_tips

pytestmark = pytest.mark.e2e


def studies(page: Any) -> None:
    page.goto(page.base_url + "/")
    page.get_by_test_id("nav-studies").click()
    page.get_by_test_id("studies-view").wait_for()


def calls(page: Any) -> list[str]:
    return list(page.evaluate("() => window.__mockApi.calls"))


def find_tab(page: Any) -> None:
    page.get_by_test_id("studies-tab-find").click()
    page.get_by_test_id("study-paste").wait_for()


def test_my_studies_lists_progress_hearts_and_filters(page: Any) -> None:
    studies(page)
    card = page.get_by_test_id("study-card")
    assert card.count() == 1
    assert card.get_by_test_id("study-title").inner_text() == "Invented gamebook"
    assert "1 of 2 chapters done" in card.inner_text() and "The plan" in card.inner_text()
    page.get_by_test_id("studies-filter").get_by_text("Finished").click()
    page.get_by_test_id("studies-empty").wait_for()
    page.get_by_test_id("studies-filter").get_by_text("Favorites").click()
    page.get_by_test_id("study-card").wait_for()
    page.get_by_test_id("study-heart").click()
    page.get_by_test_id("studies-empty").wait_for()
    assert "studyHeart:TestGb01:false" in calls(page)


def test_paste_refuses_a_non_study_address_without_a_request(page: Any) -> None:
    studies(page)
    find_tab(page)
    page.get_by_test_id("study-paste").fill("https://lichess.org/abcdefgh")
    page.get_by_test_id("study-paste-add").click()
    notice = page.get_by_test_id("study-notice")
    notice.wait_for()
    assert "isn't a Lichess study link" in notice.inner_text()
    assert not [c for c in calls(page) if c.startswith("addStudy")]


def test_paste_adds_and_opens_the_study_with_side_lines_and_a_text_chapter(page: Any) -> None:
    studies(page)
    find_tab(page)
    page.get_by_test_id("study-paste").fill("https://lichess.org/study/TestNm02")
    page.get_by_test_id("study-paste-add").click()
    page.get_by_test_id("study-page").wait_for()
    assert page.get_by_test_id("study-page-title").inner_text() == "Invented analysis"
    chapters = page.get_by_test_id("study-chapter")
    assert chapters.count() == 3
    assert "Can't be used" in chapters.nth(1).inner_text()
    # The comment's web address is text, not a link (FR-13.7).
    moves = page.get_by_test_id("study-moves")
    moves.wait_for()
    assert "https://example.com/notes" in moves.inner_text()
    assert page.locator("[data-testid=study-moves] a").count() == 0
    assert page.get_by_test_id("study-variation").count() >= 1
    # Step forward, into a side line and back to the main line.
    page.get_by_test_id("study-forward").click()
    page.get_by_test_id("study-forward").click()
    page.get_by_test_id("study-forward").click()
    assert page.get_by_test_id("study-current-move").inner_text().endswith("Nc3")
    page.locator("[data-testid=study-variation] [data-move-id]").filter(has_text="Nc6").first.click()
    page.get_by_test_id("study-main-line").click()
    assert page.get_by_test_id("study-current-move").inner_text().endswith("Nc3")
    # The text chapter: its text, no moves, nothing to play.
    chapters.nth(2).click()
    page.get_by_text("Thanks for studying! This board is empty on purpose.").wait_for()
    assert page.get_by_test_id("study-nav").count() == 0


def test_a_move_on_the_board_follows_the_chapter(page: Any) -> None:
    studies(page)
    find_tab(page)
    page.get_by_test_id("study-paste").fill("TestNm02")
    page.get_by_test_id("study-paste-add").click()
    page.get_by_test_id("study-moves").wait_for()
    play(page, "e2e4", "white")
    assert page.get_by_test_id("study-current-move").inner_text().endswith("e4")
    play(page, "d7d5", "white")
    assert page.get_by_test_id("study-feedback").inner_text() == "That move isn't in this chapter."


def test_gamebook_play_along_with_a_covered_wrong_move(page: Any) -> None:
    studies(page)
    page.get_by_test_id("study-continue").click()
    page.get_by_test_id("study-page").wait_for()
    # Continue went back to "The plan" after 1. e4 c6; open "Welcome" from its start instead.
    page.get_by_test_id("study-chapter").nth(0).click()
    page.get_by_test_id("study-comment").filter(has_text="Play the moves for Black.").wait_for()
    page.get_by_test_id("study-turn").filter(has_text="Your move.").wait_for()  # the app played 1. e4
    play(page, "e7e5", "black")
    assert "different opening" in page.get_by_test_id("study-feedback").inner_text()
    play(page, "c7c6", "black")
    page.get_by_test_id("study-comment").filter(has_text="Prepare d5.").wait_for()
    page.get_by_test_id("study-turn").filter(has_text="Your move.").wait_for()
    play(page, "d7d5", "black")
    page.get_by_test_id("study-end").wait_for()
    assert any(c == "studyDone:TestGb01:Chap0001:true" for c in calls(page))
    # Your place is saved a moment after you stop moving (FR-13.10).
    page.wait_for_function(
        "() => window.__mockApi.calls.includes('studyPlace:TestGb01:Chap0001:e2e4 c7c6 d2d4 d7d5')", timeout=5000
    )


def test_continue_returns_to_your_place(page: Any) -> None:
    studies(page)
    page.get_by_test_id("study-continue").click()
    page.get_by_test_id("study-chapter-title").filter(has_text="The plan").wait_for()
    page.get_by_test_id("study-turn").filter(has_text="Waiting for the other side…").or_(
        page.get_by_test_id("study-turn").filter(has_text="Your move.")
    ).wait_for()


def test_author_search_and_starter_list(page: Any) -> None:
    studies(page)
    find_tab(page)
    page.get_by_test_id("study-author").fill("nobody_here")
    page.get_by_test_id("study-author-search").click()
    assert "no user called" in page.get_by_test_id("study-author-error").inner_text()
    page.get_by_test_id("study-author").fill("https://lichess.org/@/player_author")
    page.get_by_test_id("study-author-search").click()
    results = page.get_by_test_id("study-author-results")
    results.wait_for()
    assert "Invented analysis" in results.inner_text()
    starter = page.get_by_test_id("study-starter")
    assert "Invented starter study" in starter.inner_text()
    page.get_by_test_id("study-starter-opening").click()
    page.get_by_role("option", name="Vienna Game").click()
    assert "Invented starter study" not in starter.inner_text()
    starter.get_by_role("button", name="Add").click()
    page.get_by_test_id("study-page-title").filter(has_text="Invented analysis").wait_for()


def test_a_private_study_with_an_old_sign_in_offers_sign_in_again(page: Any) -> None:
    studies(page)
    find_tab(page)
    page.get_by_test_id("study-paste").fill("TestPr03")
    page.get_by_test_id("study-paste-add").click()
    notice = page.get_by_test_id("study-notice")
    notice.get_by_test_id("study-sign-in").wait_for()
    assert "Sign in again" in notice.inner_text()


def test_lichess_window_and_browser_buttons(page: Any) -> None:
    studies(page)
    find_tab(page)
    page.get_by_test_id("study-open-browser").click()
    page.get_by_test_id("study-open-window").click()
    page.get_by_test_id("study-open-window").filter(has_text="Bring the Lichess window forward").wait_for()
    assert "openLichessStudiesInBrowser" in calls(page) and "openLichessWindow" in calls(page)
    # Add this study in the window: the study downloads and opens like a pasted one (FR-13.4).
    page.evaluate("() => window.__mockApi.mockLichessWindowAdd('TestNm02')")
    page.get_by_test_id("study-page-title").filter(has_text="Invented analysis").wait_for()


def test_check_for_updates_asks_before_changing_your_copy(page: Any) -> None:
    studies(page)
    page.get_by_test_id("study-continue").click()
    page.get_by_test_id("study-menu").click()
    page.get_by_test_id("study-check-updates").click()
    review = page.get_by_test_id("study-update")
    review.wait_for()
    assert "Changed chapters: The plan" in review.inner_text()
    assert not [c for c in calls(page) if c.startswith("studyApply")]
    page.get_by_test_id("study-update-apply").click()
    page.get_by_test_id("study-update-note").filter(has_text="Your copy is updated.").wait_for()


def test_delete_asks_first(page: Any) -> None:
    studies(page)
    page.get_by_test_id("study-continue").click()
    page.get_by_test_id("study-menu").click()
    page.get_by_test_id("study-delete").click()
    page.get_by_test_id("study-delete-confirm").click()
    page.get_by_test_id("studies-empty").wait_for()


def test_studies_options_have_tooltips(page: Any) -> None:
    studies(page)
    _assert_all_have_tips(page, "My studies")
    find_tab(page)
    _assert_all_have_tips(page, "Find studies")


def test_add_to_repertoire_previews_asks_at_a_conflict_and_saves(page: Any) -> None:
    studies(page)
    find_tab(page)
    page.get_by_test_id("study-paste").fill("TestNm02")
    page.get_by_test_id("study-paste-add").click()
    page.get_by_test_id("study-moves").wait_for()
    page.get_by_test_id("study-menu").click()
    page.get_by_test_id("study-add-repertoire").click()
    modal = page.get_by_test_id("study-rep-modal")
    summary = modal.get_by_test_id("study-rep-summary")
    summary.wait_for()
    assert "Adds 4 moves for you and 4 replies" in summary.inner_text()
    conflict = modal.get_by_test_id("study-rep-conflict")
    assert "After 1. e4 e5: you play Nf3, the study plays Nc3" in conflict.inner_text()
    _assert_all_have_tips(page, "Add to my repertoire")
    modal.get_by_test_id("study-rep-side-lines").click()
    modal.get_by_test_id("study-rep-summary").filter(has_text="Adds 6 moves for you").wait_for()
    modal.get_by_test_id("study-rep-conflict").get_by_text("Use the study's").click()
    modal.get_by_test_id("study-rep-save").click()
    done = page.get_by_test_id("study-rep-done")
    done.wait_for()
    assert "White repertoire" in done.inner_text() and "Openings → Practice" in done.inner_text()
    assert any(c.startswith('studyRepSave:study-rep-1:{"pos-after-e4-e5":"study"}') for c in calls(page))
    assert "studyRepPreview:TestNm02:Chap0001:white:true" in calls(page)
    # Regression (v0.14 build): study moves are labelled Study in the repertoire, not Book.
    page.get_by_role("button", name="Close").click()
    page.get_by_test_id("nav-openings").click()
    page.get_by_test_id("openings-tab-repertoire").click()
    row = page.locator("[data-testid=repertoire-row][data-san='Nc3']")
    row.wait_for()
    assert "Study" in row.inner_text()
