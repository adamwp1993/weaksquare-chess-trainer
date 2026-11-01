"""Reads puzzles.db metadata and theme counts through the attached `pz` schema."""

from __future__ import annotations

import sqlite3

from weaksquare.adapters.db.connection import Database


class PuzzleMetaRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def read(self) -> dict[str, str] | None:
        """The `meta` table of puzzles.db, or None if no database has been imported."""
        if not self._db.puzzles_db_path.exists():
            return None
        try:
            with self._db.session() as conn:
                rows = conn.execute("SELECT key, value FROM pz.meta").fetchall()
        except sqlite3.OperationalError:  # not attached (file appeared after this thread connected)
            return None
        return {r["key"]: r["value"] for r in rows} or None

    def theme_counts(self) -> dict[str, int]:
        with self._db.session() as conn:
            return {r["theme"]: r["count"] for r in conn.execute("SELECT theme, count FROM pz.theme_bits")}
