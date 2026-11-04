"""Fake game clients (v0.8): scriptable stand-ins for `LichessGames` and `ChesscomGames`, fed from the
anonymized fixtures by default. `FakeChesscom` asserts the serial rule: two calls in flight at once fail."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from weaksquare.adapters.chesscom import ChesscomNotFound
from weaksquare.adapters.http import HttpError
from weaksquare.core.games import Archive, ChesscomProfile

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "http"
CC_BASE = "https://api.chess.com/pub/player/player_a/games/"


def lichess_fixture_games() -> list[dict[str, Any]]:
    text = (FIXTURES / "lichess_games" / "user_games.ndjson").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def chesscom_fixture_month(name: str) -> list[dict[str, Any]]:
    data = json.loads((FIXTURES / "chesscom" / f"archive_{name}.json").read_text(encoding="utf-8"))
    return list(data["games"])


@dataclass
class FakeLichessGames:
    games: list[dict[str, Any]] = field(default_factory=lichess_fixture_games)
    calls: list[dict[str, Any]] = field(default_factory=list)
    error: Exception | None = None

    def user_games(
        self, token: str | None, username: str, *, since_ms: int | None, max_games: int
    ) -> Iterator[dict[str, Any]]:
        self.calls.append({"token": token, "username": username, "since_ms": since_ms, "max": max_games})
        if self.error:
            raise self.error
        newest = sorted(self.games, key=lambda g: -int(g.get("createdAt", 0)))
        yield from [g for g in newest if not since_ms or int(g.get("createdAt", 0)) > since_ms][:max_games]

    def export_game(self, token: str | None, game_id: str) -> dict[str, Any]:
        self.calls.append({"export": game_id, "token": token})
        for g in self.games:
            if g.get("id") == game_id:
                return g
        raise HttpError("HTTP 404", status=404, retryable=False)


@dataclass
class FakeChesscom:
    usernames: set[str] = field(default_factory=lambda: {"player_a"})
    months: dict[str, list[dict[str, Any]]] = field(
        default_factory=lambda: {
            CC_BASE + "2026/08": chesscom_fixture_month("2026_08"),
            CC_BASE + "2026/09": chesscom_fixture_month("2026_09"),
        }
    )
    calls: list[tuple[str, str | None]] = field(default_factory=list)
    delay_s: float = 0.0
    _in_flight: int = 0
    _guard: threading.Lock = field(default_factory=threading.Lock)

    def _enter(self, what: str, etag: str | None = None) -> None:
        with self._guard:
            self._in_flight += 1
            overlap = self._in_flight > 1
            self.calls.append((what, etag))
        if overlap:
            raise AssertionError("two chess.com requests were in flight at once (FR-10.7)")
        if self.delay_s:
            time.sleep(self.delay_s)

    def _leave(self) -> None:
        with self._guard:
            self._in_flight -= 1

    def profile(self, username: str) -> ChesscomProfile:
        self._enter(f"profile:{username}")
        try:
            if username.lower() not in self.usernames:
                raise ChesscomNotFound("HTTP 404", status=404, retryable=False)
            return ChesscomProfile(username, None, f"https://www.chess.com/member/{username}", None, 1600000000)
        finally:
            self._leave()

    def archives(self, username: str) -> list[str]:
        self._enter(f"archives:{username}")
        try:
            return sorted(self.months)
        finally:
            self._leave()

    def archive(self, url: str, etag: str | None) -> Archive:
        self._enter(url, etag)
        try:
            games = self.months.get(url, [])
            tag = f'"{len(json.dumps(games))}"'
            if etag == tag:
                return Archive(304, [], etag)
            return Archive(200, games, tag)
        finally:
            self._leave()
