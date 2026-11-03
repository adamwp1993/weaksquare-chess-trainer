"""Price arithmetic and the cost guardrails (REQUIREMENTS §9.3, FR-8.9 to 8.15)."""

from __future__ import annotations

from datetime import date

import pytest

from weaksquare.core.errors import ValidationError
from weaksquare.core.llm.cost import cost_usd, estimate, estimate_input_tokens, max_tokens_for
from weaksquare.core.llm.defaults import SEED_PRICES, PriceRow
from weaksquare.core.llm.guardrails import check, month_key, spend_level, validate_dollars

TIERED = PriceRow("anthropic", "tiered", 0.10, 0.50, 100_000, 0.50, 2.50)
FLAT = PriceRow("openai", "flat", 2.00, 10.00)


def test_cost_is_per_million_tokens() -> None:
    assert cost_usd(FLAT, 1_000_000, 0) == pytest.approx(2.00)
    assert cost_usd(FLAT, 0, 1_000_000) == pytest.approx(10.00)
    assert cost_usd(FLAT, 2_000, 600) == pytest.approx(0.004 + 0.006)


def test_long_context_tier_applies_above_the_threshold_only() -> None:
    at = cost_usd(TIERED, 100_000, 1_000)
    above = cost_usd(TIERED, 100_001, 1_000)
    assert at == pytest.approx(100_000 * 0.10 / 1e6 + 1_000 * 0.50 / 1e6)
    assert above == pytest.approx(100_001 * 0.50 / 1e6 + 1_000 * 2.50 / 1e6)


def test_a_threshold_without_long_prices_keeps_the_base_rate() -> None:
    half = PriceRow("anthropic", "half", 1.0, 1.0, 10, None, None)
    assert cost_usd(half, 1_000, 0) == pytest.approx(0.001)


def test_input_estimate_rounds_up_and_errs_high() -> None:
    assert estimate_input_tokens(0) == 0
    assert estimate_input_tokens(1) == 1
    assert estimate_input_tokens(3_000) == 1_000  # a real tokenizer would count fewer


def test_reasoning_raises_max_tokens() -> None:
    assert max_tokens_for("explain", "low") == 1500  # FR-8.14
    assert max_tokens_for("explain", "medium") == 3000
    assert max_tokens_for("explain", "high") == 6000


def test_estimate_has_a_typical_and_a_worst_case() -> None:
    e = estimate("explain", "low", 6_000, FLAT)
    assert (e.input_tokens, e.typical_output_tokens, e.max_output_tokens) == (2_000, 600, 1_500)
    assert e.worst_usd == pytest.approx(cost_usd(FLAT, 2_000, 1_500))
    assert e.typical_usd < e.worst_usd
    high = estimate("explain", "high", 6_000, FLAT)
    assert high.worst_usd == pytest.approx(cost_usd(FLAT, 2_000, 6_000))  # FR-8.15: accounted for


def test_explain_on_the_cheapest_seed_models_is_a_tenth_of_a_cent() -> None:
    cheapest = min(SEED_PRICES, key=lambda p: p.input_per_m)
    assert estimate("explain", "low", 6_000, cheapest).typical_usd < 0.002


# ---- guardrails ------------------------------------------------------------------------------------


def test_ok_under_cap_and_budget() -> None:
    assert check(0.01, 0.50, 1.00, 5.00) == "ok"


def test_blocked_when_worst_case_is_over_the_cap() -> None:
    assert check(0.51, 0.50, 0.0, 5.00) == "over_cap"
    assert check(0.50, 0.50, 0.0, 5.00) == "ok"  # exactly the cap is allowed


def test_blocked_at_exactly_100_percent_of_the_budget() -> None:
    assert check(0.001, 0.50, 5.00, 5.00) == "over_budget"
    assert check(0.001, 0.50, 4.9999, 5.00) == "ok"  # Adam: requests go through until spend reaches it


def test_budget_is_checked_before_the_cap() -> None:
    assert check(9.0, 0.50, 6.0, 5.00) == "over_budget"


def test_zero_budget_blocks_everything() -> None:
    assert check(0.0, 0.50, 0.0, 0.0) == "over_budget"


def test_spend_level_warns_at_80_percent() -> None:
    assert spend_level(3.99, 5.00) == "ok"
    assert spend_level(4.00, 5.00) == "warn"
    assert spend_level(5.00, 5.00) == "over"
    assert spend_level(0.0, 0.0) == "over"


def test_month_key_is_the_local_calendar_month() -> None:
    assert month_key(date(2026, 11, 30)) == "2026-11"
    assert month_key(date(2026, 12, 1)) == "2026-12"
    assert month_key(date(2027, 1, 1)) == "2027-01"


@pytest.mark.parametrize("bad", [-0.01, 1000.01, float("nan"), float("inf"), "5", None, True])
def test_dollar_fields_are_validated(bad: object) -> None:
    with pytest.raises(ValidationError):
        validate_dollars(bad, "budget")


def test_dollar_fields_accept_zero_and_cents() -> None:
    assert validate_dollars(0, "cap") == 0.0
    assert validate_dollars(0.05, "budget") == 0.05
