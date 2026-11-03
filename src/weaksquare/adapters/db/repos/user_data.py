"""Repositories for user.db: settings, sessions and the append-only attempts log."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from weaksquare.adapters.db.connection import Database
from weaksquare.core.modes.base import AttemptResult
from weaksquare.core.puzzle import PuzzleRef


@dataclass(frozen=True)
class SyncFields:
    """How an attempt enters the Lichess sync queue (v0.3, FR-6.13–6.16)."""

    status: str = "local"  # 'pending' to sync it
    rated: bool | None = None
    angle: str | None = None
    account: str | None = None  # the Lichess user signed in when it was solved
    already_played: bool | None = None


@dataclass(frozen=True)
class ModeFields:
    """What a v0.5 mode adds to an attempt: Commit the line's calculation accuracy (FR-4.2) and the
    depth-ladder theme set and level it was played at (FR-4.5)."""

    replies_correct: int | None = None
    replies_total: int | None = None
    ladder_key: str | None = None
    ladder_level: int | None = None


@dataclass(frozen=True)
class SrsRow:
    puzzle_id: str
    finished_at: str
    mode: str
    win: bool


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
        sync: SyncFields | None = None,
        extra: ModeFields | None = None,
    ) -> int:
        """Append one decided attempt. `sync` (v0.3) queues it for Lichess; without it the attempt
        stays local (sync_status 'local'). `extra` (v0.5) carries the mode's own columns."""
        sync = sync or SyncFields()
        extra = extra or ModeFields()
        with self._db.session() as conn:
            cur = conn.execute(
                "INSERT INTO attempts (puzzle_source, puzzle_id, session_id, mode, started_at, finished_at, win,"
                " help_used, first_move_correct, line_correct, time_ms, puzzle_rating,"
                " rated, angle, sync_status, sync_account, already_played,"
                " replies_correct, replies_total, ladder_key, ladder_level)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (ref.source, ref.id, session_id, mode, started_at, finished_at, int(result.win), result.help_used,
                 int(result.first_move_correct), int(result.line_correct), result.time_ms, puzzle_rating,
                 None if sync.rated is None else int(sync.rated), sync.angle, sync.status,
                 sync.account.lower() if sync.account else None,
                 None if sync.already_played is None else int(sync.already_played),
                 extra.replies_correct, extra.replies_total, extra.ladder_key, extra.ladder_level),
            )  # fmt: skip
            return int(cur.lastrowid or 0)

    def srs_rows(self) -> list[SrsRow]:
        """Spaced repetition (FR-4.6): every attempt of each Lichess puzzle you've missed at least once,
        oldest first per puzzle. The schedule is replayed from these (core/srs.py)."""
        with self._db.session() as conn:
            rows = conn.execute(
                "SELECT puzzle_id, finished_at, mode, win FROM attempts"
                " WHERE puzzle_source = 'lichess' AND puzzle_id IN"
                " (SELECT puzzle_id FROM attempts WHERE puzzle_source = 'lichess' AND win = 0)"
                " ORDER BY puzzle_id, id"
            ).fetchall()
        return [SrsRow(r[0], r[1], r[2], bool(r[3])) for r in rows]

    def ladder_history(self, key: str, window: int) -> tuple[int | None, list[bool]]:
        """Depth ladder (FR-4.5): the highest level recorded for `key`, and the results of the last
        `window` attempts at that level, oldest first."""
        with self._db.session() as conn:
            row = conn.execute("SELECT MAX(ladder_level) FROM attempts WHERE ladder_key = ?", (key,)).fetchone()
            level = row[0] if row else None
            if level is None:
                return None, []
            wins = conn.execute(
                "SELECT win FROM attempts WHERE ladder_key = ? AND ladder_level = ? ORDER BY id DESC LIMIT ?",
                (key, level, window),
            ).fetchall()
        return int(level), [bool(w[0]) for w in reversed(wins)]

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
