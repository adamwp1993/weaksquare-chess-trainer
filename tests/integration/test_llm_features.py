"""A model per AI feature (FR-1.15, v0.9; ROADMAP v0.9 *Done when*: "each feature's request uses that
feature's model and is logged under its feature"). Real SQLite, fake providers."""

from __future__ import annotations

import pytest

from tests.fakes.llm import FAKE_ANTHROPIC_KEY, FAKE_OPENAI_KEY
from tests.integration.test_llm_guardrails import SCHEMA, Rig, rig  # noqa: F401  (the fixture)
from weaksquare.core.errors import AppError, ValidationError
from weaksquare.core.llm.defaults import PriceRow


def _explain_on_haiku(rig: Rig) -> None:  # noqa: F811
    rig.settings.set_key("anthropic", FAKE_ANTHROPIC_KEY)
    rig.settings.update("anthropic", "claude-haiku-5-5", "low", 0.50, 5.00)


def _logged(rig: Rig) -> list[tuple[str, str, str]]:  # noqa: F811
    with rig.db.session() as conn:
        return [tuple(r) for r in conn.execute("SELECT feature, provider, model FROM llm_usage ORDER BY id")]


def test_game_review_follows_explain_until_you_pick(rig: Rig) -> None:  # noqa: F811
    _explain_on_haiku(rig)
    cfg = rig.settings.config("game_review")
    assert cfg.follows_explain and (cfg.provider, cfg.model) == ("anthropic", "claude-haiku-5-5")
    assert rig.settings.feature_choice("game_review") == ("same", "", "low")
    rig.settings.update("anthropic", "claude-sonnet-5-5", "low", 0.50, 5.00)  # Explain's model moves: so does it
    assert rig.settings.config("game_review").model == "claude-sonnet-5-5"


def test_each_feature_uses_its_own_model_and_is_logged_under_it(rig: Rig) -> None:  # noqa: F811
    _explain_on_haiku(rig)
    rig.settings.update_feature("game_review", "anthropic", "claude-sonnet-5-5", "low")
    rig.usage.run("explain", "s", "u", "x", SCHEMA)
    rig.usage.run("game_move", "s", "u", "x", SCHEMA)
    rig.usage.run("game_narrative", "s", "u", "x", SCHEMA)
    models = [r.model for r in rig.providers["anthropic"].requests]
    assert models == ["claude-haiku-5-5", "claude-sonnet-5-5", "claude-sonnet-5-5"]
    assert _logged(rig) == [
        ("explain", "anthropic", "claude-haiku-5-5"),
        ("game_review", "anthropic", "claude-sonnet-5-5"),
        ("game_review", "anthropic", "claude-sonnet-5-5"),
    ]
    spend = rig.usage.spend()
    assert set(spend.by_feature) == {"explain", "game_review"}
    assert spend.spent_usd == pytest.approx(sum(spend.by_feature.values()))


def test_a_feature_can_use_the_other_provider_with_its_key(rig: Rig) -> None:  # noqa: F811
    _explain_on_haiku(rig)
    rig.settings.update_feature("game_review", "openai", "gpt-5.4", "low")
    with pytest.raises(AppError) as e:  # no OpenAI key yet: the key is shared per provider, not per feature
        rig.usage.run("game_narrative", "s", "u", "x", SCHEMA)
    assert e.value.code == "not_configured"
    rig.settings.set_key("openai", FAKE_OPENAI_KEY)
    rig.usage.run("game_narrative", "s", "u", "x", SCHEMA)
    assert [r.model for r in rig.providers["openai"].requests] == ["gpt-5.4"]
    assert rig.providers["openai"].keys_seen == [FAKE_OPENAI_KEY]
    assert rig.settings.config("explain").provider == "anthropic"  # Explain is untouched


def test_reasoning_is_per_feature_and_sets_max_tokens(rig: Rig) -> None:  # noqa: F811
    _explain_on_haiku(rig)
    rig.settings.update_feature("game_review", "same", "ignored-model", "high")
    assert rig.settings.feature_choice("game_review") == ("same", "", "high")  # 'same' drops the model
    rig.usage.run("explain", "s", "u", "x", SCHEMA)
    rig.usage.run("game_move", "s", "u", "x", SCHEMA)
    rig.usage.run("game_narrative", "s", "u", "x", SCHEMA)
    reqs = rig.providers["anthropic"].requests
    assert [(r.reasoning, r.max_tokens) for r in reqs] == [("low", 1500), ("high", 6000), ("high", 16000)]


def test_the_budget_and_the_cap_are_shared(rig: Rig) -> None:  # noqa: F811
    _explain_on_haiku(rig)
    rig.prices.upsert(PriceRow("anthropic", "test-dear", 1.0, 1.0))
    rig.settings.update_feature("game_review", "anthropic", "test-dear", "low")
    rig.settings.update("anthropic", "claude-haiku-5-5", "low", 100.0, 1.0)
    p = rig.providers["anthropic"]
    p.input_tokens = p.output_tokens = 1_000_000  # $2 per Game Review request: over the $1 budget at once
    rig.usage.run("game_move", "s", "u", "x", SCHEMA)
    assert rig.usage.quote("explain", 10).state == "over_budget"  # Game Review's spend blocks Explain
    assert rig.usage.quote("game_narrative", 10).state == "over_budget"
    rig.settings.update("anthropic", "claude-haiku-5-5", "low", 0.001, 1000.0)  # one cap for every feature
    assert rig.usage.quote("game_narrative", 10).state == "over_cap"


def test_update_feature_rejects_bad_input(rig: Rig) -> None:  # noqa: F811
    for args in [
        ("explain", "same", "", "low"),  # Explain is set with update()
        ("puzzles", "same", "", "low"),  # not a feature
        ("game_review", "gemini", "x", "low"),
        ("game_review", "openai", "bad model id!", "low"),
        ("game_review", "openai", "gpt-5.4", "max"),
    ]:
        with pytest.raises(ValidationError):
            rig.settings.update_feature(*args)


def test_launch_check_tests_each_provider_a_feature_uses(rig: Rig) -> None:  # noqa: F811
    _explain_on_haiku(rig)
    rig.settings.set_key("openai", FAKE_OPENAI_KEY)
    rig.settings.update_feature("game_review", "openai", "gpt-5.4", "low")
    job = rig.settings.start_launch_check()
    assert job is not None
    rig.settings._runner.wait(job, 5)
    assert rig.settings.launch_check() == ("ok", None)
    assert rig.providers["anthropic"].keys_seen and rig.providers["openai"].keys_seen
