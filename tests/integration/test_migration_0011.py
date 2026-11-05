"""user.db 0011 (v0.12): plans, review passes, the journal, and the new columns, from a v0.11 database."""

from __future__ import annotations

import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from weaksquare.adapters.db.migrate import migrate
from weaksquare.config import MIGRATIONS_DIR
from weaksquare.core.clock import FixedClock

CLOCK = FixedClock(datetime(2026, 11, 5, 12, tzinfo=UTC))


def _v011(tmp_path: Path) -> Path:
    old = tmp_path / "v10"
    old.mkdir()
    for f in sorted((MIGRATIONS_DIR / "user").glob("00*.sql")):
        if f.name < "0011":
            shutil.copy(f, old / f.name)
    db_path = tmp_path / "user.db"
    migrate(db_path, old, CLOCK)
    return db_path


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def test_a_v011_database_keeps_its_rows_and_gains_the_new_columns(tmp_path: Path) -> None:
    db_path = _v011(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("INSERT INTO sessions (started_at, mode, filters_json) VALUES ('t', 'standard', '{}')")
        conn.execute(
            "INSERT INTO coach_reports (created_at, subject, subject_label, source_kind, params_json, report_json,"
            " game_ids_json) VALUES ('t', 'me', 'You', 'games', '{}', '{}', '[]')"
        )
        conn.execute(
            "INSERT INTO coach_ai_runs (report_id, created_at, format, advanced, include_notes, provider, model,"
            " cost_usd, result_json) VALUES (1, 't', 'diagnosis', 0, 0, 'p', 'm', 0.1, '{}')"
        )
    migrate(db_path, MIGRATIONS_DIR / "user", CLOCK)
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT plan_task_id FROM sessions").fetchone() == (None,)
        assert conn.execute("SELECT include_journal, journal_hash FROM coach_ai_runs").fetchone() == (0, None)
        assert "analyzed_at" in _columns(conn, "games")
        for table in ("training_plans", "plan_days", "plan_tasks", "review_passes", "journal_entries"):
            assert _columns(conn, table), table


def test_only_one_plan_can_be_current(tmp_path: Path) -> None:
    db_path = tmp_path / "user.db"
    migrate(db_path, MIGRATIONS_DIR / "user", CLOCK)
    insert = (
        "INSERT INTO training_plans (created_at, source, weeks, weekdays_json, minutes_per_day, start_date, status)"
        " VALUES ('t', 'deterministic', 2, '[0,1]', 20, '2026-11-05', ?)"
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(insert, ("replaced",))
        conn.execute(insert, ("replaced",))
        conn.execute(insert, ("current",))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(insert, ("current",))
