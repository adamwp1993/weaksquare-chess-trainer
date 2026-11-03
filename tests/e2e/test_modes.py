"""v0.5 against the mock client: the Modes control and mode switching (§6), Commit the line (FR-4.2),
Spaced repetition (FR-4.6), the depth-ladder order (FR-4.5), the collapsible filters panel (FR-1.14),
Settings → Training / Debug, and Stats by mode (FR-9.1)."""

from __future__ import annotations

import pytest

from tests.e2e.conftest import play
from tests.e2e.test_engine_ui import no_engine_output

pytestmark = pytest.mark.e2e

# The mock's first puzzle (DtKOy): you play black; d5c3 (you) b1b5 (reply) c3d1 (you).
LINE = ["d5c3", "b1b5", "c3d1"]


def calls(page) -> list[str]:  # type: ignore[no-untyped-def]
    return page.evaluate("window.__mockApi.calls")


def open_app(page, query: str = "") -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/" + query)
    page.get_by_test_id("mode-control").wait_for()


def choose_mode(page, label: str) -> None:  # type: ignore[no-untyped-def]
    page.get_by_test_id("mode-control").get_by_text(label, exact=True).click()


def start_session(page) -> None:  # type: ignore[no-untyped-def]
    page.get_by_role("button", name="Start").click()
    page.get_by_test_id("trainer-message").wait_for()
    page.wait_for_timeout(700)  # the opponent's first move


def enter(page, moves: list[str], orientation: str = "black") -> None:  # type: ignore[no-untyped-def]
    for uci in moves:
        play(page, uci, orientation)
        page.wait_for_timeout(100)


# ---- Commit the line ------------------------------------------------------------------------------


def test_commit_the_line_right_line_is_a_win_with_calculation_accuracy(page) -> None:  # type: ignore[no-untyped-def]
    open_app(page)
    choose_mode(page, "Commit the line")
    assert "Enter the whole line" in page.get_by_test_id("mode-description").inner_text()
    start_session(page)
    assert "Nothing is checked until you press Submit" in page.get_by_test_id("trainer-message").inner_text()
    enter(page, LINE)  # both sides, by hand
    assert page.get_by_test_id("commit-count").inner_text().startswith("3 moves entered")
    assert page.get_by_test_id("outcome").count() == 0  # nothing graded yet
    no_engine_output(page)  # FR-7.3: no engine before Submit
    page.get_by_test_id("commit-submit").click()
    page.get_by_test_id("outcome").filter(has_text="Solved").wait_for()
    assert page.get_by_test_id("commit-calculation").inner_text() == "Replies predicted: 1 of 1"
    assert page.get_by_test_id("commit-ply").count() == 3
    page.get_by_test_id("engine-panel").wait_for()  # the puzzle is over: the engine may show
    assert f"submitLine:{' '.join(LINE)}" in calls(page)
    assert "start:commit_line" in calls(page)


def test_commit_wrong_line_undo_clear_and_show_move_count(page) -> None:  # type: ignore[no-untyped-def]
    open_app(page)
    choose_mode(page, "Commit the line")
    page.get_by_test_id("show-length-switch").click()
    assert "setting:commit.show_length=true" in calls(page)
    start_session(page)
    assert page.get_by_test_id("commit-count").inner_text().startswith("Find 3 moves")
    enter(page, LINE[:2])
    page.get_by_test_id("commit-undo").click()
    assert "1 of 3 entered" in page.get_by_test_id("commit-count").inner_text()
    page.get_by_test_id("commit-clear").click()
    assert "0 of 3 entered" in page.get_by_test_id("commit-count").inner_text()
    assert page.get_by_test_id("commit-submit").is_disabled()
    enter(page, ["h7h6"])  # legal, not the solution
    page.get_by_test_id("commit-submit").click()
    page.get_by_test_id("outcome").filter(has_text="Failed").wait_for()
    plies = page.get_by_test_id("commit-ply")
    assert plies.first.get_by_label("wrong").count() == 1
    assert "solution:" in plies.first.inner_text()


