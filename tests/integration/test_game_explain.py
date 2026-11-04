"""Game Review AI (v0.9, §11.4) through the wired services: Explain this move and Explain my game.
ROADMAP v0.9 *Done when*: cache hit; budget enforcement; each feature's request uses that feature's
model and is logged under its feature. Real SQLite, fake providers, the stored analysis of a fixture game."""

# ruff: noqa: F811  (the `game` fixture is imported from test_review and requested by name)
from __future__ import annotations

import json
from typing import Any

import chess
import pytest

from tests.fakes.llm import FAKE_ANTHROPIC_KEY, FakeLLMProvider
from tests.integration.test_review import ANALYSES, MOVES, SCHOLAR, _reset, game  # noqa: F401  (fixtures)
from weaksquare.adapters.db.repos.game_analysis import GameAnalysisRepo
from weaksquare.core.errors import AppError, ValidationError
from weaksquare.core.game_review import grade_game
from weaksquare.core.llm.provider import LLMResponse

MOVE_ANSWER = {
    "summary": "Qe7 guards f7.", "key_ideas": ["defence"],
    "steps": [{"ply": 0, "move": "Qe7", "text": "It covers f7.", "variation": [],
               "annotations": [{"type": "arrow", "from": "d8", "to": "e7", "color": "green"}]}],
}  # fmt: skip
NARRATIVE_ANSWER = {
    "opening_summary": "An early queen sortie.", "turning_point_ply": 5, "recurring_themes": ["king safety"],
    "takeaways": ["Defend f7.", "Check queen threats."],
    "moments": [{"ply": 5, "played": "Nf6", "text": "It drops f7.", "better_line": ["Qe7"],
                 "annotations": [{"type": "arrow", "from": "h5", "to": "f7", "color": "red"}]}],
    "preset": {"themes": ["mateIn1", "notATheme"], "rating_min": 1000, "rating_max": 1500},
}  # fmt: skip


def fake(services: Any, provider: str = "anthropic") -> FakeLLMProvider:
    return services.llm_settings.provider(provider)  # type: ignore[no-any-return]


def configure(services: Any, explain: str = "claude-haiku-5-5", game_review: str | None = None) -> None:
    services.llm_settings.set_key("anthropic", FAKE_ANTHROPIC_KEY)
    services.llm_settings.update("anthropic", explain, "low", 0.50, 5.00)
    if game_review:
        services.llm_settings.update_feature("game_review", "anthropic", game_review, "low")


def wait(services: Any, job: str) -> Any:
    st = services.game_explain._runner.wait(job, 10)
    assert st is not None and st.state == "done", st
    return st


def logged(services: Any) -> list[tuple[Any, ...]]:
    with services.db.session() as conn:
        return [tuple(r) for r in conn.execute("SELECT feature, model, status FROM llm_usage ORDER BY id")]


def _status(services: Any, gid: int) -> str:
    with services.db.session() as conn:
        return str(conn.execute("SELECT analysis_status FROM games WHERE id = ?", (gid,)).fetchone()[0])


# ---- Explain this move (FR-11.17) -------------------------------------------------------------------


def test_explain_this_move_runs_once_then_comes_from_the_cache(services, game: int) -> None:  # type: ignore[no-untyped-def]
    configure(services)
    ge = services.game_explain
    fake(services).queue(json.dumps(MOVE_ANSWER))
    q = ge.quote_move(game, 5)
    assert q.state == "ok" and q.model == "claude-haiku-5-5" and q.estimate.worst_usd > 0
    assert ge.move_result(game, 5) is None
    wait(services, ge.start_move(game, 5))
    v = ge.move_result(game, 5)
    assert v is not None and not v.cached and v.cost_usd > 0
    assert [s.san for s in v.explanation.steps] == ["Qe7"]
    assert v.start_fen == grade_game(chess.STARTING_FEN, MOVES, ANALYSES)[5].fen_before and v.solution == ("d8e7",)
    req = fake(services).requests[-1]
    assert req.max_tokens == 1500 and "they played Nf6" in req.user
    # Cache hit (Done when): free, no request, shown as saved.
    assert ge.quote_move(game, 5).state == "cached"
    wait(services, ge.start_move(game, 5))
    assert len(fake(services).requests) == 1
    services.game_explain._fresh.clear()  # as after a restart
    again = ge.move_result(game, 5)
    assert again is not None and again.cached and again.cost_usd == 0
    assert logged(services) == [("game_review", "claude-haiku-5-5", "ok")]


def test_explain_this_move_is_for_your_analyzed_moves_only(services, game: int) -> None:  # type: ignore[no-untyped-def]
    configure(services)
    ge = services.game_explain
    with pytest.raises(ValidationError, match="your own moves"):
        ge.quote_move(game, 4)  # White's move: you played Black
    with pytest.raises(ValidationError, match="no such move"):
        ge.quote_move(game, 99)
    with pytest.raises(ValidationError):
        ge.quote_move(game, "5")
    other = services.games.import_pgn(SCHOLAR.replace("Nf6 4. Qxf7#", "a6 4. Qxf7+")).game_id
    with pytest.raises(ValidationError, match="Analyze this game first"):
        ge.quote_move(other, 5)


def test_a_bad_or_truncated_answer_shows_nothing_but_is_logged(services, game: int) -> None:  # type: ignore[no-untyped-def]
    configure(services)
    ge = services.game_explain
    f = fake(services)
    f.queue(LLMResponse("{}", 100, 1500, "truncated"))
    st = services.game_explain._runner.wait(ge.start_move(game, 5), 10)
    assert st.state == "failed" and st.error_code == "llm_truncated"
    f.queue("not json")
    st = services.game_explain._runner.wait(ge.start_move(game, 5), 10)
    assert st.state == "failed" and st.error_code == "llm_bad_answer"
    assert ge.move_result(game, 5) is None
    assert [r[2] for r in logged(services)] == ["truncated", "ok"]


