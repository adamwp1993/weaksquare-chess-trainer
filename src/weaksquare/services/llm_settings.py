"""LLM settings (FR-1.2–1.4, 1.8, 8.9, 8.12, 8.13, 8.15): the provider, its model, the API key, the
reasoning level, the per-run cap, the monthly budget, the editable price table, and Test key.

Keys go straight to `secret_store` (SR-1, SR-7): they're never stored in `settings`, never returned to the
UI (only "a key is stored"), never logged and never put in an error message.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, Protocol

from weaksquare.core.errors import NotFoundError, ValidationError
from weaksquare.core.llm.defaults import (
    DEFAULT_MONTHLY_BUDGET_USD,
    DEFAULT_REASONING,
    DEFAULT_RUN_CAP_USD,
    PROVIDER_LABELS,
    PROVIDERS,
    REASONING_LEVELS,
    SEED_PRICES,
    SEED_VERSION,
    PriceRow,
)
from weaksquare.core.llm.guardrails import validate_dollars
from weaksquare.core.llm.provider import LLMError, LLMProvider
from weaksquare.jobs.runner import CancelToken, JobFailed, JobRunner, ProgressFn

PROVIDER_KEY = "llm.provider"
MODEL_KEY = "llm.model.{}"
REASONING_KEY = "llm.reasoning"
RUN_CAP_KEY = "llm.run_cap_usd"
BUDGET_KEY = "llm.monthly_budget_usd"
SEED_KEY = "llm.prices_seed"
KEY_TEST_JOB = "llm_key_test"
LAUNCH_CHECK_JOB = "llm_launch_check"
CheckState = Literal["none", "checking", "ok", "failed"]

NONE = "none"
PROVIDER_CHOICES = (NONE, *PROVIDERS)
# A model ID as the providers spell them (letters, digits, . _ : / @ -), or empty for "none picked".
MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@-]{0,99}")
# Rough shape checks so a key pasted into the wrong provider is caught before it's stored. The key is
# never part of the message.
KEY_PREFIX = {"anthropic": "sk-ant-", "openai": "sk-"}
KEY_MIN, KEY_MAX = 20, 400
MAX_RATE = 1000.0  # USD per 1M tokens, a sanity bound
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


class SettingsStore(Protocol):
    def get(self, key: str) -> Any | None: ...

    def set(self, key: str, value: Any) -> None: ...


class SecretStore(Protocol):
    def get(self, account: str) -> str | None: ...

    def set(self, account: str, secret: str) -> None: ...

    def delete(self, account: str) -> None: ...


class PricesRepo(Protocol):
    def all(self) -> list[PriceRow]: ...

    def get(self, provider: str, model: str) -> PriceRow | None: ...

    def upsert(self, p: PriceRow) -> None: ...

    def insert_missing(self, rows: tuple[PriceRow, ...]) -> int: ...

    def delete(self, provider: str, model: str) -> bool: ...


@dataclass(frozen=True)
class LlmConfig:
    provider: str  # 'none' / 'anthropic' / 'openai'
    models: dict[str, str]  # the model picked for each provider ('' = none picked)
    reasoning: str
    run_cap_usd: float
    monthly_budget_usd: float
    keys: dict[str, bool]  # a key is stored for this provider (never the key itself)

    @property
    def model(self) -> str:
        return self.models.get(self.provider, "")

    @property
    def configured(self) -> bool:
        """FR-8.1: a provider with a stored key. The model may still be unpicked."""
        return self.provider != NONE and self.keys.get(self.provider, False)


def check_provider(provider: object, allow_none: bool = False) -> str:
    choices = PROVIDER_CHOICES if allow_none else PROVIDERS
    if provider not in choices:
        raise ValidationError(f"Unknown AI provider; choose one of {', '.join(choices)}.")
    return str(provider)


def check_model(model: object) -> str:
    if not isinstance(model, str):
        raise ValidationError("The model must be text.")
    m = model.strip()
    if m and not MODEL_ID.fullmatch(m):
        raise ValidationError("That isn't a valid model ID (letters, digits and . _ : / @ - only, up to 100).")
    return m


class LlmSettingsService:
    def __init__(
        self,
        settings: SettingsStore,
        secrets: SecretStore,
        prices: PricesRepo,
        providers: dict[str, LLMProvider],
        runner: JobRunner,
        today: Any,  # () -> date: the local date, for a price row's default "as of"
    ) -> None:
        self._settings = settings
        self._secrets = secrets
        self._prices = prices
        self._providers = providers
        self._runner = runner
        self._today = today
        self._seed_lock = threading.Lock()
        self._seeded = False
        # FR-1.6: the silent key check at launch. ('none' | 'checking' | 'ok' | 'failed', message)
        self._check_lock = threading.Lock()
        self._check: tuple[CheckState, str | None] = ("none", None)

    # ---- settings -------------------------------------------------------------------------------------

    def config(self) -> LlmConfig:
        provider = self._settings.get(PROVIDER_KEY)
        if provider not in PROVIDER_CHOICES:
            provider = NONE
        models: dict[str, str] = {}
        for p in PROVIDERS:
            m = self._settings.get(MODEL_KEY.format(p))
            models[p] = m if isinstance(m, str) and (not m or MODEL_ID.fullmatch(m)) else ""
        reasoning = self._settings.get(REASONING_KEY)
        if reasoning not in REASONING_LEVELS:
            reasoning = DEFAULT_REASONING
        return LlmConfig(
            provider=provider,
            models=models,
            reasoning=reasoning,
            run_cap_usd=self._dollars(RUN_CAP_KEY, DEFAULT_RUN_CAP_USD),
            monthly_budget_usd=self._dollars(BUDGET_KEY, DEFAULT_MONTHLY_BUDGET_USD),
            keys={p: self._has_key(p) for p in PROVIDERS},
        )

    def _dollars(self, key: str, default: float) -> float:
        try:
            return validate_dollars(self._settings.get(key), key)
        except ValidationError:
            return default

    def _has_key(self, provider: str) -> bool:
        return bool(self._secrets.get(provider))

    def update(
        self, provider: object, model: object, reasoning: object, run_cap_usd: object, monthly_budget_usd: object
    ) -> LlmConfig:
        """Saves everything at once; `model` is the model for `provider` (ignored for None)."""
        p = check_provider(provider, allow_none=True)
        if reasoning not in REASONING_LEVELS:
            raise ValidationError("Reasoning must be low, medium or high.")
        cap = validate_dollars(run_cap_usd, "per-run cap")
        budget = validate_dollars(monthly_budget_usd, "monthly budget")
        m = check_model(model)
        self._settings.set(PROVIDER_KEY, p)
        if p != NONE:
            self._settings.set(MODEL_KEY.format(p), m)
        self._settings.set(REASONING_KEY, reasoning)
        self._settings.set(RUN_CAP_KEY, cap)
        self._settings.set(BUDGET_KEY, budget)
        return self.config()

    # ---- the API key (SR-1, SR-7) ------------------------------------------------------------------------

    def set_key(self, provider: object, key: object) -> None:
        p = check_provider(provider)
        if not isinstance(key, str):
            raise ValidationError("The API key must be text.")
        k = key.strip()
        if not (KEY_MIN <= len(k) <= KEY_MAX) or any(c.isspace() for c in k) or not k.isascii():
            raise ValidationError(f"That doesn't look like an API key ({KEY_MIN}–{KEY_MAX} characters, no spaces).")
        if not k.startswith(KEY_PREFIX[p]):
            raise ValidationError(
                f"That doesn't look like an {PROVIDER_LABELS[p]} key: they start with {KEY_PREFIX[p]}."
            )
        self._secrets.set(p, k)
        self._forget_check("none")  # you just typed it: the launch check no longer applies

    def delete_key(self, provider: object) -> None:
        self._secrets.delete(check_provider(provider))
        self._forget_check("none")

    def key(self, provider: str) -> str | None:
        """For the services that make the request, never for the bridge."""
        return self._secrets.get(provider)

    def provider(self, name: str) -> LLMProvider:
        return self._providers[name]

    # ---- Test key (FR-1.4): the provider's free model lookup --------------------------------------------

    def start_key_test(self, provider: object, model: object) -> str:
        p = check_provider(provider)
        m = check_model(model)
        if not self._has_key(p):
            raise ValidationError(f"Save an {PROVIDER_LABELS[p]} key first.")

        def job(progress: ProgressFn, token: CancelToken) -> str:
            progress(None, f"Testing your {PROVIDER_LABELS[p]} key…")
            return self.test_key(p, m)

        return self._runner.submit(KEY_TEST_JOB, job)

    def test_key(self, provider: str, model: str) -> str:
        """Runs the test now (the job body, and the FR-1.6 silent check). Raises JobFailed on failure."""
        key = self._secrets.get(provider)
        if not key:
            raise JobFailed("no_key", f"No {PROVIDER_LABELS[provider]} key is stored.", retryable=False)
        try:
            self._providers[provider].test_key(key, model or None)
        except LLMError as e:
            raise JobFailed(f"llm_{e.kind}", e.message, retryable=e.retryable) from None
        return f"The key works with {model}." if model else "The key works. Pick a model to use it."

    # ---- the launch check (FR-1.6) ---------------------------------------------------------------------

    def start_launch_check(self) -> str | None:
        """At start-up: test the configured provider's key in the background with the free model lookup.
        The startup page shows its single Continue button only if this passes (or no AI is set up)."""
        cfg = self.config()
        if not cfg.configured:
            with self._check_lock:
                self._check = ("none", None)
            return None
        with self._check_lock:
            self._check = ("checking", None)

        def job(progress: ProgressFn, token: CancelToken) -> str:
            try:
                msg = self.test_key(cfg.provider, cfg.model)
            except JobFailed as e:
                with self._check_lock:
                    self._check = ("failed", e.message)
                raise
            with self._check_lock:
                self._check = ("ok", None)
            return msg

        return self._runner.submit(LAUNCH_CHECK_JOB, job)

    def launch_check(self) -> tuple[CheckState, str | None]:
        """The launch check's state. A key saved or removed since then makes it moot ('none' / 'ok')."""
        with self._check_lock:
            return self._check

    def _forget_check(self, state: CheckState) -> None:
        with self._check_lock:
            self._check = (state, None)

    # ---- the price table (FR-8.9) ----------------------------------------------------------------------

    def _ensure_seeded(self) -> None:
        """Adds §16's prices from core/llm/defaults.py the first time each seed version is seen. Rows you
        edited or deleted stay as you left them until a new seed version."""
        if self._seeded:
            return
        with self._seed_lock:
            if self._seeded:
                return
            done = self._settings.get(SEED_KEY)
            if not isinstance(done, int) or done < SEED_VERSION:
                self._prices.insert_missing(SEED_PRICES)
                self._settings.set(SEED_KEY, SEED_VERSION)
            self._seeded = True

    def prices(self) -> list[PriceRow]:
        self._ensure_seeded()
        return self._prices.all()

    def price(self, provider: str, model: str) -> PriceRow | None:
        self._ensure_seeded()
        return self._prices.get(provider, model)

    def save_price(
        self,
        provider: object,
        model: object,
        input_per_m: object,
        output_per_m: object,
        long_ctx_threshold: object = None,
        long_input_per_m: object = None,
        long_output_per_m: object = None,
        as_of: object = None,
    ) -> PriceRow:
        self._ensure_seeded()
        p = check_provider(provider)
        m = check_model(model)
        if not m:
            raise ValidationError("A price row needs a model ID.")
        tier = (long_ctx_threshold, long_input_per_m, long_output_per_m)
        if any(v is not None for v in tier) and any(v is None for v in tier):
            raise ValidationError("A long-context tier needs its threshold and both of its prices.")
        if long_ctx_threshold is not None and (
            isinstance(long_ctx_threshold, bool) or not isinstance(long_ctx_threshold, int) or long_ctx_threshold < 1
        ):
            raise ValidationError("The long-context threshold must be a whole number of tokens.")
        if as_of is None:
            day = self._today()
            as_of = day.isoformat() if isinstance(day, date) else str(day)
        if not isinstance(as_of, str) or not ISO_DATE.fullmatch(as_of):
            raise ValidationError("'As of' must be a date (YYYY-MM-DD).")
        row = PriceRow(
            p,
            m,
            _rate(input_per_m, "input price"),
            _rate(output_per_m, "output price"),
            long_ctx_threshold,  # type: ignore[arg-type]
            None if long_input_per_m is None else _rate(long_input_per_m, "long-context input price"),
            None if long_output_per_m is None else _rate(long_output_per_m, "long-context output price"),
            as_of,
        )
        self._prices.upsert(row)
        return row

    def delete_price(self, provider: object, model: object) -> None:
        self._ensure_seeded()
        if not self._prices.delete(check_provider(provider), check_model(model)):
            raise NotFoundError("There's no price row for that model.")


def _rate(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or value != value:
        raise ValidationError(f"The {name} must be a number (USD per 1M tokens).")
    v = float(value)
    if not 0 <= v <= MAX_RATE:
        raise ValidationError(f"The {name} must be between $0 and ${MAX_RATE:,.0f} per 1M tokens.")
    return v
