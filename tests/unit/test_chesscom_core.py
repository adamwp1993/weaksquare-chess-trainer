"""core/chesscom.py (v0.8): archive games with every optional field missing (FR-11.28), and months."""

from __future__ import annotations

from typing import Any

import pytest

from weaksquare.core.chesscom import archive_month, months_to_fetch, parse_archive_game
from weaksquare.core.games import Skip

PGN = (
    '[White "player_a"]\n[Black "opponent_b"]\n[Result "1-0"]\n[ECO "C50"]\n[TimeControl "600"]\n'
    '[ECOUrl "https://www.chess.com/openings/Italian-Game"]\n\n1. e4 e5 1-0\n'
)


def _full() -> dict[str, Any]:
    return {
        "url": "https://www.chess.com/game/live/100000001",
        "pgn": PGN,
        "time_control": "600",
        "end_time": 1767225600,
        "rated": True,
        "accuracies": {"white": 85.5, "black": 70.1},
        "fen": "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2",
        "time_class": "rapid",
        "rules": "chess",
        "eco": "https://www.chess.com/openings/Italian-Game-Two-Knights",
        "white": {"username": "player_a", "rating": 1500, "result": "win"},
        "black": {"username": "opponent_b", "rating": 1490, "result": "resigned"},
    }


def test_a_complete_archive_game() -> None:
    r = parse_archive_game(_full())
    assert (r.source, r.source_game_id) == ("chesscom", "100000001")
    assert (r.white, r.black, r.white_rating, r.result) == ("player_a", "opponent_b", 1500, "1-0")
    assert (r.time_class, r.rated, r.accuracy_white, r.accuracy_black) == ("rapid", True, 85.5, 70.1)
    assert (r.eco, r.opening, r.played_at) == ("C50", "Italian Game Two Knights", "2026-01-01T00:00:00+00:00")


@pytest.mark.parametrize(
    "drop", ["time_control", "end_time", "rated", "accuracies", "fen", "time_class", "rules", "eco", "white", "black"]
)
def test_every_optional_field_may_be_missing(drop: str) -> None:
    data = _full()
    del data[drop]
    r = parse_archive_game(data)
    assert r.source_game_id == "100000001"
    if drop == "time_class":
        assert r.time_class == "rapid"  # derived from time_control (FR-11.28)
    if drop == "accuracies":
        assert r.accuracy_white is None and r.accuracy_black is None
    if drop == "white":
        assert r.white == "player_a" and r.white_rating is None  # the PGN tag is the fallback
    if drop == "eco":
        assert r.opening == "Italian Game"  # from the PGN's ECOUrl


@pytest.mark.parametrize(
    "field, value",
    [
        ("accuracies", "n/a"),
        ("white", "player_a"),
        ("end_time", "yesterday"),
        ("rated", "yes"),
        ("time_class", "hyper"),
    ],
)
def test_malformed_optional_fields_become_none_not_errors(field: str, value: Any) -> None:
    data = _full()
    data[field] = value
    parse_archive_game(data)


def test_the_time_class_is_derived_when_missing_including_daily() -> None:
    data = _full()
    del data["time_class"]
    data["time_control"] = "1/259200"
    assert parse_archive_game(data).time_class == "daily"


@pytest.mark.parametrize("rules", ["chess960", "bughouse", "kingofthehill"])
def test_variants_are_skipped(rules: str) -> None:
    data = _full()
    data["rules"] = rules
    with pytest.raises(Skip):
        parse_archive_game(data)


@pytest.mark.parametrize("drop", ["url", "pgn"])
def test_url_and_pgn_are_required(drop: str) -> None:
    data = _full()
    del data[drop]
    with pytest.raises(Skip):
        parse_archive_game(data)


def test_draw_results() -> None:
    data = _full()
    data["white"]["result"] = "repetition"
    data["black"]["result"] = "repetition"
    assert parse_archive_game(data).result == "1/2-1/2"


def test_months_newest_first_from_the_last_synced_month() -> None:
    base = "https://api.chess.com/pub/player/player_a/games/"
    archives = [base + m for m in ("2026/07", "2026/08", "2026/09", "2026/10")] + ["https://example.com/other"]
    assert archive_month(archives[0]) == "2026/07"
    assert months_to_fetch(archives, "2026/09", None) == [base + "2026/10", base + "2026/09"]
    assert months_to_fetch(archives, None, "2026/08") == [base + "2026/10", base + "2026/09", base + "2026/08"]
    assert len(months_to_fetch(archives, None, None)) == 4
