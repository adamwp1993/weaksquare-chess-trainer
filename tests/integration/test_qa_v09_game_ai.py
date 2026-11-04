"""QA v0.9 (independent): Game Review AI and a model per AI feature, through the wired services with fake
providers. Edge cases beyond the builder's tests: a PGN full of metadata imported and sent through the real
service path, an error-free game, reasoning per feature, double clicks, a cached move over budget, the
User Guide's cache promise about grading thresholds, and Game Review working without puzzle Explain."""

# ruff: noqa: F811  (the `game` fixture is imported from test_review and requested by name)
from __future__ import annotations

import json
import threading
from typing import Any

import chess
import pytest

from tests.fakes.llm import FAKE_OPENAI_KEY
from tests.integration.test_game_explain import (
    MOVE_ANSWER,
    NARRATIVE_ANSWER,
    configure,
    fake,
    logged,
    wait,
)
from tests.integration.test_review import ANALYSES, MOVES, _reset, game  # noqa: F401  (fixtures)
from weaksquare.adapters.db.repos.game_analysis import GameAnalysisRepo
from weaksquare.core.errors import AppError, ValidationError
from weaksquare.core.game_review import grade_game

# Made-up but distinctive metadata (SR-12a): none of it may reach a provider (FR-8.16, FR-11.19).
LOUD_PGN = """[Event "QaRated Bullet Arena"]
[Site "https://example.invalid/QAGAME0001"]
[Date "2031.02.03"]
[UTCDate "2031.02.03"]
[UTCTime "23:45:01"]
[White "QaWhiteSurname"]
[Black "QaBlackSurname"]
[WhiteElo "2345"]
[BlackElo "2456"]
[WhiteTitle "FM"]
[TimeControl "60+0"]
[Termination "Time forfeit"]
[Annotator "QaAnnotatorName"]
[Result "1-0"]

1. e4 { [%clk 0:00:59] [%eval 0.3] } e5 { [%clk 0:00:58] } 2. Qh5 { [%clk 0:00:57] QaSecretComment } Nc6
3. Bc4 { [%clk 0:00:55] } Nf6 $4 { [%clk 0:00:41] (3... Qe7) } 4. Qxf7# { [%clk 0:00:54] } 1-0
"""
LOUD = [
    "QaRated", "Bullet", "Arena", "example.invalid", "QAGAME", "2031", "23:45", "QaWhiteSurname", "QaBlackSurname",
    "2345", "2456", "FM", "60+0", "forfeit", "QaAnnotatorName", "clk", "0:00", "%eval", "QaSecretComment", "$4",
    "Event", "Site", "Elo", "Annotator", "Termination", "[%", '[White', '"1-0"',
]  # fmt: skip


def _loud_game(services: Any) -> int:
    gid = int(services.games.import_pgn(LOUD_PGN).game_id)
    services.games.set_user_color(gid, "black")
    GameAnalysisRepo(services.db).replace(gid, grade_game(chess.STARTING_FEN, MOVES, ANALYSES), "analyzed", 0.3,
                                          "Stockfish 19")  # fmt: skip
    return gid


def test_qa_a_metadata_heavy_pgn_sends_no_trace_of_it_through_the_service(services) -> None:  # type: ignore[no-untyped-def]
    gid = _loud_game(services)
    configure(services)
    f = fake(services)
    f.queue(json.dumps(NARRATIVE_ANSWER))
    f.queue(json.dumps(MOVE_ANSWER))
    wait(services, services.game_explain.start_narrative(gid))
    wait(services, services.game_explain.start_move(gid, 5))
    assert len(f.requests) == 2
    for req in f.requests:
        sent = req.system + "\n" + req.user + "\n" + json.dumps(req.schema)
        for word in LOUD:
            assert word not in sent, (req.schema_name, word)
    assert "1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7#" in f.requests[0].user


def test_qa_a_game_with_no_errors_on_your_side_can_still_be_explained(services, game: int) -> None:  # type: ignore[no-untyped-def]
    services.games.set_user_color(game, "white")  # White's moves are all Stockfish's best here
    configure(services)
    ge = services.game_explain
    assert ge.quote_narrative(game).state == "ok"
    fake(services).queue(json.dumps(NARRATIVE_ANSWER))  # it talks about ply 5, which wasn't sent
    wait(services, ge.start_narrative(game))
    v = ge.narrative_result(game)
    assert v is not None and v.moments == () and v.narrative.moments == ()
    assert "Key moments" in fake(services).requests[-1].user
    # Black's move isn't yours now: Explain this move refuses it, White's best move can be explained.
    with pytest.raises(ValidationError, match="your own moves"):
        ge.quote_move(game, 5)
    assert ge.quote_move(game, 4).state == "ok"


@pytest.mark.parametrize(("level", "move", "narrative"), [("low", 1500, 4000), ("medium", 3000, 8000),
                                                           ("high", 6000, 16000)])  # fmt: skip
def test_qa_game_review_reasoning_scales_its_max_tokens_and_leaves_explain_alone(
    services, game: int, level: str, move: int, narrative: int
) -> None:  # type: ignore[no-untyped-def]
    configure(services, game_review="claude-sonnet-5-5")
    services.llm_settings.update_feature("game_review", "anthropic", "claude-sonnet-5-5", level)
    assert services.llm_settings.config("explain").reasoning == "low"
    ge = services.game_explain
    assert ge.quote_narrative(game).estimate.max_output_tokens == narrative
    assert ge.quote_move(game, 5).estimate.max_output_tokens == move
    f = fake(services)
    f.queue(json.dumps(NARRATIVE_ANSWER))
    f.queue(json.dumps(MOVE_ANSWER))
    wait(services, ge.start_narrative(game))
    wait(services, ge.start_move(game, 5))
    assert [(r.max_tokens, r.reasoning, r.model) for r in f.requests] == [
        (narrative, level, "claude-sonnet-5-5"), (move, level, "claude-sonnet-5-5")]  # fmt: skip


