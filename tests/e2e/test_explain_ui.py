"""v0.7 UI against the mock: AI settings (FR-1.2–1.4, 1.8), the spend indicator (FR-1.10), the startup fast
path's AI half (FR-1.6), the price table (FR-8.9) and Explain (FR-8.1–8.8): its gate, cost, guardrails,
cache, escaped text and Show me drawing.

The mock serves DtKOy first: you play black; the solution is d5c3 (then b1b5) c3d1.
"""

from __future__ import annotations

import pytest

from tests.e2e.conftest import play
from tests.e2e.test_engine_ui import WRONG, solve, start

pytestmark = pytest.mark.e2e

FAKE_KEY = "sk-ant-FAKE" + "key0" * 6


def open_ai_settings(page) -> None:  # type: ignore[no-untyped-def]
    page.get_by_test_id("gear").click()
    page.get_by_test_id("settings-ai").scroll_into_view_if_needed()


def test_no_ai_set_up_means_no_explain_and_no_indicator(page) -> None:  # type: ignore[no-untyped-def]
    start(page)
    solve(page)
    page.get_by_test_id("engine-panel").wait_for()
    assert page.get_by_test_id("explain-button").count() == 0  # FR-8.1: only with a provider and key
    assert page.get_by_test_id("spend-indicator").count() == 0  # FR-1.10


def test_set_up_a_provider_nothing_preselected(page) -> None:  # type: ignore[no-untyped-def]
    start(page)
    open_ai_settings(page)
    panel = page.get_by_test_id("settings-ai")
    panel.get_by_test_id("ai-provider").click()
    page.get_by_role("option", name="Anthropic").click()
    model = panel.get_by_test_id("ai-model")
    model.wait_for()
    assert model.input_value() == ""  # Adam, v0.7 planning: nothing is pre-selected
    model.click()
    page.get_by_role("option", name="claude-haiku-5-5").filter(has_text="per Explain").wait_for()
    page.get_by_role("option").filter(has_text="claude-haiku-5-5").click()
    panel.get_by_test_id("ai-key").fill(FAKE_KEY)
    panel.get_by_test_id("ai-key-save").click()
    page.get_by_text("A key is saved in Windows Credential Manager.").wait_for()
    assert panel.get_by_test_id("ai-key").input_value() == ""  # the key is never shown again
    assert FAKE_KEY not in page.content()
    panel.get_by_test_id("ai-key-test").click()
    panel.get_by_test_id("ai-key-result").filter(has_text="works with claude-haiku-5-5").wait_for()
    page.keyboard.press("Escape")
    page.get_by_test_id("spend-indicator").filter(has_text="AI $0.00 / $5.00").wait_for()


def test_a_key_for_the_wrong_provider_is_refused(page) -> None:  # type: ignore[no-untyped-def]
    start(page, "?ai=nomodel")
    open_ai_settings(page)
    panel = page.get_by_test_id("settings-ai")
    panel.get_by_test_id("ai-key").fill("sk-proj-FAKE" + "x" * 30)
    panel.get_by_test_id("ai-key-save").click()
    panel.get_by_test_id("ai-error").filter(has_text="Anthropic key: they start with sk-ant-").wait_for()


