"""QA v0.12 in the UI on the mock client: what the builder's Playwright tests don't look at (FR-10.65, 10.67-10.72), and
the screenshots for the visual check. A test exposing an open bug is marked xfail with its ID."""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.test_v012_tooltips import _assert_all_have_tips

pytestmark = pytest.mark.e2e
ART = Path("tests/e2e/artifacts")


def _open(page: Page, query: str) -> None:
    page.goto(f"{page.base_url}/?{query}")  # type: ignore[attr-defined]


def _coach(page: Page, tab: str | None = None) -> None:
    page.get_by_test_id("nav-coach").click()
    if tab:
        page.get_by_test_id(f"coach-tab-{tab}").click()


def _shot(page: Page, name: str, full: bool = True) -> None:
    ART.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(ART / f"qa-v012-{name}.png"), full_page=full)


# ---- FR-10.69, 10.70 ----


@pytest.mark.xfail(strict=True, reason="v0.12-B3: the journal's link opens the position before the move the note is on")
def test_qa_a_notes_link_opens_the_very_move_the_note_is_on(page: Page) -> None:
    _open(page, "coach=report&journal=some")
    _coach(page, "journal")
    page.get_by_test_id("journal-open-2").click()  # the mock's reflection is on ply 6
    expect(page.get_by_test_id("move-note-6")).to_be_visible()
    expect(page.get_by_test_id("move-6")).to_have_attribute("data-variant", "filled", timeout=2000)


def test_qa_a_note_links_inside_the_game_go_to_their_move(page: Page) -> None:
    _open(page, "coach=report&journal=some")
    _coach(page, "journal")
    page.get_by_test_id("journal-open-2").click()
    page.locator('[data-testid^="game-note-go-"]').first.click()
    expect(page.get_by_test_id("move-6")).to_have_attribute("data-variant", "filled")


@pytest.mark.xfail(strict=True, reason="v0.12-B4: the Journal tab has no game filter (FR-10.70)")
def test_qa_the_journal_can_be_filtered_by_game(page: Page) -> None:
    _open(page, "coach=report&journal=some")
    _coach(page, "journal")
    filters = page.get_by_test_id("journal-filters")
    expect(filters.get_by_text("Game", exact=False)).to_be_visible(timeout=2000)


def test_qa_html_in_your_own_words_is_only_text(page: Page) -> None:
    evil = '<img src=x onerror="window.__pwned=1"><script>window.__pwned=1</script>'
    _open(page, "coach=report")
    _coach(page, "journal")
    page.get_by_test_id("journal-text").fill(evil)
    page.get_by_test_id("journal-save").click()
    timeline = page.get_by_test_id("journal-timeline")
    expect(timeline).to_contain_text("<img src=x")
    assert timeline.locator("img, script").count() == 0
    assert page.evaluate("window.__pwned") is None


@pytest.mark.xfail(strict=True, reason="v0.12-B14: one long word in a note makes the whole page scroll sideways")
def test_qa_the_longest_entry_of_one_unbroken_word_stays_inside_its_box(page: Page) -> None:
    _open(page, "coach=report")
    _coach(page, "journal")
    page.get_by_test_id("journal-text").fill("y" * 5000)
    expect(page.get_by_test_id("journal-composer")).to_contain_text("5000 / 5,000")
    page.get_by_test_id("journal-save").click()
    entry = page.locator('[data-testid^="journal-entry-"]').first
    expect(entry).to_be_visible()
    _shot(page, "journal-long-entry")
    width = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert width <= 0, f"the page scrolls sideways by {width}px"
    assert entry.evaluate("e => e.scrollWidth <= e.clientWidth + 1"), "the text runs out of its box"


def test_qa_past_the_limit_the_box_stops_taking_text(page: Page) -> None:
    _open(page, "coach=report")
    _coach(page, "journal")
    box = page.get_by_test_id("journal-text")
    box.fill("y" * 5000)
    box.press_sequentially("z")
    assert len(box.input_value()) == 5000