def test_commit_try_again_lets_you_enter_the_line_again(page) -> None:  # type: ignore[no-untyped-def]
    open_app(page, "?mode=commit_line")
    start_session(page)
    enter(page, ["h7h6"])
    page.get_by_test_id("commit-submit").click()
    page.get_by_test_id("outcome").filter(has_text="Failed").wait_for()
    page.get_by_test_id("try-again").click()
    page.get_by_test_id("practice-badge").wait_for()
    page.wait_for_timeout(700)
    page.get_by_test_id("commit-controls").wait_for()
    enter(page, LINE)
    page.get_by_test_id("commit-submit").click()
    page.get_by_test_id("trainer-message").filter(has_text="practice, not scored").wait_for()
    page.get_by_test_id("outcome").filter(has_text="Failed").wait_for()  # the first result stays


# ---- Modes control ----------------------------------------------------------------------------------


def test_switching_mode_starts_a_new_session(page) -> None:  # type: ignore[no-untyped-def]
    open_app(page)
    start_session(page)
    assert page.get_by_test_id("session-mode").inner_text() == "Standard"
    choose_mode(page, "Commit the line")
    page.get_by_test_id("session-mode").filter(has_text="Commit the line").wait_for()
    assert calls(page).count("start:standard") == 1 and "start:commit_line" in calls(page)
    assert 'setting:trainer.mode="commit_line"' in calls(page)


def test_mode_is_remembered(page) -> None:  # type: ignore[no-untyped-def]
    open_app(page, "?mode=spaced_repetition")
    checked = page.get_by_test_id("mode-control").locator("input:checked")
    assert checked.get_attribute("value") == "spaced_repetition"


# ---- Spaced repetition ------------------------------------------------------------------------------


def test_spaced_repetition_serves_whats_due_and_ignores_the_filters(page) -> None:  # type: ignore[no-untyped-def]
    open_app(page)
    choose_mode(page, "Spaced repetition")
    assert page.get_by_test_id("srs-due").inner_text().startswith("2 puzzles due now")
    assert page.get_by_test_id("filters-fieldset").get_attribute("disabled") is not None
    assert page.get_by_test_id("srs-note").is_visible()
    start_session(page)
    assert page.get_by_test_id("session-mode").inner_text() == "Spaced repetition"
    assert "start:spaced_repetition" in calls(page)


def test_nothing_due_disables_start(page) -> None:  # type: ignore[no-untyped-def]
    open_app(page, "?srs=none&mode=spaced_repetition")
    page.get_by_test_id("srs-due").filter(has_text="0 puzzles due now").wait_for()
    assert page.get_by_role("button", name="Start").is_disabled()


def test_fast_forward_brings_a_miss_back_in_a_dev_run(page) -> None:  # type: ignore[no-untyped-def]
    open_app(page, "?dev=1&srs=none")
    start_session(page)
    page.get_by_test_id("next-button").click()  # skip: a miss, due tomorrow
    page.wait_for_timeout(300)
    choose_mode(page, "Spaced repetition")
    page.get_by_test_id("srs-due").filter(has_text="0 puzzles due now").wait_for()
    page.get_by_test_id("gear").click()
    page.get_by_test_id("time-offset").fill("1")
    page.get_by_test_id("time-offset-apply").click()
    page.keyboard.press("Escape")
    page.get_by_test_id("time-offset-banner").filter(has_text="+1 day").wait_for()
    choose_mode(page, "Standard")
    choose_mode(page, "Spaced repetition")
    page.get_by_test_id("srs-due").filter(has_text="1 puzzle due now").wait_for()
    assert "timeOffset:1" in calls(page)


def test_no_debug_section_outside_dev_runs(page) -> None:  # type: ignore[no-untyped-def]
    open_app(page)
    page.get_by_test_id("gear").click()
    page.get_by_test_id("training-settings").wait_for()
    assert page.get_by_test_id("debug-settings").count() == 0


# ---- Depth ladder -----------------------------------------------------------------------------------


