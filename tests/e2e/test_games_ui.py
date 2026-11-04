"""v0.8 UI against the mock: My games (FR-11.25–11.30), Import game (FR-11.1–11.5), Game Review with the eval
graph, key moments, reasons, Save as puzzle and the refutation (FR-11.12–11.16, FR-5.7), Retry mode
(FR-11.15), Import puzzles (FR-10.46–10.48), Settings → Games (FR-11.24) and the My puzzles source (FR-3.15).

Mock game 1 is the Blackburne Shilling trap, analyzed: you are White and blunder with 4.Nxe5 and 5.Nxf7.
"""

from __future__ import annotations

import re

import pytest

from tests.e2e.conftest import play

pytestmark = pytest.mark.e2e


def games(page, query: str = "") -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/" + query)
    page.get_by_test_id("nav-games").click()
    page.get_by_test_id("games-table").wait_for()


def test_my_games_lists_both_platforms_and_filters(page) -> None:  # type: ignore[no-untyped-def]
    games(page)
    assert page.get_by_test_id("games-count").inner_text() == "3 games"
    row = page.get_by_test_id("game-row-1")
    text = row.inner_text().lower()  # badges are uppercase on screen
    assert "analyzed" in text and "lichess analysis" in text
    assert "not analyzed" in page.get_by_test_id("game-row-2").inner_text().lower()
    page.get_by_test_id("filter-opponent").fill("opponent_e")
    page.get_by_test_id("games-count").filter(has_text="1 game").wait_for()
    page.get_by_test_id("filter-opponent").fill("")
    page.get_by_test_id("games-count").filter(has_text="3 games").wait_for()
    page.get_by_test_id("games-refresh").click()
    page.get_by_test_id("games-sync-done").filter(has_text="1 new game").wait_for()
    page.get_by_test_id("games-count").filter(has_text="4 games").wait_for()


def test_analyze_selected_runs_in_the_background(page) -> None:  # type: ignore[no-untyped-def]
    games(page)
    page.get_by_test_id("game-row-2").get_by_role("checkbox").check()
    page.get_by_test_id("game-row-3").get_by_role("checkbox").check()
    page.get_by_test_id("analyze-selected").click()
    page.get_by_test_id("analysis-queue").wait_for()
    page.get_by_test_id("game-row-3").filter(has_text="Analyzed").wait_for(timeout=5000)
    page.get_by_test_id("analysis-queue").wait_for(state="detached")


def test_review_shows_graph_moments_lines_and_refutation(page) -> None:  # type: ignore[no-untyped-def]
    games(page, "?showbest=1")  # v0.10: Show best moves on (FR-11.35), as these tests check the better moves
    page.get_by_test_id("review-1").click()
    page.get_by_test_id("review-view").wait_for()
    page.get_by_test_id("eval-graph").wait_for()
    assert page.get_by_test_id("key-moments").get_by_text("Played Nxe5??, better was Nxd4").count() == 1
    assert page.get_by_test_id("moment-8").count() == 1
    summary = page.get_by_test_id("review-summary").inner_text()
    assert "White (you)" in summary
    page.get_by_test_id("move-6").click()
    current = page.get_by_test_id("review-current").inner_text()
    assert "Nxe5??" in current and "blunder" in current.lower() and "Better was Nxd4" in current
    page.get_by_test_id("review-refutation").click()
    page.get_by_test_id("answer-player").wait_for()
    assert page.get_by_test_id("review-lines").count() == 0  # stepping through the refutation


def test_reasons_and_save_as_puzzle_on_a_key_moment(page) -> None:  # type: ignore[no-untyped-def]
    games(page, "?showbest=1")  # v0.10: Show best moves on (FR-11.35), as these tests check the better moves
    page.get_by_test_id("review-1").click()
    moment = page.get_by_test_id("moment-6")
    moment.get_by_role("button", name="Played Nxe5??, better was Nxd4").click()
    moment.get_by_test_id("reason-chips").wait_for()
    moment.get_by_test_id("reason-chips").get_by_role("button", name=re.compile("Didn't look")).first.click()
    moment.get_by_text("didntLook").wait_for()
    moment.get_by_test_id("save-6").click()
    page.get_by_test_id("saved-note").filter(has_text="Saved to My puzzles").wait_for()
    moment.get_by_test_id("save-6").filter(has_text="Saved").wait_for()


def test_retry_mode_checks_your_move_then_shows_the_answer(page) -> None:  # type: ignore[no-untyped-def]
    games(page)
    page.get_by_test_id("review-1").click()
    page.get_by_test_id("retry-start").click()
    page.get_by_test_id("retry-mode").wait_for()
    assert page.get_by_test_id("retry-result").count() == 0  # the answer isn't shown before you try
    play(page, "f3d4", "white")
    page.get_by_test_id("retry-result").filter(has_text="Found: Nxd4").wait_for()
    page.get_by_test_id("retry-next").click()
    play(page, "e5f7", "white")  # the same blunder again
    page.get_by_test_id("retry-result").filter(has_text="Not quite").wait_for()
    page.get_by_test_id("reason-chips").wait_for()
    page.get_by_test_id("reason-skip").click()
    page.get_by_test_id("review-view").wait_for()


