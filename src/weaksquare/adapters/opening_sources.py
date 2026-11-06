"""The opening trainer's two outside sources, through `adapters/http.py` (v0.13, FR-12.2, 12.15).

The explorer needs a Lichess token and is used only when you're signed in. Wikibooks needs nothing, and gets
only a page title, which is a line's moves. Both go one request at a time, because the jobs that call them run
one position after another."""

from __future__ import annotations

from typing import Any

from weaksquare.adapters.http import HttpClient
from weaksquare.core.opening_sources import EXPLORER_SPEEDS, MAX_MOVES

EXPLORER_BASE = "https://explorer.lichess.org"
WIKIBOOKS_API = "https://en.wikibooks.org/w/api.php"


class LichessExplorer:
    def __init__(self, http: HttpClient, base: str = EXPLORER_BASE) -> None:
        self._http = http
        self._base = base

    def fetch(self, token: str, source: str, fen: str, ratings: tuple[int, ...]) -> Any:
        params: dict[str, Any] = {"fen": fen, "moves": MAX_MOVES, "topGames": 0}
        if source == "lichess":
            params |= {"ratings": ",".join(str(r) for r in ratings), "speeds": EXPLORER_SPEEDS, "recentGames": 0}
        return self._http.get_json(f"{self._base}/{source}", token=token, params=params, retry=False)


class WikibooksClient:
    def __init__(self, http: HttpClient, url: str = WIKIBOOKS_API) -> None:
        self._http = http
        self._url = url

    def fetch(self, title: str) -> Any:
        params = {
            "action": "query",
            "prop": "extracts|revisions",
            "explaintext": 1,
            "rvprop": "ids",
            "format": "json",
            "formatversion": 2,
            "titles": title,
        }
        return self._http.get_json(self._url, params=params, retry=False)
