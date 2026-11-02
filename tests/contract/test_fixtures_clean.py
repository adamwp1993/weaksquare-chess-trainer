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