def test_qa_a_blank_note_cant_be_saved_and_a_filter_with_nothing_says_so(page: Page) -> None:
    _open(page, "coach=report")
    _coach(page, "journal")
    page.get_by_test_id("journal-text").fill("    ")
    expect(page.get_by_test_id("journal-save")).to_be_disabled()
    page.get_by_test_id("journal-search").fill("no such words anywhere")
    expect(page.get_by_test_id("journal-empty")).to_be_visible()


# ---- FR-10.72: the screens the builder's walk doesn't reach ----


def test_qa_tips_on_the_stats_page(page: Page) -> None:
    _open(page, "ai=on")
    page.get_by_test_id("trainer-page").wait_for()
    page.get_by_role("button", name="Menu").click()
    page.get_by_role("menuitem", name="Stats").click()
    page.get_by_test_id("stats-view").wait_for()
    page.wait_for_timeout(300)
    _assert_all_have_tips(page, "Stats")


@pytest.mark.parametrize("mode", ["standard", "commit_line", "name_idea", "danger_spotting", "spaced_repetition"])
def test_qa_tips_in_every_mode_before_and_during_a_session(page: Page, mode: str) -> None:
    _open(page, f"mode={mode}&engine=ready")
    page.get_by_test_id("trainer-page").wait_for()
    _assert_all_have_tips(page, f"Mixer, {mode}")
    start = page.get_by_test_id("start")
    assert start.count() == 1
    if start.is_enabled():
        start.click()
        page.wait_for_timeout(600)
        _assert_all_have_tips(page, f"Session, {mode}")


def test_qa_tips_in_the_plan_builder_with_a_preview_and_the_ai_answer(page: Page) -> None:
    _open(page, "ai=on&coach=report&plan=current&journal=some")
    _coach(page, "plan")
    page.get_by_test_id("plan-preview").click()
    page.get_by_test_id("plan-preview-list").wait_for()
    _assert_all_have_tips(page, "Plan preview")
    _shot(page, "plan-tab")
    page.get_by_test_id("plan-create").click()
    page.get_by_test_id("plan-confirm").wait_for(state="attached")
    page.wait_for_timeout(250)
    _assert_all_have_tips(page, "Plan replace confirm")
    _shot(page, "plan-confirm", full=False)


# ---- the visual check ----


def test_qa_screenshots_of_each_new_screen(page: Page) -> None:
    page.set_viewport_size({"width": 1280, "height": 800})
    _open(page, "ai=on&coach=report&plan=current&journal=some")
    page.get_by_test_id("today-card").wait_for()
    _shot(page, "today-card")
    _coach(page, "plan")
    page.get_by_test_id("plan-current").wait_for()
    _shot(page, "plan-current")
    page.get_by_test_id("coach-tab-journal").click()
    page.get_by_test_id("journal-tab").wait_for()
    _shot(page, "journal")
    page.get_by_test_id("journal-open-2").click()
    page.get_by_test_id("game-notes").wait_for()
    _shot(page, "review-notes")
    page.get_by_test_id("review-back").click()
    page.get_by_test_id("coach-tab-report").click()
    page.get_by_test_id("coach-ai").scroll_into_view_if_needed()
    _shot(page, "report")
    page.get_by_test_id("coach-ai-journal").check()
    page.get_by_test_id("coach-notes-preview").wait_for(state="attached")
    page.wait_for_timeout(300)
    _shot(page, "journal-preview", full=False)


def test_qa_a_narrow_window_keeps_the_new_screens_usable(page: Page) -> None:
    page.set_viewport_size({"width": 900, "height": 650})
    _open(page, "ai=on&coach=report&plan=current&journal=some")
    page.get_by_test_id("today-card").wait_for()
    _shot(page, "today-narrow")
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
    _coach(page, "plan")
    page.get_by_test_id("plan-current").wait_for()
    _shot(page, "plan-narrow")
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
    page.get_by_test_id("coach-tab-journal").click()
    page.get_by_test_id("journal-tab").wait_for()
    _shot(page, "journal-narrow")
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
