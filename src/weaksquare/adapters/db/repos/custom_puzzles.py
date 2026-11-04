"""user.db repository for your own puzzles (v0.8, FR-3.15): `custom_puzzles`, saved from Game Review
(origin manual, FR-11.16) or imported from a file (origin import, FR-10.46). Their attempts use the
`my:` puzzle source (ARCHITECTURE §3 decision 3)."""

from __future__ import annotations

import sqlite3

from weaksquare.adapters.db.connection import Database
from weaksquare.core.puzzle import NewCustomPuzzle

_INSERT = (
    "INSERT INTO custom_puzzles (game_id, ply, fen, solution_uci, length, player_color, origin, set_label, name,"
    " strict, kind, severity, cp_loss, phase, time_class, game_date, created_at)"
    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
)


def _values(p: NewCustomPuzzle, created_at: str) -> tuple[object, ...]:
    return (
        p.game_id, p.ply, p.fen, " ".join(p.solution), p.length, p.player_color, p.origin, p.set_label, p.name,
        int(p.strict), p.kind, p.severity, p.cp_loss, p.phase, p.time_class, p.game_date, created_at,
    )  # fmt: skip


class CustomPuzzlesRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, p: NewCustomPuzzle, created_at: str) -> tuple[int, bool]:
        """(id, created). The unique indexes make a repeat (same game and ply, or the same imported set
        entry) return the existing puzzle instead of a second copy."""
        with self._db.transaction() as conn:
            try:
                cur = conn.execute(_INSERT, _values(p, created_at))
                return int(cur.lastrowid or 0), True
            except sqlite3.IntegrityError:
                if p.game_id is not None:
                    row = conn.execute(
                        "SELECT id FROM custom_puzzles WHERE game_id = ? AND ply = ?", (p.game_id, p.ply)
                    ).fetchone()
                else:
                    row = conn.execute(
                        "SELECT id FROM custom_puzzles WHERE origin = 'import' AND set_label IS ? AND fen = ?"
                        " AND solution_uci = ?",
                        (p.set_label, p.fen, " ".join(p.solution)),
                    ).fetchone()
                if row is None:
                    raise
                return int(row[0]), False

    def add_many(self, items: list[NewCustomPuzzle], created_at: str) -> int:
        """Insert a batch of imported puzzles in one transaction; duplicates are skipped. Returns how many
        were new."""
        added = 0
        with self._db.transaction() as conn:
            for p in items:
                cur = conn.execute(_INSERT.replace("INSERT INTO", "INSERT OR IGNORE INTO"), _values(p, created_at))
                added += cur.rowcount
        return added

    def saved_plies(self, game_id: int) -> set[int]:
        with self._db.session() as conn:
            rows = conn.execute("SELECT ply FROM custom_puzzles WHERE game_id = ?", (game_id,)).fetchall()
        return {int(r[0]) for r in rows if r[0] is not None}

    def sets(self) -> list[tuple[str, int]]:
        """Imported set labels with their active puzzle counts, by label."""
        with self._db.session() as conn:
            rows = conn.execute(
                "SELECT set_label, COUNT(*) FROM custom_puzzles WHERE origin = 'import' AND status = 'active'"
                " AND set_label IS NOT NULL GROUP BY set_label ORDER BY set_label"
            ).fetchall()
        return [(str(r[0]), int(r[1])) for r in rows]


class RetryRepo:
    """Retry-mode results (FR-11.15): local only."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, game_id: int, ply: int, played_uci: str, found: bool, cp_loss: int | None, created_at: str) -> int:
        with self._db.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO retry_attempts (game_id, ply, played_uci, found, cp_loss, created_at) VALUES (?,?,?,?,?,?)",
                (game_id, ply, played_uci, int(found), cp_loss, created_at),
            )
            return int(cur.lastrowid or 0)

    def get(self, retry_id: int) -> tuple[int, int, bool] | None:
        with self._db.session() as conn:
            r = conn.execute("SELECT game_id, ply, found FROM retry_attempts WHERE id = ?", (retry_id,)).fetchone()
        return (int(r[0]), int(r[1]), bool(r[2])) if r else None

    def totals(self) -> tuple[int, int]:
        """(found, tried) over every retry."""
        with self._db.session() as conn:
            r = conn.execute("SELECT COALESCE(SUM(found), 0), COUNT(*) FROM retry_attempts").fetchone()
        return int(r[0]), int(r[1])
