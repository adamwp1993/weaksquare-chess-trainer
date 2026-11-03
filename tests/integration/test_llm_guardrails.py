"""The cost guardrails end to end through the services (REQUIREMENTS §9.3; ROADMAP v0.7 *Done when*:
"budget and cap enforcement tests (blocked when over)"). Real SQLite, a fake provider."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

import pytest

from tests.fakes.llm import FAKE_ANTHROPIC_KEY, FAKE_OPENAI_KEY, FakeLLMProvider, fake_providers
from weaksquare import config
from weaksquare.adapters.db.connection import Database
from weaksquare.adapters.db.migrate import migrate
from weaksquare.adapters.db.repos.llm import LlmPricesRepo, LlmUsageRepo
from weaksquare.adapters.db.repos.user_data import SettingsRepo
from weaksquare.adapters.secret_store import MemorySecretStore
from weaksquare.core.clock import FixedClock
from weaksquare.core.errors import AppError, ValidationError
from weaksquare.core.llm.cost import cost_usd
from weaksquare.core.llm.defaults import SEED_PRICES, PriceRow
from weaksquare.core.llm.provider import LLMError, LLMResponse
from weaksquare.jobs.runner import JobFailed, JobRunner
from weaksquare.services.llm_settings import LlmSettingsService
from weaksquare.services.llm_usage import LlmUsageService

SCHEMA = {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]}
# 1M input and output tokens at a $1/$1 test price: every request costs exactly $2.
DEAR = PriceRow("anthropic", "test-dear", 1.0, 1.0)


@dataclass
class Rig:
    settings: LlmSettingsService
    usage: LlmUsageService
    providers: dict[str, FakeLLMProvider]
    secrets: MemorySecretStore
    usage_repo: LlmUsageRepo
    prices: LlmPricesRepo
    clock: FixedClock
    db: Database

    def run(self) -> object:
        return self.usage.run("explain", "system text", "user text", "explain", SCHEMA)


@pytest.fixture
def rig(paths: config.Paths, clock: FixedClock) -> Iterator[Rig]:
    migrate(paths.user_db, config.MIGRATIONS_DIR / "user", clock)
    db = Database(paths.user_db, paths.puzzles_db)
    secrets = MemorySecretStore()
    providers = fake_providers()
    prices = LlmPricesRepo(db)
    usage_repo = LlmUsageRepo(db)
    runner = JobRunner()
    settings = LlmSettingsService(SettingsRepo(db), secrets, prices, providers, runner,  # type: ignore[arg-type]
                                  lambda: clock.local_date(clock.now()))  # fmt: skip
    yield Rig(settings, LlmUsageService(settings, usage_repo, clock), providers, secrets, usage_repo, prices, clock, db)
    runner.cancel_all()
    db.close_all()


def configure(rig: Rig, model: str = "claude-haiku-5-5", cap: float = 0.50, budget: float = 5.00) -> None:
    rig.settings.set_key("anthropic", FAKE_ANTHROPIC_KEY)
    rig.settings.update("anthropic", model, "low", cap, budget)


# ---- seeding ---------------------------------------------------------------------------------------


def test_prices_are_seeded_once_from_the_defaults_module(rig: Rig) -> None:
    rows = rig.settings.prices()
    assert {(p.provider, p.model) for p in rows} == {(p.provider, p.model) for p in SEED_PRICES}
    haiku = rig.settings.price("anthropic", "claude-haiku-5-5")
    assert haiku is not None and (haiku.long_ctx_threshold, haiku.long_input_per_m) == (100_000, 0.50)


def test_edited_and_deleted_seed_rows_stay_as_you_left_them(rig: Rig, paths: config.Paths) -> None:
    rig.settings.save_price("anthropic", "claude-haiku-5-5", 0.2, 0.9, as_of="2026-11-03")
    rig.settings.delete_price("openai", "gpt-5.5")
    fresh = LlmSettingsService(SettingsRepo(rig.db), rig.secrets, LlmPricesRepo(rig.db), rig.providers,  # type: ignore[arg-type]
                               JobRunner(), lambda: rig.clock.local_date(rig.clock.now()))  # fmt: skip
    assert fresh.price("openai", "gpt-5.5") is None  # as after a relaunch: not re-added
    edited = fresh.price("anthropic", "claude-haiku-5-5")
    assert edited is not None and (edited.input_per_m, edited.output_per_m, edited.as_of) == (0.2, 0.9, "2026-11-03")


def test_price_rows_are_validated(rig: Rig) -> None:
    for args in [
        ("anthropic", "", 1.0, 1.0),
        ("nope", "m", 1.0, 1.0),
        ("anthropic", "m", -1, 1.0),
        ("anthropic", "m", 1.0, "1"),
        ("anthropic", "m", 1.0, 5000),
        ("anthropic", "bad model", 1.0, 1.0),
    ]:
        with pytest.raises(ValidationError):
            rig.settings.save_price(*args)
    with pytest.raises(ValidationError):  # a tier needs all three parts
        rig.settings.save_price("anthropic", "m", 1.0, 1.0, long_ctx_threshold=1000)
    with pytest.raises(ValidationError):
        rig.settings.save_price("anthropic", "m", 1.0, 1.0, as_of="Nov 3")


# ---- settings and keys -----------------------------------------------------------------------------


def test_nothing_is_preselected(rig: Rig) -> None:
    cfg = rig.settings.config()
    assert cfg.provider == "none" and cfg.models == {"anthropic": "", "openai": ""}  # Adam, v0.7 planning
    assert (cfg.reasoning, cfg.run_cap_usd, cfg.monthly_budget_usd) == ("low", 0.50, 5.00)  # FR-8.12/8.13/8.15
    assert not cfg.configured


def test_keys_are_stored_in_the_secret_store_and_never_returned(rig: Rig) -> None:
    rig.settings.set_key("openai", "  " + FAKE_OPENAI_KEY + "  ")
    assert rig.secrets.get("openai") == FAKE_OPENAI_KEY
    cfg = rig.settings.config()
    assert cfg.keys == {"anthropic": False, "openai": True}
    assert FAKE_OPENAI_KEY not in repr(cfg)
    with rig.db.session() as conn:
        assert FAKE_OPENAI_KEY not in str(conn.execute("SELECT * FROM settings").fetchall())
    rig.settings.delete_key("openai")
    assert rig.secrets.get("openai") is None


@pytest.mark.parametrize(
    ("provider", "key"),
    [("anthropic", FAKE_OPENAI_KEY), ("openai", "pk-" + "x" * 30), ("anthropic", "sk-ant-short"),
     ("anthropic", "sk-ant-FAKE has spaces in it ok"), ("anthropic", 12345), ("none", FAKE_ANTHROPIC_KEY)],
)  # fmt: skip
def test_bad_keys_are_refused_without_echoing_them(rig: Rig, provider: str, key: object) -> None:
    with pytest.raises(ValidationError) as e:
        rig.settings.set_key(provider, key)
    assert str(key) not in e.value.message
    assert rig.secrets.get("anthropic") is None


def test_test_key_uses_the_free_check_and_reports_failures(rig: Rig) -> None:
    configure(rig)
    assert "works with claude-haiku-5-5" in rig.settings.test_key("anthropic", "claude-haiku-5-5")
    assert "Pick a model" in rig.settings.test_key("anthropic", "")
    assert rig.providers["anthropic"].requests == []  # nothing billed
    rig.providers["anthropic"].test_error = LLMError("bad_key", 401)
    with pytest.raises(JobFailed) as e:
        rig.settings.test_key("anthropic", "claude-haiku-5-5")
    assert e.value.code == "llm_bad_key" and "rejected" in e.value.message


# ---- quote and run: the guardrails ---------------------------------------------------------------------


def test_not_configured_no_model_and_no_price_are_blocked(rig: Rig) -> None:
    assert rig.usage.quote("explain", 1000).state == "not_configured"
    rig.settings.set_key("anthropic", FAKE_ANTHROPIC_KEY)
    rig.settings.update("anthropic", "", "low", 0.5, 5.0)
    assert rig.usage.quote("explain", 1000).state == "no_model"
    rig.settings.update("anthropic", "claude-unpriced-9", "low", 0.5, 5.0)
    q = rig.usage.quote("explain", 1000)
    assert q.state == "no_price" and "claude-unpriced-9" in (q.message or "")  # FR-8.9: no price, no request
    with pytest.raises(AppError) as e:
        rig.run()
    assert e.value.code == "no_price"
    assert rig.providers["anthropic"].requests == [] and rig.usage_repo.count() == 0


def test_a_run_is_logged_with_the_cost_from_the_price_table(rig: Rig) -> None:
    configure(rig)
    result = rig.run()
    price = rig.settings.price("anthropic", "claude-haiku-5-5")
    assert price is not None
    expected = cost_usd(price, 1200, 400)
    assert result.cost_usd == pytest.approx(expected)  # type: ignore[attr-defined]
    with rig.db.session() as conn:
        row = conn.execute("SELECT * FROM llm_usage").fetchone()
    assert (row["feature"], row["provider"], row["model"], row["input_tokens"], row["output_tokens"], row["status"]) == (
        "explain", "anthropic", "claude-haiku-5-5", 1200, 400, "ok",
    )  # fmt: skip
    assert row["cost_usd"] == pytest.approx(expected) and row["local_month"] == "2026-01"
    req = rig.providers["anthropic"].requests[0]
    assert req.max_tokens == 1500 and req.model == "claude-haiku-5-5"  # FR-8.14: always set
    assert rig.providers["anthropic"].keys_seen == [FAKE_ANTHROPIC_KEY]


def test_reasoning_raises_max_tokens_on_the_request(rig: Rig) -> None:
    configure(rig)
    rig.settings.update("anthropic", "claude-haiku-5-5", "high", 0.5, 5.0)
    rig.run()
    assert rig.providers["anthropic"].requests[0].max_tokens == 6000
    assert rig.providers["anthropic"].requests[0].reasoning == "high"


def test_blocked_when_over_the_per_run_cap_and_unblocked_by_raising_it(rig: Rig) -> None:
    rig.prices.upsert(DEAR)
    configure(rig, model="test-dear", cap=0.001)  # worst case: 1,500 output tokens at $1/M = $0.0015 + input
    q = rig.usage.quote("explain", 300)
    assert q.state == "over_cap" and q.estimate is not None and q.estimate.worst_usd > 0.001
    with pytest.raises(AppError) as e:
        rig.run()
    assert e.value.code == "over_cap" and "per-run cap" in e.value.message
    assert rig.providers["anthropic"].requests == []
    rig.settings.update("anthropic", "test-dear", "low", 0.01, 5.0)
    rig.run()
    assert len(rig.providers["anthropic"].requests) == 1


def test_blocked_once_the_month_reaches_the_budget_and_unblocked_by_raising_it(rig: Rig) -> None:
    rig.prices.upsert(DEAR)
    configure(rig, model="test-dear", cap=5.0, budget=0.05)
    fake = rig.providers["anthropic"]
    fake.input_tokens, fake.output_tokens = 10_000, 10_000  # $0.02 each
    rig.run()
    rig.run()
    assert rig.usage.spend().level == "warn"  # $0.04 of $0.05: the 80% warning (FR-8.13)
    rig.run()  # $0.04 < $0.05: allowed, and takes the month to $0.06 (Adam: block only at 100%)
    spend = rig.usage.spend()
    assert spend.spent_usd == pytest.approx(0.06) and spend.level == "over"
    with pytest.raises(AppError) as e:
        rig.run()
    assert e.value.code == "over_budget" and "$0.06 of $0.05" in e.value.message
    assert len(fake.requests) == 3
    rig.settings.update("anthropic", "test-dear", "low", 5.0, 1.00)
    rig.run()
    assert len(fake.requests) == 4


def test_the_budget_resets_with_the_local_month(paths: config.Paths) -> None:
    eastern = timezone(timedelta(hours=-5))
    clock = FixedClock(datetime(2026, 12, 1, 3, 0, tzinfo=UTC), local_tz=eastern)  # still Nov 30 locally
    migrate(paths.user_db, config.MIGRATIONS_DIR / "user", clock)
    db = Database(paths.user_db, paths.puzzles_db)
    try:
        repo = LlmUsageRepo(db)
        settings = LlmSettingsService(SettingsRepo(db), MemorySecretStore(), LlmPricesRepo(db), fake_providers(),  # type: ignore[arg-type]
                                      JobRunner(), lambda: clock.local_date(clock.now()))  # fmt: skip
        usage = LlmUsageService(settings, repo, clock)
        settings.set_key("anthropic", FAKE_ANTHROPIC_KEY)
        settings.update("anthropic", "claude-haiku-5-5", "low", 0.5, 0.0001)
        usage.run("explain", "s", "u", "explain", SCHEMA)
        assert usage.spend().month == "2026-11"
        assert usage.quote("explain", 10).state == "over_budget"
        clock.advance(hours=6)  # Dec 1 locally
        assert usage.spend().month == "2026-12" and usage.spend().spent_usd == 0
        assert usage.quote("explain", 10).state == "ok"
    finally:
        db.close_all()


def test_truncated_and_refused_answers_are_still_logged(rig: Rig) -> None:
    configure(rig)
    fake = rig.providers["anthropic"]
    fake.queue(LLMResponse('{"summ', 900, 1500, "truncated"))
    fake.queue(LLMResponse("", 900, 3, "refused"))
    assert rig.run().response.status == "truncated"  # type: ignore[attr-defined]
    assert rig.run().response.status == "refused"  # type: ignore[attr-defined]
    with rig.db.session() as conn:
        assert [r[0] for r in conn.execute("SELECT status FROM llm_usage ORDER BY id")] == ["truncated", "refused"]


def test_provider_errors_become_readable_app_errors_and_log_nothing(rig: Rig) -> None:
    configure(rig)
    for kind, retryable in [("bad_key", False), ("quota", False), ("network", True), ("timeout", True)]:
        rig.providers["anthropic"].queue(LLMError(kind, None))  # type: ignore[arg-type]
        with pytest.raises(AppError) as e:
            rig.run()
        assert e.value.code == f"llm_{kind}" and e.value.retryable is retryable
        assert e.value.message.startswith("Anthropic: ")
    assert rig.usage_repo.count() == 0  # nothing reported usage, so nothing was billed


def test_the_key_is_read_per_request(rig: Rig) -> None:
    configure(rig)
    rig.settings.delete_key("anthropic")
    with pytest.raises(AppError) as e:
        rig.run()
    assert e.value.code == "not_configured"
