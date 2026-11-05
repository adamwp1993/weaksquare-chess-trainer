"""user.db repository for training plans and review passes (v0.12, FR-10.61–10.66)."""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from weaksquare.adapters.db.connection import Database
from weaksquare.core.plan import DayRow, PlanDraft, PlanParams, PlanRow, Task, TaskRow

_PLAN_COLS = (
    "id, created_at, report_id, source, ai_run_id, weeks, weekdays_json, minutes_per_day, start_date, status, ended_at"
)
_TASK_COLS = (
    "id, day_id, position, type, weakness_key, minutes, title, params_json, manual_state, skipped_at, done_at,"
    " carried_from, swapped_from"
)


def _task(r: Any) -> TaskRow:
    return TaskRow(
        int(r[0]), int(r[1]), int(r[2]), str(r[3]), r[4], int(r[5]), str(r[6]), json.loads(r[7]), r[8], r[9], r[10],
        r[11], r[12],
    )  # fmt: skip


def _chunks(items: Sequence[int], size: int = 500) -> Iterable[Sequence[int]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


@dataclass(frozen=True)
class TaskPlace:
    task: TaskRow
    day: DayRow
    plan_id: int


class PlansRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    # ---- reading ----

    def _load(self, conn: Any, r: Any) -> PlanRow:
        plan_id = int(r[0])
        days = conn.execute(
            "SELECT id, plan_id, week, position, date FROM plan_days WHERE plan_id = ? ORDER BY position", (plan_id,)
        ).fetchall()
        tasks = conn.execute(
            f"SELECT {_TASK_COLS} FROM plan_tasks WHERE removed = 0 AND day_id IN"
            " (SELECT id FROM plan_days WHERE plan_id = ?) ORDER BY position, id",
            (plan_id,),
        ).fetchall()
        by_day: dict[int, list[TaskRow]] = {}
        for t in tasks:
            row = _task(t)
            by_day.setdefault(row.day_id, []).append(row)
        return PlanRow(
            plan_id, str(r[1]), r[2], str(r[3]), r[4],
            PlanParams(int(r[5]), tuple(json.loads(r[6])), int(r[7])), str(r[8]), str(r[9]), r[10],
            tuple(
                DayRow(int(d[0]), int(d[1]), int(d[2]), int(d[3]), str(d[4]), tuple(by_day.get(int(d[0]), ())))
                for d in days
            ),
        )  # fmt: skip

    def current(self) -> PlanRow | None:
        with self._db.session() as conn:
            r = conn.execute(f"SELECT {_PLAN_COLS} FROM training_plans WHERE status = 'current'").fetchone()
            return self._load(conn, r) if r else None

    def get(self, plan_id: int) -> PlanRow | None:
        with self._db.session() as conn:
            r = conn.execute(f"SELECT {_PLAN_COLS} FROM training_plans WHERE id = ?", (plan_id,)).fetchone()
            return self._load(conn, r) if r else None

    def history(self, limit: int = 50) -> list[PlanRow]:
        """Every plan, newest first (FR-10.65: old plans stay with their completion)."""
        with self._db.session() as conn:
            rows = conn.execute(
                f"SELECT {_PLAN_COLS} FROM training_plans ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [self._load(conn, r) for r in rows]

    def place(self, task_id: int) -> TaskPlace | None:
        with self._db.session() as conn:
            r = conn.execute(f"SELECT {_TASK_COLS} FROM plan_tasks WHERE id = ? AND removed = 0", (task_id,)).fetchone()
            if r is None:
                return None
            task = _task(r)
            d = conn.execute(
                "SELECT id, plan_id, week, position, date FROM plan_days WHERE id = ?", (task.day_id,)
            ).fetchone()
            rows = conn.execute(
                f"SELECT {_TASK_COLS} FROM plan_tasks WHERE day_id = ? AND removed = 0 ORDER BY position, id",
                (task.day_id,),
            ).fetchall()
        day = DayRow(int(d[0]), int(d[1]), int(d[2]), int(d[3]), str(d[4]), tuple(_task(x) for x in rows))
        return TaskPlace(task, day, day.plan_id)

    # ---- writing ----

    def add(
        self, draft: PlanDraft, dates: Sequence[date], created_at: str, *, report_id: int | None, source: str,
        ai_run_id: int | None = None,
    ) -> int:  # fmt: skip
        """Store a plan and make it current; the old one stays as history (FR-10.65)."""
        if len(dates) != len(draft.days):
            raise ValueError("every day of a plan needs a date")
        p = draft.params
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE training_plans SET status = 'replaced', ended_at = ? WHERE status = 'current'", (created_at,)
            )
            cur = conn.execute(
                f"INSERT INTO training_plans ({_PLAN_COLS.split(', ', 1)[1]}) VALUES (?,?,?,?,?,?,?,?,'current',NULL)",
                (created_at, report_id, source, ai_run_id, p.weeks, json.dumps(list(p.weekdays)), p.minutes,
                 dates[0].isoformat()),
            )  # fmt: skip
            plan_id = int(cur.lastrowid or 0)
            for day, when in zip(draft.days, dates, strict=True):
                d = conn.execute(
                    "INSERT INTO plan_days (plan_id, week, position, date) VALUES (?,?,?,?)",
                    (plan_id, day.week, day.position, when.isoformat()),
                )
                day_id = int(d.lastrowid or 0)
                for n, t in enumerate(day.tasks, start=1):
                    self._insert(conn, day_id, n, t)
            return plan_id

    @staticmethod
    def _insert(
        conn: Any, day_id: int, position: int, t: Task, *, carried_from: int | None = None,
        swapped_from: int | None = None,
    ) -> int:  # fmt: skip
        cur = conn.execute(
            "INSERT INTO plan_tasks (day_id, position, type, weakness_key, minutes, title, params_json, carried_from,"
            " swapped_from) VALUES (?,?,?,?,?,?,?,?,?)",
            (day_id, position, t.type, t.weakness_key, t.minutes, t.title, json.dumps(t.params), carried_from,
             swapped_from),
        )  # fmt: skip
        return int(cur.lastrowid or 0)

    def set_manual(self, task_id: int, state: str | None, at: str) -> None:
        """Your hand choice. Ticking or unticking also takes a skip back."""
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE plan_tasks SET manual_state = ?, manual_at = ?, skipped_at = NULL WHERE id = ?",
                (state, at, task_id),
            )

    def swapped_away(self, task_id: int) -> list[Task]:
        """QA v0.12-B11: what this task's slot has been before, following `swapped_from`."""
        out: list[Task] = []
        with self._db.session() as conn:
            current: int | None = task_id
            while current is not None:
                r = conn.execute(f"SELECT {_TASK_COLS} FROM plan_tasks WHERE id = ?", (current,)).fetchone()
                if r is None:
                    break
                row = _task(r)
                current = row.swapped_from
                if current is not None:
                    prev = conn.execute(f"SELECT {_TASK_COLS} FROM plan_tasks WHERE id = ?", (current,)).fetchone()
                    if prev is not None:
                        p = _task(prev)
                        out.append(Task(p.type, p.minutes, p.title, p.params, p.weakness_key))
        return out

    def set_skipped(self, task_id: int, at: str | None) -> None:
        with self._db.transaction() as conn:
            conn.execute("UPDATE plan_tasks SET skipped_at = ? WHERE id = ?", (at, task_id))

    def set_done(self, task_ids: Sequence[int], at: str) -> None:
        """When the app first saw these done. Never overwrites an earlier time."""
        if not task_ids:
            return
        with self._db.transaction() as conn:
            conn.executemany(
                "UPDATE plan_tasks SET done_at = ? WHERE id = ? AND done_at IS NULL", [(at, t) for t in task_ids]
            )

    def swap(self, task_id: int, new: Task) -> int:
        """The new task takes the old one's place; the old one stays (hidden) so its sessions stay linked."""
        with self._db.transaction() as conn:
            r = conn.execute("SELECT day_id, position FROM plan_tasks WHERE id = ?", (task_id,)).fetchone()
            conn.execute("UPDATE plan_tasks SET removed = 1 WHERE id = ?", (task_id,))
            return self._insert(conn, int(r[0]), int(r[1]), new, swapped_from=task_id)

    def carry(self, day_id: int, tasks: Sequence[TaskRow]) -> None:
        with self._db.transaction() as conn:
            last = conn.execute(
                "SELECT COALESCE(MAX(position), 0) FROM plan_tasks WHERE day_id = ?", (day_id,)
            ).fetchone()
            pos = int(last[0])
            for t in tasks:
                exists = conn.execute("SELECT 1 FROM plan_tasks WHERE carried_from = ?", (t.id,)).fetchone()
                if exists:  # safe to repeat
                    continue
                pos += 1
                self._insert(conn, day_id, pos, Task(t.type, t.minutes, t.title, t.params, t.weakness_key), carried_from=t.id)  # fmt: skip

    def link_session(self, session_id: int, task_id: int) -> None:
        with self._db.transaction() as conn:
            conn.execute("UPDATE sessions SET plan_task_id = ? WHERE id = ?", (task_id, session_id))

    # ---- what the app saw (FR-10.64) ----

    def attempt_facts(self, until: str | None = None) -> dict[int, tuple[int, int]]:
        """Task id → (decided attempts, milliseconds) in the sessions started from it, kept tasks and swapped
        ones alike. `until`: an ended plan's end (QA v0.12-B9)."""
        with self._db.session() as conn:
            rows = conn.execute(
                "SELECT s.plan_task_id, COUNT(a.id), COALESCE(SUM(a.time_ms), 0) FROM sessions s"
                " JOIN attempts a ON a.session_id = s.id WHERE s.plan_task_id IS NOT NULL"
                " AND (? IS NULL OR a.finished_at <= ?) GROUP BY s.plan_task_id",
                (until, until),
            ).fetchall()
        return {int(r[0]): (int(r[1]), int(r[2])) for r in rows}

    def retries_since(self, game_ids: Sequence[int], since: str, until: str | None = None) -> dict[int, frozenset[int]]:
        """Game id → plies with a recorded Retry try since this time."""
        out: dict[int, set[int]] = {}
        with self._db.session() as conn:
            for chunk in _chunks(list(game_ids)):
                rows = conn.execute(
                    "SELECT game_id, ply FROM retry_attempts WHERE created_at >= ? AND (? IS NULL OR created_at <= ?)"
                    f" AND game_id IN ({','.join('?' * len(chunk))})",
                    (since, until, until, *chunk),
                ).fetchall()
                for g, p in rows:
                    out.setdefault(int(g), set()).add(int(p))
        return {k: frozenset(v) for k, v in out.items()}

    def entry_tasks(self, until: str | None = None) -> frozenset[int]:
        """Tasks a journal entry was saved from."""
        with self._db.session() as conn:
            rows = conn.execute(
                "SELECT DISTINCT plan_task_id FROM journal_entries WHERE plan_task_id IS NOT NULL"
                " AND (? IS NULL OR created_at <= ?)",
                (until, until),
            ).fetchall()
        return frozenset(int(r[0]) for r in rows)

    def task_ids_with_sessions(self, plan_id: int) -> list[int]:
        """Every task of this plan that started a session, swapped-away ones too, for its puzzle accuracy."""
        with self._db.session() as conn:
            rows = conn.execute(
                "SELECT DISTINCT s.plan_task_id FROM sessions s JOIN plan_tasks t ON t.id = s.plan_task_id"
                " JOIN plan_days d ON d.id = t.day_id WHERE d.plan_id = ?",
                (plan_id,),
            ).fetchall()
        return [int(r[0]) for r in rows]


