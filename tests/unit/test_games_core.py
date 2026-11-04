"""core/games.py (v0.8): PGN edge cases, color detection, URLs, time classes, Lichess game JSON."""

from __future__ import annotations

import pytest

from weaksquare.core.games import (
    GameError,
    ParsedGame,
    Skip,
    detect_color,
    low_clock,
    moves_hash,
    parse_chesscom_url,
    parse_lichess_game,
    parse_lichess_url,
    parse_pgn,
    parse_single_pgn,
    record_from_parsed,
    time_class,
    username_from,
)

MATE = '[White "player_a"]\n[Black "opponent_b"]\n[Result "1-0"]\n\n1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7# 1-0\n'
SECOND = '[White "opponent_c"]\n[Black "player_a"]\n[Result "0-1"]\n\n1. f3 e5 2. g4 Qh4# 0-1\n'


def _ok(items: list[ParsedGame | GameError]) -> list[ParsedGame]:
    return [g for g in items if isinstance(g, ParsedGame)]


def test_a_multi_game_file_gives_every_game_in_order() -> None:
    games = parse_pgn(MATE + "\n" + SECOND)
    assert [g.white for g in _ok(games)] == ["player_a", "opponent_c"]
    first = _ok(games)[0]
    assert first.moves[-1] == "h5f7" and first.sans[-1] == "Qxf7#" and first.result == "1-0"
    assert "player_a – opponent_b" in first.label


def test_a_bad_game_in_a_file_is_reported_and_the_others_still_load() -> None:
    bad = '[White "x"]\n[Black "y"]\n\n1. e4 e5 2. Ke3 *\n'
    games = parse_pgn(MATE + "\n" + bad + "\n" + SECOND)
    assert isinstance(games[1], GameError) and "illegal" in games[1].reason and games[1].index == 1
    assert len(_ok(games)) == 2


@pytest.mark.parametrize(
    "variant",
    [
        '[Variant "Chess960"]\n[FEN "bbqnnrkr/pppppppp/8/8/8/8/PPPPPPPP/BBQNNRKR w HFhf - 0 1"]',
        '[Variant "Atomic"]',
        '[Variant "Crazyhouse"]',
    ],
)
def test_variants_are_rejected(variant: str) -> None:
    (g,) = parse_pgn(variant + '\n[White "a"]\n\n1. e4 *\n')
    assert isinstance(g, GameError) and "only standard chess" in g.reason


def test_a_from_position_game_with_a_legal_start_is_accepted() -> None:
    pgn = '[White "a"]\n[Variant "From Position"]\n[SetUp "1"]\n[FEN "4k3/8/8/8/8/8/4P3/4K3 w - - 0 1"]\n\n1. e4 *\n'
    g = parse_single_pgn(pgn)
    assert g.start_fen.startswith("4k3/") and g.moves == ("e2e4",)


@pytest.mark.parametrize(
    "text, words",
    [
        ("hello world", "No game found"),
        ("", "No game found"),
        ('[White "a"]\n[Black "b"]\n\n*', "no moves"),
        ("1. e4 -- 2. d4 *", "illegal move"),
        ('[White "a"]\n[FEN "8/8/8/8/8/8/8/8 w - - 0 1"]\n[SetUp "1"]\n\n1. e4 *', "invalid starting position"),
    ],
)
def test_bad_pgns_give_a_clear_reason(text: str, words: str) -> None:
    with pytest.raises(GameError, match=words):
        parse_single_pgn(text)


def test_clocks_are_read_from_clk_comments() -> None:
    pgn = '[TimeControl "300+0"]\n\n1. e4 { [%clk 0:04:58] } e5 { [%clk 0:00:20] } *'
    g = parse_single_pgn(pgn)
    assert g.clocks == (298.0, 20.0)
    assert low_clock(g.clocks[1], "300+0") is True and low_clock(g.clocks[0], "300+0") is False
    assert low_clock(None, "300+0") is None and low_clock(10.0, None) is None


def test_moves_hash_is_the_same_for_the_same_moves_only() -> None:
    a = parse_single_pgn(MATE)
    b = parse_single_pgn('[White "someone"]\n\n' + MATE.split("\n\n", 1)[1])  # other tags, same moves
    assert moves_hash(a.start_fen, a.moves) == moves_hash(b.start_fen, b.moves)
    assert moves_hash(a.start_fen, a.moves) != moves_hash(a.start_fen, a.moves[:-1])


def test_detect_color_is_case_insensitive_and_unsure_when_both_or_neither_match() -> None:
    assert detect_color("Player_A", "opp", ["player_a"]) == "white"
    assert detect_color("opp", "player_a", ["x", "PLAYER_A"]) == "black"
    assert detect_color("opp", "other", ["player_a"]) is None
    assert detect_color("player_a", "player_a", ["player_a"]) is None
    assert detect_color(None, None, []) is None


