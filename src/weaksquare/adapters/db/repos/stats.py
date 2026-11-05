"""Reads the attempts log for Stats (FR-9.1, 9.2, 9.3, 9.7), joined to puzzles.db with a left join so attempts on
puzzles a newer export dropped still count (FR-2.4). Each row carries its latest mistake reason (§7.3)."""

from __future__ import annotations

from datetime import UTC, datetime

from weaksquare.adapters.db.connection import Database
from weaksquare.adapters.db.repos.user_data import LATEST_REASON
from weaksquare.core.stats import AttemptRow

_COLUMNS = (
    "a.win, a.first_move_correct, a.line_correct, a.puzzle_rating, {themes}, {length}, a.mode,"
    f" {LATEST_REASON}, a.finished_at, a.replies_correct, a.replies_total, a.idea_found, a.idea_total,"
    " a.idea_extra, a.danger_safe"
)


def _time(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        t = datetime.fromisoformat(text)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


class StatsRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def game_reason_rows(self) -> list[AttemptRow]:
        return game_reason_rows(self._db)

    def retry_totals(self) -> tuple[int, int]:
        return retry_totals(self._db)

    def source_accuracy(self) -> list[tuple[str, int, int]]:
        return source_accuracy(self._db)

    def attempt_rows(self) -> list[AttemptRow]:
        return [row for row, _ in self._select("", ())]

    def attempt_rows_between(self, since: str, until: str) -> list[tuple[AttemptRow, str]]:
        """(row, puzzle source) for attempts finished in this range (v0.12, the daily log, FR-10.68)."""
        return self._select(" WHERE a.finished_at >= ? AND a.finished_at < ?", (since, until))

    def attempt_rows_for_tasks(self, task_ids: list[int]) -> list[AttemptRow]:
        """Attempts in the sessions started from these plan tasks (v0.12, FR-10.66)."""
        if not task_ids:
            return []
        marks = ",".join("?" * len(task_ids))
        where = f" WHERE a.session_id IN (SELECT id FROM sessions WHERE plan_task_id IN ({marks}))"
        return [row for row, _ in self._select(where, tuple(task_ids))]

    def recent_solve_ms(self, sample: int) -> int | None:
        """Your average solving time over your last `sample` attempts, when you have that many (v0.12)."""
        with self._db.session() as conn:
            rows = conn.execute(
                "SELECT time_ms FROM attempts WHERE mode != 'danger_spotting' ORDER BY id DESC LIMIT ?", (sample,)
            ).fetchall()
        return round(sum(int(r[0]) for r in rows) / len(rows)) if len(rows) >= sample else None

    def _select(self, where: str, args: tuple[object, ...]) -> list[tuple[AttemptRow, str]]:
        with self._db.session() as conn:
            attached = conn.execute("SELECT 1 FROM pragma_database_list WHERE name = 'pz'").fetchone()
            if attached:
                cols = _COLUMNS.format(themes="COALESCE(p.themes, c.themes)", length="COALESCE(p.length, c.length)")
                rows = conn.execute(
                    f"SELECT {cols}, a.puzzle_source FROM attempts a LEFT JOIN pz.puzzles p"
                    " ON a.puzzle_source = 'lichess' AND p.id = a.puzzle_id"
                    " LEFT JOIN custom_puzzles c ON a.puzzle_source = 'my' AND c.id = CAST(a.puzzle_id AS INTEGER)"
                    + where,
                    args,
                ).fetchall()
            else:
                cols = _COLUMNS.format(themes="c.themes", length="c.length")
                rows = conn.execute(
                    f"SELECT {cols}, a.puzzle_source FROM attempts a"
                    " LEFT JOIN custom_puzzles c ON a.puzzle_source = 'my' AND c.id = CAST(a.puzzle_id AS INTEGER)"
                    + where,
                    args,
                ).fetchall()
        return [
            (AttemptRow(
                win=bool(r[0]),
                first_move_correct=bool(r[1]),
                line_correct=bool(r[2]),
                puzzle_rating=r[3],
                themes=None if r[4] is None else tuple(r[4].split()),
                length=r[5],
                mode=r[6],
                reason=r[7],
                finished_at=_time(r[8]),
                replies_correct=r[9],
                replies_total=r[10],
                idea_found=r[11],
                idea_total=r[12],
                idea_extra=r[13],
                danger_safe=None if r[14] is None else bool(r[14]),
            ), str(r[15]))
            for r in rows
        ]  # fmt: skip


# v0.8 (FR-9.7, puzzles vs games): your own game mistakes and Retry misses, each with its latest reason.
_GAME_REASON = (
    "(SELECT r.reason FROM mistake_reasons r WHERE r.source = 'game'"
    " AND r.ref_id = ga.game_id || ':' || ga.ply ORDER BY r.id DESC LIMIT 1)"
)
_RETRY_REASON = (
    "(SELECT r.reason FROM mistake_reasons r WHERE r.source = 'retry'"
    " AND r.ref_id = CAST(t.id AS TEXT) ORDER BY r.id DESC LIMIT 1)"
)


def game_reason_rows(db: Database) -> list[AttemptRow]:
    """Every inaccuracy, mistake and blunder of yours in an analyzed game (mode `game_review`) and every
    Retry miss (mode `retry`), as loss rows for `reason_report`. A game move's week is the game's date."""
    with db.session() as conn:
        games = conn.execute(
            f"SELECT {_GAME_REASON}, COALESCE(g.played_at, g.fetched_at) FROM game_analysis ga"
            " JOIN games g ON g.id = ga.game_id"
            # v0.10-B1: your games only (another player's games carry their color in user_color)
            " JOIN game_subjects s ON s.game_id = ga.game_id AND s.subject = 'me'"
            " WHERE ga.classification IN ('inaccuracy', 'mistake', 'blunder')"
            " AND (s.color = ga.mover OR s.color = 'both')"
        ).fetchall()
        retries = conn.execute(
            f"SELECT {_RETRY_REASON}, t.created_at FROM retry_attempts t WHERE t.found = 0"
        ).fetchall()
    rows = [AttemptRow(False, False, False, None, None, None, "game_review", r[0], _time(r[1])) for r in games]
    rows += [AttemptRow(False, False, False, None, None, None, "retry", r[0], _time(r[1])) for r in retries]
    return rows


def retry_totals(db: Database) -> tuple[int, int]:
    """Retry mode (FR-11.15): (found, tried)."""
    with db.session() as conn:
        r = conn.execute("SELECT COALESCE(SUM(found), 0), COUNT(*) FROM retry_attempts").fetchone()
    return int(r[0]), int(r[1])


def source_accuracy(db: Database) -> list[tuple[str, int, int]]:
    """(source, attempts, wins) per puzzle source, the way local accuracy counts them: no Danger spotting
    and no misclicks (FR-5.10)."""
    from weaksquare.adapters.db.repos.user_data import NOT_MISCLICK

    with db.session() as conn:
        rows = conn.execute(
            f"SELECT a.puzzle_source, COUNT(*), COALESCE(SUM(a.win), 0) FROM attempts a"
            f" WHERE a.mode != 'danger_spotting' AND {NOT_MISCLICK} GROUP BY a.puzzle_source ORDER BY a.puzzle_source"
        ).fetchall()
    return [(str(r[0]), int(r[1]), int(r[2])) for r in rows]
