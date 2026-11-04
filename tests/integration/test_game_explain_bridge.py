"""Game Review AI and the per-feature model through the bridge (v0.9: FR-1.15, §11.4): the settings DTO,
set_llm_feature, the quotes, the results as DTOs, the AI-reviewed status in My games, and errors."""

from __future__ import annotations

import json
import shutil
from typing import Any

import chess
import pytest

from tests.fakes.llm import FAKE_ANTHROPIC_KEY, FakeLLMProvider
from tests.helpers import build_api
from tests.integration.test_game_explain import MOVE_ANSWER, NARRATIVE_ANSWER
from tests.integration.test_review import ANALYSES, MOVES, SCHOLAR
from weaksquare import config
from weaksquare.adapters.db.repos.game_analysis import GameAnalysisRepo
from weaksquare.core.game_review import grade_game


def ok(r: dict[str, Any]) -> Any:
    assert r.get("ok"), r
    return r["data"]


@pytest.fixture
def api(paths, clock, fixture_puzzles_db):  # type: ignore[no-untyped-def]
    from weaksquare.adapters.db.migrate import migrate

    shutil.copyfile(fixture_puzzles_db, paths.puzzles_db)
    migrate(paths.user_db, config.MIGRATIONS_DIR / "user", clock)
    a = build_api(paths, clock)
    yield a
    a._runner.cancel_all()


@pytest.fixture
def game(api: Any) -> int:
    gid = ok(api.import_game_pgn(SCHOLAR))["game_id"]
    ok(api.set_game_color(gid, "black"))
    GameAnalysisRepo(api._game_explain._games._db).replace(gid, grade_game(chess.STARTING_FEN, MOVES, ANALYSES), "analyzed",
                                                    0.3, "Stockfish 19")  # fmt: skip
    return int(gid)


def fake(api: Any) -> FakeLLMProvider:
    return api._llm_settings._providers["anthropic"]  # type: ignore[no-any-return]


def configure(api: Any) -> None:
    ok(api.set_llm_key("anthropic", FAKE_ANTHROPIC_KEY))
    ok(api.set_llm_settings("anthropic", "claude-haiku-5-5", "low", 0.5, 5.0))


def finish(api: Any, job: str) -> None:
    st = api._runner.wait(job, 10)
    assert st is not None and st.state == "done", st


def test_the_settings_list_both_features_with_their_models_and_spend(api: Any) -> None:
    s = ok(api.get_llm_settings())
    assert [f["feature"] for f in s["features"]] == ["explain", "game_review"]
    gr = s["features"][1]
    assert (gr["choice"], gr["provider"], gr["ready"]) == ("same", "none", False)
    configure(api)
    s = ok(api.set_llm_feature("game_review", "anthropic", "claude-sonnet-5-5", "medium"))
    ex, gr = s["features"]
    assert (ex["choice"], ex["effective_model"], ex["reasoning"]) == ("anthropic", "claude-haiku-5-5", "low")
    assert (gr["choice"], gr["model"], gr["effective_model"], gr["reasoning"], gr["ready"]) == (
        "anthropic", "claude-sonnet-5-5", "claude-sonnet-5-5", "medium", True)  # fmt: skip
    models = {(o["provider"], o["model"]): o["usd"] for o in gr["options"]}
    assert ("openai", "gpt-5.4") in models  # every provider's models; the key check comes when you use one
    # Game Review's dropdown shows an Explain my game's cost: more than one puzzle Explain on the same model.
    ex_cost = {(o["provider"], o["model"]): o["usd"] for o in ex["options"]}
    assert models[("anthropic", "claude-sonnet-5-5")] > ex_cost[("anthropic", "claude-sonnet-5-5")]
    s = ok(api.set_llm_feature("game_review", "same", "", "low"))
    assert s["features"][1]["effective_model"] == "claude-haiku-5-5"
    r = api.set_llm_feature("explain", "same", "", "low")
    assert not r["ok"] and r["error"]["code"] == "invalid_argument"


def test_explain_my_game_through_the_bridge(api: Any, game: int) -> None:
    configure(api)
    q = ok(api.get_game_narrative_quote(game, None))
    assert q["state"] == "ok" and q["max_output_tokens"] == 4000 and q["input_tokens"] > 0
    assert q["worst_usd"] >= q["typical_usd"] and q["budget_usd"] == 5.0 and q["run_cap_usd"] == 0.5
    assert ok(api.get_game_narrative(game, None)) is None
    fake(api).queue(json.dumps(NARRATIVE_ANSWER))
    finish(api, ok(api.start_game_narrative(game, None)))
    n = ok(api.get_game_narrative(game, None))
    assert n["n"] == 5 and n["key_moments"] == [5] and n["turning_point"] == 5 and not n["cached"]
    assert n["moments"][0]["better_uci"] == ["d8e7"] and n["moments"][0]["annotations"][0]["kind"] == "arrow"
    assert n["preset"] == {"themes": ["mateIn1"], "names": ["Mate in 1"], "rating_min": 1000, "rating_max": 1500}
    page = ok(api.list_games({"statuses": ["ai_reviewed"]}))
    assert [g["analysis_status"] for g in page["games"]] == ["ai_reviewed"]
    s = ok(api.get_llm_settings())
    assert s["features"][1]["spent_usd"] > 0 and s["features"][0]["spent_usd"] == 0


def test_explain_this_move_through_the_bridge(api: Any, game: int) -> None:
    configure(api)
    assert ok(api.get_game_move_quote(game, 5))["state"] == "ok"
    fake(api).queue(json.dumps(MOVE_ANSWER))
    finish(api, ok(api.start_game_move_explain(game, 5)))
    x = ok(api.get_game_move_explanation(game, 5))
    assert x["steps"][0]["san"] == "Qe7" and x["solution"] == ["d8e7"] and x["cost_usd"] > 0
    assert ok(api.get_game_move_quote(game, 5))["state"] == "cached"


def test_bad_requests_are_readable_errors(api: Any, game: int) -> None:
    configure(api)
    for r in (api.get_game_move_quote(game, 4), api.get_game_narrative_quote(game, 11),
              api.get_game_move_quote(9999, 0)):  # fmt: skip
        assert not r["ok"] and r["error"]["message"]
    ok(api.set_llm_settings("anthropic", "claude-haiku-5-5", "low", 0.5, 0.0))
    r = api.start_game_narrative(game, None)
    assert not r["ok"] and r["error"]["code"] == "over_budget"
