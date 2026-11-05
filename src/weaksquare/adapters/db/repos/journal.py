"""user.db repository for the journal and the facts behind its daily log (v0.12, FR-10.67–10.70)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from weaksquare.adapters.db.connection import Database

_COLS = "id, created_at, updated_at, entry_date, kind, text, game_id, ply, weakness_key, plan_day_id, plan_task_id"


@dataclass(frozen=True)
class EntryRow:
    id: int
    created_at: str
    updated_at: str
    entry_date: str
    kind: str  # note / reflection
    text: str
    game_id: int | None
    ply: int | None  # 0-based
    weakness_key: str | None
    plan_day_id: int | None
    plan_task_id: int | None


def _entry(r: Any) -> EntryRow:
    return EntryRow(
        int(r[0]), str(r[1]), str(r[2]), str(r[3]), str(r[4]), str(r[5]), r[6], r[7], r[8], r[9], r[10],
    )  # fmt: skip


def _like(text: str) -> str:
    """A LIKE pattern for literal text: % and _ in your search mean themselves."""
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


class JournalRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add(
        self, at: str, entry_date: str, kind: str, text: str, *, game_id: int | None = None, ply: int | None = None,
        weakness_key: str | None = None, plan_day_id: int | None = None, plan_task_id: int | None = None,
    ) -> int:  # fmt: skip
        with self._db.transaction() as conn:
            cur = conn.execute(
                f"INSERT INTO journal_entries ({_COLS.split(', ', 1)[1]}) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (at, at, entry_date, kind, text, game_id, ply, weakness_key, plan_day_id, plan_task_id),
            )
            return int(cur.lastrowid or 0)

    def get(self, entry_id: int) -> EntryRow | None:
        with self._db.session() as conn:
            r = conn.execute(f"SELECT {_COLS} FROM journal_entries WHERE id = ?", (entry_id,)).fetchone()
        return _entry(r) if r else None

    def update(self, entry_id: int, at: str, text: str, weakness_key: str | None) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE journal_entries SET text = ?, weakness_key = ?, updated_at = ? WHERE id = ?",
                (text, weakness_key, at, entry_id),
            )

    def delete(self, entry_id: int) -> None:
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM journal_entries WHERE id = ?", (entry_id,))

    def search(
        self, *, kinds: Sequence[str] = (), game_id: int | None = None, weakness_key: str | None = None,
        date_from: str | None = None, date_to: str | None = None, query: str | None = None, limit: int = 500,
    ) -> list[EntryRow]:  # fmt: skip
        """FR-10.70: your entries, newest first."""
        where: list[str] = []
        args: list[Any] = []
        if kinds:
            where.append(f"kind IN ({','.join('?' * len(kinds))})")
            args += list(kinds)
        if game_id is not None:
            where.append("game_id = ?")
            args.append(game_id)
        if weakness_key is not None:
            where.append("weakness_key = ?")
            args.append(weakness_key)
        if date_from is not None:
            where.append("entry_date >= ?")
            args.append(date_from)
        if date_to is not None:
            where.append("entry_date <= ?")
            args.append(date_to)
        if query:
            where.append("text LIKE ? ESCAPE '\\'")
            args.append(_like(query))
        sql = f"SELECT {_COLS} FROM journal_entries"
        if where:
            sql += " WHERE " + " AND ".join(where)
        with self._db.session() as conn:
            rows = conn.execute(sql + " ORDER BY entry_date DESC, id DESC LIMIT ?", (*args, limit)).fetchall()
        return [_entry(r) for r in rows]

    def for_game(self, game_id: int) -> list[EntryRow]:
        """FR-10.69: a game's notes, in order of the move they're on (notes on the whole game first)."""
        with self._db.session() as conn:
            rows = conn.execute(
                f"SELECT {_COLS} FROM journal_entries WHERE game_id = ? ORDER BY COALESCE(ply, -1), id", (game_id,)
            ).fetchall()
        return [_entry(r) for r in rows]

    def for_prompt(self, game_ids: Sequence[int], since: str | None, limit: int) -> list[EntryRow]:
        """FR-10.71: entries on one of these games, or dated from `since` onward; the newest `limit`."""
        tests: list[str] = []
        args: list[Any] = []
        ids = list(game_ids)
        if ids:
            tests.append(f"game_id IN ({','.join('?' * len(ids))})")
            args += ids
        if since:
            tests.append("entry_date >= ?")
            args.append(since[:10])
        if not tests:
            return []
        with self._db.session() as conn:
            rows = conn.execute(
                f"SELECT {_COLS} FROM journal_entries WHERE ({' OR '.join(tests)})"
                " ORDER BY entry_date DESC, id DESC LIMIT ?",
                (*args, limit),
            ).fetchall()
        return [_entry(r) for r in rows]


@dataclass(frozen=True)
class RetryFact:
    at: str
    found: bool


@dataclass(frozen=True)
class ReportFact:
    at: str
    report: dict[str, Any]


class DailyLogRepo:
    """Raw timestamps for the daily log (FR-10.68). `since` and `until` are UTC day bounds a day wider than
    asked for; the service sorts each row onto your local calendar day."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def _times(self, sql: str, since: str, until: str) -> list[str]:
        with self._db.session() as conn:
            return [str(r[0]) for r in conn.execute(sql, (since, until)).fetchall() if r[0]]

    def games_synced(self, since: str, until: str) -> list[str]:
        return self._times(
            "SELECT g.fetched_at FROM games g JOIN game_subjects s ON s.game_id = g.id AND s.subject = 'me'"
            " WHERE g.fetched_at >= ? AND g.fetched_at < ?",
            since, until,
        )  # fmt: skip

    def games_analyzed(self, since: str, until: str) -> list[str]:
        return self._times(
            "SELECT g.analyzed_at FROM games g JOIN game_subjects s ON s.game_id = g.id AND s.subject = 'me'"
            " WHERE g.analyzed_at >= ? AND g.analyzed_at < ?",
            since, until,
        )  # fmt: skip

    def games_reviewed(self, since: str, until: str) -> list[str]:
        return self._times(
            "SELECT completed_at FROM review_passes WHERE completed_at >= ? AND completed_at < ?", since, until
        )

    def retries(self, since: str, until: str) -> list[RetryFact]:
        with self._db.session() as conn:
            rows = conn.execute(
                "SELECT created_at, found FROM retry_attempts WHERE created_at >= ? AND created_at < ?", (since, until)
            ).fetchall()
        return [RetryFact(str(r[0]), bool(r[1])) for r in rows]

    def plan_tasks_done(self, since: str, until: str) -> list[str]:
        return self._times(
            "SELECT done_at FROM plan_tasks WHERE removed = 0 AND done_at >= ? AND done_at < ?", since, until
        )

    def reports(self, since: str, until: str) -> list[ReportFact]:
        with self._db.session() as conn:
            rows = conn.execute(
                "SELECT created_at, report_json FROM coach_reports WHERE subject = 'me'"
                " AND created_at >= ? AND created_at < ?",
                (since, until),
            ).fetchall()
        return [ReportFact(str(r[0]), json.loads(r[1])) for r in rows]
