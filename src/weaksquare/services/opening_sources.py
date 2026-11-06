"""The explorer and Wikibooks behind a local store (v0.13, FR-12.2, 12.15).

Each has two ways in: `stored_…` never touches the network, for reading a screen, and `fetch_…` may, for a job
or a click. Being signed out, offline or rate-limited is never an error here: the answer is just "nothing",
and the trainer carries on without it (Done when: skipped cleanly). A stored answer is used for 30 days, and
after that only if a new one can't be had.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

import chess

from weaksquare.adapters.http import HttpError
from weaksquare.adapters.lichess import is_network_error, is_rate_limited, is_unauthorized
from weaksquare.core.clock import Clock
from weaksquare.core.errors import ValidationError
from weaksquare.core.opening_sources import (
    DEFAULT_RATINGS,
    ExplorerMove,
    ExplorerResult,
    WikiPage,
    parse_explorer,
    parse_extract,
    validate_explorer_settings,
)
from weaksquare.core.openings import position_key

STALE_AFTER = timedelta(days=30)
RATE_LIMIT_PAUSE = timedelta(seconds=60)  # Lichess asks for a full minute after a 429
WIKIBOOKS_KEY = "openings.use_wikibooks"  # FR-12.15, default on
EXPLORER_KEY = "openings.explorer"  # FR-12.2: source and rating bands


class Settings(Protocol):
    def get(self, key: str) -> Any | None: ...

    def set(self, key: str, value: Any) -> None: ...


class ExplorerStore(Protocol):
    def get(self, position_key: str, params: str) -> tuple[Any, str] | None: ...

    def put(self, position_key: str, params: str, body: Any, fetched_at: str) -> None: ...


class WikiStore(Protocol):
    def get(self, title: str) -> tuple[WikiPage, str] | None: ...

    def put(self, page: WikiPage, fetched_at: str) -> None: ...


class ExplorerApi(Protocol):
    def fetch(self, token: str, source: str, fen: str, ratings: tuple[int, ...]) -> Any: ...


class WikiApi(Protocol):
    def fetch(self, title: str) -> Any: ...


class Tokens(Protocol):
    def token(self) -> str | None: ...


@dataclass(frozen=True)
class ExplorerSettings:
    source: str
    ratings: tuple[int, ...]

    @property
    def params(self) -> str:
        return self.source if self.source == "masters" else f"{self.source}:{','.join(map(str, self.ratings))}"


class OpeningSources:
    def __init__(
        self, explorer: ExplorerApi, wiki: WikiApi, explorer_store: ExplorerStore, wiki_store: WikiStore,
        settings: Settings, tokens: Tokens, clock: Clock,
    ) -> None:  # fmt: skip
        self._explorer = explorer
        self._wiki = wiki
        self._explorer_store = explorer_store
        self._wiki_store = wiki_store
        self._settings = settings
        self._tokens = tokens
        self._clock = clock
        self._lock = threading.Lock()
        self._paused_until: datetime | None = None

    # ---- settings ------------------------------------------------------------------------------------------

    def signed_in(self) -> bool:
        return bool(self._tokens.token())

    def explorer_settings(self) -> ExplorerSettings:
        saved = self._settings.get(EXPLORER_KEY)
        if isinstance(saved, dict):
            try:
                return ExplorerSettings(*validate_explorer_settings(saved.get("source"), saved.get("ratings")))
            except ValidationError:
                pass
        return ExplorerSettings("lichess", DEFAULT_RATINGS)

    def set_explorer_settings(self, source: object, ratings: object) -> ExplorerSettings:
        s, r = validate_explorer_settings(source, ratings)
        self._settings.set(EXPLORER_KEY, {"source": s, "ratings": list(r)})
        return ExplorerSettings(s, r)

    def use_wikibooks(self) -> bool:
        return self._settings.get(WIKIBOOKS_KEY) is not False

    def set_use_wikibooks(self, on: object) -> bool:
        if not isinstance(on, bool):
            raise ValidationError("Choose whether to use Wikibooks.")
        self._settings.set(WIKIBOOKS_KEY, on)
        return on

    # ---- the explorer (FR-12.2) ---------------------------------------------------------------------------

    def _fresh(self, fetched_at: str) -> bool:
        try:
            return self._clock.now() - datetime.fromisoformat(fetched_at) < STALE_AFTER
        except ValueError:
            return False

    def stored_explorer(self, board: chess.Board) -> ExplorerResult | None:
        hit = self._explorer_store.get(position_key(board), self.explorer_settings().params)
        return parse_explorer(board, hit[0]) if hit is not None else None

    def _paused(self) -> bool:
        with self._lock:
            return self._paused_until is not None and self._clock.now() < self._paused_until

    def fetch_explorer(self, board: chess.Board) -> ExplorerResult | None:
        """One position, from the store if it's fresh. None when it's skipped: signed out, offline, or Lichess
        asked us to wait. A failed refresh falls back to the stored answer."""
        settings = self.explorer_settings()
        key = position_key(board)
        hit = self._explorer_store.get(key, settings.params)
        if hit is not None and self._fresh(hit[1]):
            return parse_explorer(board, hit[0])
        stale = parse_explorer(board, hit[0]) if hit is not None else None
        token = self._tokens.token()
        if not token or self._paused():
            return stale
        try:
            body = self._explorer.fetch(token, settings.source, board.fen(en_passant="legal"), settings.ratings)
        except Exception as e:
            if is_rate_limited(e):
                with self._lock:
                    self._paused_until = self._clock.now() + RATE_LIMIT_PAUSE
                return stale
            if is_network_error(e) or is_unauthorized(e) or isinstance(e, HttpError):
                return stale
            raise
        self._explorer_store.put(key, settings.params, body, self._clock.now().isoformat())
        return parse_explorer(board, body)

    @staticmethod
    def most_played(result: ExplorerResult | None, min_games: int = 1) -> ExplorerMove | None:
        if result is None or not result.moves or result.moves[0].games < min_games:
            return None
        return result.moves[0]

    # ---- Wikibooks (FR-12.15) --------------------------------------------------------------------------------

    def stored_page(self, title: str) -> WikiPage | None:
        hit = self._wiki_store.get(title)
        return hit[0] if hit is not None else None

    def fetch_page(self, title: str) -> WikiPage | None:
        """A page, from the store if it's fresh. None when the setting's off, or offline with nothing stored."""
        if not self.use_wikibooks():
            return None
        hit = self._wiki_store.get(title)
        if hit is not None and self._fresh(hit[1]):
            return hit[0]
        try:
            page = parse_extract(title, self._wiki.fetch(title))
        except Exception as e:
            if is_network_error(e) or isinstance(e, HttpError):
                return hit[0] if hit is not None else None
            raise
        if page.status == "ok" or hit is None or hit[0].status != "ok":
            self._wiki_store.put(page, self._clock.now().isoformat())
        return page
