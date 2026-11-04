"""v0.10 optional AI coaching on a Coach report (§10.6): the anonymized prompt, validation with the
deterministic fallback, the Coach's own model and usage log, the cap and the budget, and the saved
answer that shows again for free."""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.fakes.engine import FakeEngine, plant_managed_install
from tests.integration.test_coach_run import ANY_GAME, _my_games, _run
from tests.integration.test_game_explain import configure, fake, logged
from weaksquare.core.coach_llm import validate
from weaksquare.core.errors import AppError


@pytest.fixture(autouse=True)
def _reset() -> None:
    FakeEngine.instances.clear()


def _answer(key: str = "missed:mateIn1", presets: list[dict[str, Any]] | None = None) -> str:
    return json.dumps(
        {
            "summary": "You miss back-rank mates. See E1.",
            "weaknesses": [
                {"key": key, "explanation": "Twice you missed Rd8#.", "drill": "Mate-in-one puzzles."},
                {"key": "invented:thing", "explanation": "x", "drill": "y"},
            ],
            "presets": presets
            if presets is not None
            else [
                {"name": "Back rank", "themes": ["backRankMate", "mateIn1", "notATheme"], "rating_min": 1200,
                 "rating_max": 1600, "lengths": [1, 7], "mode": "standard", "queue_size": 30},
            ],
        }
    )  # fmt: skip


def _report(services, paths) -> int:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    _my_games(services, 2)
    return _run(services, {"source": "games", **ANY_GAME})


def _wait(services, job: str) -> None:  # type: ignore[no-untyped-def]
    st = services.coach._runner.wait(job, 10)
    assert st is not None and st.state == "done", st


def test_the_prompt_is_anonymized(services, paths) -> None:  # type: ignore[no-untyped-def]
    rid = _report(services, paths)
    configure(services)
    fake(services).queue(_answer())
    _wait(services, services.coach.start_ai(rid))
    req = fake(services).requests[-1]
    text = req.system + req.user
    for leak in ("player_a", "opponent_b", "lichess.org", "chess.com", "2026", "[%clk", "game_id", '"ply"', "Site"):
        assert leak not in text, leak
    assert "E1" in req.user and "Rd8#" in req.user  # positions go as labelled SAN
    assert req.max_tokens == 2500  # FR-8.14: Coach Summary


def test_the_answer_is_validated_saved_and_logged_under_the_coach(services, paths) -> None:  # type: ignore[no-untyped-def]
    rid = _report(services, paths)
    configure(services)
    services.llm_settings.update_feature("coach", "anthropic", "claude-sonnet-5-5", "low")
    fake(services).queue(_answer())
    _wait(services, services.coach.start_ai(rid))
    coaching, meta = services.coach.ai_result(rid)
    assert [w.key for w in coaching.weaknesses] == ["missed:mateIn1"]  # the invented key is dropped
    preset = coaching.presets[0]
    assert preset.themes == ("backRankMate", "mateIn1") and preset.lengths == (1,) and preset.queue_size == 30
    assert coaching.discarded >= 3 and not coaching.fallback_preset
    assert meta["model"] == "claude-sonnet-5-5"
    assert logged(services)[-1] == ("coach", "claude-sonnet-5-5", "ok")
    assert fake(services).requests[-1].model == "claude-sonnet-5-5"
    # Shown again for free: no second request.
    assert services.coach.quote_ai(rid).state == "cached"
    _wait(services, services.coach.start_ai(rid))
    assert len(fake(services).requests) == 1


def test_no_valid_preset_falls_back_to_the_reports_own(services, paths) -> None:  # type: ignore[no-untyped-def]
    rid = _report(services, paths)
    configure(services)
    fake(services).queue(_answer(presets=[{"name": "x", "themes": ["nope"], "rating_min": 5000, "rating_max": 1,
                                           "lengths": [], "mode": "fly", "queue_size": 0}]))  # fmt: skip
    _wait(services, services.coach.start_ai(rid))
    coaching, _ = services.coach.ai_result(rid)
    assert coaching.fallback_preset and coaching.presets and coaching.presets[0].name == "The report's mix"


def test_the_cap_and_the_budget_block_the_request(services, paths) -> None:  # type: ignore[no-untyped-def]
    rid = _report(services, paths)
    configure(services)
    services.llm_settings.update_feature("coach", "anthropic", "claude-fable-5-1", "high")
    services.llm_settings.update("anthropic", "claude-haiku-5-5", "low", 0.01, 5.00)
    q = services.coach.quote_ai(rid)
    assert q.state == "over_cap" and q.estimate.worst_usd > 0.01
    with pytest.raises(AppError):
        services.coach.start_ai(rid)
    services.llm_settings.update("anthropic", "claude-haiku-5-5", "low", 0.50, 0.0)
    assert services.coach.quote_ai(rid).state == "over_budget"
    assert fake(services).requests == []


def test_another_players_report_gets_coaching_without_their_name(services, paths) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    rid = _run(services, {"source": "games", "player": "opponent_b", "platform": "lichess", **ANY_GAME})
    configure(services)
    row, _ = services.coach.report(rid)
    keys = [w["key"] for g in ("missed", "allowed", "habits") for w in row.report[g]]
    fake(services).queue(_answer(key=keys[0] if keys else "missed:fork"))
    _wait(services, services.coach.start_ai(rid))
    req = fake(services).requests[-1]
    assert "opponent_b" not in req.user and "opponent_b" not in req.system


def test_validate_rejects_a_non_object() -> None:
    assert validate("[]", [], None) is None
    assert validate("not json", [], None) is None
    assert validate(json.dumps({"summary": ""}), [], None) is None
