"""Builds a fresh puzzles.new.db (FR-2.3). The live puzzles.db is never opened for writing.

Bulk-load tuned: journal off and synchronous off while loading (the file is thrown away if anything
fails), indexes built after the load, then a row-count and integrity check before it's handed over.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from weaksquare.adapters.db.connection import readonly_uri
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
    new_count: int | None = None  # puzzle IDs not in the previous database (None: nothing to compare)
    removed_count: int | None = None  # puzzle IDs the previous database had and this one doesn't


def opening_tags(raw: str) -> tuple[str | None, str | None]:
    """(family, variation) from a Lichess OpeningTags value. The first tag is the family and the
    second, when present, its variation (e.g. `Sicilian_Defense Sicilian_Defense_Najdorf_Variation`)."""
    tags = raw.split()
    return (tags[0] if tags else None, tags[1] if len(tags) > 1 else None)


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
        self._openings: dict[str, int] = {}
        self._opening_family: dict[int, int | None] = {}
        self._opening_counts: dict[int, int] = {}
        self.rows_written = 0

    def open(self) -> None:
        self.discard()
        migrate(self.path, MIGRATIONS_DIR / "puzzles", self._clock)
        conn = sqlite3.connect(self.path, isolation_level=None, uri=True)  # uri: ATTACH the old DB read-only
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

    def _opening(self, tag: str | None, family: int | None) -> int | None:
        if tag is None:
            return None
        oid = self._openings.get(tag)
        if oid is None:
            oid = self._openings[tag] = len(self._openings) + 1
            self._opening_family[oid] = family
        self._opening_counts[oid] = self._opening_counts.get(oid, 0) + 1
        return oid

    def add(self, rows: list[PuzzleRow]) -> None:
        assert self._conn is not None
        values = []
        for r in rows:
            for t in r.themes:
                self._bit(t)
                self._counts[t] = self._counts.get(t, 0) + 1
            t0, t1, t2 = theme_masks(r.themes, self._bits)
            family_tag, variation_tag = opening_tags(r.opening_tags)
            family = self._opening(family_tag, None)
            variation = self._opening(variation_tag, family)
            values.append(
                (
                    r.id, r.fen, r.moves, r.rating, r.rating_dev, r.popularity, r.nb_plays, " ".join(r.themes),
                    r.game_url, r.opening_tags, r.length, 0 if r.player_color == "white" else 1, t0, t1, t2,
                    family, variation,
                )
            )  # fmt: skip
        self._conn.execute("BEGIN")
        self._conn.executemany(
            "INSERT INTO puzzles (id, fen, moves, rating, rating_dev, popularity, nb_plays, themes, game_url,"
            " opening_tags, length, player_color, t0, t1, t2, opening_family, opening_variation)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            values,
        )
        self._conn.execute("COMMIT")
        self.rows_written += len(values)

    def finish(self, meta: dict[str, str], previous: Path | None = None) -> ImportSummary:
        """Indexes, metadata, ANALYZE, then the row-count and integrity checks. With `previous` (the
        database this one replaces), also counts the puzzle IDs that are new and removed (FR-2.5)."""
        conn = self._conn
        assert conn is not None
        conn.execute("BEGIN")
        conn.executemany(
            "INSERT INTO theme_bits (theme, bit, count) VALUES (?, ?, ?)",
            [(t, b, self._counts.get(t, 0)) for t, b in self._bits.items()],
        )
        conn.executemany(
            "INSERT INTO openings (id, tag, family_id, count) VALUES (?, ?, ?, ?)",
            [(i, t, self._opening_family[i], self._opening_counts.get(i, 0)) for t, i in self._openings.items()],
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
        new_count = removed_count = None
        if previous is not None and previous.is_file():
            new_count, removed_count = _compare_ids(conn, previous)
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
        return ImportSummary(count, len(self._bits), int(rmin), int(rmax), new_count, removed_count)

    def discard(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        for suffix in ("", "-journal", "-wal", "-shm"):
            Path(str(self.path) + suffix).unlink(missing_ok=True)


def _compare_ids(conn: sqlite3.Connection, previous: Path) -> tuple[int, int] | tuple[None, None]:
    """(new, removed) puzzle IDs against the database being replaced. Both sides have a unique index
    on `id`, so this is two index-driven scans (a few seconds on the full export)."""
    try:
        conn.execute("ATTACH DATABASE ? AS old", (readonly_uri(previous),))
    except sqlite3.Error:
        log.warning("couldn't open the previous puzzle database to compare puzzle IDs", exc_info=True)
        return None, None
    try:
        new = conn.execute("SELECT COUNT(*) FROM puzzles WHERE id NOT IN (SELECT id FROM old.puzzles)").fetchone()[0]
        removed = conn.execute(
            "SELECT COUNT(*) FROM old.puzzles WHERE id NOT IN (SELECT id FROM main.puzzles)"
        ).fetchone()[0]
        return int(new), int(removed)
    except sqlite3.Error:
        log.warning("couldn't compare puzzle IDs with the previous database", exc_info=True)
        return None, None
    finally:
        conn.execute("DETACH DATABASE old")


class ExistingPuzzleDb:
    """Reads the rows of an existing puzzles.db as if they were the Lichess CSV (header first), so an
    older-schema database is rebuilt through exactly the same import path, with no download (v0.2)."""

    HEADER = ("PuzzleId", "FEN", "Moves", "Rating", "RatingDeviation", "Popularity", "NbPlays", "Themes",
              "GameUrl", "OpeningTags")  # fmt: skip
    _BATCH = 10_000

    def __init__(self, path: Path) -> None:
        self.path = path
        self._done = 0
        self._total = 1

    def fraction(self) -> float:
        return min(self._done / self._total, 1.0)

    @contextmanager
    def rows(self) -> Iterator[Iterator[list[str]]]:
        conn = sqlite3.connect(readonly_uri(self.path), uri=True)
        try:
            self._total = max(int(conn.execute("SELECT MAX(n) FROM puzzles").fetchone()[0] or 0), 1)
            yield self._iter(conn)
        finally:
            conn.close()

    def _iter(self, conn: sqlite3.Connection) -> Iterator[list[str]]:
        yield list(self.HEADER)
        last = 0
        while True:
            batch = conn.execute(
                "SELECT n, id, fen, moves, rating, rating_dev, popularity, nb_plays, themes, game_url, opening_tags"
                " FROM puzzles WHERE n > ? ORDER BY n LIMIT ?",
                (last, self._BATCH),
            ).fetchall()
            if not batch:
                return
            for n, *cols in batch:
                last = self._done = n
                yield [str(c) for c in cols]
