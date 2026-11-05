"""v0.10 through the bridge: Analyze from here (FR-11.34), Show best moves (FR-11.35), the puzzle level,
the Player filter, and the Coach's report and Suggested mix DTOs."""

from __future__ import annotations

from typing import Any

import pytest

from tests.fakes.engine import FakeEngine, plant_managed_install
from tests.helpers import build_api
from tests.integration.test_coach_run import ANY_GAME, _my_games, _run
from tests.integration.test_review import _reset, game  # noqa: F401  (fixtures)
from weaksquare.adapters.db.repos.game_analysis import GameAnalysisRepo


@pytest.fixture
def api(services, paths, clock):  # type: ignore[no-untyped-def]
    a = build_api(paths, clock)
    # The bridge built by build_api has its own services; use the shared fixture's instead.
    a._review, a._coach, a._game_puzzles, a._games = (
        services.review,
        services.coach,
        services.game_puzzles,
        services.games,
    )
    a._ui_settings, a._runner = services.ui_settings, services.coach._runner
    return a


def ok(result: dict[str, Any]) -> Any:
    assert result["ok"], result
    return result["data"]


def test_analyze_from_here_uses_the_interactive_engine_and_changes_nothing(services, paths, api, game: int) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    plant_managed_install(paths)
    before = GameAnalysisRepo(services.db).rows(game)
    status = services.games.get(game).analysis_status
    FakeEngine.instances.clear()
    a = ok(api.analyze_game_position(game, "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2", "board"))
    assert a["lines"]
    used = [e for e in FakeEngine.instances if e.calls]
    assert used and all(e.options[0] == 7 for e in used)  # the interactive engine only, never the background one
    assert GameAnalysisRepo(services.db).rows(game) == before and services.games.get(game).analysis_status == status
    bad = api.analyze_game_position(game, "not a fen", "board")
    assert not bad["ok"]


def test_show_best_moves_is_off_by_default_and_remembered(api) -> None:  # type: ignore[no-untyped-def]
    assert ok(api.get_settings())["show_best"] is False
    ok(api.set_setting("review.show_best", True))
    assert ok(api.get_settings())["show_best"] is True
    assert not api.set_setting("review.show_best", "yes")["ok"]


def test_the_puzzle_level_through_the_games_settings(api) -> None:  # type: ignore[no-untyped-def]
    s = ok(api.get_games_settings())
    assert s["puzzle_level"] == "mistakes" and s["puzzle_think_s"] == 1.0
    s = ok(api.set_games_settings(puzzle_level="blunders", puzzle_think_s=2.0))
    assert s["puzzle_level"] == "blunders" and s["puzzle_think_s"] == 2.0
    assert not api.set_games_settings(puzzle_level="everything")["ok"]


def test_the_player_filter_is_checked(api) -> None:  # type: ignore[no-untyped-def]
    assert ok(api.list_games({"player": "lichess:someone"}))["total"] == 0
    assert not api.list_games({"player": "x'; DROP TABLE games"})["ok"]


def test_a_coach_report_and_the_suggestion_through_the_bridge(services, paths, api) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    _my_games(services, 1)
    rid = _run(services, {"source": "games", **ANY_GAME})
    rep = ok(api.get_coach_report(rid))
    assert rep["is_me"] and rep["games"] == 1 and rep["preset"]["spec"]["ratios"]
    assert rep["missed"][0]["trend"] is None  # no previous report yet
    summaries = ok(api.list_coach_reports())
    assert summaries[0]["id"] == rid and summaries[0]["top"]
    sug = ok(api.get_suggestion())
    assert sug["label"].startswith("Suggested — from Coach run #1, ") and sug["active"] and not sug["pending"]
    assert ok(api.get_coach_defaults())["params"]["source"] == "games"
    assert ok(api.get_coach_ai_quote(rid))["quote"]["state"] == "not_configured"
    assert ok(api.list_coach_ai_runs(rid)) == []  # v0.11: the AI runs replace get_coach_ai
