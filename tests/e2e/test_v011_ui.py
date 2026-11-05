"""v0.11 UI against the mock: whole-game measures (FR-10.53), the AI diagnosis with evidence (FR-10.54,
10.55), Advanced analysis and its comparison (FR-10.56), Include my notes and its preview (FR-10.60),
lesson pointers whose links only the backend builds (FR-10.59), the AI-run picker, Settings → Coach.

Mock game 1 is the Blackburne Shilling trap, analyzed: you are White and blunder with 4.Nxe5 (ply 6)."""

from __future__ import annotations

import pytest

from tests.e2e.test_v010_ui import coach

pytestmark = pytest.mark.e2e


def calls(page) -> list[str]:  # type: ignore[no-untyped-def]
    return list(page.evaluate("window.__mockApi.calls"))


def ask(page, *, advanced: bool = False, notes: bool = False) -> None:  # type: ignore[no-untyped-def]
    if advanced:
        page.get_by_test_id("coach-ai-advanced").check()
    if notes:
        page.get_by_test_id("coach-ai-notes").check()
        page.get_by_test_id("coach-notes-ok").click()
    page.get_by_test_id("coach-ai-start").click()
    page.get_by_test_id("coach-ai-confirm-button").click()


def test_the_report_shows_whole_game_measures_with_the_guard(page) -> None:  # type: ignore[no-untyped-def]
    coach(page, "?coach=report")
    m = page.get_by_test_id("coach-measures")
    m.wait_for()
    assert "Italian Game" in page.get_by_test_id("measures-openings").inner_text()
    french = page.get_by_test_id("measures-openings").get_by_role("row").filter(has_text="French Defense")
    assert french.get_by_test_id("not-enough").count() == 1  # 3 games: not enough data yet
    assert "Won from +2 or better: 55% of 11" in page.get_by_test_id("measures-phases").inner_text()
    assert page.get_by_test_id("weakness-time:low_clock").count() == 1  # a whole-game weakness


def test_a_standard_run_shows_the_diagnosis_with_evidence(page) -> None:  # type: ignore[no-untyped-def]
    coach(page, "?ai=on&coach=report")
    page.get_by_test_id("coach-ai-start").click()
    page.get_by_test_id("narrative-estimate").filter(has_text="a short digest of each game").wait_for()
    assert page.get_by_test_id("coach-ai-compare").count() == 0  # a standard run has no Advanced comparison
    page.get_by_test_id("coach-ai-confirm-button").click()
    page.get_by_test_id("coach-ai-result").wait_for(timeout=5000)
    assert any(c.endswith(":standard:nonotes") for c in calls(page))
    findings = page.get_by_test_id("ai-finding")
    assert findings.count() == 3
    assert findings.nth(1).get_by_test_id("finding-tentative").count() == 1
    assert findings.nth(2).get_by_test_id("finding-observation").count() == 1
    page.get_by_test_id("evidence-G1-6").click()
    page.get_by_test_id("review-view").wait_for()
    assert page.get_by_test_id("review-back").inner_text() == "← Coach"
    assert page.get_by_test_id("review-move").inner_text().startswith("3")  # the position before 4.Nxe5


def test_advanced_shows_the_comparison_before_confirm(page) -> None:  # type: ignore[no-untyped-def]
    coach(page, "?ai=on&coach=report")
    page.get_by_test_id("coach-ai-advanced").check()
    page.get_by_test_id("coach-ai-cap").fill("20")
    page.get_by_test_id("coach-ai-start").click()
    compare = page.get_by_test_id("coach-ai-compare")
    compare.wait_for()
    text = compare.inner_text()
    assert (
        "3.8× the tokens of a standard run" in text and "of this month's budget" in text and "about 2 minutes" in text
    )
    assert "It takes longer and uses more API tokens." in text
    assert "Advanced also sends the moves (SAN only)" in page.get_by_test_id("narrative-estimate").inner_text()
    page.get_by_test_id("coach-ai-confirm-button").click()
    page.get_by_test_id("coach-ai-result").filter(has_text="Advanced (20 games)").wait_for(timeout=5000)
    assert any(c.endswith(":advanced:20:nonotes") for c in calls(page))


