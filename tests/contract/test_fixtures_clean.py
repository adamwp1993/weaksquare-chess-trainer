"""SR-12 / SR-12a: fixtures hold no secrets and identify no one (no real game IDs, URLs or usernames)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

SECRET_PATTERNS = [
    re.compile(r"\bli[a-z]_[A-Za-z0-9]{16,}"),
    re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{20,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9_\-.]{20,}"),
    re.compile(r"(?i)\"(access_token|code_verifier|refresh_token)\"\s*:\s*\"[^\"]{8,}\""),
]
PLACEHOLDERS = re.compile(r"(lip_FAKE|sk-ant-FAKE|sk-FAKE)\w*")
# A Lichess game URL is lichess.org/<8-char id>; only GAMEID placeholders are allowed.
GAME_URL = re.compile(r"lichess\.org/(?!GAMEID\d)([A-Za-z0-9]{8})\b")
# v0.8: chess.com game URLs use 1000000NN placeholder ids; the player API path names someone too.
CHESSCOM_GAME_URL = re.compile(r"chess\.com/(?:game/)?(?:live|daily)/(?:game/)?(?!1000000\d\d\b)\d+")
CHESSCOM_PLAYER_API = re.compile(r"api\.chess\.com/pub/player/(?!player_|opponent_)\w+")
# v0.8: PGN player tags, also inside JSON strings (escaped quotes).
PGN_PLAYER = re.compile(r'\[(?:White|Black) \\?"(?!player_|opponent_|\?\\?")')
# v0.8: player names and ids in the game APIs' JSON (an opening's "name" is fine).
GAME_PLAYER_FIELD = re.compile(
    r'"(?:username|user"\s*:\s*\{\s*"name)"\s*:\s*"(?!player_|opponent_)[^"]*"|"id"\s*:\s*"(?!player_|opponent_|GAMEID)[^"]*"'
)
PROFILE_URL = re.compile(r"(lichess\.org/@/|chess\.com/member/)(?!player_|opponent_)\w+")
# Recorded API responses (v0.3): account names must be placeholders.
USERNAME_FIELD = re.compile(r'"(username|id|name)"\s*:\s*"(?!player_|opponent_)[^"]*"')


def _is_text(p: Path) -> bool:
    data = p.read_bytes()
    if b"\0" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _files() -> list[Path]:
    """Every text file under tests/fixtures, whatever its extension (v0.2: an .html recording was
    skipped by the earlier list of extensions)."""
    return [p for p in FIXTURES.rglob("*") if p.is_file() and "__pycache__" not in p.parts and _is_text(p)]


@pytest.mark.parametrize("path", _files(), ids=lambda p: p.name)
def test_no_secrets(path: Path) -> None:
    text = PLACEHOLDERS.sub("", path.read_text(encoding="utf-8"))
    for pattern in SECRET_PATTERNS:
        assert not pattern.search(text), f"{path.name} matches {pattern.pattern}"


@pytest.mark.parametrize("path", _files(), ids=lambda p: p.name)
def test_anonymized(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert not GAME_URL.search(text), f"{path.name} contains a real Lichess game URL"
    assert not PROFILE_URL.search(text), f"{path.name} contains a real profile URL"
    assert not CHESSCOM_GAME_URL.search(text), f"{path.name} contains a real chess.com game URL"
    assert not CHESSCOM_PLAYER_API.search(text), f"{path.name} names a real chess.com player"
    assert not PGN_PLAYER.search(text), f"{path.name} has a PGN player tag that isn't a placeholder"
    if path.suffix in (".json", ".ndjson") and {"chesscom", "lichess_games"} & set(path.parts):
        m = GAME_PLAYER_FIELD.search(text)  # names player_/opponent_, game ids GAMEID placeholders
        assert m is None, f"{path.name} names someone: {m.group(0) if m else ''}"
    if path.suffix == ".json" and "lichess" in path.parts:
        # Puzzle ids are public dataset ids, so an "id" is allowed in a solve response's rounds.
        for m in USERNAME_FIELD.finditer(text):
            assert m.group(1) == "id" and '"rounds"' in text, f"{path.name} names someone: {m.group(0)}"


def test_username_checker() -> None:
    assert USERNAME_FIELD.search('{"username": "RealPerson"}')
    assert not USERNAME_FIELD.search('{"username": "player_a"}')


def test_checker_catches_a_real_url() -> None:
    assert GAME_URL.search("https://lichess.org/Xy12Ab34/black#48")  # shaped like a real ID (v0.1-B12)
    assert not GAME_URL.search("https://lichess.org/GAMEID01")


def test_v08_checkers_catch_real_chesscom_urls_names_and_pgn_tags() -> None:
    assert CHESSCOM_GAME_URL.search("https://www.chess.com/game/live/123456789")
    assert CHESSCOM_GAME_URL.search("https://www.chess.com/live/game/123456789")
    assert not CHESSCOM_GAME_URL.search("https://www.chess.com/game/live/100000001")
    assert CHESSCOM_PLAYER_API.search("https://api.chess.com/pub/player/realperson/games/2026/09")
    assert not CHESSCOM_PLAYER_API.search("https://api.chess.com/pub/player/player_a/games/2026/09")
    assert PGN_PLAYER.search('[White "RealPerson"]') and PGN_PLAYER.search('[Black \\"RealPerson\\"]')
    assert not PGN_PLAYER.search('[White "player_a"]') and not PGN_PLAYER.search('[Black "?"]')
    assert GAME_PLAYER_FIELD.search('{"user": {"name": "RealPerson"}}')
    assert GAME_PLAYER_FIELD.search('{"username": "RealPerson"}') and GAME_PLAYER_FIELD.search('{"id": "Xy12Ab34"}')
    assert not GAME_PLAYER_FIELD.search('{"opening": {"name": "Italian Game"}, "id": "GAMEID11"}')
