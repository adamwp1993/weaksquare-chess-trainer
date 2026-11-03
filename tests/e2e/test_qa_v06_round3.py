"""QA v0.6 round 3 (qa/QA-v0.6.md): the v0.6-B9 fix (every Danger puzzle takes at least the engine think time to
appear, padded in TrainerView.load) against the mock client: settings changed mid-session, Next/Skip spam,
mode switch and Try again during the wait."""

from __future__ import annotations

import pytest

from tests.e2e.test_modes import calls, choose_mode, open_app

pytestmark = pytest.mark.e2e


def danger_start(page) -> None:  # type: ignore[no-untyped-def]
    open_app(page, "?mode=danger_spotting")
    page.get_by_role("button", name="Start").click()
    page.get_by_test_id("danger-call").wait_for()


def timed_next(page) -> float:  # type: ignore[no-untyped-def]
    t0 = page.evaluate("performance.now()")
    page.get_by_test_id("next-button").click()
    page.get_by_test_id("trainer-message").filter(has_text="Preparing the position").wait_for()
    page.get_by_test_id("danger-call").wait_for(timeout=15_000)
    return float(page.evaluate("performance.now()") - t0)


# Regression test for v0.6-B10 (fixed after QA round 3).
def test_b10_a_longer_think_time_set_mid_session_pads_to_the_new_time(page) -> None:  # type: ignore[no-untyped-def]
    danger_start(page)
    page.get_by_test_id("danger-safe").click()
    page.evaluate("window.__mockApi.setEngineSettings({ think_s: 3 })")  # as Settings → Engine does
    page.get_by_test_id("danger-call").wait_for(state="detached")
    elapsed = timed_next(page)
    print(f"\nQA-OBS load after raising think time to 3 s: {elapsed:.0f} ms")
    assert elapsed >= 2900, f"{elapsed:.0f} ms: a forced position would still load early"


def test_next_spam_during_the_wait_loads_one_puzzle(page) -> None:  # type: ignore[no-untyped-def]
    danger_start(page)
    page.get_by_test_id("danger-safe").click()
    before = len([c for c in calls(page) if c.startswith("danger:")])
    page.get_by_test_id("next-button").click()
    for _ in range(6):
        page.keyboard.press("n")
        page.wait_for_timeout(60)
    page.get_by_test_id("danger-call").wait_for()
    page.wait_for_timeout(1500)
    header = page.get_by_test_id("puzzle-header").inner_text()
    assert header.startswith("Puzzle 2"), header  # one load, nothing skipped (a skip would be a recorded loss)
    assert page.get_by_test_id("stat-failed").inner_text() == "0"
    assert len([c for c in calls(page) if c.startswith("danger:")]) == before


def test_s_u_and_try_again_do_nothing_during_the_wait(page) -> None:  # type: ignore[no-untyped-def]
    danger_start(page)
    page.get_by_test_id("danger-safe").click()
    page.get_by_test_id("next-button").click()
    page.get_by_test_id("trainer-message").filter(has_text="Preparing the position").wait_for()
    page.keyboard.press("r")
    page.keyboard.press("s")
    page.keyboard.press("u")
    assert [c for c in calls(page) if c.startswith("danger:")] == ["danger:safe"]
    page.get_by_test_id("danger-call").wait_for()
    assert page.get_by_test_id("outcome").count() == 0  # the new puzzle, undecided


def test_mode_switch_during_the_wait_ends_on_the_new_mode(page) -> None:  # type: ignore[no-untyped-def]
    danger_start(page)
    page.get_by_test_id("danger-safe").click()
    page.get_by_test_id("next-button").click()
    page.get_by_test_id("trainer-message").filter(has_text="Preparing the position").wait_for()
    choose_mode(page, "Standard")
    page.get_by_test_id("session-mode").filter(has_text="Standard").wait_for(timeout=10_000)
    page.wait_for_timeout(1500)  # past the old load's padding
    assert page.get_by_test_id("danger-call").count() == 0
    assert page.get_by_test_id("session-mode").inner_text() == "Standard"
    assert "Your turn" in page.get_by_test_id("trainer-message").inner_text()


def test_try_again_then_next_still_pads(page) -> None:  # type: ignore[no-untyped-def]
    danger_start(page)
    page.get_by_test_id("danger-safe").click()
    page.get_by_test_id("try-again").click()
    page.get_by_test_id("danger-call").wait_for()  # practice: no wait (same position)
    page.get_by_test_id("danger-unsafe").click()
    elapsed = timed_next(page)
    assert elapsed >= 950, f"{elapsed:.0f} ms"
