"""v0.12 in the real UI, on the mock client: the plan, the Today card, the journal, Since last report, and AI coaching
with the plan and the journal (REQUIREMENTS §10.12)."""

from __future__ import annotations

from typing import Any

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def _calls(page: Page) -> list[str]:
    return list(page.evaluate("window.__mockApi.calls"))


def _open(page: Page, query: str) -> None:
    page.goto(f"{page.base_url}/?{query}")  # type: ignore[attr-defined]


def _coach(page: Page, tab: str | None = None) -> None:
    page.get_by_test_id("nav-coach").click()
    if tab:
        page.get_by_test_id(f"coach-tab-{tab}").click()


def _in_plan(page: Page) -> Any:
    """The Plan tab. The Today card stays mounted (hidden) on the trainer page, so its ids also exist there."""
    return page.get_by_test_id("plan-current")


def _first_task(page: Page, scope: str) -> Any:
    return page.get_by_test_id(scope).locator('[data-testid^="plan-task-"]').first


# ---- the tabs ----


def test_the_coach_has_report_plan_and_journal_tabs(page: Page) -> None:
    _open(page, "coach=report")
    _coach(page)
    expect(page.get_by_test_id("coach-report")).to_be_visible()
    page.get_by_test_id("coach-tab-plan").click()
    expect(page.get_by_test_id("plan-tab")).to_be_visible()
    expect(page.get_by_test_id("coach-report")).to_be_hidden()
    page.get_by_test_id("coach-tab-journal").click()
    expect(page.get_by_test_id("journal-tab")).to_be_visible()


# ---- building a plan ----


def test_preview_then_start_a_plan_on_picked_weekdays(page: Page) -> None:
    _open(page, "coach=report")
    _coach(page, "plan")
    page.get_by_test_id("plan-weekday-4").click()  # Friday off
    page.get_by_test_id("plan-preview").click()
    expect(page.get_by_test_id("plan-preview-list")).to_be_visible()
    assert not any(c.startswith("createPlan") for c in _calls(page))  # a preview saves nothing
    page.get_by_test_id("plan-create").click()
    expect(page.get_by_test_id("plan-current")).to_be_visible()
    assert "createPlan:2:0123:20" in _calls(page)


def test_a_new_plan_replaces_the_current_one_only_after_a_confirm(page: Page) -> None:
    _open(page, "coach=report&plan=current")
    _coach(page, "plan")
    page.get_by_test_id("plan-preview").click()
    page.get_by_test_id("plan-create").click()
    expect(page.get_by_test_id("plan-confirm-button")).to_be_visible()
    assert not any(c.startswith("createPlan") for c in _calls(page))
    page.get_by_test_id("plan-confirm-button").click()
    expect(page.get_by_test_id("plan-history")).to_be_visible()  # the old plan stays with its completion
    assert any(c.startswith("createPlan") for c in _calls(page))


def test_without_a_report_the_plan_tab_says_to_run_the_coach(page: Page) -> None:
    _open(page, "")
    _coach(page, "plan")
    expect(page.get_by_test_id("plan-no-report")).to_be_visible()


def test_todays_day_is_open(page: Page) -> None:
    _open(page, "coach=report&plan=current")
    _coach(page, "plan")
    expect(page.get_by_test_id("plan-today-badge")).to_be_visible()
    expect(page.get_by_test_id("plan-current").locator('[data-testid^="plan-tick-"]').first).to_be_visible()


# ---- the Today card ----


def test_no_plan_no_today_card(page: Page) -> None:
    _open(page, "coach=report")
    expect(page.get_by_test_id("trainer-page")).to_be_visible()
    expect(page.get_by_test_id("today-card")).to_have_count(0)


def test_a_tick_in_the_today_card_shows_in_the_plan_tab_and_back(page: Page) -> None:
    _open(page, "coach=report&plan=current")
    task = _first_task(page, "today-card")
    tid = task.get_attribute("data-testid").split("-")[-1]
    page.get_by_test_id(f"plan-tick-{tid}").check()
    expect(page.get_by_test_id("today-count")).to_have_text("1 of 2 done")
    _coach(page, "plan")
    expect(_in_plan(page).get_by_test_id(f"plan-task-{tid}")).to_have_attribute("data-status", "done")
    _in_plan(page).get_by_test_id(f"plan-tick-{tid}").uncheck()
    expect(_in_plan(page).get_by_test_id(f"plan-task-{tid}")).to_have_attribute("data-status", "left")
    page.get_by_test_id("nav-puzzles").click()
    expect(page.get_by_test_id("today-count")).to_have_text("0 of 2 done")


