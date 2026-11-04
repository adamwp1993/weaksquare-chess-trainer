"""The cost guardrails in one place (REQUIREMENTS §9.3). Every LLM request in the app goes through
`LlmUsageService.run`, which:

1. resolves the provider, model, key and price row (a model without a price row can't be used, FR-8.9);
2. estimates the request and checks the monthly budget and the per-run cap (FR-8.11–8.13);
3. sends it with a hard `max_tokens` (FR-8.14, raised for reasoning per FR-8.15);
4. logs the usage the provider reported, priced from `llm_prices` (FR-8.10), even when the answer was
   cut short or refused, because those are billed too.

Requests run one at a time, so the budget is always checked against fully-logged spend.
Explain (v0.7) is the only caller; Game Review AI (v0.9) and the Coach (v0.10) reuse it.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import Any, Protocol

from weaksquare.core.clock import Clock
from weaksquare.core.errors import AppError
from weaksquare.core.llm.cost import Estimate, cost_usd, estimate, max_tokens_for
from weaksquare.core.llm.defaults import PROVIDER_LABELS
from weaksquare.core.llm.guardrails import SpendLevel, Verdict, check, month_key, spend_level
from weaksquare.core.llm.provider import LLMError, LLMRequest, LLMResponse
from weaksquare.services.llm_settings import LlmConfig, LlmSettingsService


class UsageRepo(Protocol):
    def append(
        self, ts: str, local_month: str, feature: str, provider: str, model: str, input_tokens: int,
        output_tokens: int, cost_usd: float, status: str,
    ) -> int: ...  # fmt: skip

    def spent_in(self, local_month: str) -> float: ...


QuoteState = Verdict | str  # also 'not_configured', 'no_model', 'no_price'


@dataclass(frozen=True)
class Spend:
    month: str  # YYYY-MM, local
    spent_usd: float
    budget_usd: float
    level: SpendLevel  # FR-1.10: ok / warn (80%) / over (100%)


@dataclass(frozen=True)
class Quote:
    """Whether a request can run now, and what it would cost (FR-8.11)."""

    state: QuoteState  # 'ok' or the reason it can't run
    message: str | None  # for the UI when state isn't 'ok'
    provider: str
    model: str
    estimate: Estimate | None
    run_cap_usd: float


@dataclass(frozen=True)
class RunResult:
    response: LLMResponse
    provider: str
    model: str
    cost_usd: float


BLOCK_MESSAGES = {
    "not_configured": "Choose an AI provider and save its key in Settings → AI.",
    "no_model": "Pick a model in Settings → AI.",
    "no_price": "{model} has no row in the price table, so its cost can't be worked out. Add its prices in Settings → AI.",
    "over_budget": "You've used this month's AI budget (${spent:.2f} of ${budget:.2f}). Raise it in Settings → AI, or wait until next month.",
    "over_cap": "This request could cost up to ${worst:.4f}, more than your per-run cap of ${cap:.2f}. Raise the cap in Settings → AI.",
}


def prompt_chars(system: str, user: str, schema: dict[str, Any]) -> int:
    """What the estimate counts: everything sent that the provider bills as input."""
    return len(system) + len(user) + len(json.dumps(schema, separators=(",", ":")))


class LlmUsageService:
    def __init__(self, settings: LlmSettingsService, usage: UsageRepo, clock: Clock) -> None:
        self._settings = settings
        self._usage = usage
        self._clock = clock
        self._lock = threading.Lock()

    def _month(self) -> str:
        return month_key(self._clock.local_date(self._clock.now()))

    def spend(self, cfg: LlmConfig | None = None) -> Spend:
        cfg = cfg or self._settings.config()
        month = self._month()
        spent = self._usage.spent_in(month)
        return Spend(month, spent, cfg.monthly_budget_usd, spend_level(spent, cfg.monthly_budget_usd))

    def quote(self, feature: str, chars: int, cfg: LlmConfig | None = None) -> Quote:
        cfg = cfg or self._settings.config()
        provider, model = cfg.provider, cfg.model

        def blocked(state: str, **fmt: Any) -> Quote:
            return Quote(state, BLOCK_MESSAGES[state].format(model=model, **fmt), provider, model, est, cfg.run_cap_usd)

        est: Estimate | None = None
        if not cfg.configured:
            return blocked("not_configured")
        if not model:
            return blocked("no_model")
        price = self._settings.price(provider, model)
        if price is None:
            return blocked("no_price")
        est = estimate(feature, cfg.reasoning, chars, price)
        spend = self.spend(cfg)
        verdict = check(est.worst_usd, cfg.run_cap_usd, spend.spent_usd, spend.budget_usd)
        if verdict != "ok":
            return blocked(verdict, spent=spend.spent_usd, budget=spend.budget_usd, worst=est.worst_usd,
                           cap=cfg.run_cap_usd)  # fmt: skip
        return Quote("ok", None, provider, model, est, cfg.run_cap_usd)

    def run(self, feature: str, system: str, user: str, schema_name: str, schema: dict[str, Any]) -> RunResult:
        """Check, send and log one request. Raises AppError when it's blocked or the provider fails."""
        with self._lock:
            cfg = self._settings.config()
            q = self.quote(feature, prompt_chars(system, user, schema), cfg)
            if q.state != "ok":
                raise AppError(q.message or "The request was blocked.", code=str(q.state))
            key = self._settings.key(cfg.provider)
            if not key:  # removed since the quote
                raise AppError(BLOCK_MESSAGES["not_configured"], code="not_configured")
            price = self._settings.price(cfg.provider, cfg.model)
            assert price is not None and q.estimate is not None
            request = LLMRequest(
                model=cfg.model,
                system=system,
                user=user,
                schema_name=schema_name,
                schema=schema,
                max_tokens=max_tokens_for(feature, cfg.reasoning),
                reasoning=cfg.reasoning,  # type: ignore[arg-type]
            )
            try:
                response = self._settings.provider(cfg.provider).generate(key, request)
            except LLMError as e:
                label = PROVIDER_LABELS.get(cfg.provider, cfg.provider)
                raise AppError(f"{label}: {e.message}", code=f"llm_{e.kind}", retryable=e.retryable) from None
            finally:
                key = None  # SR-7: held only as long as the request needs it
            cost = cost_usd(price, response.input_tokens, response.output_tokens)
            now = self._clock.now()
            self._usage.append(
                now.isoformat(), month_key(self._clock.local_date(now)), feature, cfg.provider, cfg.model,
                response.input_tokens, response.output_tokens, cost, response.status,
            )  # fmt: skip
            return RunResult(response, cfg.provider, cfg.model, cost)
