"""Repositories for user.db: settings, sessions and the append-only attempts log."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from weaksquare.adapters.db.connection import Database
from weaksquare.core.modes.base import AttemptResult
from weaksquare.core.puzzle import PuzzleRef


@dataclass(frozen=True)
class Tally:
    solved: int
    failed: int


class SettingsRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, key: str) -> Any | None:
        with self._db.session() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return json.loads(row["value"]) if row else None

    def set(self, key: str, value: Any) -> None:
        with self._db.session() as conn:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value)),
            )


class SessionsRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(self, started_at: str, mode: str, filters: dict[str, Any], queue_size: int | None) -> int:
        with self._db.session() as conn:
            cur = conn.execute(
                "INSERT INTO sessions (started_at, mode, filters_json, queue_size) VALUES (?, ?, ?, ?)",
                (started_at, mode, json.dumps(filters), queue_size),
            )
            return int(cur.lastrowid or 0)


class AttemptsRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def append(
        self,
        ref: PuzzleRef,
        session_id: int,
        mode: str,
        started_at: str,
        finished_at: str,
        result: AttemptResult,
        puzzle_rating: int | None = None,
    ) -> int:
        with self._db.session() as conn:
            cur = conn.execute(
                "INSERT INTO attempts (puzzle_source, puzzle_id, session_id, mode, started_at, finished_at, win,"
                " help_used, first_move_correct, line_correct, time_ms, puzzle_rating)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (ref.source, ref.id, session_id, mode, started_at, finished_at, int(result.win), result.help_used,
                 int(result.first_move_correct), int(result.line_correct), result.time_ms, puzzle_rating),
            )  # fmt: skip
            return int(cur.lastrowid or 0)

    def backfill_puzzle_ratings(self) -> int:
        """Fill `puzzle_rating` on attempts recorded before v0.2, from puzzles.db where the puzzle still
        exists. Idempotent and cheap (only rows still missing it); returns how many were filled."""
        with self._db.session() as conn:
            attached = conn.execute("SELECT 1 FROM pragma_database_list WHERE name = 'pz'").fetchone()
            if not attached:
                return 0
            cur = conn.execute(
                "UPDATE attempts SET puzzle_rating = (SELECT p.rating FROM pz.puzzles p WHERE p.id = attempts.puzzle_id)"
                " WHERE puzzle_rating IS NULL AND puzzle_source = 'lichess'"
                " AND EXISTS (SELECT 1 FROM pz.puzzles p WHERE p.id = attempts.puzzle_id)"
            )
            return cur.rowcount

    def _tally(self, where: str, params: tuple[Any, ...]) -> Tally:
        with self._db.session() as conn:
            row = conn.execute(
                f"SELECT COALESCE(SUM(win), 0), COALESCE(SUM(1 - win), 0) FROM attempts WHERE {where}", params
            ).fetchone()
        return Tally(int(row[0]), int(row[1]))

    def session_tally(self, session_id: int) -> Tally:
        return self._tally("session_id = ?", (session_id,))

    def all_time_tally(self) -> Tally:
        return self._tally("1", ())
