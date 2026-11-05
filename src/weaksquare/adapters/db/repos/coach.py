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

    def history(self, subject: str, puzzles_only: bool, before_id: int, limit: int) -> list[ReportRow]:
        """FR-10.73: the subject's reports of the same kind before this one, oldest first. Reports on your
        puzzle history compare only with each other; reports on games (games or both) likewise."""
        kind = "source_kind = 'puzzles'" if puzzles_only else "source_kind <> 'puzzles'"
        with self._db.session() as conn:
            rows = conn.execute(
                f"SELECT {_REPORT_COLS} FROM coach_reports WHERE subject = ? AND id < ? AND {kind}"
                " ORDER BY id DESC LIMIT ?",
                (subject, before_id, limit),
            ).fetchall()
        return [_report(r) for r in reversed(rows)]

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

    # ---- notes (FR-10.60, v0.11) ----

    def game_notes(self, game_ids: list[int]) -> list[NoteRow]:
        """The latest reason and note per move of these games, where that latest entry has a note; plus
        the notes on Retry attempts of these games."""
        wanted = set(game_ids)
        out: list[NoteRow] = []
        with self._db.session() as conn:
            rows = conn.execute(
                "SELECT m.source, m.ref_id, m.reason, m.note, m.created_at FROM mistake_reasons m"
                " WHERE m.source = 'game' AND m.id ="
                " (SELECT MAX(id) FROM mistake_reasons WHERE source = 'game' AND ref_id = m.ref_id)"
                " AND m.note IS NOT NULL AND TRIM(m.note) <> '' ORDER BY m.id"
            ).fetchall()
            for src, ref, reason, note, at in rows:
                gid, _, ply = str(ref).partition(":")
                if gid.isdigit() and ply.isdigit() and int(gid) in wanted:
                    out.append(NoteRow(str(src), int(gid), int(ply), reason, str(note), str(at)))
            retry = conn.execute(
                "SELECT m.source, r.game_id, r.ply, m.reason, m.note, m.created_at FROM mistake_reasons m"
                " JOIN retry_attempts r ON CAST(r.id AS TEXT) = m.ref_id"
                " WHERE m.source = 'retry' AND m.id ="
                " (SELECT MAX(id) FROM mistake_reasons WHERE source = 'retry' AND ref_id = m.ref_id)"
                " AND m.note IS NOT NULL AND TRIM(m.note) <> '' ORDER BY m.id"
            ).fetchall()
            out.extend(
                NoteRow(str(s), int(g), int(p), r, str(n), str(a)) for s, g, p, r, n, a in retry if int(g) in wanted
            )
        return out

    def puzzle_notes(self, since: str | None, until: str | None) -> list[NoteRow]:
        """The latest reason and note per puzzle attempt (Standard and Danger spotting) made in this
        period, where that entry has a note."""
        q = (
            "SELECT m.source, m.reason, m.note, m.created_at FROM mistake_reasons m"
            " WHERE m.source IN ('puzzle', 'danger') AND m.id ="
            " (SELECT MAX(id) FROM mistake_reasons WHERE source = m.source AND ref_id = m.ref_id)"
            " AND m.note IS NOT NULL AND TRIM(m.note) <> ''"
        )
        args: list[str] = []
        if since:
            q += " AND m.created_at >= ?"
            args.append(since)
        if until:
            q += " AND m.created_at <= ?"
            args.append(until)
        with self._db.session() as conn:
            rows = conn.execute(q + " ORDER BY m.id", args).fetchall()
        return [NoteRow(str(s), None, None, r, str(n), str(a)) for s, r, n, a in rows]


@dataclass(frozen=True)
class NoteRow:
    source: str  # game / retry / puzzle / danger
    game_id: int | None
    ply: int | None  # 0-based
    reason: str | None
    note: str
    created_at: str


