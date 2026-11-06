"""The opening book and its lines (v0.13, REQUIREMENTS §18.1): import, browse, line selection, extension past
the book, and the engine for the Learn board.

**Reading a line never runs the engine.** `lines` extends only from stored results, so opening a screen is
instant and always gives the same line. `start_extend` is the background job that fills the store, on the
background engine, so it doesn't hold up the position you're looking at (FR-12.3).
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import chess

from weaksquare.core.clock import Clock
from weaksquare.core.engine import EngineLine, EngineNotInstalled, validate_fen
from weaksquare.core.errors import NotFoundError, ValidationError
from weaksquare.core.openings import (
    SOURCE_ENGINE,
    SOURCE_EXPLORER,
    BookIndex,
    BookLine,
    Family,
    Line,
    OpeningScope,
    board_of,
    build_index,
    extend_line,
    families,
    parse_line,
    position_key,
    root_of,
    rows_of_tsv,
    select_lines,
    validate_scope,
)
from weaksquare.jobs.runner import CancelToken, JobFailed, JobRunner, ProgressFn
from weaksquare.services.opening_sources import OpeningSources

BOOK_FILES = ("a.tsv", "b.tsv", "c.tsv", "d.tsv", "e.tsv")
BOOK_VERSION_KEY = "openings.book_version"
SCOPE_KEY = "openings.scope"  # FR-12.7a
EXTEND_KEY = "openings.extend"  # FR-12.13, default on
MULTIPV = 3
MIN_POPULAR_GAMES = 10  # fewer than this isn't a popular move, it's a few people's game
IMPORT_JOB, EXTEND_JOB = "opening_book_import", "opening_extend"


class Book(Protocol):
    def count(self) -> int: ...

    def replace(self, lines: list[BookLine]) -> None: ...

    def lines(self) -> list[BookLine]: ...


class EngineCache(Protocol):
    def get(self, position_key: str, think_ms: int, multipv: int, engine: str) -> list[EngineLine] | None: ...

    def put(
        self, position_key: str, think_ms: int, multipv: int, engine: str, lines: list[EngineLine], created_at: str
    ) -> None: ...


class Engine(Protocol):
    def status(self) -> Any: ...

    def settings(self) -> Any: ...

    def engine_id(self) -> str: ...

    def ticket(self, key: Any) -> int: ...

    def analyse_background(self, board: chess.Board, think_s: float, multipv: int = ...) -> list[EngineLine]: ...

    def analyse_lines(
        self, board: chess.Board, *, multipv: int = ..., key: Any = ..., gen: int | None = ...
    ) -> list[EngineLine] | None: ...

    def analysis_of(self, board: chess.Board, lines: list[EngineLine], player: Any) -> Any: ...

    def superseded(self, fen: str) -> Any: ...


class Settings(Protocol):
    def get(self, key: str) -> Any | None: ...

    def set(self, key: str, value: Any) -> None: ...


@dataclass(frozen=True)
class BookStatus:
    ready: bool
    lines: int


@dataclass(frozen=True)
class LinesView:
    lines: tuple[Line, ...]
    extend: bool
    pending: int  # lines that could still grow if the extension job ran
    engine_ready: bool


class OpeningsService:
    def __init__(
        self, book: Book, cache: EngineCache, settings: Settings, engine: Engine, runner: JobRunner, clock: Clock,
        folder: Path, sources: OpeningSources,
    ) -> None:  # fmt: skip
        self._sources = sources
        self._book = book
        self._cache = cache
        self._settings = settings
        self._engine = engine
        self._runner = runner
        self._clock = clock
        self._folder = folder
        self._lock = threading.Lock()
        self._loaded: tuple[list[BookLine], BookIndex] | None = None
        self._import_job: str | None = None
        self._extend_jobs: dict[tuple[str, int, int], str] = {}

    # ---- the book (FR-12.1) -------------------------------------------------------------------------------

    def _bundled_version(self) -> str:
        return hashlib.sha256(b"".join((self._folder / name).read_bytes() for name in BOOK_FILES)).hexdigest()

    def status(self) -> BookStatus:
        ready = self._settings.get(BOOK_VERSION_KEY) == self._bundled_version() and self._book.count() > 0
        return BookStatus(ready, self._book.count())

    def _import(self, progress: ProgressFn) -> int:
        lines: list[BookLine] = []
        for i, name in enumerate(BOOK_FILES):
            progress(i / len(BOOK_FILES), "Reading the opening book…")
            text = (self._folder / name).read_text(encoding="utf-8")
            lines.extend(parse_line(*row) for row in rows_of_tsv(text))
        self._book.replace(lines)
        self._settings.set(BOOK_VERSION_KEY, self._bundled_version())
        with self._lock:
            self._loaded = None
        return len(lines)

    def import_now(self) -> int:
        """The import itself, for the job and for tests. A bad line raises: the book ships with the app and a
        test proves every line, so one here means the install is damaged, and the old book stays."""
        return self._import(lambda _f, _m: None)

    def start_import(self) -> str:
        with self._lock:
            job = self._import_job
            status = self._runner.status(job) if job else None
            if job is not None and status is not None and status.state == "running":
                return job

        def run(progress: ProgressFn, token: CancelToken) -> str:
            try:
                return f"Imported {self._import(progress)} opening lines."
            except ValueError as e:
                raise JobFailed("opening_book", f"The opening book couldn't be read: {e}", False) from e

        job = self._runner.submit(IMPORT_JOB, run)
        with self._lock:
            self._import_job = job
        return job

    def _data(self) -> tuple[list[BookLine], BookIndex]:
        with self._lock:
            if self._loaded is None:
                lines = self._book.lines()
                self._loaded = (lines, build_index(lines))
            return self._loaded

    # ---- browse ---------------------------------------------------------------------------------------------

    def families(self, query: object = "") -> list[Family]:
        if not isinstance(query, str):
            raise ValidationError("Search for an opening by name or ECO code.")
        q = query.strip().lower()
        found = families(self._data()[0])
        if not q:
            return found
        return [f for f in found if q in f.name.lower() or f.eco.lower().startswith(q)]

    def root(self, family: object) -> BookLine:
        if not isinstance(family, str):
            raise ValidationError("Choose an opening.")
        found = root_of(self._data()[0], family)
        if found is None:
            raise NotFoundError("That opening isn't in the book.")
        return found

    def name_of(self, key: str) -> BookLine | None:
        """The book line that ends at this position, whatever move order reached it (FR-12.1)."""
        return self._data()[1].named.get(key)

    def match_family(self, name: object) -> str | None:
        """FR-10.58: the family for an opening name from a game, such as 'Italian Game: Giuoco Piano'."""
        if not isinstance(name, str) or not name.strip():
            return None
        wanted = name.split(":", 1)[0].strip().lower()
        for f in families(self._data()[0]):
            if f.name.lower() == wanted:
                return f.name
        return None

    # ---- settings -------------------------------------------------------------------------------------------

    def scope(self) -> OpeningScope:
        saved = self._settings.get(SCOPE_KEY)
        if isinstance(saved, dict):
            try:
                return validate_scope(saved.get("preset"), saved.get("sub_lines"), saved.get("max_moves"))
            except ValidationError:
                pass
        return validate_scope("standard")

    def set_scope(self, preset: object, sub_lines: object = None, max_moves: object = None) -> OpeningScope:
        scope = validate_scope(preset, sub_lines, max_moves)
        self._settings.set(
            SCOPE_KEY, {"preset": scope.preset, "sub_lines": scope.sub_lines, "max_moves": scope.max_moves}
        )
        return scope

    def extend_setting(self) -> bool:
        return self._settings.get(EXTEND_KEY) is not False

    def set_extend(self, on: object) -> bool:
        if not isinstance(on, bool):
            raise ValidationError("Choose whether lines continue past the book.")
        self._settings.set(EXTEND_KEY, on)
        return on

    # ---- lines (FR-12.2, 12.7a, 12.13) ----------------------------------------------------------------------

    def _engine_ready(self) -> bool:
        return bool(self._engine.status().state == "ready")

    def _think_ms(self) -> int:
        return round(float(self._engine.settings().think_s) * 1000)

    def _stored(self, key: str) -> list[EngineLine] | None:
        return self._cache.get(key, self._think_ms(), MULTIPV, self._engine.engine_id())

    def _popularity(self, key: str) -> dict[str, int] | None:
        """FR-12.2: explorer games per move, from the store only: reading a screen never uses the network."""
        found = self._sources.stored_explorer(board_of(key))
        return found.popularity() if found is not None else None

    def _next_stored(self, board: chess.Board) -> tuple[str, str] | None:
        """FR-12.13: the explorer's most-played move, otherwise Stockfish's best. Stored results only."""
        popular = self._sources.most_played(self._sources.stored_explorer(board), MIN_POPULAR_GAMES)
        if popular is not None:
            return popular.uci, SOURCE_EXPLORER
        lines = self._stored(position_key(board)) if self._engine_ready() else None
        if not lines or not lines[0].pv:
            return None
        return lines[0].pv[0], SOURCE_ENGINE

    def _book_lines(self, family: object, sub_lines: int, max_moves: int) -> list[Line]:
        root = self.root(family)
        return select_lines(self._data()[1], root, sub_lines, max_moves, self._popularity)

    def lines(self, family: object, scope: OpeningScope | None = None, extend: bool | None = None) -> LinesView:
        s = scope or self.scope()
        ext = self.extend_setting() if extend is None else extend
        book = self._book_lines(family, s.sub_lines, s.max_moves)
        if not ext:
            return LinesView(tuple(book), False, 0, self._engine_ready())
        lines = [extend_line(ln, s.max_moves, self._next_stored) for ln in book]
        pending = sum(1 for ln in lines if self._can_grow(ln, s.max_moves))
        return LinesView(tuple(lines), True, pending, self._engine_ready())

    @staticmethod
    def _can_grow(line: Line, max_moves: int) -> bool:
        if len(line.moves) >= max_moves * 2:
            return False
        board = chess.Board()
        for m in line.moves:
            board.push(chess.Move.from_uci(m.uci))
        return not board.is_game_over(claim_draw=False)

    def _next_computed(
        self, token: CancelToken, on_position: Callable[[], None]
    ) -> Callable[[chess.Board], tuple[str, str] | None]:
        def next_move(board: chess.Board) -> tuple[str, str] | None:
            token.raise_if_cancelled()
            popular = self._sources.most_played(self._sources.fetch_explorer(board), MIN_POPULAR_GAMES)
            if popular is not None:
                return popular.uci, SOURCE_EXPLORER
            if not self._engine_ready():
                return None
            key = position_key(board)
            lines = self._stored(key)
            if lines is None:
                lines = self._engine.analyse_background(board, float(self._engine.settings().think_s), MULTIPV)
                self._cache.put(
                    key, self._think_ms(), MULTIPV, self._engine.engine_id(), lines, self._clock.now().isoformat()
                )
                on_position()
            if not lines or not lines[0].pv:
                return None
            return lines[0].pv[0], SOURCE_ENGINE

        return next_move

    def extend_now(self, lines: Iterable[Line], max_moves: int, token: CancelToken, progress: ProgressFn) -> int:
        """Fill the store for these lines. Finished positions stay stored if it's cancelled. Returns how many
        positions it analyzed."""
        done = [0]

        def counted() -> None:
            done[0] += 1
            progress(None, f"Stockfish has looked at {done[0]} positions…")

        next_move = self._next_computed(token, counted)
        for line in lines:
            board = chess.Board()
            for m in line.moves:  # the book's own positions too: their popularity ranks its lines (FR-12.2)
                token.raise_if_cancelled()
                self._sources.fetch_explorer(board)
                board.push(chess.Move.from_uci(m.uci))
            extend_line(line, max_moves, next_move)
        return done[0]

    def start_extend(self, family: object, scope: OpeningScope | None = None) -> str | None:
        """Grow the lines past the book with Stockfish. None when there's nothing to do."""
        s = scope or self.scope()
        if not self._engine_ready() and not self._sources.signed_in():
            raise EngineNotInstalled("Install Stockfish to continue lines past the book.")
        book = self._book_lines(family, s.sub_lines, s.max_moves)
        key = (str(family), s.sub_lines, s.max_moves)
        with self._lock:
            running = self._extend_jobs.get(key)
            status = self._runner.status(running) if running else None
            if running is not None and status is not None and status.state == "running":
                return running
        if not any(self._can_grow(extend_line(ln, s.max_moves, self._next_stored), s.max_moves) for ln in book):
            return None

        def run(progress: ProgressFn, token: CancelToken) -> str:
            n = self.extend_now(book, s.max_moves, token, progress)
            return f"Stockfish continued the lines ({n} positions)."

        job = self._runner.submit(EXTEND_JOB, run)
        with self._lock:
            self._extend_jobs[key] = job
        return job

    # ---- the Learn board's engine (FR-12.3) -----------------------------------------------------------------

    def analyze(self, fen: object, purpose: object, player: object) -> Any:
        """Eval and top lines on the interactive engine, from the store when it has them (FR-12.8)."""
        if purpose not in ("start", "panel", "board"):
            raise ValidationError("Unknown analysis purpose.")
        if player not in ("white", "black"):
            raise ValidationError("Choose a side.")
        board = validate_fen(fen)
        if not self._engine_ready():
            raise EngineNotInstalled("Install Stockfish to analyze positions.")
        key = position_key(board)
        stored = self._stored(key)
        if stored is not None:
            return self._engine.analysis_of(board, stored, player)
        ticket_key = ("openings", purpose)
        lines = self._engine.analyse_lines(board, multipv=MULTIPV, key=ticket_key, gen=self._engine.ticket(ticket_key))
        if lines is None:
            return self._engine.superseded(board.fen())
        if lines:
            self._cache.put(
                key, self._think_ms(), MULTIPV, self._engine.engine_id(), lines, self._clock.now().isoformat()
            )
        return self._engine.analysis_of(board, lines, player)
