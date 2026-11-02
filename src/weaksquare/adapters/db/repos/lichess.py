"""user.db repositories for Lichess (v0.3): the sync queue on the attempts log, rating history and
your Lichess puzzle history."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from weaksquare.adapters.db.connection import Database


@dataclass(frozen=True)
class PendingSolve:
    attempt_id: int
    puzzle_id: str
    win: bool
    rated: bool
    angle: str


@dataclass(frozen=True)
class AttemptSync:
    attempt_id: int
    sync_status: str | None
    rated: bool | None
    already_played: bool | None
    rating_diff: int | None


@dataclass(frozen=True)
class RatingPoint:
    at: str  # finished_at of the attempt that carried the new rating
    rating: int
    session_id: int | None


@dataclass(frozen=True)
class SessionChange:
    session_id: int
    started_at: str
    change: int
    solves: int  # attempts with a returned change


class SyncRepo:
    """The sync queue lives on `attempts` (sync_status = 'pending'); nothing keeps its own copy."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def pending(self, account: str, limit: int = 1000) -> list[PendingSolve]:
        """Pending solves for `account`, plus those made while nobody was signed in, oldest first."""
        with self._db.session() as conn:
            rows = conn.execute(
                "SELECT id, puzzle_id, win, rated, angle FROM attempts"
                " WHERE sync_status = 'pending' AND puzzle_source = 'lichess'"
                " AND (sync_account IS NULL OR sync_account = ?) ORDER BY id LIMIT ?",
                (account.lower(), limit),
            ).fetchall()
        return [PendingSolve(r[0], r[1], bool(r[2]), bool(r[3]), r[4] or "mix") for r in rows]

    def pending_count(self, account: str | None) -> int:
        """Solves waiting to sync. With no account: every pending solve."""
        with self._db.session() as conn:
            if account is None:
                row = conn.execute("SELECT COUNT(*) FROM attempts WHERE sync_status = 'pending'").fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) FROM attempts WHERE sync_status = 'pending'"
                    " AND (sync_account IS NULL OR sync_account = ?)",
                    (account.lower(),),
                ).fetchone()
        return int(row[0])

    def mark_synced(
        self, results: Iterable[tuple[int, int | None]], rating_after: tuple[int, int] | None, at: str
    ) -> None:
        """`results`: (attempt_id, ratingDiff or None). `rating_after`: (attempt_id, rating) for the
        batch's last attempt, from the response's glicko (never computed here)."""
        with self._db.session() as conn:
            conn.executemany(
                "UPDATE attempts SET sync_status = 'synced', rating_diff = ?, synced_at = ? WHERE id = ?",
                [(diff, at, aid) for aid, diff in results],
            )
            if rating_after is not None:
                conn.execute("UPDATE attempts SET rating_after = ? WHERE id = ?", (rating_after[1], rating_after[0]))

    def mark(self, attempt_ids: Iterable[int], status: str, at: str) -> None:
        with self._db.session() as conn:
            conn.executemany(
                "UPDATE attempts SET sync_status = ?, synced_at = ? WHERE id = ?",
                [(status, at, aid) for aid in attempt_ids],
            )

    def attempts(self, attempt_ids: list[int]) -> list[AttemptSync]:
        if not attempt_ids:
            return []
        marks = ",".join("?" * len(attempt_ids))
        with self._db.session() as conn:
            rows = conn.execute(
                f"SELECT id, sync_status, rated, already_played, rating_diff FROM attempts WHERE id IN ({marks})",
                attempt_ids,
            ).fetchall()

        def b(v: int | None) -> bool | None:
            return None if v is None else bool(v)

        return [AttemptSync(r[0], r[1], b(r[2]), b(r[3]), r[4]) for r in rows]

    def played_before(self, puzzle_id: str) -> bool:
        """Lichess has seen this puzzle from you: it's in your imported history, or an earlier attempt
        here is waiting to sync or has synced (Lichess only rates the first attempt)."""
        with self._db.session() as conn:
            row = conn.execute(
                "SELECT EXISTS (SELECT 1 FROM lichess_history WHERE puzzle_id = ?)"
                " OR EXISTS (SELECT 1 FROM attempts WHERE puzzle_source = 'lichess' AND puzzle_id = ?"
                "            AND sync_status IN ('pending', 'synced'))",
                (puzzle_id, puzzle_id),
            ).fetchone()
        return bool(row[0])

    def session_change(self, session_id: int) -> int | None:
        """FR-6.11c: the sum of the changes Lichess returned this session (None if none yet)."""
        with self._db.session() as conn:
            row = conn.execute(
                "SELECT SUM(rating_diff) FROM attempts WHERE session_id = ? AND rating_diff IS NOT NULL",
                (session_id,),
            ).fetchone()
        return None if row[0] is None else int(row[0])

    def rating_points(self) -> list[RatingPoint]:
        with self._db.session() as conn:
            rows = conn.execute(
                "SELECT finished_at, rating_after, session_id FROM attempts WHERE rating_after IS NOT NULL ORDER BY id"
            ).fetchall()
        return [RatingPoint(r[0], int(r[1]), r[2]) for r in rows]

    def session_changes(self) -> list[SessionChange]:
        with self._db.session() as conn:
            rows = conn.execute(
                "SELECT s.id, s.started_at, SUM(a.rating_diff), COUNT(*) FROM attempts a JOIN sessions s"
                " ON s.id = a.session_id WHERE a.rating_diff IS NOT NULL GROUP BY s.id ORDER BY s.id"
            ).fetchall()
        return [SessionChange(r[0], r[1], int(r[2]), int(r[3])) for r in rows]


class LichessHistoryRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, rows: Iterable[tuple[str, str | None, bool | None]]) -> int:
        """Upsert (puzzle_id, played_at, win). Idempotent, so a broken import can simply restart."""
        data = [(pid, at, None if win is None else int(win)) for pid, at, win in rows]
        with self._db.session() as conn:
            conn.executemany(
                "INSERT INTO lichess_history (puzzle_id, played_at, win) VALUES (?, ?, ?)"
                " ON CONFLICT(puzzle_id) DO UPDATE SET"
                " played_at = COALESCE(MAX(excluded.played_at, lichess_history.played_at), lichess_history.played_at),"
                " win = COALESCE(excluded.win, lichess_history.win)",
                data,
            )
        return len(data)

    def count(self) -> int:
        with self._db.session() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM lichess_history").fetchone()[0])

    def clear(self) -> None:
        with self._db.session() as conn:
            conn.execute("DELETE FROM lichess_history")
