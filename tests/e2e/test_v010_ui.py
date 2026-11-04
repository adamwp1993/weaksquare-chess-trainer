"""v0.10 UI against the mock: Show best moves (FR-11.35), Analyze from here (FR-11.34), the Coach page
(§10.1–10.6), the Suggested mix and its banner (FR-10.28–10.31), Send to Coach (FR-11.30), another player
(FR-10.3) and the My-puzzles severity filter (FR-10.40).

Mock game 1 is the Blackburne Shilling trap, analyzed: you are White and blunder with 4.Nxe5 and 5.Nxf7.
"""

from __future__ import annotations

import pytest

from tests.e2e.conftest import play

pytestmark = pytest.mark.e2e


def review(page, query: str = "") -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/" + query)
    page.get_by_test_id("nav-games").click()
    page.get_by_test_id("review-1").click()
    page.get_by_test_id("review-view").wait_for()


def coach(page, query: str = "") -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/" + query)
    page.get_by_test_id("nav-coach").click()
    page.get_by_test_id("coach-page").wait_for()


# ---- Show best moves (FR-11.35) -------------------------------------------------------------------------


def test_show_best_moves_off_hides_every_better_move(page) -> None:  # type: ignore[no-untyped-def]
    review(page)
    moments = page.get_by_test_id("key-moments").inner_text()
    assert "Played Nxe5??" in moments and "better was" not in moments
    page.get_by_test_id("move-6").click()  # 4.Nxe5??
    page.get_by_test_id("review-current").wait_for()
    assert page.get_by_test_id("review-better").count() == 0
    assert page.get_by_test_id("review-lines").count() == 0
    assert page.get_by_test_id("review-refutation").count() == 1  # why it fails stays visible
    assert page.get_by_test_id("eval-graph").count() == 1
    page.get_by_test_id("review-show-best").click()
    page.get_by_test_id("review-better").filter(has_text="Better was Nxd4").wait_for()
    assert "better was Nxd4" in page.get_by_test_id("key-moments").inner_text()
    calls = page.evaluate("window.__mockApi.calls")
    assert "setting:review.show_best=true" in calls


def test_show_best_moves_is_read_from_the_saved_setting(page) -> None:  # type: ignore[no-untyped-def]
    review(page, "?showbest=1")
    page.get_by_test_id("key-moments").get_by_text("better was Nxd4").wait_for()
    assert page.get_by_test_id("review-show-best").is_checked()


# ---- Analyze from here (FR-11.34) -----------------------------------------------------------------------


def test_analyze_from_here_plays_any_line_and_goes_back(page) -> None:  # type: ignore[no-untyped-def]
    review(page)
    page.get_by_test_id("review-analyze-here").click()
    page.get_by_test_id("review-free").wait_for()
    page.get_by_test_id("review-free-hidden").wait_for()  # Show best moves is off: no engine
    assert page.get_by_test_id("engine-panel").count() == 0
    play(page, "e2e4", "white")
    page.get_by_test_id("analysis-moves").filter(has_text="e4").wait_for()
    page.get_by_test_id("review-show-best").click()
    page.get_by_test_id("engine-panel").wait_for()
    page.get_by_test_id("engine-lines").wait_for()
    assert "analyzeGame:1:board" in page.evaluate("window.__mockApi.calls")
    page.get_by_test_id("analysis-close").click()
    page.get_by_test_id("review-free").wait_for(state="detached")
    assert page.get_by_test_id("review-move").inner_text() == "Start"  # the game is where you left it


# ---- the Coach ------------------------------------------------------------------------------------------


def test_a_coach_run_shows_the_report_and_applies_the_suggestion(page) -> None:  # type: ignore[no-untyped-def]
    coach(page)
    page.get_by_test_id("coach-empty").wait_for()
    page.get_by_test_id("coach-run").click()
    page.get_by_test_id("coach-report").wait_for(timeout=5000)
    page.get_by_test_id("weakness-allowed:fork").wait_for()
    assert "13.3" in page.get_by_test_id("weakness-allowed:fork").inner_text()
    page.get_by_test_id("coach-preset-why").wait_for()
    page.get_by_test_id("nav-puzzles").click()
    label = page.get_by_test_id("suggestion-label")
    label.filter(has_text="Suggested — from Coach run #1").wait_for()
    page.get_by_test_id("suggestion-why-toggle").click()
    page.get_by_test_id("suggestion-why").filter(has_text="your #1 leak").wait_for()