@pytest.mark.parametrize(
    "url, gid",
    [
        ("https://lichess.org/GAMEID01", "GAMEID01"),
        ("lichess.org/GAMEID01/black", "GAMEID01"),
        ("https://lichess.org/GAMEID01abcd", "GAMEID01"),  # the 12-character player URL
        ("https://lichess.org/GAMEID01#32", "GAMEID01"),
        ("https://lichess.org/@/player_a", None),
        ("https://example.com/GAMEID01", None),
    ],
)
def test_lichess_urls(url: str, gid: str | None) -> None:
    assert parse_lichess_url(url) == gid


@pytest.mark.parametrize(
    "url, out",
    [
        ("https://www.chess.com/game/live/123456789", ("live", "123456789")),
        ("chess.com/game/daily/42?move=3", ("daily", "42")),
        ("https://www.chess.com/analysis/game/live/77", ("live", "77")),
        ("https://www.chess.com/live/game/88", ("live", "88")),
        ("https://www.chess.com/member/player_a", None),
        ("https://www.chess.com/callback/live/game/1", None),
    ],
)
def test_chesscom_urls(url: str, out: tuple[str, str] | None) -> None:
    assert parse_chesscom_url(url) == out


def test_profile_urls_become_usernames() -> None:
    assert username_from("https://www.chess.com/member/Player_A") == "Player_A"
    assert username_from("lichess.org/@/player_a/") == "player_a"
    assert username_from("  player_a ") == "player_a"


@pytest.mark.parametrize(
    "tc, cls",
    [("60+0", "bullet"), ("120+1", "bullet"), ("180+0", "blitz"), ("300+3", "blitz"), ("600+0", "rapid"),
     ("900+10", "rapid"), ("1800+0", "classical"), ("1/86400", "daily"), ("-", "daily"), ("?", None), (None, None)],
)  # fmt: skip
def test_time_class_follows_the_estimated_duration(tc: str | None, cls: str | None) -> None:
    assert time_class(tc) == cls


def test_lichess_game_json_with_everything() -> None:
    data = {
        "id": "GAMEID03",
        "rated": True,
        "variant": "standard",
        "speed": "rapid",
        "createdAt": 1767225600000,
        "status": "mate",
        "winner": "black",
        "players": {
            "white": {"user": {"name": "player_a"}, "rating": 1500, "analysis": {"accuracy": 81}},
            "black": {"user": {"name": "opponent_b"}, "rating": 1520, "analysis": {"accuracy": 90}},
        },
        "opening": {"eco": "C50", "name": "Italian Game"},
        "clock": {"initial": 600, "increment": 5},
        "division": {"middle": 20, "end": 60},
        "analysis": [{"eval": 20}],
        "pgn": MATE,
    }
    r = parse_lichess_game(data)
    assert (r.source, r.source_game_id, r.url) == ("lichess", "GAMEID03", "https://lichess.org/GAMEID03")
    assert (r.result, r.time_control, r.time_class, r.rated) == ("0-1", "600+5", "rapid", True)
    assert (r.white, r.black_rating, r.eco, r.accuracy_black) == ("player_a", 1520, "C50", 90.0)
    assert r.lichess_analyzed and r.extra["division"] == {"middle": 20, "end": 60}
    assert r.played_at == "2026-01-01T00:00:00+00:00"


def test_lichess_game_json_with_only_id_and_pgn() -> None:
    r = parse_lichess_game({"id": "GAMEID04", "pgn": MATE})
    assert r.result == "1-0" and r.white is None and r.time_class is None and not r.lichess_analyzed


@pytest.mark.parametrize(
    "data", [{"id": "GAMEID05", "pgn": MATE, "variant": "atomic"}, {"id": "GAMEID05"}, {"pgn": MATE}]
)
def test_lichess_variants_and_incomplete_entries_are_skipped(data: dict[str, object]) -> None:
    with pytest.raises(Skip):
        parse_lichess_game(data)


def test_a_pasted_game_takes_its_details_from_the_tags() -> None:
    pgn = (
        '[Site "https://lichess.org/GAMEID06"]\n[UTCDate "2026.10.01"]\n[UTCTime "12:30:00"]\n[White "player_a"]\n'
        '[Black "opponent_b"]\n[WhiteElo "1500"]\n[TimeControl "180+2"]\n[ECO "C20"]\n[Result "1-0"]\n\n1. e4 e5 1-0\n'
    )
    r = record_from_parsed(parse_single_pgn(pgn), "paste")
    assert (r.source, r.source_game_id, r.url) == ("paste", None, "https://lichess.org/GAMEID06")
    assert (r.played_at, r.time_class, r.white_rating, r.black_rating) == (
        "2026-10-01T12:30:00+00:00",
        "blitz",
        1500,
        None,
    )
