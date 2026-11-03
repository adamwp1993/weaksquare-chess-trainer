"""Reads the attempts log for Stats (FR-9.1, 9.2), joined to puzzles.db with a left join so attempts on
puzzles a newer export dropped still count (FR-2.4)."""

from __future__ import annotations

from weaksquare.adapters.db.connection import Database
from weaksquare.core.stats import AttemptRow


class StatsRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def attempt_rows(self) -> list[AttemptRow]:
        with self._db.session() as conn:
            attached = conn.execute("SELECT 1 FROM pragma_database_list WHERE name = 'pz'").fetchone()
            if attached:
                rows = conn.execute(
                    "SELECT a.win, a.first_move_correct, a.line_correct, a.puzzle_rating, p.themes, p.length, a.mode"
                    " FROM attempts a LEFT JOIN pz.puzzles p"
                    " ON a.puzzle_source = 'lichess' AND p.id = a.puzzle_id"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT win, first_move_correct, line_correct, puzzle_rating, NULL AS themes, NULL AS length, mode"
                    " FROM attempts"
                ).fetchall()
        return [
            AttemptRow(
                win=bool(r[0]),
                first_move_correct=bool(r[1]),
                line_correct=bool(r[2]),
                puzzle_rating=r[3],
                themes=None if r[4] is None else tuple(r[4].split()),
                length=r[5],
                mode=r[6],
            )
            for r in rows
        ]
