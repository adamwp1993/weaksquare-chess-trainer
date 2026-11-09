"""The Analysis tab (v0.15, REQUIREMENTS §20): set up a position, import a PGN, explore with the engine and popular
replies.

**Nothing counts here (FR-14.5).** This service holds no repository: it can't touch puzzles, stats, your game
library or Coach reports, and it has no LLM dependency (a test checks the import graph). The engine is the
**interactive** one (ARCHITECTURE §3 decision 12). Your lines live only in the page, for as long as the app is open
(Adam, v0.15 planning). Popular replies go through `OpeningSources`, so they share the opening trainer's cache and
are skipped when you're signed out, offline or Lichess asked us to wait.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

import chess

from weaksquare.core.analysis_pgn import AnalysisGame, parse_analysis_pgn
from weaksquare.core.engine import EngineNotInstalled, validate_fen
from weaksquare.core.errors import ValidationError
from weaksquare.core.games import GameError
from weaksquare.core.opening_sources import ExplorerMove, ExplorerResult
from weaksquare.core.position_setup import PositionCheck, check_fen

PURPOSES = ("start", "panel", "board")  # the engine panel pins the start position too
MAX_REPLIES = 8


class Engine(Protocol):
    def status(self) -> Any: ...

    def ticket(self, key: Any) -> int: ...

    def analyse(self, board: chess.Board, player: Any, *, key: Any = None, gen: int | None = None) -> Any: ...


class Sources(Protocol):
    def signed_in(self) -> bool: ...

    def fetch_explorer(self, board: chess.Board) -> ExplorerResult | None: ...


@dataclass(frozen=True)
class PopularReplies:
    state: Literal["ok", "signed_out", "unavailable"]
    total: int
    moves: tuple[ExplorerMove, ...]


class AnalysisTabService:
    def __init__(self, engine: Engine, sources: Sources) -> None:
        self._engine = engine
        self._sources = sources

    @staticmethod
    def check_position(fen: object) -> PositionCheck:
        """FR-14.2: the editor's position or a pasted FEN, with a sentence per problem."""
        return check_fen(fen)

    @staticmethod
    def import_pgn(text: object) -> tuple[list[AnalysisGame], list[str]]:
        """FR-14.3: the games in a pasted PGN. Raises ValidationError with the reason (and nothing changes on the
        board) when none is usable."""
        try:
            return parse_analysis_pgn(text)
        except GameError as e:
            raise ValidationError(e.reason) from None

    def pgn_game(self, text: object, index: object) -> AnalysisGame:
        """One game of a pasted PGN, picked from `import_pgn`'s list (the text is parsed again: nothing is kept)."""
        games, _ = self.import_pgn(text)
        found = next((g for g in games if g.index == index), None)
        if found is None:
            raise ValidationError("That game isn't in the PGN.")
        return found

    def _board(self, fen: object) -> chess.Board:
        check = check_fen(fen)
        if not check.ok:
            raise ValidationError(check.problems[0])
        return validate_fen(check.fen)  # the engine's own check, again (FR-7.6)

    def analyze(self, fen: object, purpose: object = "board") -> Any:
        """FR-14.4: eval and top 3 lines, worded from White's side ("+0.3", "White mates in 2"), on the interactive
        engine. Latest request wins."""
        if purpose not in PURPOSES:
            raise ValidationError("Unknown analysis purpose.")
        board = self._board(fen)
        if self._engine.status().state != "ready":
            raise EngineNotInstalled("Install Stockfish to analyze positions.")
        key = ("analysis_tab", purpose)
        return self._engine.analyse(board, "both", key=key, gen=self._engine.ticket(key))

    def popular_replies(self, fen: object) -> PopularReplies:
        """FR-14.4: the Lichess explorer's most played moves here, or a quiet reason there are none."""
        board = self._board(fen)
        if not self._sources.signed_in():
            return PopularReplies("signed_out", 0, ())
        found = self._sources.fetch_explorer(board)
        if found is None:
            return PopularReplies("unavailable", 0, ())
        return PopularReplies("ok", found.total, found.moves[:MAX_REPLIES])