def test_an_example_opens_its_position_in_game_review(page) -> None:  # type: ignore[no-untyped-def]
    coach(page, "?coach=report")
    page.get_by_test_id("example-allowed:fork-0").click()
    page.get_by_test_id("review-view").wait_for()
    assert page.get_by_test_id("review-back").inner_text() == "← Coach"
    assert page.get_by_test_id("review-move").inner_text().startswith("3")  # the position before 4.Nxe5??
    page.get_by_test_id("review-back").click()
    page.get_by_test_id("coach-report").wait_for()


def test_the_banner_waits_when_you_changed_your_filters(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/?coach=banner")
    page.get_by_test_id("suggestion-banner").wait_for()
    page.get_by_test_id("suggestion-compare").click()
    page.get_by_test_id("compare-suggested").wait_for()  # inside the Compare dialog
    assert page.get_by_test_id("compare-current").inner_text()
    page.get_by_role("button", name="Keep mine").click()
    page.get_by_test_id("suggestion-dismiss").click()
    page.get_by_test_id("suggestion-banner").wait_for(state="detached")
    assert "suggestion:dismiss" in page.evaluate("window.__mockApi.calls")
    assert "suggestion:apply" not in page.evaluate("window.__mockApi.calls")


def test_apply_from_the_banner(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/?coach=banner")
    page.get_by_test_id("suggestion-apply").click()
    page.get_by_test_id("suggestion-label").wait_for()
    assert "suggestion:apply" in page.evaluate("window.__mockApi.calls")


def test_another_player_is_kept_apart(page) -> None:  # type: ignore[no-untyped-def]
    coach(page)
    page.get_by_test_id("coach-whose").get_by_text("Another player").click()
    page.get_by_test_id("coach-player").fill("https://lichess.org/@/someone_x")
    page.get_by_test_id("coach-run").click()
    page.get_by_test_id("coach-report").filter(has_text="Another player's report").wait_for(timeout=5000)
    assert "someone_x" in page.get_by_test_id("coach-report").inner_text()
    page.get_by_test_id("nav-puzzles").click()
    assert page.get_by_test_id("suggestion-label").count() == 0  # your mix is untouched
    page.get_by_test_id("nav-games").click()
    page.get_by_test_id("filter-player").wait_for()


def test_send_to_coach_runs_on_exactly_those_games(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/")
    page.get_by_test_id("nav-games").click()
    page.get_by_test_id("game-row-1").get_by_role("checkbox").check()
    page.get_by_test_id("send-to-coach").click()
    page.get_by_test_id("coach-sent").filter(has_text="1 game sent").wait_for()
    page.get_by_test_id("coach-run").click()
    page.get_by_test_id("coach-report").wait_for(timeout=5000)
    assert "coach:games:me:1" in page.evaluate("window.__mockApi.calls")


def test_ai_coaching_needs_a_confirm(page) -> None:  # type: ignore[no-untyped-def]
    coach(page, "?ai=on&coach=report")
    page.get_by_test_id("coach-ai-start").click()
    page.get_by_test_id("narrative-estimate").filter(has_text="no names, usernames").wait_for()  # the Confirm dialog
    page.get_by_test_id("coach-ai-confirm-button").click()
    page.get_by_test_id("coach-ai-result").wait_for(timeout=5000)
    assert "Allowed: Fork" in page.get_by_test_id("coach-ai-result").inner_text()
    page.get_by_test_id("coach-ai-preset-0-load").click()
    page.get_by_test_id("trainer-page").wait_for()


def test_my_puzzles_have_origin_and_severity_filters(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/?mine=1")
    page.get_by_test_id("source-select").get_by_text("My puzzles").click()
    page.get_by_test_id("my-severities").wait_for()
    page.get_by_test_id("my-origins").click()
    page.get_by_role("option", name="From my games (made automatically)").wait_for()


def test_b5_you_can_coach_one_of_your_accounts(page) -> None:  # type: ignore[no-untyped-def]
    """v0.10-B5 regression: Lichess / chess.com / all of your games (FR-10.3)."""
    coach(page)
    page.get_by_test_id("coach-platforms").get_by_text("chess.com").click()
    page.get_by_test_id("coach-run").click()
    page.get_by_test_id("coach-report").wait_for(timeout=5000)
    assert "coachPlatforms:chesscom" in page.evaluate("window.__mockApi.calls")


def test_b6_one_game_is_singular_in_saved_reports(page) -> None:  # type: ignore[no-untyped-def]
    """v0.10-B6 regression."""
    page.goto(page.base_url + "/")
    page.get_by_test_id("nav-games").click()
    page.get_by_test_id("game-row-1").get_by_role("checkbox").check()
    page.get_by_test_id("send-to-coach").click()
    page.get_by_test_id("coach-run").click()
    page.get_by_test_id("coach-history").filter(has_text="1 game").wait_for(timeout=5000)
    assert "1 games" not in page.get_by_test_id("coach-history").inner_text()