def test_skip_and_swap(page: Page) -> None:
    _open(page, "coach=report&plan=current")
    tid = _first_task(page, "today-card").get_attribute("data-testid").split("-")[-1]
    page.get_by_test_id(f"plan-more-{tid}").click()
    page.get_by_test_id(f"plan-skip-{tid}").click()
    expect(page.get_by_test_id(f"plan-task-{tid}")).to_have_attribute("data-status", "skipped")
    expect(page.get_by_test_id(f"plan-start-{tid}")).to_have_count(0)
    page.get_by_test_id(f"plan-more-{tid}").click()
    page.get_by_test_id(f"plan-skip-{tid}").click()
    page.get_by_test_id(f"plan-more-{tid}").click()
    page.get_by_test_id(f"plan-swap-{tid}").click()
    expect(page.get_by_test_id(f"plan-task-{tid}")).to_contain_text("swapped")


# ---- FR-10.63: every task type opens its screen ----


def _task_of_type(page: Page, title_part: str) -> str:
    row = page.get_by_test_id("plan-current").locator('[data-testid^="plan-task-"]').filter(has_text=title_part).first
    testid = row.get_attribute("data-testid")
    assert testid is not None
    return testid.split("-")[-1]


def _expand_all(page: Page) -> None:
    for c in page.locator('[data-testid^="plan-day-control-"]').all():
        if c.get_attribute("aria-expanded") == "false":
            c.click()


def test_a_puzzle_task_starts_a_session_and_leaves_the_mixer_alone(page: Page) -> None:
    _open(page, "coach=report&plan=current")
    tid = _first_task(page, "today-card").get_attribute("data-testid").split("-")[-1]
    page.get_by_test_id(f"plan-start-{tid}").click()
    expect(page.get_by_test_id("plan-session-banner")).to_be_visible()
    expect(page.get_by_test_id("plan-session-banner")).to_contain_text("yours are unchanged")
    assert not any(c.startswith("setting:mixer.filters") or c.startswith("setting:trainer.mode") for c in _calls(page))
    assert f"startTask:{tid}:puzzles" in _calls(page)


def test_start_starts_one_session_only(page: Page) -> None:
    """StrictMode runs a state updater twice, so an API call inside one would start two sessions."""
    _open(page, "coach=report&plan=current")
    tid = _first_task(page, "today-card").get_attribute("data-testid").split("-")[-1]
    page.get_by_test_id(f"plan-start-{tid}").click()
    expect(page.get_by_test_id("plan-session-banner")).to_be_visible()
    assert _calls(page).count(f"startTask:{tid}:puzzles") == 1


def test_the_plan_settings_are_kept_as_you_change_them_and_the_ai_box_says_them(page: Page) -> None:
    _open(page, "ai=on&coach=report")
    _coach(page, "plan")
    page.get_by_test_id("plan-weekday-0").click()  # Monday off: 4 days a week
    assert any(c.startswith("setting:plan.params") for c in _calls(page))
    page.get_by_test_id("coach-tab-report").click()
    page.get_by_test_id("coach-history-1").click()
    expect(page.get_by_test_id("coach-ai")).to_be_visible()


def test_retry_opens_retry_mode(page: Page) -> None:
    _open(page, "coach=report&plan=current")
    _coach(page, "plan")
    _expand_all(page)
    _in_plan(page).get_by_test_id(f"plan-start-{_task_of_type(page, 'Retry your mistakes')}").click()
    expect(page.get_by_test_id("retry-mode")).to_be_visible()


def test_a_review_task_hides_best_moves_without_changing_your_setting(page: Page) -> None:
    _open(page, "coach=report&plan=current&showbest=1")
    _coach(page, "plan")
    _expand_all(page)
    _in_plan(page).get_by_test_id(f"plan-start-{_task_of_type(page, 'with best moves hidden')}").click()
    expect(page.get_by_test_id("review-show-best")).not_to_be_checked()
    assert not any(c.startswith("setting:review.show_best") for c in _calls(page))
    page.get_by_test_id("review-show-best").check()  # you can still look, for this game
    assert not any(c.startswith("setting:review.show_best") for c in _calls(page))


def test_a_review_task_ticks_from_the_moves_you_visit(page: Page) -> None:
    _open(page, "coach=report&plan=current")
    _coach(page, "plan")
    _expand_all(page)
    tid = _task_of_type(page, "with best moves hidden")
    _in_plan(page).get_by_test_id(f"plan-start-{tid}").click()
    page.get_by_test_id("move-2").click()
    assert "markPly:1:2" in _calls(page)
    page.get_by_test_id("move-8").click()
    page.get_by_role("button", name="← Coach").click()
    _expand_all(page)
    expect(_in_plan(page).get_by_test_id(f"plan-task-{tid}")).to_have_attribute("data-status", "done")


