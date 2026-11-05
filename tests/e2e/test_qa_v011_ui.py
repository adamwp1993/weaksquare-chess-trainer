"""QA v0.11 (independent) against the mock: edge cases of the Coach's AI box and the preset manager, and a
screenshot of each new screen in tests/e2e/artifacts/ (gitignored) for the visual check."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.e2e.test_v010_ui import coach
from tests.e2e.test_v011_ui import ask, calls

pytestmark = pytest.mark.e2e
ART = Path("tests/e2e/artifacts")


def shot(page, name: str, full: bool = True) -> None:  # type: ignore[no-untyped-def]
    ART.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(ART / f"qa-v011-{name}.png"), full_page=full)


def test_qa_screens_for_the_visual_check(page) -> None:  # type: ignore[no-untyped-def]
    page.set_viewport_size({"width": 1280, "height": 900})
    coach(page, "?ai=on&coach=report")
    page.get_by_test_id("coach-measures").wait_for()
    page.get_by_test_id("coach-measures").scroll_into_view_if_needed()
    shot(page, "measures")
    page.get_by_test_id("coach-ai-advanced").check()
    page.get_by_test_id("coach-ai-start").click()
    page.get_by_test_id("coach-ai-compare").wait_for()
    shot(page, "advanced-confirm", full=False)
    page.get_by_test_id("coach-ai-confirm-button").click()
    page.get_by_test_id("coach-ai-result").wait_for(timeout=5000)
    page.get_by_test_id("coach-ai-result").scroll_into_view_if_needed()
    shot(page, "diagnosis")
    page.get_by_test_id("coach-ai-notes").check()
    page.get_by_test_id("coach-note").first.wait_for()
    shot(page, "notes-preview", full=False)
    page.get_by_test_id("coach-notes-ok").click()
    page.set_viewport_size({"width": 900, "height": 800})  # a narrower window: nothing clipped
    page.get_by_test_id("coach-ai").scroll_into_view_if_needed()
    shot(page, "ai-box-narrow")
    page.get_by_test_id("gear").click()
    page.get_by_test_id("coach-settings").wait_for()
    page.get_by_test_id("coach-settings").scroll_into_view_if_needed()
    shot(page, "settings-coach", full=False)


def test_qa_an_out_of_range_cap_is_never_sent(page) -> None:  # type: ignore[no-untyped-def]
    coach(page, "?ai=on&coach=report")
    page.get_by_test_id("coach-ai-advanced").check()
    cap = page.get_by_test_id("coach-ai-cap")
    cap.fill("15")
    cap.fill("5")  # below 10: ignored
    cap.fill("500")  # above 50: ignored
    cap.blur()
    page.get_by_test_id("coach-ai-start").click()
    page.get_by_test_id("coach-ai-confirm-button").click()
    page.get_by_test_id("coach-ai-result").wait_for(timeout=5000)
    sent = [c for c in calls(page) if c.startswith("coachAi:")]
    assert len(sent) == 1 and ":advanced:" in sent[0]
    n = int(sent[0].split(":advanced:")[1].split(":")[0])
    assert 10 <= n <= 50, sent


def test_qa_unticking_advanced_drops_the_comparison(page) -> None:  # type: ignore[no-untyped-def]
    coach(page, "?ai=on&coach=report")
    page.get_by_test_id("coach-ai-advanced").check()
    page.get_by_test_id("coach-ai-advanced").uncheck()
    assert page.get_by_test_id("coach-ai-cap").count() == 0
    page.get_by_test_id("coach-ai-start").click()
    page.get_by_test_id("coach-ai-confirm-button").wait_for()
    assert page.get_by_test_id("coach-ai-compare").count() == 0
    assert "Advanced also sends" not in page.get_by_test_id("narrative-estimate").inner_text()


@pytest.mark.xfail(reason="QA v0.11 B5: a double-click on Confirm starts two paid AI runs", strict=True)
def test_qa_a_double_click_on_confirm_sends_one_request(page) -> None:  # type: ignore[no-untyped-def]
    coach(page, "?ai=on&coach=report")
    page.get_by_test_id("coach-ai-start").click()
    page.get_by_test_id("coach-ai-confirm-button").dblclick()
    page.get_by_test_id("coach-ai-result").wait_for(timeout=5000)
    page.wait_for_timeout(500)
    assert len([c for c in calls(page) if c.startswith("coachAi:")]) == 1


def test_qa_the_same_options_show_the_saved_answer(page) -> None:  # type: ignore[no-untyped-def]
    coach(page, "?ai=on&coach=report")
    ask(page)
    page.get_by_test_id("coach-ai-result").wait_for(timeout=5000)
    start = page.get_by_test_id("coach-ai-start")
    start.filter(has_text="Show the saved answer").wait_for(timeout=5000)
    page.get_by_test_id("coach-ai-advanced").check()  # different options: a new run is offered
    start.filter(has_text="with these options").wait_for(timeout=5000)


def test_qa_overwriting_another_preset_keeps_your_filters_and_the_loaded_one(page) -> None:  # type: ignore[no-untyped-def]
    from tests.e2e.test_mixer_v02 import pick_theme
    from tests.e2e.test_qa_v01_ui import count_text, ready
    from tests.e2e.test_v011_ui import _save_preset

    ready(page)
    pick_theme(page, "themes-picker", "fork", "Fork")
    _save_preset(page, "Forks")
    pick_theme(page, "themes-picker", "pin", "Pin")
    before = count_text(page)
    page.get_by_test_id("preset-actions").click()
    page.get_by_test_id("preset-manage").click()
    manager = page.get_by_test_id("preset-manager")
    manager.get_by_test_id("preset-row-Endgame drill").get_by_test_id("preset-row-update").click()
    manager.get_by_text("“Endgame drill” now has your current filters.").wait_for()
    shot(page, "preset-manager", full=False)
    # Rename the loaded preset from the manager: the menu follows the new name.
    manager.get_by_test_id("preset-row-Forks").get_by_test_id("preset-row-rename").click()
    page.get_by_test_id("preset-name").fill("Fork drill")
    page.get_by_test_id("preset-confirm").click()
    manager.get_by_test_id("preset-row-Fork drill").wait_for()
    page.keyboard.press("Escape")
    manager.wait_for(state="hidden")
    assert count_text(page) == before
    page.get_by_test_id("preset-actions").click()
    page.get_by_test_id("preset-update").filter(has_text="Update “Fork drill” with these filters").wait_for()


def test_qa_retry_explain_is_never_there_before_each_attempt(page) -> None:  # type: ignore[no-untyped-def]
    from tests.e2e.conftest import play
    from tests.e2e.test_game_ai_ui import review

    review(page)
    page.get_by_test_id("retry-start").click()
    retry = page.get_by_test_id("retry-mode")
    retry.wait_for()
    assert retry.get_by_test_id("move-explain").count() == 0
    play(page, "f3d4", "white")
    page.get_by_test_id("retry-result").wait_for()
    retry.get_by_test_id("move-explain").wait_for()
    shot(page, "retry-explain", full=False)
    nxt = page.get_by_test_id("retry-next")
    if nxt.count() and nxt.is_enabled():
        nxt.click()
        page.wait_for_timeout(300)
        if page.get_by_test_id("retry-result").count() == 0:  # the next mistake: no Explain until you try
            assert retry.get_by_test_id("move-explain").count() == 0
