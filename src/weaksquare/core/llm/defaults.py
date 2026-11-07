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

# FR-1.15 (v0.9): each AI feature has its own provider, model and reasoning level. The usage log records
# the feature. A feature makes one or more kinds of request, each with its own limits.
Feature = Literal["explain", "game_review", "coach", "openings"]
FEATURES: tuple[Feature, ...] = ("explain", "game_review", "coach", "openings")  # coach: v0.10, openings: v0.13
FEATURE_LABELS = {"explain": "Puzzle Explain", "game_review": "Game Review", "coach": "Coach", "openings": "Openings"}
# Request kind -> the feature it belongs to (and is logged under).
FEATURE_OF: dict[str, Feature] = {
    "explain": "explain",
    "game_move": "game_review",
    "game_narrative": "game_review",
    "coach_summary": "coach",
    "coach_detailed": "coach",
    "opening_overview": "openings",
    "opening_line": "openings",
    "opening_move": "openings",
}
# The kind whose typical cost the feature's model dropdown shows.
DROPDOWN_KIND: dict[Feature, str] = {
    "explain": "explain",
    "game_review": "game_narrative",
    "coach": "coach_summary",
    "openings": "opening_line",
}

# FR-8.14: the hard max_tokens per request kind at Low reasoning.
# The Coach's limits leave room for the AI's training plan, up to 112 tasks (FR-10.66; Adam, v0.12 planning).
MAX_TOKENS = {
    "explain": 1500,
    "game_move": 1500,
    "game_narrative": 4000,
    "coach_summary": 7500,
    "coach_detailed": 10000,
    "opening_overview": 2000,
    "opening_line": 5000,  # up to 20 moves, each with its own explanation (FR-12.7)
    "opening_move": 1000,
}
# A typical prompt's size in characters, for the per-model cost shown in the model dropdown (FR-1.3).
# Explain my game is about 10k input tokens (FR-11.21).
TYPICAL_PROMPT_CHARS = {
    "explain": 6000,
    "game_move": 6000,
    "game_narrative": 30000,
    "coach_summary": 18000,  # FR-10.5: about 5k input tokens
    "coach_detailed": 70000,  # about 20k
    "opening_overview": 14000,  # with Wikibooks text (FR-12.15)
    "opening_line": 18000,
    "opening_move": 8000,
}
# The typical output of one call, shown as the "about" figure next to the worst case (actual usage is logged).
TYPICAL_OUTPUT_TOKENS = {
    "explain": 600,
    "game_move": 600,
    "game_narrative": 3000,
    "coach_summary": 2900,  # v0.12: with a default plan of 30 tasks
    "coach_detailed": 4400,
    "opening_overview": 900,
    "opening_line": 2500,
    "opening_move": 400,
}

# v0.11 (FR-10.56): the "about N minutes" of an AI coaching run. A typical speed, not a measurement:
# output tokens per second, and input tokens read per second, across the default models.
TYPICAL_OUTPUT_TOKENS_PER_S = 50
TYPICAL_INPUT_TOKENS_PER_S = 2000
COACH_TIMEOUT_S = 300.0  # v0.12: 10,000 tokens at the typical speed above takes 200 s

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
