"""v0.8 game clients over `httpx.MockTransport`: chess.com's serial rule, ETags, 404/410/429, the
Published-Data API only; the Lichess games export's parameters; the fixtures parse."""

from __future__ import annotations

import contextlib
import json
import threading
import time
from pathlib import Path

import httpx
import pytest

from weaksquare.adapters.chesscom import ChesscomGames, ChesscomGone, ChesscomNotFound
from weaksquare.adapters.http import USER_AGENT, HttpClient, RateLimited
from weaksquare.adapters.lichess_games import LichessGames
from weaksquare.config import REPO_URL
from weaksquare.core.chesscom import parse_archive_game
from weaksquare.core.games import Skip, parse_lichess_game, parse_single_pgn

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "http"
CC = "https://api.chess.com/pub/player/player_a"


def _fixture(*parts: str) -> bytes:
    return (FIX.joinpath(*parts)).read_bytes()


def _client(handler: object, sleeps: list[float] | None = None) -> ChesscomGames:
    http = HttpClient(transport=httpx.MockTransport(handler), retries=0, sleep=lambda s: None)  # type: ignore[arg-type]
    return ChesscomGames(http, sleep=(sleeps.append if sleeps is not None else (lambda s: None)), backoff_s=1.0)


def test_requests_are_strictly_one_at_a_time_across_threads() -> None:
    in_flight = 0
    peak = 0
    lock = threading.Lock()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal in_flight, peak
        with lock:
            in_flight += 1
            peak = max(peak, in_flight)
        time.sleep(0.02)
        with lock:
            in_flight -= 1
        return httpx.Response(200, json={"games": []})

    client = _client(handler)
    threads = [threading.Thread(target=client.archive, args=(f"{CC}/games/2026/{m:02d}", None)) for m in range(1, 9)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert peak == 1  # FR-10.7: parallel requests get 429


def test_user_agent_names_the_app_and_repo_and_nothing_personal() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["user-agent"])
        return httpx.Response(200, content=_fixture("chesscom", "profile.json"))

    _client(handler).profile("player_a")
    assert seen == [USER_AGENT] and REPO_URL in seen[0] and "@" not in seen[0]


def test_only_the_published_data_api_is_called() -> None:
    client = _client(lambda r: httpx.Response(200, json={}))
    with pytest.raises(ValueError):
        client.archive("https://www.chess.com/callback/live/game/1", None)


def test_verify_reads_the_profile_and_a_404_means_no_such_user() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/player_a"):
            return httpx.Response(200, content=_fixture("chesscom", "profile.json"))
        return httpx.Response(404, json={"code": 0, "message": "User not found"})

    client = _client(handler)
    p = client.profile("Player_A")
    assert p.username == "player_a" and p.url == "https://www.chess.com/member/player_a"
    with pytest.raises(ChesscomNotFound):
        client.profile("nobody_here")
    with pytest.raises(ValueError):
        client.profile("bad name!")


def test_an_unchanged_month_is_a_304_using_the_etag() -> None:
    sent: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request.headers.get("if-none-match"))
        if request.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(200, content=_fixture("chesscom", "archive_2026_09.json"), headers={"ETag": '"v1"'})

    client = _client(handler)
    first = client.archive(f"{CC}/games/2026/09", None)
    assert first.status == 200 and len(first.games) == 3 and first.etag == '"v1"'
    second = client.archive(f"{CC}/games/2026/09", first.etag)
    assert second.status == 304 and second.games == [] and second.etag == '"v1"'
    assert sent == [None, '"v1"']


def test_410_is_permanent() -> None:
    client = _client(lambda r: httpx.Response(410))
    with pytest.raises(ChesscomGone):
        client.archive(f"{CC}/games/2001/01", None)


def test_429_waits_and_tries_again_then_gives_up() -> None:
    hits = 0

    def flaky(request: httpx.Request) -> httpx.Response:
        nonlocal hits
        hits += 1
        if hits == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(200, content=_fixture("chesscom", "archives.json"))

    sleeps: list[float] = []
    assert len(_client(flaky, sleeps).archives("player_a")) == 2
    assert sleeps == [7.0]

    sleeps2: list[float] = []
    with pytest.raises(RateLimited):
        _client(lambda r: httpx.Response(429), sleeps2).archives("player_a")
    assert sleeps2 == [1.0, 2.0, 4.0]  # doubling backoff, then give up


def test_every_fixture_archive_game_parses_or_is_skipped_for_a_reason() -> None:
    games = json.loads(_fixture("chesscom", "archive_2026_09.json"))["games"]
    parsed, skipped = [], 0
    for g in games:
        try:
            parsed.append(parse_archive_game(g))
        except Skip:
            skipped += 1
    assert len(parsed) == 2 and skipped == 1  # the Chess960 game
    for r in parsed:
        parse_single_pgn(r.pgn)  # the PGN itself is valid standard chess
    assert parsed[1].time_class == "blitz"  # the minimal entry: derived from its PGN's TimeControl


def test_lichess_user_games_sends_the_documented_flags_and_the_token() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=_fixture("lichess_games", "user_games.ndjson"))

    http = HttpClient(transport=httpx.MockTransport(handler), retries=0)
    games = list(LichessGames(http).user_games("lip_FAKE0000", "player_a", since_ms=1789000000000, max_games=200))
    q = seen[0].url.params
    assert seen[0].url.path == "/api/games/user/player_a"
    assert (q["since"], q["max"], q["pgnInJson"], q["clocks"], q["evals"], q["accuracy"], q["opening"]) == (
        "1789000000000", "200", "true", "true", "true", "true", "true",
    )  # fmt: skip
    assert seen[0].headers["authorization"] == "Bearer lip_FAKE0000"
    assert seen[0].headers["accept"] == "application/x-ndjson"
    records = []
    for g in games:
        with contextlib.suppress(Skip):
            records.append(parse_lichess_game(g))
    assert [r.source_game_id for r in records] == ["GAMEID11", "GAMEID12"]  # the atomic game is skipped
    assert records[0].lichess_analyzed and records[0].accuracy_white == 55.0


def test_lichess_single_game_export_is_json_and_works_without_a_token() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=_fixture("lichess_games", "export_game.json"))

    http = HttpClient(transport=httpx.MockTransport(handler), retries=0)
    data = LichessGames(http).export_game(None, "GAMEID11")
    assert seen[0].url.path == "/game/export/GAMEID11" and "authorization" not in seen[0].headers
    assert seen[0].headers["accept"] == "application/json" and seen[0].url.params["division"] == "true"
    assert parse_lichess_game(data).extra["division"] == {"middle": 8}
    with pytest.raises(ValueError):
        LichessGames(http).export_game(None, "../x")


def test_recorded_game_fixtures_parse() -> None:
    """Adam's live recorder (`-m live --record-games`) writes recorded_* files; they must parse like the app does."""
    from weaksquare.core.chesscom import parse_archive_game

    found = 0
    for p in (FIX / "lichess_games").glob("recorded_*"):
        for line in (
            p.read_text(encoding="utf-8").splitlines() if p.suffix == ".ndjson" else [p.read_text(encoding="utf-8")]
        ):
            if line.strip():
                parse_single_pgn(parse_lichess_game(json.loads(line)).pgn)
                found += 1
    archive = FIX / "chesscom" / "recorded_archive.json"
    if archive.exists():
        for g in json.loads(archive.read_text(encoding="utf-8"))["games"]:
            parse_single_pgn(parse_archive_game(g).pgn)
            found += 1
    if not found:
        pytest.skip("no recorded game fixtures yet")
