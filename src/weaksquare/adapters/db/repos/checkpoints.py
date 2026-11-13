"""user.db repository for checkpoints and fix tracking (v1.0, REQUIREMENTS §10.8): `coach_checkpoints`,
`weakness_tracking` and `weakness_metrics`, plus the reads game health needs. A checkpoint's id is its number."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from weaksquare.adapters.db.connection import Database
from weaksquare.core.fix_tracking import Change, CheckpointDraft, Metric, Step, Tracked


@dataclass(frozen=True)
class CheckpointRow:
    number: int
    created_at: str
    trigger: str
    report_id: int | None
    reconstructed: bool
    game_ids: list[int]
    games: int
    newest_played_at: str | None
    health: dict[str, Any]
    changes: list[Change]
    ai_run_id: int | None


_CP_COLS = ("number, created_at, trigger, report_id, reconstructed, game_ids_json, games, newest_played_at, health_json,"
            " changes_json, ai_run_id")  # fmt: skip


def _checkpoint(r: Any) -> CheckpointRow:
    changes = [Change(str(c["key"]), str(c["label"]), c.get("old"), str(c["new"])) for c in json.loads(r[9] or "[]")]
    return CheckpointRow(
        int(r[0]), str(r[1]), str(r[2]), r[3], bool(r[4]), [int(x) for x in json.loads(r[5])], int(r[6]), r[7],
        json.loads(r[8]), changes, r[10],
    )  # fmt: skip


def _tracked(r: Any) -> Tracked:
    return Tracked(
        str(r[0]), str(r[1]), str(r[2]), tuple(json.loads(r[3] or "[]")), float(r[4]), int(r[5]), int(r[6]), str(r[7]),
        int(r[8]), int(r[9]),
    )  # fmt: skip


class CheckpointsRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    # ---- checkpoints ----

    def last(self, *, live_only: bool = False) -> CheckpointRow | None:
        where = " WHERE reconstructed = 0" if live_only else ""
        with self._db.session() as conn:
            r = conn.execute(f"SELECT {_CP_COLS} FROM coach_checkpoints{where} ORDER BY number DESC LIMIT 1").fetchone()
        return _checkpoint(r) if r else None

    def all(self) -> list[CheckpointRow]:
        with self._db.session() as conn:
            rows = conn.execute(f"SELECT {_CP_COLS} FROM coach_checkpoints ORDER BY number").fetchall()
        return [_checkpoint(r) for r in rows]

    def get(self, number: int) -> CheckpointRow | None:
        with self._db.session() as conn:
            r = conn.execute(f"SELECT {_CP_COLS} FROM coach_checkpoints WHERE number = ?", (number,)).fetchone()
        return _checkpoint(r) if r else None

    def by_report(self, report_id: int) -> CheckpointRow | None:
        with self._db.session() as conn:
            r = conn.execute(f"SELECT {_CP_COLS} FROM coach_checkpoints WHERE report_id = ?", (report_id,)).fetchone()
        return _checkpoint(r) if r else None

    def count(self) -> int:
        with self._db.session() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM coach_checkpoints").fetchone()[0])

    def next_number(self) -> int:
        with self._db.session() as conn:
            return int(conn.execute("SELECT COALESCE(MAX(number), 0) + 1 FROM coach_checkpoints").fetchone()[0])

    def set_ai_run(self, number: int, run_id: int | None) -> None:
        with self._db.transaction() as conn:
            conn.execute("UPDATE coach_checkpoints SET ai_run_id = ? WHERE number = ?", (run_id, number))

    def save(self, draft: CheckpointDraft, step: Step) -> None:
        """The checkpoint, its metrics and the new tracking state, in one transaction."""
        changes = json.dumps([asdict(c) for c in step.changes], ensure_ascii=False)
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO coach_checkpoints (id, number, created_at, trigger, report_id, reconstructed, game_ids_json,"
                " games, newest_played_at, health_json, changes_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    draft.number, draft.number, draft.created_at, draft.trigger, draft.report_id, int(draft.reconstructed),
                    json.dumps(list(draft.game_ids)), len(draft.game_ids), draft.newest_played_at,
                    json.dumps(draft.health, ensure_ascii=False), changes,
                ),
            )  # fmt: skip
            conn.executemany(
                "INSERT INTO weakness_metrics (checkpoint_id, key, per10, count, puzzle_accuracy, puzzle_attempts,"
                " guarded, status, reasons_json) VALUES (?,?,?,?,?,?,?,?,?)",
                [
                    (draft.number, m.key, m.per10, m.count, m.puzzle_accuracy, m.puzzle_attempts, int(m.guarded),
                     m.status, json.dumps(m.reasons, sort_keys=True))
                    for m in step.metrics
                ],
            )  # fmt: skip
            self._put_tracked(conn, step.tracked.values())

    def put_tracked(self, tracked: Iterable[Tracked]) -> None:
        with self._db.transaction() as conn:
            self._put_tracked(conn, tracked)

    @staticmethod
    def _put_tracked(conn: sqlite3.Connection, tracked: Iterable[Tracked]) -> None:
        conn.executemany(
            "INSERT INTO weakness_tracking (key, kind, label, themes_json, baseline_per10, baseline_games,"
            " first_checkpoint_id, status, status_since_id, fixed_streak) VALUES (?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(key) DO UPDATE SET label = excluded.label, themes_json = excluded.themes_json,"
            " status = excluded.status, status_since_id = excluded.status_since_id, fixed_streak = excluded.fixed_streak",
            [
                (t.key, t.kind, t.label, json.dumps(list(t.themes)), t.baseline_per10, t.baseline_games,
                 t.first_checkpoint, t.status, t.status_since, t.fixed_streak)
                for t in tracked
            ],
        )  # fmt: skip

    # ---- tracking ----

    def tracked(self) -> dict[str, Tracked]:
        with self._db.session() as conn:
            rows = conn.execute(
                "SELECT key, kind, label, themes_json, baseline_per10, baseline_games, first_checkpoint_id, status,"
                " status_since_id, fixed_streak FROM weakness_tracking ORDER BY key"
            ).fetchall()
        return {str(r[0]): _tracked(r) for r in rows}

    def metrics(self) -> list[tuple[int, Metric]]:
        """Every point, oldest checkpoint first."""
        with self._db.session() as conn:
            rows = conn.execute(
                "SELECT checkpoint_id, key, per10, count, puzzle_accuracy, puzzle_attempts, guarded, status, reasons_json"
                " FROM weakness_metrics ORDER BY checkpoint_id, key"
            ).fetchall()
        return [
            (int(r[0]), Metric(str(r[1]), float(r[2]), int(r[3]), r[4], int(r[5]), bool(r[6]), str(r[7]),
                               json.loads(r[8] or "{}")))
            for r in rows
        ]  # fmt: skip

    # ---- reads for game health (FR-10.36) ----

    def my_moves(self, game_ids: Sequence[int], subject: str = "me") -> list[tuple[int, int, str, int]]:
        """(game id, ply, phase, cp loss) of every graded move of yours in these games."""
        if not game_ids:
            return []
        marks = ",".join("?" * len(game_ids))
        with self._db.session() as conn:
            rows = conn.execute(
                f"SELECT a.game_id, a.ply, a.phase, a.cp_loss FROM game_analysis a"
                f" JOIN game_subjects s ON s.game_id = a.game_id AND s.subject = ? AND (s.color = a.mover OR s.color = 'both')"
                f" WHERE a.game_id IN ({marks}) ORDER BY a.game_id, a.ply",
                (subject, *game_ids),
            ).fetchall()
        return [(int(r[0]), int(r[1]), str(r[2]), int(r[3])) for r in rows]

    def my_ratings(self, game_ids: Sequence[int]) -> list[tuple[str, str | None, int | None]]:
        """(platform, played_at, your rating) for these games."""
        if not game_ids:
            return []
        marks = ",".join("?" * len(game_ids))
        with self._db.session() as conn:
            rows = conn.execute(
                f"SELECT source, played_at, CASE user_color WHEN 'white' THEN white_rating WHEN 'black' THEN black_rating"
                f" END FROM games WHERE id IN ({marks})",
                tuple(game_ids),
            ).fetchall()
        return [(str(r[0]), r[1], r[2]) for r in rows]
