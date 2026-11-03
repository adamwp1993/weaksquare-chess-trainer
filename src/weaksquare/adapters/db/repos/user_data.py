"""Repositories for user.db: settings, sessions, the append-only attempts log and (v0.6) mistake reasons."""

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
    """What a mode adds to an attempt: Commit the line's calculation accuracy (FR-4.2) and the
    depth-ladder theme set and level it was played at (FR-4.5), from v0.5; Name the idea's tags and
    their score (FR-4.3) and Danger spotting's candidate and call (FR-4.4), from v0.6."""

    replies_correct: int | None = None
    replies_total: int | None = None
    ladder_key: str | None = None
    ladder_level: int | None = None
    idea_tags: dict[str, list[str]] | None = None
    idea_found: int | None = None
    idea_total: int | None = None
    idea_extra: int | None = None
    danger_candidate: str | None = None
    danger_safe: bool | None = None
    danger_call: str | None = None


@dataclass(frozen=True)
class SrsRow:
    puzzle_id: str
    finished_at: str
    mode: str
    win: bool


# The reason that counts for an attempt `a`: the latest one recorded (§7.3; append-only).
LATEST_REASON = (
    "(SELECT r.reason FROM mistake_reasons r WHERE r.source IN ('puzzle', 'danger')"
    " AND r.ref_id = CAST(a.id AS TEXT) ORDER BY r.id DESC LIMIT 1)"
)
# FR-5.10: a miss tagged Misclick is left out of local accuracy (and counted separately).
NOT_MISCLICK = f"COALESCE({LATEST_REASON}, '') != 'misclick'"


@dataclass(frozen=True)
class Tally:
    solved: int
    failed: int
    misclicks: int = 0  # not counted in `failed` (FR-5.10)


@dataclass(frozen=True)
class AttemptBrief:
    id: int
    mode: str
    win: bool


@dataclass(frozen=True)
class ReasonRow:
    reason: str
    suggested_reason: str | None
    note: str | None


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
                " replies_correct, replies_total, ladder_key, ladder_level,"
                " idea_tags, idea_found, idea_total, idea_extra, danger_candidate, danger_safe, danger_call)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (ref.source, ref.id, session_id, mode, started_at, finished_at, int(result.win), result.help_used,
                 int(result.first_move_correct), int(result.line_correct), result.time_ms, puzzle_rating,
                 None if sync.rated is None else int(sync.rated), sync.angle, sync.status,
                 sync.account.lower() if sync.account else None,
                 None if sync.already_played is None else int(sync.already_played),
                 extra.replies_correct, extra.replies_total, extra.ladder_key, extra.ladder_level,
                 None if extra.idea_tags is None else json.dumps(extra.idea_tags), extra.idea_found,
                 extra.idea_total, extra.idea_extra, extra.danger_candidate,
                 None if extra.danger_safe is None else int(extra.danger_safe), extra.danger_call),
            )  # fmt: skip
            return int(cur.lastrowid or 0)

    def srs_rows(self) -> list[SrsRow]:
        """Spaced repetition (FR-4.6): every attempt of each Lichess puzzle you've missed at least once,
        oldest first per puzzle. The schedule is replayed from these (core/srs.py). Danger-spotting
        results don't count (FR-4.4, v0.6); misclicks still do (FR-5.10)."""
        with self._db.session() as conn:
            rows = conn.execute(
                "SELECT puzzle_id, finished_at, mode, win FROM attempts"
                " WHERE puzzle_source = 'lichess' AND mode != 'danger_spotting' AND puzzle_id IN"
                " (SELECT puzzle_id FROM attempts WHERE puzzle_source = 'lichess' AND win = 0"
                "  AND mode != 'danger_spotting')"
                " ORDER BY puzzle_id, id"
            ).fetchall()
        return [SrsRow(r[0], r[1], r[2], bool(r[3])) for r in rows]

    def ladder_history(self, key: str, window: int) -> tuple[int | None, list[bool]]:
        """Depth ladder (FR-4.5): the highest level recorded for `key`, and the results of the last
        `window` attempts at that level, oldest first. Misclicks aren't in the window (FR-5.10)."""
        with self._db.session() as conn:
            row = conn.execute("SELECT MAX(ladder_level) FROM attempts WHERE ladder_key = ?", (key,)).fetchone()
            level = row[0] if row else None
            if level is None:
                return None, []
            wins = conn.execute(
                f"SELECT win FROM attempts a WHERE ladder_key = ? AND ladder_level = ? AND {NOT_MISCLICK}"
                " ORDER BY id DESC LIMIT ?",
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
        """Solved and failed, with misclicks counted apart (FR-5.10)."""
        with self._db.session() as conn:
            row = conn.execute(
                f"SELECT COALESCE(SUM(win), 0), COALESCE(SUM(1 - win), 0), COALESCE(SUM(misclick), 0)"
                f" FROM (SELECT a.win, (a.win = 0 AND {LATEST_REASON} = 'misclick') AS misclick"
                f"       FROM attempts a WHERE {where})",
                params,
            ).fetchone()
        misclicks = int(row[2])
        return Tally(int(row[0]), int(row[1]) - misclicks, misclicks)

    def session_tally(self, session_id: int) -> Tally:
        return self._tally("a.session_id = ?", (session_id,))

    def all_time_tally(self) -> Tally:
        return self._tally("1", ())

    def brief(self, attempt_id: int) -> AttemptBrief | None:
        with self._db.session() as conn:
            row = conn.execute("SELECT id, mode, win FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
        return AttemptBrief(int(row[0]), row[1], bool(row[2])) if row else None


class MistakeReasonsRepo:
    """§7.3: append-only; the latest row per (source, ref_id) counts."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def add(
        self, source: str, ref_id: str, reason: str, suggested: str | None, note: str | None, created_at: str
    ) -> None:
        with self._db.session() as conn:
            conn.execute(
                "INSERT INTO mistake_reasons (source, ref_id, reason, suggested_reason, note, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (source, ref_id, reason, suggested, note, created_at),
            )

    def latest(self, source: str, ref_id: str) -> ReasonRow | None:
        with self._db.session() as conn:
            row = conn.execute(
                "SELECT reason, suggested_reason, note FROM mistake_reasons WHERE source = ? AND ref_id = ?"
                " ORDER BY id DESC LIMIT 1",
                (source, ref_id),
            ).fetchone()
        return ReasonRow(row[0], row[1], row[2]) if row else None