def test_qa_a_double_click_sends_one_request(services, game: int) -> None:  # type: ignore[no-untyped-def]
    configure(services)
    ge = services.game_explain
    f = fake(services)
    gate, entered = threading.Event(), threading.Event()
    real = f.generate

    def slow(key: str, request: Any) -> Any:
        entered.set()
        assert gate.wait(10)
        return real(key, request)

    f.generate = slow  # type: ignore[method-assign]
    f.queue(json.dumps(NARRATIVE_ANSWER))
    first = ge.start_narrative(game)
    assert entered.wait(10)
    second = ge.start_narrative(game)
    gate.set()
    wait(services, first)
    assert second == first
    assert len(f.requests) == 1 and len(logged(services)) == 1


def test_qa_a_saved_move_explanation_still_shows_over_budget(services, game: int) -> None:  # type: ignore[no-untyped-def]
    configure(services)
    ge = services.game_explain
    fake(services).queue(json.dumps(MOVE_ANSWER))
    wait(services, ge.start_move(game, 5))
    services.llm_settings.update("anthropic", "claude-haiku-5-5", "low", 0.50, 0.0)
    ge._fresh.clear()  # as after a restart
    assert ge.quote_move(game, 5).state == "cached"
    v = ge.move_result(game, 5)
    assert v is not None and v.cached and v.cost_usd == 0
    wait(services, ge.start_move(game, 5))
    assert len(fake(services).requests) == 1
    assert ge.quote_narrative(game).state == "over_budget"  # the shared budget blocks the other kind


def test_qa_game_review_can_use_its_own_provider_when_puzzle_explain_is_off(services, game: int) -> None:  # type: ignore[no-untyped-def]
    services.llm_settings.set_key("openai", FAKE_OPENAI_KEY)
    services.llm_settings.update_feature("game_review", "openai", "gpt-5.4-mini", "low")
    assert services.llm_settings.config("explain").configured is False
    ge = services.game_explain
    q = ge.quote_narrative(game)
    assert q.state == "ok" and (q.provider, q.model) == ("openai", "gpt-5.4-mini")
    fake(services, "openai").queue(json.dumps(NARRATIVE_ANSWER))
    wait(services, ge.start_narrative(game))
    assert logged(services) == [("game_review", "gpt-5.4-mini", "ok")]
    assert fake(services, "anthropic").requests == []


def test_qa_same_as_explain_follows_a_later_change_of_explains_model(services, game: int) -> None:  # type: ignore[no-untyped-def]
    configure(services, explain="claude-haiku-5-5")
    assert services.game_explain.quote_narrative(game).model == "claude-haiku-5-5"
    services.llm_settings.update("anthropic", "claude-sonnet-5-5", "low", 0.50, 5.00)
    assert services.game_explain.quote_narrative(game).model == "claude-sonnet-5-5"
    services.llm_settings.set_key("openai", FAKE_OPENAI_KEY)
    services.llm_settings.update("openai", "gpt-5.4-mini", "low", 0.50, 5.00)
    assert services.game_explain.quote_narrative(game).provider == "openai"


def test_qa_an_unknown_color_is_refused_with_a_readable_message(services) -> None:  # type: ignore[no-untyped-def]
    from tests.integration.test_review import SCHOLAR

    gid = int(services.games.import_pgn(SCHOLAR.replace("opponent_b", "x_b").replace("player_a", "x_a")).game_id)
    GameAnalysisRepo(services.db).replace(gid, grade_game(chess.STARTING_FEN, MOVES, ANALYSES), "analyzed", 0.3,
                                          "Stockfish 19")  # fmt: skip
    configure(services)
    with pytest.raises(ValidationError, match="which side you played"):
        services.game_explain.quote_narrative(gid)


def test_qa_a_blocked_start_is_an_apperror_with_the_guardrail_code(services, game: int) -> None:  # type: ignore[no-untyped-def]
    configure(services, game_review="claude-fable-5-1")
    services.llm_settings.update("anthropic", "claude-haiku-5-5", "low", 0.01, 5.00)
    with pytest.raises(AppError) as e:
        services.game_explain.start_move(game, 5)
    assert e.value.code == "over_cap"
    assert fake(services).requests == []


# v0.9-B2 regression test (fixed: the thresholds are in the cache key).
def test_qa_new_grading_thresholds_give_a_new_explanation_as_the_user_guide_says(services, game: int) -> None:  # type: ignore[no-untyped-def]
    configure(services)
    ge = services.game_explain
    f = fake(services)
    f.queue(json.dumps(MOVE_ANSWER))
    f.queue(json.dumps(NARRATIVE_ANSWER))
    wait(services, ge.start_move(game, 5))
    wait(services, ge.start_narrative(game))
    services.analysis.set_settings(thresholds={"inaccuracy": 20, "mistake": 40, "blunder": 80})
    ge._fresh.clear()
    # USER_GUIDE "AI explanations in Game Review" > Gotchas: "A new analysis at other settings, or other
    # grading thresholds, gets a new explanation."
    assert ge.quote_move(game, 5).state != "cached"
    assert ge.quote_narrative(game).state != "cached"
