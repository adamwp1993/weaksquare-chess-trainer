"""user.db schema v4 (v0.5): Commit-the-line and depth-ladder columns on the attempts log."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from weaksquare.adapters.db.migrate import load_migrations, migrate
from weaksquare.config import MIGRATIONS_DIR
from weaksquare.core.clock import FixedClock

USER = MIGRATIONS_DIR / "user"


def test_v3_attempts_keep_their_data_and_get_null_mode_columns(tmp_path: Path, clock: FixedClock) -> None:
    folder = tmp_path / "v3"
    folder.mkdir()
    for m in load_migrations(USER)[:3]:
        shutil.copy(m.path, folder / m.path.name)
    db = tmp_path / "user.db"
    migrate(db, folder, clock)
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO sessions (started_at, mode, filters_json) VALUES ('t', 'standard', '{}')")
    conn.execute(
        "INSERT INTO attempts (puzzle_source, puzzle_id, session_id, mode, started_at, finished_at, win,"
        " first_move_correct, line_correct, time_ms, sync_status) VALUES ('lichess', 'OLD01', 1, 'standard',"
        " 't', 't', 0, 0, 0, 5, 'synced')"
    )
    conn.commit()
    conn.close()

    result = migrate(db, USER, clock, tmp_path / "backups")
    assert result.from_version == 3 and result.to_version >= 4  # later versions add migrations on top
    assert result.backup is not None  # NFR-3

    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT puzzle_id, win, sync_status, replies_correct, replies_total, ladder_key, ladder_level FROM attempts"
    ).fetchone()
    assert row == ("OLD01", 0, "synced", None, None, None, None)
    indexes = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert "attempts_ladder" in indexes
    conn.close()