# ---- Explain my game (FR-11.18) ---------------------------------------------------------------------


def test_explain_my_game_validates_caches_and_marks_the_game_ai_reviewed(services, game: int) -> None:  # type: ignore[no-untyped-def]
    configure(services)
    ge = services.game_explain
    fake(services).queue(json.dumps(NARRATIVE_ANSWER))
    q = ge.quote_narrative(game)
    assert q.state == "ok" and q.estimate.max_output_tokens == 4000 and q.spend.budget_usd == 5.0
    wait(services, ge.start_narrative(game))
    v = ge.narrative_result(game)
    assert v is not None and not v.cached and v.n == 5 and v.moments == (5,)
    n = v.narrative
    assert n.turning_point == 5 and n.moments[0].better_uci == ("d8e7",)
    assert n.preset is not None and n.preset.themes == ("mateIn1",) and n.discarded == 1
    assert _status(services, game) == "ai_reviewed"
    req = fake(services).requests[-1]
    assert req.max_tokens == 4000 and req.schema_name == "game_review"
    for word in ("opponent_b", "player_a", "[White", 'Result "'):
        assert word not in req.user
    # Cache hit: free; a different N is a different request.
    assert ge.quote_narrative(game).state == "cached"
    assert ge.quote_narrative(game, 3).state == "ok"
    # Re-analysis sets the status back, and a re-analysis at other settings misses the cache.
    rows = grade_game(chess.STARTING_FEN, MOVES, ANALYSES)
    GameAnalysisRepo(services.db).replace(game, rows, "analyzed", 0.3, "Stockfish 19")
    assert _status(services, game) == "analyzed"
    assert ge.quote_narrative(game).state == "cached"  # same settings: the same evals
    GameAnalysisRepo(services.db).replace(game, rows, "analyzed", 1.0, "Stockfish 19")
    assert ge.quote_narrative(game).state == "ok"


def test_n_is_checked(services, game: int) -> None:  # type: ignore[no-untyped-def]
    configure(services)
    for n in (0, 11, True, "5"):
        with pytest.raises(ValidationError):
            services.game_explain.quote_narrative(game, n)


# ---- guardrails (§9.3) and the per-feature model (FR-1.15) --------------------------------------------


def test_each_feature_uses_its_own_model_and_is_logged_under_it(services, game: int) -> None:  # type: ignore[no-untyped-def]
    configure(services, explain="claude-haiku-5-5", game_review="claude-sonnet-5-5")
    ge = services.game_explain
    fake(services).queue(json.dumps(NARRATIVE_ANSWER))
    assert ge.quote_narrative(game).model == "claude-sonnet-5-5"
    wait(services, ge.start_narrative(game))
    assert fake(services).requests[-1].model == "claude-sonnet-5-5"
    assert logged(services) == [("game_review", "claude-sonnet-5-5", "ok")]
    # The cache includes the model: switching Game Review to Haiku shows nothing saved.
    services.llm_settings.update_feature("game_review", "same", "", "low")
    assert ge.narrative_result(game) is None and ge.quote_narrative(game).model == "claude-haiku-5-5"


def test_the_budget_blocks_a_new_request_but_a_saved_one_still_shows(services, game: int) -> None:  # type: ignore[no-untyped-def]
    configure(services)
    ge = services.game_explain
    fake(services).queue(json.dumps(NARRATIVE_ANSWER))
    wait(services, ge.start_narrative(game))
    services.llm_settings.update("anthropic", "claude-haiku-5-5", "low", 0.50, 0.0)  # $0 budget: over at once
    assert ge.quote_move(game, 5).state == "over_budget"
    with pytest.raises(AppError) as e:
        ge.start_move(game, 5)
    assert e.value.code == "over_budget"
    assert ge.quote_narrative(game).state == "cached"
    wait(services, ge.start_narrative(game))  # free, so it runs
    assert len(fake(services).requests) == 1


def test_the_per_run_cap_blocks_explain_my_game(services, game: int) -> None:  # type: ignore[no-untyped-def]
    configure(services, game_review="claude-fable-5-1")
    services.llm_settings.update("anthropic", "claude-haiku-5-5", "low", 0.05, 5.00)
    q = services.game_explain.quote_narrative(game)
    assert q.state == "over_cap" and q.estimate.worst_usd > 0.05
    with pytest.raises(AppError):
        services.game_explain.start_narrative(game)
    assert fake(services).requests == []


def test_no_model_means_no_request(services, game: int) -> None:  # type: ignore[no-untyped-def]
    assert services.game_explain.quote_narrative(game).state == "not_configured"
    assert services.game_explain.narrative_result(game) is None
    with pytest.raises(AppError):
        services.game_explain.start_narrative(game)


def test_the_library_filters_and_shows_ai_reviewed_games(services, game: int) -> None:  # type: ignore[no-untyped-def]
    from weaksquare.core.games import LibraryFilter

    configure(services)
    fake(services).queue(json.dumps(NARRATIVE_ANSWER))
    wait(services, services.game_explain.start_narrative(game))
    assert services.games.list_games(LibraryFilter(statuses=("ai_reviewed",)))[1] == 1
    assert services.games.list_games(LibraryFilter(statuses=("analyzed",)))[1] == 0
    rows, _ = services.games.list_games(LibraryFilter(statuses=("analyzed", "ai_reviewed")))
    assert [r.analysis_status for r in rows] == ["ai_reviewed"]