def test_depth_ladder_order_sets_the_move_count_and_climbs(page) -> None:  # type: ignore[no-untyped-def]
    open_app(page)
    page.evaluate("window.__mockApi.setSetting('ladder.window', 3)")
    page.evaluate("window.__mockApi.setSetting('ladder.threshold', 100)")
    page.get_by_label("Order").get_by_text("Depth ladder").click()
    status = page.get_by_test_id("ladder-status")
    status.filter(has_text="Short puzzles (2 moves), step 1 of 3").wait_for()
    assert page.get_by_test_id("lengths-by-ladder").is_visible()
    assert page.get_by_test_id("ratio-switch").is_disabled()
    page.get_by_test_id("match-count").filter(has_text="at short").wait_for()
    start_session(page)
    page.get_by_test_id("session-ladder").filter(has_text="Short (1/3)").wait_for()
    # The mock's first three 2-move puzzles, solved in order.
    for first, second, color in (("d5c3", "c3d1", "black"), ("d4e2", "e2c1", "white"), ("d4c6", "c6b4", "white")):
        play(page, first, color)
        page.get_by_test_id("trainer-message").filter(has_text="Correct").wait_for()
        page.wait_for_timeout(500)
        play(page, second, color)
        page.get_by_test_id("outcome").filter(has_text="Solved").wait_for()
        if (first, color) != ("d4c6", "white"):
            page.get_by_test_id("next-button").click()
            page.wait_for_timeout(700)
    page.get_by_test_id("level-up").filter(has_text="Level up! Now long puzzles").wait_for()
    page.get_by_test_id("session-ladder").filter(has_text="Long (2/3)").wait_for()


# ---- Collapsible filters panel (FR-1.14) -----------------------------------------------------------


def test_hide_and_show_filters_keeps_them_and_saves_the_state(page) -> None:  # type: ignore[no-untyped-def]
    open_app(page)
    page.get_by_label("Order").get_by_text("By theme").click()
    page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for()
    page.get_by_test_id("hide-filters").click()
    strip = page.get_by_test_id("filters-strip")
    strip.wait_for()
    assert not page.get_by_test_id("mixer-column").is_visible()
    summary = page.get_by_test_id("filters-summary").inner_text()
    assert summary.startswith("Standard · All themes") and "puzzles" in summary
    assert "setting:ui.filters_collapsed=true" in calls(page)
    page.keyboard.press("f")  # F toggles it back
    page.get_by_test_id("mixer-column").wait_for(state="visible")
    assert page.get_by_label("Order").locator("input:checked").get_attribute("value") == "by_theme"
    assert "setting:ui.filters_collapsed=false" in calls(page)
    assert page.evaluate("localStorage.length + sessionStorage.length") == 0  # through the bridge only


def test_collapsed_panel_while_playing(page) -> None:  # type: ignore[no-untyped-def]
    open_app(page)
    start_session(page)
    page.get_by_test_id("hide-filters").click()
    page.get_by_test_id("filters-strip").wait_for()
    play(page, "d5c3", "black")  # the board still works, wider
    page.get_by_test_id("trainer-message").filter(has_text="Correct").wait_for()
    page.get_by_test_id("show-filters").click()
    page.get_by_test_id("mixer-column").wait_for(state="visible")


# ---- Stats and settings -----------------------------------------------------------------------------


def test_stats_by_mode_and_training_settings(page) -> None:  # type: ignore[no-untyped-def]
    open_app(page)
    page.get_by_role("button", name="Menu").click()
    page.get_by_role("menuitem", name="Stats").click()
    page.get_by_test_id("stats-mode-tab").click()
    table = page.get_by_test_id("stats-by-mode")
    table.wait_for()
    assert "Commit the line" in table.inner_text() and "Spaced repetition" in table.inner_text()
    page.keyboard.press("Escape")
    page.get_by_test_id("gear").click()
    page.get_by_test_id("srs-intervals").fill("2, 4, 8")
    page.get_by_test_id("srs-intervals-save").click()
    assert "setting:srs.intervals=[2,4,8]" in calls(page)