def test_an_unanalyzed_game_offers_analyze(page) -> None:  # type: ignore[no-untyped-def]
    games(page)
    page.get_by_test_id("review-2").click()
    page.get_by_test_id("review-not-analyzed").wait_for()
    page.get_by_test_id("review-analyze").click()
    page.get_by_test_id("eval-graph").wait_for(timeout=5000)


def test_import_a_pasted_game_asks_your_color(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/")
    page.get_by_test_id("nav-import-game").click()
    page.get_by_test_id("import-pgn-text").fill(
        '[White "a"]\n[Black "b"]\n\n1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7# 1-0'
    )
    page.get_by_test_id("import-pgn").click()
    dialog = page.get_by_test_id("import-game-dialog")
    dialog.get_by_text("Which side did you play?").wait_for()
    dialog.get_by_text("Black", exact=True).click()
    page.get_by_test_id("import-color-ok").click()
    page.get_by_test_id("review-not-analyzed").wait_for()


def test_import_errors_are_clear(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/")
    page.get_by_test_id("nav-import-game").click()
    page.get_by_test_id("import-pgn-text").fill('[Variant "Chess960"]\n\n1. e4 *')
    page.get_by_test_id("import-pgn").click()
    page.get_by_test_id("import-error").filter(has_text="only standard chess").wait_for()


def test_a_multi_game_file_lets_you_pick(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/")
    page.get_by_test_id("nav-import-game").click()
    page.get_by_role("tab", name="PGN file").click()
    page.get_by_test_id("import-file").click()
    page.get_by_test_id("import-choice-1").wait_for()
    assert page.get_by_test_id("import-choice-1").is_disabled()  # it has an illegal move
    page.get_by_test_id("import-pick").click()
    page.get_by_text("Which side did you play?").wait_for()


def test_a_chesscom_url_asks_for_your_username_once(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/")
    page.get_by_test_id("nav-import-game").click()
    page.get_by_role("tab", name="Game URL").click()
    page.get_by_test_id("import-url").fill("https://www.chess.com/game/live/100000002")
    page.get_by_test_id("import-url-go").click()
    page.get_by_test_id("import-cc-user").fill("player_a")
    page.get_by_test_id("import-url-go").click()
    page.get_by_test_id("review-view").wait_for()


def test_import_puzzles_from_a_file_shows_the_report(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/")
    page.get_by_role("button", name="Menu").click()
    page.get_by_test_id("menu-import-puzzles").click()
    page.get_by_test_id("import-puzzles-label").fill("My book")
    page.get_by_test_id("import-puzzles-choose").click()
    report = page.get_by_test_id("import-report")
    report.filter(has_text="12 added, 0 already there, 2 skipped").wait_for()
    assert "no FEN tag" in report.inner_text()


def test_link_chesscom_with_verify(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/")
    page.get_by_test_id("gear").click()
    panel = page.get_by_test_id("settings-games")
    panel.scroll_into_view_if_needed()
    panel.get_by_test_id("chesscom-user").fill("nobody_here")
    panel.get_by_test_id("chesscom-verify").click()
    panel.get_by_test_id("games-settings-msg").filter(has_text="no chess.com player").wait_for()
    panel.get_by_test_id("chesscom-user").fill("player_a")
    panel.get_by_test_id("chesscom-verify").click()
    panel.get_by_test_id("chesscom-profile").wait_for()
    panel.get_by_test_id("chesscom-link").click()
    panel.get_by_test_id("games-settings-msg").filter(has_text="Linked player_a").wait_for()


def test_my_puzzles_source_serves_your_own_puzzle(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/?mine=1")
    page.get_by_test_id("source-select").get_by_text("My puzzles").click()
    page.get_by_test_id("my-puzzles-filters").wait_for()
    page.get_by_test_id("lichess-only-note").wait_for()
    page.get_by_test_id("match-count").filter(has_text="1 puzzle").wait_for()
    page.get_by_role("button", name="Start").click()
    page.get_by_test_id("puzzle-header").filter(has_text="my puzzle").wait_for()
    page.wait_for_timeout(700)
    play(page, "d1d8", "white")
    page.get_by_test_id("outcome").filter(has_text="Solved").wait_for()


def test_stats_show_retry_and_reasons_from_games(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/")
    page.get_by_role("button", name="Menu").click()
    page.get_by_role("menuitem", name="Stats").click()
    page.get_by_test_id("game-stats").wait_for()
    assert "Retry: found 0 of 0" in page.get_by_test_id("retry-stats").inner_text()
