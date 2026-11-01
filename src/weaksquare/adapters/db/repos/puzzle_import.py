"""Builds a fresh puzzles.new.db (FR-2.3). The live puzzles.db is never opened for writing.

Bulk-load tuned: journal off and synchronous off while loading (the file is thrown away if anything
fails), indexes built after the load, then a row-count and integrity check before it's handed over.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from weaksquare.adapters.db.migrate import migrate
from weaksquare.config import MIGRATIONS_DIR, PACKAGE_DIR
from weaksquare.core.clock import Clock
from weaksquare.core.csv_rows import PuzzleRow

log = logging.getLogger(__name__)

BITS_PER_COLUMN = 62  # stays clear of the sign bit, so masks are plain positive integers
THEME_COLUMNS = 3
MAX_THEMES = BITS_PER_COLUMN * THEME_COLUMNS
INDEXES_SQL = PACKAGE_DIR / "adapters" / "db" / "puzzles_indexes.sql"


class IntegrityError(RuntimeError):
    pass


@dataclass(frozen=True)
class ImportSummary:
    row_count: int
    theme_count: int
    rating_min: int
    rating_max: int


def theme_masks(themes: Iterable[str], bits: dict[str, int]) -> tuple[int, int, int]:
    masks = [0] * THEME_COLUMNS
    for t in themes:
        b = bits.get(t)
        if b is not None:
            masks[b // BITS_PER_COLUMN] |= 1 << (b % BITS_PER_COLUMN)
    return masks[0], masks[1], masks[2]


class PuzzleDbWriter:
    def __init__(self, path: Path, clock: Clock) -> None:
        self.path = path
        self._clock = clock
        self._conn: sqlite3.Connection | None = None
        self._bits: dict[str, int] = {}
        self._counts: dict[str, int] = {}
        self._dropped_themes: set[str] = set()
        self.rows_written = 0

    def open(self) -> None:
        self.discard()
        migrate(self.path, MIGRATIONS_DIR / "puzzles", self._clock)
        conn = sqlite3.connect(self.path, isolation_level=None)
        conn.execute("PRAGMA journal_mode=OFF")
        conn.execute("PRAGMA synchronous=OFF")
        conn.execute("PRAGMA cache_size=-262144")  # 256 MB
        conn.execute("PRAGMA temp_store=MEMORY")
        self._conn = conn

    def _bit(self, theme: str) -> int | None:
        b = self._bits.get(theme)
        if b is None:
            if len(self._bits) >= MAX_THEMES:
                if theme not in self._dropped_themes:
                    log.warning("more than %d themes; %r can't be filtered on", MAX_THEMES, theme)
                    self._dropped_themes.add(theme)
                return None
            b = self._bits[theme] = len(self._bits)
        return b

    def add(self, rows: list[PuzzleRow]) -> None:
        assert self._conn is not None
        values = []
        for r in rows:
            for t in r.themes:
                self._bit(t)
                self._counts[t] = self._counts.get(t, 0) + 1
            t0, t1, t2 = theme_masks(r.themes, self._bits)
            values.append(
                (
                    r.id, r.fen, r.moves, r.rating, r.rating_dev, r.popularity, r.nb_plays, " ".join(r.themes),
                    r.game_url, r.opening_tags, r.length, 0 if r.player_color == "white" else 1, t0, t1, t2,
                )
            )  # fmt: skip
        self._conn.execute("BEGIN")
        self._conn.executemany(
            "INSERT INTO puzzles (id, fen, moves, rating, rating_dev, popularity, nb_plays, themes, game_url,"
            " opening_tags, length, player_color, t0, t1, t2) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            values,
        )
        self._conn.execute("COMMIT")
        self.rows_written += len(values)

    def finish(self, meta: dict[str, str]) -> ImportSummary:
        """Indexes, metadata, ANALYZE, then the row-count and integrity checks."""
        conn = self._conn
        assert conn is not None
        conn.execute("BEGIN")
        conn.executemany(
            "INSERT INTO theme_bits (theme, bit, count) VALUES (?, ?, ?)",
            [(t, b, self._counts.get(t, 0)) for t, b in self._bits.items()],
        )
        conn.execute("COMMIT")
        dupes = conn.execute("SELECT COUNT(*) - COUNT(DISTINCT id) FROM puzzles").fetchone()[0]
        if dupes:
            log.warning("removing %d duplicate puzzle IDs", dupes)
            conn.execute("DELETE FROM puzzles WHERE n NOT IN (SELECT MIN(n) FROM puzzles GROUP BY id)")
        conn.executescript(INDEXES_SQL.read_text(encoding="utf-8"))
        count, rmin, rmax = conn.execute("SELECT COUNT(*), MIN(rating), MAX(rating) FROM puzzles").fetchone()
        if count != self.rows_written - dupes or count == 0:
            raise IntegrityError(f"row count check failed: {count} rows in the file, {self.rows_written} written")
        all_meta = {
            **meta,
            "row_count": str(count),
            "rating_min": str(rmin),
            "rating_max": str(rmax),
            "imported_at": self._clock.now().isoformat(timespec="seconds"),
        }
        conn.execute("BEGIN")
        conn.executemany("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", all_meta.items())
        conn.execute("COMMIT")
        conn.execute("ANALYZE")
        check = conn.execute("PRAGMA quick_check").fetchone()[0]
        if check != "ok":
            raise IntegrityError(f"integrity check failed: {check}")
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.close()
        self._conn = None
        return ImportSummary(count, len(self._bits), int(rmin), int(rmax))

    def discard(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        for suffix in ("", "-journal", "-wal", "-shm"):
            Path(str(self.path) + suffix).unlink(missing_ok=True)
