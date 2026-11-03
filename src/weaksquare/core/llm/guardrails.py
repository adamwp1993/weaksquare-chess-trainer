"""The cost guardrails (REQUIREMENTS §9.3): the per-run cap and the monthly budget.

- **Monthly budget** (FR-8.13, Adam, v0.7 planning): requests go through until this month's logged spend
  reaches the budget, then everything is blocked until next month or until the budget is raised. The
  last request can take you slightly over.
- **Per-run cap** (FR-8.12): a request whose *worst-case* cost (estimated input plus every output token
  it may use) is above the cap is blocked.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from weaksquare.core.errors import ValidationError
from weaksquare.core.llm.defaults import WARN_FRACTION

Verdict = Literal["ok", "over_cap", "over_budget"]
SpendLevel = Literal["ok", "warn", "over"]

MAX_DOLLARS = 1000.0  # sanity bound for the cap and budget fields


def check(worst_case_usd: float, run_cap_usd: float, month_spent_usd: float, budget_usd: float) -> Verdict:
    """The budget comes first: at 100% nothing runs, whatever the cap."""
    if month_spent_usd >= budget_usd:
        return "over_budget"
    if worst_case_usd > run_cap_usd:
        return "over_cap"
    return "ok"


def spend_level(month_spent_usd: float, budget_usd: float) -> SpendLevel:
    """The spend indicator's color (FR-1.10, 8.13): a warning from 80%, blocked at 100%."""
    if month_spent_usd >= budget_usd:
        return "over"
    if month_spent_usd >= WARN_FRACTION * budget_usd:
        return "warn"
    return "ok"


def month_key(day: date) -> str:
    """The local calendar month a request falls in, e.g. '2026-11'."""
    return f"{day.year:04d}-{day.month:02d}"


def validate_dollars(value: object, name: str) -> float:
    """A cap or budget from the UI: a number from 0 up to $1,000 (0 blocks everything)."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValidationError(f"The {name} must be a number of dollars.")
    v = float(value)
    if not (0 <= v <= MAX_DOLLARS) or v != v:
        raise ValidationError(f"The {name} must be between $0 and ${MAX_DOLLARS:,.0f}.")
    return round(v, 4)
