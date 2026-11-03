"""The provider defaults module: the ONLY place model names appear (CLAUDE.md, FR-1.3).

It seeds the editable price table (`llm_prices`, FR-8.9) with REQUIREMENTS.md §16's prices and holds the
request limits (FR-8.14, 8.15). Nothing here is a default *choice*: no model is pre-selected (Adam, v0.7
planning). These rows only fill the model dropdown and the cost figures.

To change the seed (new models, new prices), edit SEED_PRICES and bump SEED_VERSION. The app then adds
the rows that are missing, once, and leaves rows you edited or deleted alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Provider = Literal["anthropic", "openai"]
PROVIDERS: tuple[Provider, ...] = ("anthropic", "openai")
PROVIDER_LABELS = {"anthropic": "Anthropic", "openai": "OpenAI"}

Reasoning = Literal["low", "medium", "high"]
REASONING_LEVELS: tuple[Reasoning, ...] = ("low", "medium", "high")
DEFAULT_REASONING: Reasoning = "low"
# FR-8.15: hidden reasoning is billed as output, so Medium and High raise max_tokens (and the estimate).
REASONING_MULTIPLIER = {"low": 1, "medium": 2, "high": 4}

# FR-8.14: the hard max_tokens per feature at Low reasoning.
MAX_TOKENS = {"explain": 1500}
# The typical output of one call, shown as the "about" figure next to the worst case (actual usage is logged).
TYPICAL_OUTPUT_TOKENS = {"explain": 600}

DEFAULT_RUN_CAP_USD = 0.50  # FR-8.12
DEFAULT_MONTHLY_BUDGET_USD = 5.00  # FR-8.13
WARN_FRACTION = 0.8  # FR-8.13: warn at 80%


@dataclass(frozen=True)
class PriceRow:
    """USD per 1M tokens. The long tier applies when a request's input tokens exceed the threshold."""

    provider: str
    model: str
    input_per_m: float
    output_per_m: float
    long_ctx_threshold: int | None = None
    long_input_per_m: float | None = None
    long_output_per_m: float | None = None
    as_of: str = "2026-10-31"


SEED_VERSION = 1
SEED_PRICES: tuple[PriceRow, ...] = (
    # Anthropic (re-checked against Anthropic's model table at v0.7 planning, 2026-11-03).
    PriceRow("anthropic", "claude-haiku-5-5", 0.10, 0.50, 100_000, 0.50, 2.50),
    PriceRow("anthropic", "claude-sonnet-5-5", 2.00, 10.00),
    PriceRow("anthropic", "claude-opus-5-5", 4.00, 20.00),
    PriceRow("anthropic", "claude-fable-5-1", 10.00, 50.00),
    # OpenAI (REQUIREMENTS §16; re-checked when the adapter is written).
    PriceRow("openai", "gpt-5.4-nano", 0.20, 1.25),
    PriceRow("openai", "gpt-5.4-mini", 0.75, 4.50),
    PriceRow("openai", "gpt-5.4", 2.50, 15.00),
    PriceRow("openai", "gpt-5.5", 5.00, 30.00),
)

# The smallest model per provider, used only by the opt-in live test (tests/live, SR-13).
LIVE_TEST_MODEL = {"anthropic": "claude-haiku-5-5", "openai": "gpt-5.4-nano"}