def test_a_lesson_task_opens_its_links_and_ticks(page: Page) -> None:
    _open(page, "coach=report&plan=current")
    _coach(page, "plan")
    _expand_all(page)
    tid = _task_of_type(page, "Lesson:")
    _in_plan(page).get_by_test_id(f"plan-start-{tid}").click()
    page.get_by_test_id("lesson-task-curated-0").click()
    expect(_in_plan(page).get_by_test_id(f"plan-task-{tid}")).to_have_attribute("data-status", "done")
    assert f"openPlanLesson:{tid}:curated:0" in _calls(page)


def test_a_reflection_task_opens_the_journal_and_saving_ticks_it(page: Page) -> None:
    _open(page, "coach=report&plan=current")
    _coach(page, "plan")
    _expand_all(page)
    tid = _task_of_type(page, "Reflection:")
    _in_plan(page).get_by_test_id(f"plan-start-{tid}").click()
    expect(page.get_by_test_id("journal-prompt")).to_be_visible()
    page.get_by_test_id("journal-text").fill("I'm checking replies more often now.")
    page.get_by_test_id("journal-save").click()
    page.get_by_test_id("coach-tab-plan").click()
    _expand_all(page)
    expect(_in_plan(page).get_by_test_id(f"plan-task-{tid}")).to_have_attribute("data-status", "done")


def test_saving_a_reflection_ticks_its_task_after_you_closed_the_question(page: Page) -> None:
    """Adam, 2026-11-06: closing the box only gets it out of the way, and the composer says what saving will do."""
    _open(page, "coach=report&plan=current")
    _coach(page, "plan")
    _expand_all(page)
    tid = _task_of_type(page, "Reflection:")
    _in_plan(page).get_by_test_id(f"plan-start-{tid}").click()
    expect(page.get_by_test_id("journal-prompt")).to_be_visible()
    expect(page.get_by_test_id("journal-task-link")).to_have_count(0)
    page.get_by_test_id("journal-prompt").get_by_role("button").click()
    expect(page.get_by_test_id("journal-prompt")).to_have_count(0)
    expect(page.get_by_test_id("journal-task-link")).to_be_visible()
    page.get_by_test_id("journal-text").fill("Saved after closing the question.")
    page.get_by_test_id("journal-save").click()
    expect(page.get_by_test_id("journal-task-link")).to_have_count(0)
    page.get_by_test_id("coach-tab-plan").click()
    _expand_all(page)
    expect(_in_plan(page).get_by_test_id(f"plan-task-{tid}")).to_have_attribute("data-status", "done")


# ---- the journal ----


def test_the_daily_log_says_how_many_games_you_played(page: Page) -> None:
    _open(page, "coach=report&plan=current&journal=some")
    _coach(page, "journal")
    expect(page.get_by_test_id("journal-log").first).to_contain_text("played")


def test_write_edit_and_delete_a_note(page: Page) -> None:
    _open(page, "coach=report")
    _coach(page, "journal")
    page.get_by_test_id("journal-text").fill("<b>not html</b> a note")
    page.get_by_test_id("journal-save").click()
    entry = page.get_by_test_id("journal-entry-1")
    expect(entry).to_contain_text("<b>not html</b> a note")  # shown as text, never as HTML
    page.get_by_test_id("journal-edit-1").click()
    page.get_by_test_id("journal-edit-text-1").fill("Edited.")
    page.get_by_test_id("journal-save-1").click()
    expect(entry).to_contain_text("Edited.")
    page.get_by_test_id("journal-delete-1").click()
    expect(entry).to_have_count(0)


def test_filters_search_and_the_daily_log(page: Page) -> None:
    _open(page, "coach=report&journal=some")
    _coach(page, "journal")
    expect(page.get_by_test_id("journal-log")).to_be_visible()
    page.get_by_test_id("journal-search").fill("knight")
    expect(page.get_by_test_id("journal-entry-2")).to_be_visible()
    expect(page.get_by_test_id("journal-entry-1")).to_have_count(0)
    expect(page.get_by_test_id("journal-log")).to_have_count(0)  # the log has no text to search
    page.get_by_test_id("journal-search").fill("")
    page.get_by_test_id("journal-filter-note").click()
    expect(page.get_by_test_id("journal-entry-1")).to_be_visible()
    expect(page.get_by_test_id("journal-entry-2")).to_have_count(0)


def test_a_reflection_links_back_to_the_position(page: Page) -> None:
    _open(page, "coach=report&journal=some")
    _coach(page, "journal")
    page.get_by_test_id("journal-open-2").click()
    expect(page.get_by_test_id("move-list")).to_be_visible()