class ReviewPassesRepo:
    """Each pass through a game in Game Review (FR-10.64, 10.68)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def start(self, game_id: int, task_id: int | None, at: str) -> int:
        """A task resumes its own open pass; otherwise a new one starts, so moves you looked at before the task
        don't count towards it (QA v0.12-B12)."""
        with self._db.transaction() as conn:
            r = conn.execute(
                "SELECT id, plan_task_id FROM review_passes WHERE game_id = ? AND completed_at IS NULL"
                " ORDER BY id DESC LIMIT 1",
                (game_id,),
            ).fetchone()
            if r is not None and r[1] == task_id:
                return int(r[0])
            cur = conn.execute(
                "INSERT INTO review_passes (game_id, plan_task_id, started_at) VALUES (?,?,?)", (game_id, task_id, at)
            )
            return int(cur.lastrowid or 0)

    def visit(self, game_id: int, ply: int, at: str, needed: frozenset[int]) -> bool:
        """Record a visited move on the game's open pass (a new pass if there's none) and complete the pass
        when every needed ply was visited. True when this call completed it."""
        with self._db.transaction() as conn:
            r = conn.execute(
                "SELECT id, plies_json FROM review_passes WHERE game_id = ? AND completed_at IS NULL"
                " ORDER BY id DESC LIMIT 1",
                (game_id,),
            ).fetchone()
            if r is None:
                cur = conn.execute("INSERT INTO review_passes (game_id, started_at) VALUES (?,?)", (game_id, at))
                pass_id, plies = int(cur.lastrowid or 0), set[int]()
            else:
                pass_id, plies = int(r[0]), {int(x) for x in json.loads(r[1])}
            plies.add(ply)
            done = bool(needed) and needed <= plies
            conn.execute(
                "UPDATE review_passes SET plies_json = ?, completed_at = ? WHERE id = ?",
                (json.dumps(sorted(plies)), at if done else None, pass_id),
            )
            return done

    def completed_tasks(self, until: str | None = None) -> frozenset[int]:
        with self._db.session() as conn:
            rows = conn.execute(
                "SELECT DISTINCT plan_task_id FROM review_passes WHERE plan_task_id IS NOT NULL"
                " AND completed_at IS NOT NULL AND (? IS NULL OR completed_at <= ?)",
                (until, until),
            ).fetchall()
        return frozenset(int(r[0]) for r in rows)

    def completed_games(self, since: str, until: str | None = None) -> frozenset[int]:
        """Games stepped through in a pass that began and ended in this time."""
        with self._db.session() as conn:
            rows = conn.execute(
                "SELECT DISTINCT game_id FROM review_passes WHERE started_at >= ? AND completed_at >= ?"
                " AND (? IS NULL OR completed_at <= ?)",
                (since, since, until, until),
            ).fetchall()
        return frozenset(int(r[0]) for r in rows)
