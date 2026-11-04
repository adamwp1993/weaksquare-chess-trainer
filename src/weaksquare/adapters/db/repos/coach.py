"""user.db repository for the Coach (v0.10): the puzzle quality checks (`coach_candidates`) and saved
reports (`coach_reports`)."""

from __future__ import annotations

import json
from dataclasses import dataclass

from weaksquare.adapters.db.connection import Database


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
