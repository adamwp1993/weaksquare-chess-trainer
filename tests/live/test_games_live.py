"""Live game-API test (v0.8): opt-in with `uv run pytest -m live`; Adam runs it, never Claude Code.

It reads, and never writes:
- **Lichess:** the account of the `weaksquare-test` token, then your newest finished game from
  `/api/games/user/{you}` and the same game from `/game/export/{id}`.
- **chess.com** (only with `--chesscom-user <name>`): the public profile, the archives list and your
  newest month, one request at a time.

It checks the real shapes against the app's parsers. With `--record-games` it writes `recorded_*` files
next to the hand-written fixtures in tests/fixtures/http/lichess_games/ and chesscom/ (the service tests
keep using the hand-written ones; `test_recorded_game_fixtures_parse` parses the recorded ones). They're
**scrubbed and anonymized** (SR-12, SR-12a):
- you become `player_a` and opponents `opponent_b`, `opponent_c`…;
- game ids become `GAMEID11`… (Lichess) or `100000001`… (chess.com), and URLs follow;
- dates and times are fixed, ratings are rounded to fixture values, and profile details are dropped.
The written files must pass tests/contract/test_fixtures_clean.py, which the recorder checks first.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.live

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "http"


def _token() -> str:
    from weaksquare.adapters.secret_store import LICHESS, SERVICE_TEST, KeyringSecretStore, SecretStoreError

    try:
        token = KeyringSecretStore(SERVICE_TEST).get(LICHESS)
    except SecretStoreError:
        token = None
    if not token:
        pytest.skip("no live-test token: run uv run python scripts/set_test_token.py in your own PowerShell window")
    return token


class Anonymizer:
    """Replaces every name and id it's told about, then fixes dates, times and ratings."""

    def __init__(self, you: str) -> None:
        self.names: dict[str, str] = {you.lower(): "player_a"}
        self.ids: dict[str, str] = {}

    def name(self, n: str | None) -> None:
        if n and n.lower() not in self.names:
            self.names[n.lower()] = f"opponent_{chr(ord('b') + len(self.names) - 1)}"

    def game_id(self, gid: str, lichess: bool) -> None:
        if gid not in self.ids:
            n = len(self.ids) + 1
            self.ids[gid] = f"GAMEID{10 + n}" if lichess else f"1000000{n:02d}"

    def text(self, s: str) -> str:
        for real, fake in sorted(self.ids.items(), key=lambda kv: -len(kv[0])):
            s = s.replace(real, fake)
        for real, fake in sorted(self.names.items(), key=lambda kv: -len(kv[0])):
            s = re.sub(re.escape(real), fake, s, flags=re.IGNORECASE)
        s = re.sub(r'(\[(?:Date|UTCDate|EndDate|StartDate) ")[0-9.?]+(")', r"\g<1>2026.09.21\2", s)
        s = re.sub(r'(\[(?:UTCTime|StartTime|EndTime) ")[0-9:?]+(")', r"\g<1>12:00:00\2", s)
        s = re.sub(r'(\[(?:WhiteElo|BlackElo) ")\d+(")', r"\g<1>1500\2", s)
        s = re.sub(r'(\[(?:WhiteRatingDiff|BlackRatingDiff) ")[-+]?\d+(")', r"\g<1>+0\2", s)
        s = re.sub(r'(\[Link ")[^"]*(")', r"\1https://www.chess.com/game/live/100000001\2", s)
        s = re.sub(r'"(createdAt|lastMoveAt)": \d+', r'"\1": 1790000000000', s)
        s = re.sub(r'"(end_time|start_time|joined|last_online)": \d+', r'"\1": 1790000000', s)
        s = re.sub(r'"rating": \d+', '"rating": 1500', s)
        s = re.sub(r'"ratingDiff": -?\d+', '"ratingDiff": 0', s)
        s = re.sub(r'"(uuid|player_id|avatar|name|country|title|status|flair|patron|tcn)": "[^"]*"', r'"\1": ""', s)
        return s


