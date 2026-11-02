"""v0.3 UI against the mock client: the startup page (FR-1.1, 1.5–1.7), sign-in and sign-out, the
header rating (FR-6.11a), the result-panel change (FR-6.11b), the session total (FR-6.11c), Rated
(FR-1.9), offline mode, the already-played badge and the gear settings (FR-1.8)."""

from __future__ import annotations

import pytest

from tests.e2e.conftest import continue_past_startup, play
from tests.e2e.test_mixer_v02 import pick_theme
from tests.e2e.test_qa_v01_ui import your_turn

pytestmark = pytest.mark.e2e


def open_startup(page, query: str = "") -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/?startup=show" + query)
    page.get_by_test_id("startup").wait_for()


def solve_mate_in_one(page, query: str = "", rated: bool = True) -> None:  # type: ignore[no-untyped-def]
    """The mock serves 001KR first for Mate in 1 (white mates with f1f8)."""
    page.goto(page.base_url + "/" + query)
    page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for()
    pick_theme(page, "themes-picker", "mate in 1", "Mate in 1")
    page.get_by_label("Puzzles").fill("1")
    if not rated:
        page.get_by_test_id("rated-switch").uncheck()
    page.get_by_role("button", name="Start").click()
    your_turn(page)
    play(page, "f1f8", "white")
    page.get_by_test_id("outcome").filter(has_text="Solved").wait_for()


# ---- startup page ------------------------------------------------------------------------------
def test_fast_path_continue_as(page) -> None:  # type: ignore[no-untyped-def]
    """FR-1.6: a sign-in Lichess accepts gives one Continue as <username> button."""
    open_startup(page)
    assert page.get_by_test_id("startup-continue").inner_text() == "Continue as your_name"
    assert page.get_by_test_id("sign-out").count() == 0  # the other options are folded away
    page.get_by_test_id("startup-more").click()
    page.get_by_test_id("sign-out").wait_for()
    page.get_by_test_id("startup-continue").click()
    page.get_by_test_id("header-rating").filter(has_text="Puzzle rating 1834").wait_for()


def test_signed_out_sign_in_flow(page) -> None:  # type: ignore[no-untyped-def]
    open_startup(page, "&account=signed_out")
    assert "Not signed in" in page.get_by_test_id("startup-status").inner_text()
    assert page.get_by_test_id("startup-continue").inner_text() == "Continue without signing in"
    page.get_by_test_id("sign-in").click()
    page.get_by_test_id("sign-in-waiting").wait_for()  # "Waiting for you in your browser…"
    page.get_by_test_id("startup-status").filter(has_text="Signed in as your_name").wait_for()
    assert page.get_by_test_id("startup-continue").inner_text() == "Continue as your_name"


def test_sign_in_failure_is_shown(page) -> None:  # type: ignore[no-untyped-def]
    open_startup(page, "&account=signed_out&signin=fail")
    page.get_by_test_id("sign-in").click()
    page.get_by_test_id("sign-in-failed").filter(has_text="Sign-in failed").wait_for()
    page.get_by_test_id("startup-continue").click()  # you can always continue (FR-1.7)
    page.get_by_test_id("match-count").wait_for()
    assert page.get_by_test_id("header-rating").count() == 0  # no rating unless signed in


def test_offline_and_expired_startup(page) -> None:  # type: ignore[no-untyped-def]
    open_startup(page, "&account=offline")
    page.get_by_test_id("startup-offline").wait_for()
    assert page.get_by_test_id("startup-continue").inner_text() == "Continue offline as your_name"
    open_startup(page, "&account=expired")
    assert "expired" in page.get_by_test_id("startup-status").inner_text()
    page.get_by_test_id("sign-in").wait_for()


# ---- rating display ------------------------------------------------------------------------------
def test_rated_solve_shows_the_change_header_and_session_total(page) -> None:  # type: ignore[no-untyped-def]
    solve_mate_in_one(page, "?sync=slow")
    assert page.get_by_test_id("rating-change").inner_text() == "Syncing…"  # until Lichess replies
    page.evaluate("window.__mockSyncNow()")
    page.get_by_test_id("rating-change").filter(has_text="+8").wait_for()
    page.get_by_test_id("header-rating").filter(has_text="Puzzle rating 1842").wait_for()
    page.get_by_test_id("session-rating").filter(has_text="+8 this session").wait_for()


def test_rated_off_says_unrated(page) -> None:  # type: ignore[no-untyped-def]
    solve_mate_in_one(page, rated=False)
    assert page.get_by_test_id("rating-change").inner_text() == "Unrated (Rated is off)"
    page.wait_for_timeout(600)
    assert page.get_by_test_id("header-rating").inner_text() == "Puzzle rating 1834"  # unchanged


def test_offline_solve_will_sync_later(page) -> None:  # type: ignore[no-untyped-def]
    solve_mate_in_one(page, "?account=offline")
    assert page.get_by_test_id("rating-change").inner_text() == "Will sync later"
    page.get_by_test_id("sync-chip").filter(has_text="Offline: 1 solve waiting to sync").wait_for()
    assert page.get_by_test_id("header-rating").count() == 0


def test_already_played_badge(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/?played=1")
    page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for()
    page.get_by_test_id("more-filters").click()
    played = page.get_by_test_id("exclude-played")
    played.wait_for()
    assert played.is_checked()  # on by default (Adam, v0.3 planning)
    played.uncheck()
    page.get_by_role("button", name="Start").click()
    your_turn(page)
    assert page.get_by_test_id("already-played").count() == 0
    page.get_by_test_id("next-button").click()  # the second mock puzzle is in your Lichess history
    page.get_by_test_id("already-played").filter(has_text="rating unaffected").wait_for()


def test_exclude_played_needs_a_sign_in(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/?account=signed_out")
    page.get_by_test_id("more-filters").click()
    box = page.get_by_test_id("exclude-played")
    box.wait_for()
    assert box.is_disabled()
    assert "Sign in with Lichess" in page.get_by_text("Sign in with Lichess to use this.").inner_text()


# ---- gear settings and sign-out ------------------------------------------------------------------
def test_gear_opens_settings_with_the_account(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/")
    page.get_by_test_id("gear").click()
    page.get_by_test_id("settings").get_by_text("Signed in as your_name").wait_for()
    page.get_by_test_id("sign-out").click()
    page.get_by_test_id("settings").get_by_text("Not signed in").wait_for()
    assert page.get_by_test_id("header-rating").count() == 0


def test_sign_out_offline_asks_before_removing(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/?revoke=offline")
    page.get_by_test_id("gear").click()
    page.get_by_test_id("sign-out").click()
    page.get_by_test_id("revoke-failed").wait_for()
    assert page.get_by_test_id("settings").get_by_text("Signed in as your_name").count() == 1  # nothing removed yet
    page.get_by_test_id("sign-out-anyway").click()
    page.get_by_test_id("settings").get_by_text("Not signed in").wait_for()


def test_continue_helper_is_used_by_new_pages(browser, mock_url: str) -> None:  # type: ignore[no-untyped-def]
    ctx = browser.new_context()
    page = ctx.new_page()
    try:
        page.goto(mock_url + "/")
        page.get_by_test_id("startup").wait_for()  # the startup page always comes first
        continue_past_startup(page)
        page.get_by_test_id("match-count").wait_for()
    finally:
        ctx.close()
