"""Reads the attempts log for Stats (FR-9.1, 9.2, 9.3, 9.7), joined to puzzles.db with a left join so attempts on
puzzles a newer export dropped still count (FR-2.4). Each row carries its latest mistake reason (§7.3)."""

from __future__ import annotations

from datetime import UTC, datetime

from weaksquare.adapters.db.connection import Database
from weaksquare.adapters.db.repos.user_data import LATEST_REASON
from weaksquare.core.stats import AttemptRow

_COLUMNS = (
    "a.win, a.first_move_correct, a.line_correct, a.puzzle_rating, {themes}, {length}, a.mode,"
    f" {LATEST_REASON}, a.finished_at, a.replies_correct, a.replies_total, a.idea_found, a.idea_total,"
    " a.idea_extra, a.danger_safe"
)


def _time(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        t = datetime.fromisoformat(text)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


class StatsRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def attempt_rows(self) -> list[AttemptRow]:
        with self._db.session() as conn:
            attached = conn.execute("SELECT 1 FROM pragma_database_list WHERE name = 'pz'").fetchone()
            if attached:
                cols = _COLUMNS.format(themes="COALESCE(p.themes, c.themes)", length="COALESCE(p.length, c.length)")
                rows = conn.execute(
                    f"SELECT {cols} FROM attempts a LEFT JOIN pz.puzzles p"
                    " ON a.puzzle_source = 'lichess' AND p.id = a.puzzle_id"
                    " LEFT JOIN custom_puzzles c ON a.puzzle_source = 'my' AND c.id = CAST(a.puzzle_id AS INTEGER)"
                ).fetchall()
            else:
                cols = _COLUMNS.format(themes="c.themes", length="c.length")
                rows = conn.execute(
                    f"SELECT {cols} FROM attempts a"
                    " LEFT JOIN custom_puzzles c ON a.puzzle_source = 'my' AND c.id = CAST(a.puzzle_id AS INTEGER)"
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
                reason=r[7],
                finished_at=_time(r[8]),
                replies_correct=r[9],
                replies_total=r[10],
                idea_found=r[11],
                idea_total=r[12],
                idea_extra=r[13],
                danger_safe=None if r[14] is None else bool(r[14]),
            )
            for r in rows
        ]