def _check_clean(texts: dict[str, str]) -> None:
    from tests.contract import test_fixtures_clean as clean

    for name, text in texts.items():
        stripped = clean.PLACEHOLDERS.sub("", text)
        for p in clean.SECRET_PATTERNS:
            assert not p.search(stripped), f"{name} still matches {p.pattern}"
        for p in (
            clean.GAME_URL,
            clean.PROFILE_URL,
            clean.CHESSCOM_GAME_URL,
            clean.CHESSCOM_PLAYER_API,
            clean.PGN_PLAYER,
        ):
            assert not p.search(text), f"{name} still identifies someone ({p.pattern})"
        assert not clean.GAME_PLAYER_FIELD.search(text), f"{name} still names someone"


def test_lichess_game_export_shapes(request: pytest.FixtureRequest) -> None:
    from weaksquare.adapters.http import HttpClient
    from weaksquare.adapters.lichess_games import LichessGames
    from weaksquare.core.games import Skip, parse_lichess_game, parse_single_pgn

    token = _token()
    http = HttpClient()
    try:
        account = http.get_json("https://lichess.org/api/account", token=token)
        you = account["username"]
        client = LichessGames(http)
        listed = list(client.user_games(token, you, since_ms=None, max_games=1))
        if not listed:
            pytest.skip("the test account has no finished games")
        exported = client.export_game(None, listed[0]["id"])
    finally:
        http.close()
    for data in (listed[0], exported):
        try:
            rec = parse_lichess_game(data)
        except Skip:
            pytest.skip("the newest game is a variant")
        parse_single_pgn(rec.pgn)
        assert rec.source_game_id == listed[0]["id"][:8]
    if request.config.getoption("--record-games"):
        anon = Anonymizer(you)
        players = listed[0].get("players", {})
        for color in ("white", "black"):
            user = (players.get(color) or {}).get("user") or {}
            anon.name(user.get("name"))
            anon.name(user.get("id"))
        anon.game_id(listed[0]["id"], lichess=True)
        texts = {
            "recorded_user_games.ndjson": anon.text(json.dumps(listed[0])) + "\n",
            "recorded_export_game.json": anon.text(json.dumps(exported, indent=2)) + "\n",
        }
        _check_clean(texts)
        out = FIX / "lichess_games"
        for name, text in texts.items():
            (out / name).write_text(text, encoding="utf-8")


def test_chesscom_archive_shapes(request: pytest.FixtureRequest) -> None:
    from weaksquare.adapters.chesscom import ChesscomGames
    from weaksquare.adapters.http import HttpClient
    from weaksquare.core.chesscom import game_id_from_url, months_to_fetch, parse_archive_game
    from weaksquare.core.games import Skip, parse_single_pgn

    you = request.config.getoption("--chesscom-user")
    if not you:
        pytest.skip("pass --chesscom-user <your chess.com username> to check chess.com")
    http = HttpClient()
    try:
        client = ChesscomGames(http)
        profile = client.profile(you)
        archives = client.archives(you)
        if not archives:
            pytest.skip("no chess.com archives")
        newest = months_to_fetch(archives, None, None)[0]
        month = client.archive(newest, None)
        raw_profile = http.get_json(f"https://api.chess.com/pub/player/{you.lower()}")
        raw_archives = http.get_json(f"https://api.chess.com/pub/player/{you.lower()}/games/archives")
    finally:
        http.close()
    assert profile.username.lower() == you.lower() and month.status == 200
    games: list[dict[str, Any]] = []
    for g in month.games:
        try:
            parse_single_pgn(parse_archive_game(g).pgn)
            games.append(g)
        except Skip:
            continue
    assert games, "the newest month has no standard games"
    if request.config.getoption("--record-games"):
        anon = Anonymizer(you)
        g = games[-1]
        anon.name((g.get("white") or {}).get("username"))
        anon.name((g.get("black") or {}).get("username"))
        anon.game_id(game_id_from_url(g["url"]) or "", lichess=False)
        texts = {
            "recorded_profile.json": anon.text(
                json.dumps({k: raw_profile.get(k) for k in ("@id", "url", "username", "joined")}, indent=2)
            )
            + "\n",
            "recorded_archives.json": anon.text(json.dumps({"archives": raw_archives["archives"][-2:]}, indent=2))
            + "\n",
            "recorded_archive.json": anon.text(json.dumps({"games": [g]}, indent=2)) + "\n",
        }
        _check_clean(texts)
        out = FIX / "chesscom"
        for name, text in texts.items():
            (out / name).write_text(text, encoding="utf-8")
