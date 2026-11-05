"""user.db 0009 (v0.11): digests, stored AI runs (v0.10 answers become first runs) and observations."""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from weaksquare.adapters.db.connection import Database
from weaksquare.adapters.db.migrate import migrate
from weaksquare.adapters.db.repos.coach import AiRunsRepo, CoachReportsRepo, DigestsRepo, ObservationsRepo
from weaksquare.config import MIGRATIONS_DIR
from weaksquare.core.clock import FixedClock

CLOCK = FixedClock(datetime(2026, 11, 4, 12, tzinfo=UTC))
V010_ANSWER = {
    "summary": "s",
    "weaknesses": [],
    "presets": [],
    "provider": "anthropic",
    "model": "m1",
    "cost_usd": 0.02,
}


def _v010(tmp_path: Path) -> Path:
    old = tmp_path / "v8"
    old.mkdir()
    for f in sorted((MIGRATIONS_DIR / "user").glob("000[1-8]_*.sql")):
        shutil.copy(f, old / f.name)
    db_path = tmp_path / "user.db"
    migrate(db_path, old, CLOCK)
    return db_path


def _report(conn: sqlite3.Connection, llm: str | None) -> None:
    conn.execute(
        "INSERT INTO coach_reports (created_at, subject, subject_label, source_kind, params_json, report_json,"
        " game_ids_json, llm_json) VALUES ('2026-11-03T10:00:00Z', 'me', 'You', 'games', '{}', '{}', '[]', ?)",
        (llm,),
    )


def test_v010_answers_become_first_runs(tmp_path: Path) -> None:
    db_path = _v010(tmp_path)
    conn = sqlite3.connect(db_path)
    _report(conn, json.dumps(V010_ANSWER))
    _report(conn, None)
    conn.commit()
    conn.close()

    migrate(db_path, MIGRATIONS_DIR / "user", CLOCK)
    db = Database(db_path, tmp_path / "puzzles.db")
    runs = AiRunsRepo(db).for_report(1)
    assert len(runs) == 1
    r = runs[0]
    assert (r.format, r.advanced, r.include_notes, r.provider, r.model, r.cost_usd) == (
        "keyed", False, False, "anthropic", "m1", 0.02,
    )  # fmt: skip
    assert r.result == V010_ANSWER
    assert AiRunsRepo(db).for_report(2) == []
    row = CoachReportsRepo(db).get(1)
    assert row is not None and row.llm == V010_ANSWER  # left as it was


def test_digests_are_keyed_by_game_and_color(tmp_path: Path) -> None:
    db_path = tmp_path / "user.db"
    migrate(db_path, MIGRATIONS_DIR / "user", CLOCK)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO games (source, pgn, moves_hash, user_color, fetched_at) VALUES ('paste', '*', 'h', 'white', 'x')"
    )
    conn.commit()
    conn.close()
    repo = DigestsRepo(Database(db_path, tmp_path / "puzzles.db"))
    repo.put(1, "white", "k1", {"a": 1}, "t")
    repo.put(1, "black", "k1", {"a": 2}, "t")
    repo.put(1, "white", "k2", {"a": 3}, "t")
    assert repo.get([1]) == {(1, "white"): ("k2", {"a": 3}), (1, "black"): ("k1", {"a": 2})}
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("DELETE FROM games")
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM game_digests").fetchone() == (0,)
    conn.close()


def test_an_observation_counts_once_per_report(tmp_path: Path) -> None:
    db_path = tmp_path / "user.db"
    migrate(db_path, MIGRATIONS_DIR / "user", CLOCK)
    repo = ObservationsRepo(Database(db_path, tmp_path / "puzzles.db"))
    assert repo.note("me", "concept:pawnStructure", "", "", "Weak pawns", 1) == 1
    assert repo.note("me", "concept:pawnStructure", "", "", "Weak pawns again", 1) == 1  # a second run
    assert repo.note("me", "concept:pawnStructure", "", "", "Weak pawns", 2) == 2
    assert repo.note("lichess:someone", "concept:pawnStructure", "", "", "Weak pawns", 3) == 1
    (o,) = repo.all("me")
    assert (o.times_seen, o.first_report_id, o.last_report_id) == (2, 1, 2)
