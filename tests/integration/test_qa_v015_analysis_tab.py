"""QA v0.15 (independent): the Analysis tab through the bridge, beyond the builder's tests. Rate limits, an expired
sign-in, the White's-side wording, and that the opening trainer's wording is unchanged. Invented data only."""

from __future__ import annotations

from typing import Any

import chess

from tests.fakes.engine import FakeEngine, plant_managed_install
from tests.integration.test_analysis_tab import AFTER_E4, api, net, ok, tokens  # noqa: F401  (fixtures)
from tests.integration.test_opening_sources import Net
from weaksquare.core.engine import EngineLine, format_score, game_over_text


def test_qa_rate_limited_popular_replies_are_unavailable_and_pause_further_requests(api: Any, net: Net) -> None:  # noqa: F811
    net.status = 429
    assert ok(api.get_popular_replies(AFTER_E4)) == {"state": "unavailable", "total": 0, "moves": []}
    asked = len(net.requests)
    net.status = 200
    other = "rnbqkbnr/pppppppp/8/8/3P4/8/PPP1PPPP/RNBQKBNR b KQkq - 0 1"
    assert ok(api.get_popular_replies(other))["state"] == "unavailable"
    assert len(net.requests) == asked  # Lichess asked us to wait: nothing more is sent


def test_qa_an_expired_sign_in_is_unavailable_not_an_error(api: Any, net: Net) -> None:  # noqa: F811
    net.status = 401
    assert ok(api.get_popular_replies(AFTER_E4))["state"] == "unavailable"


def test_qa_a_cached_answer_is_used_when_offline(api: Any, net: Net) -> None:  # noqa: F811
    first = ok(api.get_popular_replies(AFTER_E4))
    assert first["state"] == "ok"
    import httpx

    net.fail = httpx.ConnectError
    again = ok(api.get_popular_replies(AFTER_E4))
    assert again == first


def test_qa_the_engine_wording_is_from_whites_side_on_this_tab(api: Any, paths: Any) -> None:  # noqa: F811
    plant_managed_install(paths)
    FakeEngine.instances.clear()
    a = ok(api.analyze_board_position(AFTER_E4, "start"))
    for line in a["lines"]:
        s = line["score"]
        assert "you" not in s.lower() and "for" not in s
    mate = ok(api.analyze_board_position("7k/6Q1/6K1/8/8/8/8/8 b - - 0 1", "board"))
    text = repr(mate)
    assert "Checkmate: White wins" in text and "you" not in text.lower()


def test_qa_an_unknown_purpose_is_refused(api: Any, paths: Any) -> None:  # noqa: F811
    plant_managed_install(paths)
    r = api.analyze_board_position(AFTER_E4, "background")
    assert not r["ok"]


def test_qa_b1_a_null_move_in_check_never_reaches_the_board(api: Any) -> None:  # noqa: F811
    """v0.15-B1 through the bridge: either the PGN is refused, or no node in the tree is an illegal position."""
    r = api.import_analysis_pgn("1. e4 e5 2. Qh5 Nc6 3. Qxf7+ -- 4. Qxe8 *")
    if not r["ok"]:
        return
    g = ok(api.get_analysis_pgn_game("1. e4 e5 2. Qh5 Nc6 3. Qxf7+ -- 4. Qxe8 *", 0))
    for m in g["moves"]:
        assert chess.Board(m["fen"]).is_valid(), m


# ---- The new "both" viewpoint leaves the other screens' wording alone -------------------------------------------


def test_qa_colour_viewpoints_keep_the_for_you_wording() -> None:
    line = EngineLine(cp=30, mate=None, pv=())
    assert format_score(line, "white") == "+0.3 for you"
    assert format_score(line, "black") == "−0.3 for you"
    assert format_score(line, "both") == "+0.3"
    mate = EngineLine(cp=None, mate=-2, pv=())
    assert format_score(mate, "white") == "You're mated in 2"
    assert format_score(mate, "black") == "You mate in 2"
    assert format_score(mate, "both") == "Black mates in 2"
    level = EngineLine(cp=2, mate=None, pv=())
    assert format_score(level, "both") == format_score(level, "white") == "0.0 (level)"
    mated = chess.Board("7k/6Q1/6K1/8/8/8/8/8 b - - 0 1")
    assert game_over_text(mated, "white") == "Checkmate: you win"
    assert game_over_text(mated, "black") == "You're checkmated"
    assert game_over_text(mated, "both") == "Checkmate: White wins"
