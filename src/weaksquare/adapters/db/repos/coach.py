"""user.db repository for the Coach (v0.10): the puzzle quality checks (`coach_candidates`) and saved
reports (`coach_reports`)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from weaksquare.adapters.db.connection import Database
from weaksquare.core.coach import ErrorRow


@dataclass(frozen=True)
class Candidate:
    game_id: int
    ply: int
    check_key: str
    kind: str
    passed: bool
    reason: str | None
    line: tuple[str, ...]
    cp: int | None


class CoachRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    # ---- quality checks (FR-10.41) ----

    def candidates(self, game_id: int) -> dict[int, Candidate]:
        with self._db.session() as conn:
            rows = conn.execute(
                "SELECT game_id, ply, check_key, kind, passed, reason, line_json, cp FROM coach_candidates"
                " WHERE game_id = ?",
                (game_id,),
            ).fetchall()
        return {
            int(r[1]): Candidate(
                int(r[0]), int(r[1]), str(r[2]), str(r[3]), bool(r[4]), r[5], tuple(json.loads(r[6] or "[]")), r[7]
            )
            for r in rows
        }

    def put_candidate(self, c: Candidate, checked_at: str) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO coach_candidates (game_id, ply, check_key, kind, passed, reason, line_json, cp, checked_at)"
                " VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(game_id, ply) DO UPDATE SET check_key = excluded.check_key,"
                " kind = excluded.kind, passed = excluded.passed, reason = excluded.reason,"
                " line_json = excluded.line_json, cp = excluded.cp, checked_at = excluded.checked_at",
                (
                    c.game_id, c.ply, c.check_key, c.kind, int(c.passed), c.reason,
                    json.dumps(list(c.line)) if c.line else None, c.cp, checked_at,
                ),
            )  # fmt: skip


@dataclass(frozen=True)
class ReportRow:
    id: int
    created_at: str
    subject: str
    subject_label: str
    source_kind: str
    params: dict[str, Any]
    report: dict[str, Any]
    game_ids: list[int]
    llm: dict[str, Any] | None


def _report(r: Any) -> ReportRow:
    return ReportRow(
        int(r[0]), str(r[1]), str(r[2]), str(r[3]), str(r[4]), json.loads(r[5]), json.loads(r[6]),
        [int(x) for x in json.loads(r[7])], json.loads(r[8]) if r[8] else None,
    )  # fmt: skip


_REPORT_COLS = "id, created_at, subject, subject_label, source_kind, params_json, report_json, game_ids_json, llm_json"


class CoachReportsRepo:
    """Saved reports (FR-10.20) and the reads the Coach aggregates from."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def add(
        self, created_at: str, subject: str, label: str, source: str, params: dict[str, Any],
        report: dict[str, Any], game_ids: list[int],
    ) -> int:  # fmt: skip
        with self._db.transaction() as conn:
            cur = conn.execute(
                f"INSERT INTO coach_reports ({_REPORT_COLS.split(', ', 1)[1]}) VALUES (?,?,?,?,?,?,?,?)",
                (
                    created_at,
                    subject,
                    label,
                    source,
                    json.dumps(params),
                    json.dumps(report),
                    json.dumps(game_ids),
                    None,
                ),
            )
            return int(cur.lastrowid or 0)

    def get(self, report_id: int) -> ReportRow | None:
        with self._db.session() as conn:
            r = conn.execute(f"SELECT {_REPORT_COLS} FROM coach_reports WHERE id = ?", (report_id,)).fetchone()
        return _report(r) if r else None

    def recent(self, limit: int = 100) -> list[ReportRow]:
        with self._db.session() as conn:
            rows = conn.execute(
                f"SELECT {_REPORT_COLS} FROM coach_reports ORDER BY id DESC LIMIT ?", (max(1, min(limit, 500)),)
            ).fetchall()
        return [_report(r) for r in rows]

    def previous(self, subject: str, before_id: int) -> ReportRow | None:
        """The subject's report before this one, for the trend (FR-10.20)."""
        with self._db.session() as conn:
            r = conn.execute(
                f"SELECT {_REPORT_COLS} FROM coach_reports WHERE subject = ? AND id < ? AND source_kind <> 'puzzles'"
                " ORDER BY id DESC LIMIT 1",
                (subject, before_id),
            ).fetchone()
        return _report(r) if r else None

    def count(self, subject: str) -> int:
        with self._db.session() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM coach_reports WHERE subject = ?", (subject,)).fetchone()[0])

    def set_llm(self, report_id: int, llm: dict[str, Any]) -> None:
        with self._db.transaction() as conn:
            conn.execute("UPDATE coach_reports SET llm_json = ? WHERE id = ?", (json.dumps(llm), report_id))

    def errors(self, subject: str, game_ids: list[int]) -> list[ErrorRow]:
        """The subject's graded errors in these games (the `game_errors` view)."""
        out: list[ErrorRow] = []
        with self._db.session() as conn:
            for i in range(0, len(game_ids), 500):
                chunk = game_ids[i : i + 500]
                rows = conn.execute(
                    "SELECT game_id, ply, classification, kind, phase, cp_loss, themes, habits, low_clock"
                    f" FROM game_errors WHERE subject = ? AND game_id IN ({','.join('?' * len(chunk))})",
                    (subject, *chunk),
                ).fetchall()
                out.extend(
                    ErrorRow(
                        int(r[0]),
                        int(r[1]),
                        str(r[2]),
                        r[3],
                        str(r[4]),
                        int(r[5]),
                        tuple(json.loads(r[6]) if r[6] else ()),
                        tuple(json.loads(r[7]) if r[7] else ()),
                        None if r[8] is None else bool(r[8]),
                    )
                    for r in rows
                )
        return out

    def game_reasons(self) -> dict[tuple[int, int], str]:
        """The latest mistake reason per game move (§7.3), keyed (game id, ply)."""
        with self._db.session() as conn:
            rows = conn.execute(
                "SELECT m.ref_id, m.reason FROM mistake_reasons m WHERE m.source = 'game' AND m.id ="
                " (SELECT MAX(id) FROM mistake_reasons WHERE source = 'game' AND ref_id = m.ref_id)"
            ).fetchall()
        out: dict[tuple[int, int], str] = {}
        for ref, reason in rows:
            gid, _, ply = str(ref).partition(":")
            if gid.isdigit() and ply.isdigit():
                out[(int(gid), int(ply))] = str(reason)
        return out
