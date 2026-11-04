"""`LichessGamesClient` over the shared HTTP client (v0.8, FR-11.3, FR-11.23, FR-11.27).

Your own games are exported with your token, which Lichess serves fastest (60 games/s). A single game
by URL works without a token (it's public). Metadata and PGNs only: Lichess's own evals come along
(`evals=true`) just to show the *Analyzed on Lichess* badge; grading is always local (Adam, v0.8).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from weaksquare.adapters.http import HttpClient, HttpError
from weaksquare.core.games import valid_username

BASE = "https://lichess.org"
FLAGS = {"pgnInJson": "true", "clocks": "true", "evals": "true", "accuracy": "true", "opening": "true"}


class LichessGames:
    def __init__(self, http: HttpClient, base: str = BASE) -> None:
        self._http = http
        self._base = base

    def user_games(
        self, token: str | None, username: str, *, since_ms: int | None, max_games: int
    ) -> Iterator[dict[str, Any]]:
        """Newest first, as ndjson. `since_ms` is the last sync time (FR-11.27)."""
        if not valid_username(username):
            raise ValueError("not a Lichess username")
        params: dict[str, Any] = {**FLAGS, "division": "true", "max": max(1, int(max_games)), "finished": "true"}
        if since_ms:
            params["since"] = int(since_ms)
        yield from self._http.stream_ndjson(f"{self._base}/api/games/user/{username}", token=token, params=params)

    def export_game(self, token: str | None, game_id: str) -> dict[str, Any]:
        if not (len(game_id) == 8 and game_id.isalnum()):
            raise ValueError("not a Lichess game id")
        data = self._http.get_json(
            f"{self._base}/game/export/{game_id}", token=token, params={**FLAGS, "division": "true"}
        )
        if not isinstance(data, dict):
            raise HttpError("Lichess returned an unexpected game response", retryable=False)
        return data
