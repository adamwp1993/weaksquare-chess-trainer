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


# ---- Wikibooks and the explorer's settings (FR-12.2, 12.15) ---------------------------------------------


def calls(page: Any) -> list[str]:
    return list(page.evaluate("window.__mockApi.calls"))


def test_wikibooks_loads_only_when_you_open_the_panel_and_credits_its_source(page: Any) -> None:
    openings(page)
    pick(page, "Italian Game")
    page.get_by_test_id("learn-forward").click()
    assert not [c for c in calls(page) if c.startswith("openingPage")]
    page.get_by_test_id("wikibooks-toggle").click()
    page.get_by_test_id("wikibooks-text").wait_for()
    attribution = page.get_by_test_id("wikibooks-attribution")
    assert "CC BY-SA 4.0" in attribution.inner_text()
    links = [a.get_attribute("href") for a in attribution.get_by_role("link").all()]
    assert any(h and h.startswith("https://en.wikibooks.org/wiki/") for h in links)
    assert "https://creativecommons.org/licenses/by-sa/4.0/" in links


def test_wikibooks_can_be_turned_off(page: Any) -> None:
    openings(page)
    pick(page, "Italian Game")
    page.get_by_test_id("wikibooks-toggle").click()
    page.get_by_test_id("wikibooks-text").wait_for()
    page.get_by_test_id("opening-sources").locator(".mantine-Switch-track").click()
    page.get_by_test_id("learn-forward").click()
    page.get_by_test_id("wikibooks-off").wait_for()


def test_play_along_doesnt_reveal_the_line_through_wikibooks(page: Any) -> None:
    openings(page)
    pick(page, "Italian Game")
    page.get_by_test_id("wikibooks-toggle").click()
    page.get_by_test_id("wikibooks-text").wait_for()
    page.get_by_test_id("learn-mode").get_by_text("Play along").click()
    page.get_by_text("Your move.").wait_for()
    assert [c for c in calls(page) if c.startswith("openingPage")][-1] == "openingPage:"


def test_signed_out_says_why_there_are_no_popular_moves(page: Any) -> None:
    openings(page, "?openings=ready&account=signed_out")
    pick(page, "Italian Game")
    page.get_by_test_id("opening-explorer-signed-out").wait_for()
    assert page.get_by_test_id("opening-explorer-source").count() == 0


def test_masters_hides_the_rating_bands(page: Any) -> None:
    openings(page)
    pick(page, "Italian Game")
    page.get_by_test_id("opening-explorer-ratings").wait_for()
    page.get_by_test_id("opening-explorer-source").get_by_text("Masters").click()
    page.get_by_test_id("opening-explorer-ratings").wait_for(state="detached")


# ---- notes and prefetch (FR-12.5-12.7, 12.7a, 12.7b) ----------------------------------------------------


AI = "?openings=ready&engine=ready&ai=on"


def test_an_overview_and_a_move_note_are_saved_and_credited(page: Any) -> None:
    openings(page, AI)
    pick(page, "Italian Game")
    page.get_by_test_id("overview-note-button").click()
    page.get_by_test_id("overview-note").get_by_test_id("opening-note").wait_for()
    page.get_by_test_id("overview-note").get_by_test_id("opening-note-credit").wait_for()
    assert "CC BY-SA 4.0" in page.get_by_test_id("overview-note").inner_text()
    page.get_by_test_id("move-note-button").click()
    page.get_by_test_id("move-note").get_by_test_id("opening-note").wait_for()
    assert page.get_by_test_id("move-note-button").count() == 0


def test_explain_says_why_without_an_ai_and_the_board_still_works(page: Any) -> None:
    openings(page)
    pick(page, "Italian Game")
    page.get_by_test_id("move-note-why").filter(has_text="Settings").wait_for()
    assert page.get_by_test_id("move-note-button").is_disabled()
    page.get_by_test_id("learn-forward").click()
    page.get_by_test_id("engine-panel").wait_for()


def test_regenerate_shows_the_cost_before_replacing(page: Any) -> None:
    openings(page, AI)
    pick(page, "Italian Game")
    page.get_by_test_id("overview-note-button").click()
    page.get_by_test_id("overview-note-regenerate").click()
    confirm = page.get_by_test_id("overview-note-regen-confirm")
    confirm.filter(has_text="$").wait_for()
    before = [c for c in calls(page) if c.startswith("openingNote")]
    assert before == ["openingNote:null:false"]
    page.get_by_test_id("overview-note-regen-yes").click()
    page.wait_for_function("() => window.__mockApi.calls.includes('openingNote:null:true')")