def test_advanced_and_notes_are_off_every_time(page) -> None:  # type: ignore[no-untyped-def]
    coach(page, "?ai=on&coach=report")
    page.get_by_test_id("coach-ai-advanced").check()
    page.get_by_test_id("nav-puzzles").click()
    page.get_by_test_id("nav-coach").click()
    page.get_by_test_id("coach-ai").wait_for()
    assert not page.get_by_test_id("coach-ai-advanced").is_checked()
    assert not page.get_by_test_id("coach-ai-notes").is_checked()


def test_the_notes_preview_lists_exactly_what_is_sent(page) -> None:  # type: ignore[no-untyped-def]
    coach(page, "?ai=on&coach=report")
    page.get_by_test_id("coach-ai-notes").check()
    preview = page.get_by_test_id("coach-notes-preview")
    preview.get_by_test_id("coach-note").first.wait_for()
    notes = [n.inner_text() for n in preview.get_by_test_id("coach-note").all()]
    assert len(notes) == 3
    assert "G1 · 4. Nxe5" in notes[0] and "[link removed]" in notes[0]
    assert notes[2].startswith("A puzzle")
    page.get_by_test_id("coach-notes-remove").click()
    assert not page.get_by_test_id("coach-ai-notes").is_checked()
    ask(page, notes=True)
    page.get_by_test_id("coach-ai-result").filter(has_text="with your notes").wait_for(timeout=5000)
    assert any(c.endswith(":standard:notes") for c in calls(page))


def test_a_lesson_click_sends_only_the_topic_and_target(page) -> None:  # type: ignore[no-untyped-def]
    coach(page, "?ai=on&coach=report")
    ask(page)
    page.get_by_test_id("coach-ai-result").wait_for(timeout=5000)
    lesson = page.get_by_test_id("ai-finding").first.get_by_test_id("finding-lesson")
    lesson.get_by_test_id("lesson-curated-0").click()
    lesson.get_by_test_id("lesson-youtube").click()
    opened = [c for c in calls(page) if c.startswith("openLesson:")]
    assert opened == ["openLesson:1:theme:fork:curated:0", "openLesson:1:theme:fork:youtube"]
    assert all("http" not in c for c in opened)
    assert page.locator("a[href^='http']").filter(has_text="Lichess Practice").count() == 0  # no URL in the page
    lesson.get_by_test_id("lesson-drill").click()  # Learn Fork: the drill loads into the trainer
    page.get_by_test_id("trainer-page").wait_for()


def test_the_run_picker_switches_answers(page) -> None:  # type: ignore[no-untyped-def]
    coach(page, "?ai=on&coach=report")
    ask(page)
    page.get_by_test_id("coach-ai-result").filter(has_text="Standard").wait_for(timeout=5000)
    ask(page, advanced=True)
    result = page.get_by_test_id("coach-ai-result")
    result.filter(has_text="Advanced (30 games)").wait_for(timeout=5000)
    assert result.get_by_test_id("finding-new").count() == 1  # found only with the move lists
    picker = page.get_by_test_id("coach-ai-runs")
    picker.click()
    page.get_by_role("option").filter(has_text="#1 · Standard").click()
    result.filter(has_text="Standard ·").wait_for()
    assert result.get_by_test_id("ai-finding").count() == 3