def test_add_a_note_in_game_review_marks_the_move(page: Page) -> None:
    _open(page, "coach=report")
    _coach(page)
    page.get_by_test_id("example-allowed:fork-0").click()
    expect(page.get_by_test_id("game-notes")).to_be_visible()
    page.get_by_test_id("move-4").click()
    page.get_by_test_id("game-note-add").click()
    page.get_by_test_id("game-note-text").fill("I didn't see the knight jump.")
    page.get_by_test_id("game-note-save").click()
    expect(page.get_by_test_id("game-notes")).to_contain_text("I didn't see the knight jump.")
    expect(page.get_by_test_id("move-note-4")).to_be_visible()
    assert "journalAdd:reflection" in _calls(page)


# ---- Since last report ----


def _second_report(page: Page) -> None:
    page.get_by_test_id("coach-run").click()
    expect(page.get_by_test_id("since-last-report")).to_be_visible(timeout=5000)


def test_a_first_report_has_no_comparison(page: Page) -> None:
    _open(page, "coach=report")
    _coach(page)
    expect(page.get_by_test_id("coach-report")).to_be_visible()
    expect(page.get_by_test_id("since-last-report")).to_have_count(0)


def test_the_second_report_compares_with_new_and_gone_marked(page: Page) -> None:
    _open(page, "coach=report")
    _coach(page)
    _second_report(page)
    assert (
        page.get_by_test_id("since-missed:pin").locator("[data-verdict]").first.get_attribute("data-verdict")
        == "better"
    )
    assert (
        page.get_by_test_id("since-allowed:fork").locator("[data-verdict]").first.get_attribute("data-verdict")
        == "worse"
    )
    expect(page.get_by_test_id("since-new-habit:hungPiece")).to_be_visible()
    expect(page.get_by_test_id("since-gone-missed:skewer")).to_be_visible()
    expect(page.get_by_test_id("since-opening_score:French Defense")).to_contain_text("not enough new games yet")


# ---- AI coaching ----


def _ai(page: Page, extra: str = "") -> None:
    _open(page, f"ai=on&coach=report{extra}")
    _coach(page)
    expect(page.get_by_test_id("coach-ai")).to_be_visible()


def _run_ai(page: Page) -> None:
    page.get_by_test_id("coach-ai-start").click()
    page.get_by_test_id("coach-ai-confirm-button").click()
    expect(page.get_by_test_id("coach-ai-result")).to_be_visible(timeout=5000)


def test_include_my_journal_is_off_shows_a_preview_and_warns(page: Page) -> None:
    _ai(page)
    box = page.get_by_test_id("coach-ai-journal")
    expect(box).not_to_be_checked()
    box.check()
    expect(page.get_by_test_id("coach-journal-line")).to_have_count(2)
    expect(page.get_by_test_id("coach-journal-warning")).to_contain_text("sent as written")
    page.get_by_test_id("coach-notes-remove").click()
    expect(box).not_to_be_checked()


def test_the_journal_option_goes_with_the_run(page: Page) -> None:
    _ai(page)
    page.get_by_test_id("coach-ai-journal").check()
    page.get_by_test_id("coach-notes-ok").click()
    _run_ai(page)
    assert any(c.endswith(":journal") and c.startswith("coachAi:") for c in _calls(page))


def test_the_ai_plan_compares_with_the_free_one_and_can_be_used(page: Page) -> None:
    _ai(page)
    _run_ai(page)
    expect(page.get_by_test_id("ai-plan-list")).to_be_visible()
    expect(page.get_by_test_id("ai-plan-check")).to_contain_text("tasks from the AI")
    page.get_by_test_id("ai-plan-compare").click()
    expect(page.get_by_test_id("ai-plan-free")).to_be_visible()
    page.get_by_test_id("ai-plan-use").click()
    expect(page.get_by_test_id("ai-plan-used")).to_be_visible()
    assert any(c.startswith("useAiPlan:") for c in _calls(page))
    page.get_by_test_id("coach-tab-plan").click()
    expect(page.get_by_test_id("plan-current")).to_contain_text("from the AI")


def test_using_the_ai_plan_over_a_current_one_asks_first(page: Page) -> None:
    _ai(page, "&plan=current")
    _run_ai(page)
    page.get_by_test_id("ai-plan-use").click()
    expect(page.get_by_test_id("ai-plan-confirm-button")).to_be_visible()
    assert not any(c.startswith("useAiPlan:") for c in _calls(page))
    page.get_by_test_id("ai-plan-confirm-button").click()
    expect(page.get_by_test_id("ai-plan-used")).to_be_visible()
    assert any(c.startswith("useAiPlan:") for c in _calls(page))


def test_the_ai_says_what_changed_since_last_report(page: Page) -> None:
    _ai(page)
    _second_report(page)
    _run_ai(page)
    expect(page.get_by_test_id("ai-trend-missed:pin")).to_contain_text("Improved")
    expect(page.get_by_test_id("ai-trend-allowed:fork")).to_contain_text("Worse")