def test_a_move_note_is_hidden_in_play_along(page: Any) -> None:
    openings(page, AI)
    pick(page, "Italian Game")
    page.get_by_test_id("move-note-panel").wait_for()
    page.get_by_test_id("learn-mode").get_by_text("Play along").click()
    page.get_by_test_id("move-note-panel").wait_for(state="detached")


def open_prefetch(page: Any, query: str = AI) -> None:
    openings(page, query)
    pick(page, "Italian Game")
    page.get_by_test_id("opening-prefetch").click()
    page.get_by_test_id("prefetch-plan").wait_for()


def test_the_prefetch_dialog_updates_with_the_scope(page: Any) -> None:
    open_prefetch(page)
    counts = page.get_by_test_id("prefetch-counts")
    assert counts.inner_text().startswith("4 lines")
    page.get_by_test_id("prefetch-preset").get_by_text("Light").click()
    counts.filter(has_text="2 lines").wait_for()
    assert "$" in page.get_by_test_id("prefetch-usage").inner_text()
    assert "Stockfish" in page.get_by_test_id("prefetch-time").inner_text()
    page.get_by_test_id("prefetch-preset").get_by_text("Custom").click()
    page.get_by_test_id("prefetch-sub-lines").wait_for()


def test_nothing_is_sent_before_confirm_and_a_second_run_is_free(page: Any) -> None:
    open_prefetch(page)
    assert not [c for c in calls(page) if c.startswith("openingPrefetch:")]
    page.get_by_test_id("prefetch-confirm").click()
    page.get_by_test_id("prefetch-done").filter(has_text="Saved").wait_for()
    page.get_by_test_id("prefetch-counts").filter(has_text="0 requests").wait_for()
    assert page.get_by_test_id("prefetch-confirm").is_disabled()


def test_cancel_says_what_stays(page: Any) -> None:
    open_prefetch(page, AI + "&prefetch=slow")
    page.get_by_test_id("prefetch-confirm").click()
    page.get_by_test_id("prefetch-cancel").click()
    page.get_by_test_id("prefetch-cancelled").wait_for()


def test_warnings_split_and_blocked_show_plainly(page: Any) -> None:
    open_prefetch(page, AI + "&prefetch=warn")
    page.get_by_test_id("prefetch-warning").filter(has_text="40%").wait_for()
    open_prefetch(page, AI + "&prefetch=split")
    page.get_by_test_id("prefetch-split").filter(has_text="doesn't change").wait_for()
    open_prefetch(page, AI + "&prefetch=over_budget")
    page.get_by_test_id("prefetch-blocked").wait_for()
    assert page.get_by_test_id("prefetch-confirm").is_disabled()


def test_without_an_ai_the_dialog_shows_engine_time_only(page: Any) -> None:
    open_prefetch(page, "?openings=ready&engine=ready")
    assert page.get_by_test_id("prefetch-usage").count() == 0
    assert "of AI" not in page.get_by_test_id("prefetch-time").inner_text()


def test_export_and_delete(page: Any) -> None:
    openings(page, AI)
    pick(page, "Italian Game")
    page.get_by_test_id("opening-export").click()
    page.get_by_test_id("opening-notes-message").filter(has_text="no notes").wait_for()
    page.get_by_test_id("overview-note-button").click()
    page.get_by_test_id("overview-note").get_by_test_id("opening-note").wait_for()
    page.get_by_test_id("opening-export").click()
    page.get_by_test_id("opening-notes-message").filter(has_text="notes.md").wait_for()
    page.get_by_test_id("opening-delete-notes").click()
    page.get_by_test_id("overview-note-button").wait_for()


def test_the_dialogs_options_have_tooltips(page: Any) -> None:
    open_prefetch(page)
    page.get_by_test_id("prefetch-preset").get_by_text("Custom").click()
    page.get_by_test_id("prefetch-sub-lines").wait_for()
    _assert_all_have_tips(page, "Prefetch dialog")


def test_finishing_a_prefetch_settles(page: Any) -> None:
    """Regression: the dialog's "finished" callback re-rendered its parent, which fired it again, forever."""
    open_prefetch(page)
    page.get_by_test_id("prefetch-confirm").click()
    page.get_by_test_id("prefetch-done").wait_for()
    page.wait_for_timeout(300)
    plans = page.evaluate("window.__mockApi.calls.length")
    page.wait_for_timeout(500)
    assert page.evaluate("window.__mockApi.calls.length") == plans
    page.get_by_test_id("prefetch-counts").filter(has_text="0 requests").wait_for()
