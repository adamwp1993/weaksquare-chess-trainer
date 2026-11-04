"""Price arithmetic (FR-8.9, 8.11). Every cost figure comes from a price-table row and token counts."""

from __future__ import annotations

import math
from dataclasses import dataclass

from weaksquare.core.llm.defaults import MAX_TOKENS, REASONING_MULTIPLIER, TYPICAL_OUTPUT_TOKENS, PriceRow

# Deliberately high: real tokenizers average about 3.5–4 characters per token for English and chess text,
# so dividing by 3 over-estimates the input a little. The estimate errs towards blocking, never past the cap.
CHARS_PER_TOKEN = 3


def cost_usd(price: PriceRow, input_tokens: int, output_tokens: int) -> float:
    """The cost of one request. The long-context tier applies to the whole request when its input
    exceeds the row's threshold (as Anthropic bills Haiku 5.5 above a 100k prompt)."""
    long_tier = (
        price.long_ctx_threshold is not None
        and input_tokens > price.long_ctx_threshold
        and price.long_input_per_m is not None
        and price.long_output_per_m is not None
    )
    in_rate = price.long_input_per_m if long_tier else price.input_per_m
    out_rate = price.long_output_per_m if long_tier else price.output_per_m
    assert in_rate is not None and out_rate is not None
    return (input_tokens * in_rate + output_tokens * out_rate) / 1_000_000


def estimate_input_tokens(prompt_chars: int) -> int:
    return math.ceil(max(prompt_chars, 0) / CHARS_PER_TOKEN)


def max_tokens_for(feature: str, reasoning: str) -> int:
    """FR-8.14's hard limit, raised for Medium and High reasoning (FR-8.15) so thinking can't cut the answer short."""
    return MAX_TOKENS[feature] * REASONING_MULTIPLIER[reasoning]


@dataclass(frozen=True)
class Estimate:
    input_tokens: int
    typical_output_tokens: int
    max_output_tokens: int
    typical_usd: float  # the "about" figure shown on the button
    worst_usd: float  # every output token used: what the per-run cap is checked against (FR-8.12)


def estimate(feature: str, reasoning: str, prompt_chars: int, price: PriceRow) -> Estimate:
    inp = estimate_input_tokens(prompt_chars)
    max_out = max_tokens_for(feature, reasoning)
    typical = min(TYPICAL_OUTPUT_TOKENS[feature] * REASONING_MULTIPLIER[reasoning], max_out)
    return Estimate(inp, typical, max_out, cost_usd(price, inp, typical), cost_usd(price, inp, max_out))