def test_settings_choose_the_search_sites(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/")
    page.get_by_test_id("gear").click()
    panel = page.get_by_test_id("coach-settings")
    panel.wait_for()
    panel.get_by_test_id("lesson-site-chesscom").uncheck()
    panel.get_by_test_id("lesson-custom-url").fill("http://example.org/?q={q}")
    panel.get_by_test_id("lesson-custom-url").blur()
    panel.get_by_test_id("coach-settings-error").wait_for()
    panel.get_by_test_id("lesson-custom-url").fill("https://example.org/search?q={q}")
    panel.get_by_test_id("lesson-custom-url").blur()
    panel.get_by_text("Search site saved.").wait_for()
    assert 'setting:coach.lesson_sites=["youtube"]' in calls(page)
    assert 'setting:coach.lesson_custom_url="https://example.org/search?q={q}"' in calls(page)


def test_retry_offers_explain_after_you_try(page) -> None:  # type: ignore[no-untyped-def]
    """Adam, 2026-11-04: Retry your mistakes has Explain this move too, once you've tried (FR-11.15)."""
    from tests.e2e.conftest import play
    from tests.e2e.test_game_ai_ui import review

    review(page)
    page.get_by_test_id("retry-start").click()
    page.get_by_test_id("retry-mode").wait_for()
    assert page.get_by_test_id("move-explain").count() == 0  # never before your attempt
    play(page, "f3d4", "white")
    page.get_by_test_id("retry-result").wait_for()
    retry = page.get_by_test_id("retry-mode")
    retry.get_by_test_id("move-explain-button").click()
    retry.get_by_test_id("move-explain").get_by_text("Show me").first.wait_for(timeout=5000)


# ---- presets (Adam, 2026-11-04, during the v0.11 build) -------------------------------------------------


def _save_preset(page, name: str) -> None:  # type: ignore[no-untyped-def]
    page.get_by_test_id("preset-save").click()
    page.get_by_test_id("preset-name").fill(name)
    page.get_by_test_id("preset-confirm").click()
    page.get_by_test_id("preset-name").wait_for(state="hidden")


def test_manage_presets_renames_and_deletes_any_preset_without_loading_it(page) -> None:  # type: ignore[no-untyped-def]
    from tests.e2e.test_mixer_v02 import pick_theme
    from tests.e2e.test_qa_v01_ui import count_text, ready

    ready(page)
    pick_theme(page, "themes-picker", "fork", "Fork")
    _save_preset(page, "Forks")
    before = count_text(page)
    page.get_by_test_id("preset-actions").click()
    page.get_by_test_id("preset-manage").click()
    manager = page.get_by_test_id("preset-manager")
    manager.get_by_test_id("preset-row-Endgame drill").get_by_test_id("preset-row-rename").click()
    page.get_by_test_id("preset-name").fill("Old endgames")
    page.get_by_test_id("preset-confirm").click()
    manager.get_by_test_id("preset-row-Old endgames").wait_for()  # back in the list, renamed
    manager.get_by_test_id("preset-row-Old endgames").get_by_test_id("preset-row-delete").click()
    page.get_by_test_id("preset-delete-confirm").click()
    manager.get_by_test_id("preset-row-Forks").wait_for()
    assert manager.get_by_test_id("preset-row-Old endgames").count() == 0
    assert count_text(page) == before  # managing presets never changes your filters


def test_update_overwrites_the_loaded_preset_with_the_current_filters(page) -> None:  # type: ignore[no-untyped-def]
    from tests.e2e.test_mixer_v02 import pick_theme
    from tests.e2e.test_qa_v01_ui import count_text, ready

    ready(page)
    pick_theme(page, "themes-picker", "fork", "Fork")
    _save_preset(page, "Tactics")
    pick_theme(page, "themes-picker", "pin", "Pin")
    with_pin = count_text(page)
    page.get_by_test_id("preset-actions").click()
    page.get_by_test_id("preset-update").click()
    page.get_by_test_id("preset-notice").filter(has_text="“Tactics” now has your current filters.").wait_for()
    page.get_by_test_id("themes-picker").click()
    page.get_by_role("button", name="Clear").click()
    page.keyboard.press("Escape")
    page.get_by_test_id("preset-select").click()
    page.get_by_role("option", name="Tactics").click()
    assert count_text(page) == with_pin


def test_a_coach_preset_with_a_name_you_use_can_replace_it_or_take_another(page) -> None:  # type: ignore[no-untyped-def]
    coach(page, "?coach=report")
    box = page.get_by_test_id("coach-preset")
    box.get_by_test_id("coach-preset-save").click()
    box.get_by_text("Saved as “The report's mix”.").wait_for()
    box.get_by_test_id("coach-preset-save").click()
    box.get_by_test_id("coach-preset-clash").wait_for()
    box.get_by_test_id("coach-preset-replace").click()
    box.get_by_test_id("coach-preset-clash").wait_for(state="hidden")
    box.get_by_test_id("coach-preset-save").click()
    box.get_by_test_id("coach-preset-name").fill("Coach mix, November")
    box.get_by_test_id("coach-preset-save-as").click()
    box.get_by_text("Saved as “Coach mix, November”.").wait_for()
