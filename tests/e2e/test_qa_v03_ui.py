"""QA v0.3: UI edge cases against the mock, plus screenshots of every v0.3 screen in Light and Dark into
tests/e2e/artifacts/qa-v03/ (gitignored) for the visual check. Written by the independent QA pass
(qa/QA-v0.3.md).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.e2e.test_lichess_ui import open_startup, open_stats, solve_mate_in_one

pytestmark = pytest.mark.e2e
ART = Path(__file__).resolve().parent / "artifacts" / "qa-v03"


def shot(page, name: str) -> None:  # type: ignore[no-untyped-def]
    ART.mkdir(parents=True, exist_ok=True)
    page.wait_for_timeout(300)
    page.screenshot(path=str(ART / f"{name}.png"), full_page=True)


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_qa_screenshots_of_every_v03_screen(page, scheme: str) -> None:  # type: ignore[no-untyped-def]
    for account in ("signed_in", "signed_out", "offline", "expired"):
        open_startup(page, f"&scheme={scheme}&account={account}")
        shot(page, f"{scheme}-startup-{account}")
    open_startup(page, f"&scheme={scheme}")
    page.get_by_test_id("startup-more").click()
    shot(page, f"{scheme}-startup-all-options")
    open_startup(page, f"&scheme={scheme}&account=signed_out&signin=fail")
    page.get_by_test_id("sign-in").click()
    page.get_by_test_id("sign-in-failed").wait_for()
    shot(page, f"{scheme}-startup-sign-in-failed")

    solve_mate_in_one(page, f"?scheme={scheme}&sync=slow")
    shot(page, f"{scheme}-result-syncing")
    page.evaluate("window.__mockSyncNow()")
    page.get_by_test_id("rating-change").filter(has_text="+8").wait_for()
    shot(page, f"{scheme}-result-plus8-header-session-total")
    solve_mate_in_one(page, f"?scheme={scheme}&account=offline")
    shot(page, f"{scheme}-result-offline-chip")
    solve_mate_in_one(page, f"?scheme={scheme}", rated=False)
    shot(page, f"{scheme}-result-unrated")

    page.goto(page.base_url + f"/?scheme={scheme}&played=1")
    page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for()
    page.get_by_test_id("more-filters").click()
    page.get_by_test_id("exclude-played").wait_for()
    shot(page, f"{scheme}-mixer-history-and-rated")
    page.get_by_test_id("gear").click()
    page.get_by_test_id("settings").wait_for()
    shot(page, f"{scheme}-settings-account")
    page.keyboard.press("Escape")
    open_stats(page)
    page.get_by_test_id("rating-chart").locator(".recharts-line-curve").wait_for()
    shot(page, f"{scheme}-stats-rating-trend")

    page.goto(page.base_url + f"/?scheme={scheme}&revoke=offline")
    page.get_by_test_id("gear").click()
    page.get_by_test_id("sign-out").click()
    page.get_by_test_id("revoke-failed").wait_for()
    shot(page, f"{scheme}-sign-out-revoke-failed")


def test_qa_rated_is_on_again_after_reload(page) -> None:  # type: ignore[no-untyped-def]
    """FR-1.9: Rated is session-level and never saved: a relaunch (reload) turns it back on."""
    page.goto(page.base_url + "/")
    page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for()
    sw = page.get_by_test_id("rated-switch")
    sw.uncheck()
    assert not sw.is_checked()
    page.goto(page.base_url + "/")
    page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for()
    assert page.get_by_test_id("rated-switch").is_checked()


def test_qa_exclude_played_changes_the_count(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/?played=1")
    count = page.get_by_test_id("match-count")
    count.filter(has_text="puzzles match").wait_for()
    page.get_by_test_id("more-filters").click()
    box = page.get_by_test_id("exclude-played")
    box.wait_for()
    with_filter = count.inner_text()
    box.uncheck()
    page.wait_for_function("t => document.querySelector('[data-testid=match-count]').innerText !== t", arg=with_filter)
    assert count.inner_text() != with_filter


def test_qa_no_header_rating_or_chip_on_the_startup_page(page) -> None:  # type: ignore[no-untyped-def]
    open_startup(page)
    assert page.get_by_test_id("header-rating").count() == 0
    assert page.get_by_test_id("gear").count() == 1  # settings stay reachable from the startup page


def test_qa_double_click_sign_in_starts_one_wait(page) -> None:  # type: ignore[no-untyped-def]
    open_startup(page, "&account=signed_out")
    page.get_by_test_id("sign-in").dblclick()
    page.get_by_test_id("startup-status").filter(has_text="Signed in as your_name").wait_for()
    assert page.get_by_test_id("sign-in-failed").count() == 0


# Regression test for v0.3-B2 (fixed in QA round 1).
def test_qa_expired_sign_in_says_sign_in_again_on_the_main_page(page) -> None:  # type: ignore[no-untyped-def]
    """FR-6.4: on a 401 the token is discarded and the app shows "Sign in again". A 401 can arrive
    mid-session (sync, history import); the main page must say so without opening the gear."""
    page.goto(page.base_url + "/?account=expired")
    page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for()
    page.get_by_text("Sign in again").first.wait_for(timeout=3000)


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_qa_expired_banner_screenshot(page, scheme: str) -> None:  # type: ignore[no-untyped-def]
    """Round 2: the B2 banner on the main page, for the visual check."""
    page.goto(page.base_url + f"/?scheme={scheme}&account=expired")
    page.get_by_test_id("expired-banner").wait_for()
    shot(page, f"{scheme}-main-expired-banner")
