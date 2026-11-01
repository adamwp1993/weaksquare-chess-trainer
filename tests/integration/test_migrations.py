"""NFR-3: backup before migrating, refuse a newer schema without touching the file."""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
from pathlib import Path

import pytest

from weaksquare.adapters.db.migrate import (
    KEEP_BACKUPS,
    MigrationError,
    NewerSchemaError,
    load_migrations,
    migrate,
    read_version,
)
from weaksquare.config import MIGRATIONS_DIR
from weaksquare.core.clock import FixedClock

USER_MIGRATIONS = MIGRATIONS_DIR / "user"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _migrations_with_extra(tmp_path: Path, extra_sql: str) -> Path:
    folder = tmp_path / "migs"
    shutil.copytree(USER_MIGRATIONS, folder)
    n = len(load_migrations(folder)) + 1
    (folder / f"{n:04d}_extra.sql").write_text(extra_sql, encoding="utf-8")
    return folder


def test_fresh_database_gets_every_migration_and_no_backup(tmp_path: Path, clock: FixedClock) -> None:
    db = tmp_path / "user.db"
    result = migrate(db, USER_MIGRATIONS, clock, tmp_path / "backups")
    assert result.from_version == 0
    assert result.to_version == len(load_migrations(USER_MIGRATIONS))
    assert result.backup is None
    assert read_version(db) == result.to_version


def test_newer_schema_refused_untouched(tmp_path: Path, clock: FixedClock) -> None:
    db = tmp_path / "user.db"
    migrate(db, USER_MIGRATIONS, clock)
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO schema_version (version, applied_at) VALUES (999, 'future')")
    conn.commit()
    conn.close()
    before_sha, before_mtime = _sha(db), db.stat().st_mtime_ns
    backups = tmp_path / "backups"

    with pytest.raises(NewerSchemaError) as exc:
        migrate(db, USER_MIGRATIONS, clock, backups)

    assert exc.value.found == 999
    assert _sha(db) == before_sha
    assert db.stat().st_mtime_ns == before_mtime
    assert not backups.exists() or not any(backups.iterdir())
    assert not (tmp_path / "user.db-wal").exists()


def test_backup_before_migration(tmp_path: Path, clock: FixedClock) -> None:
    db = tmp_path / "user.db"
    migrate(db, USER_MIGRATIONS, clock)
    old_version = read_version(db)
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO settings (key, value) VALUES ('marker', '\"before\"')")
    conn.commit()
    conn.close()
    folder = _migrations_with_extra(tmp_path, "CREATE TABLE extra (x INTEGER);")

    result = migrate(db, folder, clock, tmp_path / "backups")

    assert result.backup is not None
    assert result.backup.name == f"user-{old_version}-20260101-120000.db"
    # The backup is the old schema, with the data, and without the new table.
    assert read_version(result.backup) == old_version
    b = sqlite3.connect(result.backup)
    assert b.execute("SELECT value FROM settings WHERE key='marker'").fetchone()[0] == '"before"'
    assert b.execute("SELECT 1 FROM sqlite_master WHERE name='extra'").fetchone() is None
    b.close()
    assert read_version(db) == old_version + 1


def test_failing_migration_leaves_backup_and_original(tmp_path: Path, clock: FixedClock) -> None:
    db = tmp_path / "user.db"
    migrate(db, USER_MIGRATIONS, clock)
    old_version = read_version(db)
    folder = _migrations_with_extra(tmp_path, "CREATE TABLE ok_part (x INTEGER);\nTHIS IS NOT SQL;")

    with pytest.raises(MigrationError):
        migrate(db, folder, clock, tmp_path / "backups")

    assert read_version(db) == old_version
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='ok_part'").fetchone() is None
    conn.close()
    backups = list((tmp_path / "backups").glob("user-*.db"))
    assert len(backups) == 1


def test_keeps_last_five_backups(tmp_path: Path) -> None:
    clock = FixedClock()
    db = tmp_path / "user.db"
    migrate(db, USER_MIGRATIONS, clock)
    folder = tmp_path / "migs"
    shutil.copytree(USER_MIGRATIONS, folder)
    base = len(load_migrations(folder))
    for i in range(1, 8):
        (folder / f"{base + i:04d}_step{i}.sql").write_text(f"CREATE TABLE t{i} (x INTEGER);")
        clock.advance(minutes=1)
        migrate(db, folder, clock, tmp_path / "backups")
    assert len(list((tmp_path / "backups").glob("user-*.db"))) == KEEP_BACKUPS


def test_migration_numbering_must_be_contiguous(tmp_path: Path) -> None:
    folder = tmp_path / "m"
    folder.mkdir()
    (folder / "0001_a.sql").write_text("CREATE TABLE a (x);")
    (folder / "0003_c.sql").write_text("CREATE TABLE c (x);")
    with pytest.raises(MigrationError):
        load_migrations(folder)


def test_puzzle_migrations_apply(tmp_path: Path, clock: FixedClock) -> None:
    db = tmp_path / "puzzles.db"
    migrate(db, MIGRATIONS_DIR / "puzzles", clock)
    conn = sqlite3.connect(db)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert {"puzzles", "theme_bits", "meta"} <= names