def test_explain_after_the_puzzle_draws_on_the_board(page) -> None:  # type: ignore[no-untyped-def]
    start(page, "?ai=on")
    button = page.get_by_test_id("explain-button")
    button.wait_for()
    assert button.is_disabled()  # FR-7.3 gate: not while solving
    play(page, WRONG, "black")
    page.get_by_test_id("outcome").filter(has_text="Failed").wait_for()
    assert button.is_disabled()  # lost, but still in progress
    page.get_by_test_id("answer-button").click()
    page.get_by_text("Explain (≈ $0.0").wait_for()  # the estimate inline, no confirm (FR-8.11)
    button.click()
    page.get_by_test_id("explanation").wait_for()
    summary = page.get_by_test_id("explanation-summary")
    assert "<b>This text is shown as typed</b>" in summary.inner_text()  # FR-8.7: escaped, not HTML
    assert summary.locator("b").count() == 0
    page.get_by_test_id("explanation-discarded").wait_for()  # FR-8.4's note
    assert "claude-haiku-5-5" in page.get_by_test_id("explanation-cost").inner_text()
    # Show me (FR-8.5): the solution from its start, with the first move's arrow and circle drawn.
    board = page.get_by_test_id("board")
    page.get_by_test_id("line-preview").wait_for()
    assert board.get_attribute("data-shapes") == "green:d5c3 yellow:c3"
    page.get_by_test_id("line-preview-note").filter(has_text="hits two things at once").wait_for()
    page.get_by_role("button", name="Forward").last.click()
    assert board.get_attribute("data-shapes") == "red:b1b5"  # the opponent's reply, its own shapes
    # Cached: a second Explain is free (FR-8.6), and the spend indicator moved once.
    page.get_by_text("Explain (saved)").wait_for()
    spend = page.get_by_test_id("spend-indicator").inner_text()
    assert spend.startswith("AI $0.00") and "/ $5.00" in spend


def test_over_budget_blocks_explain(page) -> None:  # type: ignore[no-untyped-def]
    start(page, "?ai=over")
    indicator = page.get_by_test_id("spend-indicator")
    assert indicator.get_attribute("data-level") == "over"  # red at 100% (FR-8.13)
    solve(page)
    page.get_by_test_id("explain-why").filter(has_text="this month's AI budget").wait_for()
    assert page.get_by_test_id("explain-button").is_disabled()
    # Raise the budget: Explain comes back (Adam's manual test).
    indicator.click()
    budget = page.get_by_test_id("ai-budget")
    budget.fill("10")
    budget.blur()
    page.keyboard.press("Escape")
    page.get_by_text("Explain (≈ $0.0").wait_for()
    assert not page.get_by_test_id("explain-button").is_disabled()


def test_warning_level_at_80_percent(page) -> None:  # type: ignore[no-untyped-def]
    start(page, "?ai=warn")
    assert page.get_by_test_id("spend-indicator").get_attribute("data-level") == "warn"


def test_explain_needs_stockfish(page) -> None:  # type: ignore[no-untyped-def]
    start(page, "?ai=on&engine=missing")
    play(page, WRONG, "black")
    page.get_by_test_id("outcome").filter(has_text="Failed").wait_for()
    page.get_by_test_id("answer-button").click()
    page.get_by_test_id("explain-why").filter(has_text="needs Stockfish").wait_for()
    assert page.get_by_test_id("explain-button").is_disabled()


def test_no_model_picked(page) -> None:  # type: ignore[no-untyped-def]
    start(page, "?ai=nomodel")
    solve(page)
    page.get_by_test_id("explain-why").filter(has_text="Pick a model").wait_for()


def test_startup_fast_path_and_a_failed_ai_key(page) -> None:  # type: ignore[no-untyped-def]
    page.goto(page.base_url + "/?startup=show&ai=on")
    page.get_by_test_id("startup-continue").filter(has_text="Continue as").wait_for()
    assert page.get_by_test_id("ai-settings").count() == 0  # the fast path: one button
    page.goto(page.base_url + "/?startup=show&ai=failed")
    page.get_by_test_id("startup-ai-failed").filter(has_text="rejected").wait_for()
    page.get_by_test_id("ai-settings").wait_for()  # FR-1.6: the full form opens


def test_price_table_add_and_delete(page) -> None:  # type: ignore[no-untyped-def]
    start(page)
    open_ai_settings(page)
    table = page.get_by_test_id("price-table")
    assert table.get_by_test_id("price-row").count() == 8
    table.get_by_test_id("price-model").fill("claude-custom-1")
    table.get_by_test_id("price-input").fill("1")
    table.get_by_test_id("price-output").fill("5")
    table.get_by_test_id("price-save").click()
    table.get_by_test_id("price-row").filter(has_text="claude-custom-1").wait_for()
    row = table.get_by_test_id("price-row").filter(has_text="claude-custom-1")
    row.get_by_role("button", name="Delete").click()
    row.wait_for(state="detached")
    assert table.get_by_test_id("price-row").count() == 8