class DigestsRepo:
    """Game digests (FR-10.52, v0.11)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, game_ids: list[int]) -> dict[tuple[int, str], tuple[str, dict[str, Any]]]:
        """(game id, color) → (analysis key, digest JSON)."""
        out: dict[tuple[int, str], tuple[str, dict[str, Any]]] = {}
        with self._db.session() as conn:
            for i in range(0, len(game_ids), 500):
                chunk = game_ids[i : i + 500]
                rows = conn.execute(
                    "SELECT game_id, color, analysis_key, digest_json FROM game_digests"
                    f" WHERE game_id IN ({','.join('?' * len(chunk))})",
                    chunk,
                ).fetchall()
                for gid, color, key, data in rows:
                    out[(int(gid), str(color))] = (str(key), json.loads(data))
        return out

    def put(self, game_id: int, color: str, key: str, digest: dict[str, Any], built_at: str) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO game_digests (game_id, color, analysis_key, digest_json, built_at) VALUES (?,?,?,?,?)"
                " ON CONFLICT(game_id, color) DO UPDATE SET analysis_key = excluded.analysis_key,"
                " digest_json = excluded.digest_json, built_at = excluded.built_at",
                (game_id, color, key, json.dumps(digest), built_at),
            )


@dataclass(frozen=True)
class AiRunRow:
    id: int
    report_id: int
    created_at: str
    format: str  # keyed (v0.10) / diagnosis (v0.11)
    advanced: bool
    include_notes: bool
    game_cap: int | None
    provider: str
    model: str
    cost_usd: float
    result: dict[str, Any]
    include_journal: bool = False  # v0.12, FR-10.71
    journal_hash: str | None = None


_RUN_COLS = (
    "id, report_id, created_at, format, advanced, include_notes, game_cap, provider, model, cost_usd, result_json,"
    " include_journal, journal_hash"
)


def _run(r: Any) -> AiRunRow:
    return AiRunRow(
        int(r[0]), int(r[1]), str(r[2]), str(r[3]), bool(r[4]), bool(r[5]), None if r[6] is None else int(r[6]),
        str(r[7]), str(r[8]), float(r[9] or 0), json.loads(r[10]), bool(r[11]), r[12],
    )  # fmt: skip


class AiRunsRepo:
    """Every AI coaching answer for a report (Adam, v0.11 planning)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def add(
        self, report_id: int, created_at: str, fmt: str, *, advanced: bool, include_notes: bool,
        game_cap: int | None, provider: str, model: str, cost_usd: float, result: dict[str, Any],
        include_journal: bool = False, journal_hash: str | None = None,
    ) -> int:  # fmt: skip
        with self._db.transaction() as conn:
            cur = conn.execute(
                f"INSERT INTO coach_ai_runs ({_RUN_COLS.split(', ', 1)[1]}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    report_id, created_at, fmt, int(advanced), int(include_notes), game_cap, provider, model,
                    cost_usd, json.dumps(result), int(include_journal), journal_hash,
                ),
            )  # fmt: skip
            return int(cur.lastrowid or 0)

    def for_report(self, report_id: int) -> list[AiRunRow]:
        with self._db.session() as conn:
            rows = conn.execute(
                f"SELECT {_RUN_COLS} FROM coach_ai_runs WHERE report_id = ? ORDER BY id", (report_id,)
            ).fetchall()
        return [_run(r) for r in rows]

    def get(self, run_id: int) -> AiRunRow | None:
        with self._db.session() as conn:
            r = conn.execute(f"SELECT {_RUN_COLS} FROM coach_ai_runs WHERE id = ?", (run_id,)).fetchone()
        return _run(r) if r else None


@dataclass(frozen=True)
class ObservationRow:
    id: int
    subject: str
    topic_key: str
    category: str
    title_key: str
    title: str
    first_report_id: int | None
    last_report_id: int | None
    times_seen: int


class ObservationsRepo:
    """Findings that can't be measured, noted when they recur across a subject's reports (FR-10.57).
    Several AI runs of one report count once."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def note(self, subject: str, topic_key: str, category: str, title_key: str, title: str, report_id: int) -> int:
        """Record one sighting; returns how many reports have seen it."""
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT id, report_ids FROM coach_observations"
                " WHERE subject = ? AND topic_key = ? AND category = ? AND title_key = ?",
                (subject, topic_key, category, title_key),
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO coach_observations (subject, topic_key, category, title_key, title,"
                    " first_report_id, last_report_id, times_seen, report_ids) VALUES (?,?,?,?,?,?,?,1,?)",
                    (subject, topic_key, category, title_key, title, report_id, report_id, json.dumps([report_id])),
                )
                return 1
            # QA v0.11-B3: count distinct reports, in any order (0010 added report_ids)
            reports = [int(x) for x in json.loads(row[1] or "[]")]
            if report_id not in reports:
                reports.append(report_id)
            conn.execute(
                "UPDATE coach_observations SET title = ?, last_report_id = ?, times_seen = ?, report_ids = ?"
                " WHERE id = ?",
                (title, report_id, len(reports), json.dumps(reports), int(row[0])),
            )
            return len(reports)

    def all(self, subject: str) -> list[ObservationRow]:
        with self._db.session() as conn:
            rows = conn.execute(
                "SELECT id, subject, topic_key, category, title_key, title, first_report_id, last_report_id,"
                " times_seen FROM coach_observations WHERE subject = ? ORDER BY id",
                (subject,),
            ).fetchall()
        return [
            ObservationRow(int(r[0]), str(r[1]), str(r[2]), str(r[3]), str(r[4]), str(r[5]), r[6], r[7], int(r[8]))
            for r in rows
        ]
