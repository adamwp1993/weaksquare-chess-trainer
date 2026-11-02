"""user.db schema v3 (v0.3): sync columns, lichess_history, and pre-v0.3 attempts never synced."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from weaksquare.adapters.db.connection import Database
from weaksquare.adapters.db.migrate import load_migrations, migrate
from weaksquare.adapters.db.repos.lichess import LichessHistoryRepo, SyncRepo
from weaksquare.adapters.db.repos.user_data import AttemptsRepo, SyncFields
from weaksquare.config import MIGRATIONS_DIR
from weaksquare.core.clock import FixedClock
from weaksquare.core.modes.base import AttemptResult
from weaksquare.core.puzzle import PuzzleRef

USER = MIGRATIONS_DIR / "user"
WIN = AttemptResult(win=True, first_move_correct=True, line_correct=True, help_used="none", time_ms=1)
LOSS = AttemptResult(win=False, first_move_correct=False, line_correct=False, help_used="none", time_ms=1)


def _v2_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "v2"
    folder.mkdir()
    for m in load_migrations(USER)[:2]:
        shutil.copy(m.path, folder / m.path.name)
    return folder


def test_v2_attempts_become_local_and_are_never_queued(tmp_path: Path, clock: FixedClock) -> None:
    db_path = tmp_path / "user.db"
    migrate(db_path, _v2_folder(tmp_path), clock)
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO sessions (started_at, mode, filters_json) VALUES ('t', 'standard', '{}')")
    conn.execute(
        "INSERT INTO attempts (puzzle_source, puzzle_id, session_id, mode, started_at, finished_at, win,"
        " first_move_correct, line_correct, time_ms) VALUES ('lichess', 'OLD01', 1, 'standard', 't', 't', 1, 1, 1, 5)"
    )
    conn.commit()
    conn.close()

    result = migrate(db_path, USER, clock, tmp_path / "backups")
    assert (result.from_version, result.to_version) == (2, 3)
    assert result.backup is not None  # NFR-3

    db = Database(db_path, tmp_path / "no-puzzles.db")
    try:
        with db.session() as c:
            assert c.execute("SELECT sync_status FROM attempts").fetchone()[0] == "local"
        sync = SyncRepo(db)
        assert sync.pending("player_a") == []
        assert sync.pending_count(None) == 0
        assert not sync.played_before("OLD01")  # a local-only attempt never reached Lichess
    finally:
        db.close_all()


def _db(tmp_path: Path, clock: FixedClock) -> Database:
    p = tmp_path / "user.db"
    migrate(p, USER, clock)
    db = Database(p, tmp_path / "no-puzzles.db")
    with db.session() as c:
        c.execute(
            "INSERT INTO sessions (started_at, mode, filters_json) VALUES ('2026-11-01T10:00:00', 'standard', '{}')"
        )
    return db


def _add(db: Database, pid: str, sync: SyncFields, result: AttemptResult = WIN) -> int:
    return AttemptsRepo(db).append(
        PuzzleRef("lichess", pid), 1, "standard", "t", "2026-11-01T10:05:00", result, 1500, sync
    )


def test_pending_queue_per_account(tmp_path: Path, clock: FixedClock) -> None:
    db = _db(tmp_path, clock)
    try:
        a = _add(db, "P1", SyncFields("pending", True, "fork", "Player_A", False))
        b = _add(db, "P2", SyncFields("pending", False, "mix", None, False), LOSS)
        _add(db, "P3", SyncFields("pending", True, "mix", "player_b", False))
        _add(db, "P4", SyncFields())  # local
        sync = SyncRepo(db)
        pend = sync.pending("player_a")
        assert [(p.attempt_id, p.puzzle_id, p.win, p.rated, p.angle) for p in pend] == [
            (a, "P1", True, True, "fork"),
            (b, "P2", False, False, "mix"),
        ]
        assert sync.pending_count("PLAYER_A") == 2  # usernames are case-insensitive
        assert sync.pending_count(None) == 3
        assert sync.played_before("P1")  # pending counts as played on Lichess
    finally:
        db.close_all()


def test_mark_synced_rating_history_and_session_change(tmp_path: Path, clock: FixedClock) -> None:
    db = _db(tmp_path, clock)
    try:
        a = _add(db, "P1", SyncFields("pending", True, "mix", "player_a", False))
        b = _add(db, "P2", SyncFields("pending", True, "mix", "player_a", False), LOSS)
        c = _add(db, "P3", SyncFields("pending", True, "mix", "player_a", False))
        sync = SyncRepo(db)
        assert sync.session_change(1) is None
        sync.mark_synced([(a, 8), (b, -12)], (b, 1496), "2026-11-01T10:06:00")
        sync.mark([c], "skipped", "2026-11-01T10:06:00")
        assert sync.session_change(1) == -4
        assert [
            (r.attempt_id, r.sync_status, r.rating_diff)
            for r in sorted(sync.attempts([a, b, c]), key=lambda r: r.attempt_id)
        ] == [
            (a, "synced", 8),
            (b, "synced", -12),
            (c, "skipped", None),
        ]
        pts = sync.rating_points()
        assert [(p.rating, p.session_id) for p in pts] == [(1496, 1)]
        changes = sync.session_changes()
        assert [(s.session_id, s.change, s.solves) for s in changes] == [(1, -4, 2)]
        assert sync.pending_count(None) == 0
    finally:
        db.close_all()


def test_lichess_history_upsert_is_idempotent(tmp_path: Path, clock: FixedClock) -> None:
    db = _db(tmp_path, clock)
    try:
        h = LichessHistoryRepo(db)
        h.add([("H1", "2026-10-01T00:00:00", True), ("H2", "2026-10-02T00:00:00", False)])
        h.add([("H1", "2026-10-03T00:00:00", False), ("H2", None, None)])
        assert h.count() == 2
        with db.session() as c:
            rows = {r[0]: (r[1], r[2]) for r in c.execute("SELECT puzzle_id, played_at, win FROM lichess_history")}
        assert rows == {"H1": ("2026-10-03T00:00:00", 0), "H2": ("2026-10-02T00:00:00", 0)}
        assert SyncRepo(db).played_before("H1")
        h.clear()
        assert h.count() == 0
    finally:
        db.close_all()
