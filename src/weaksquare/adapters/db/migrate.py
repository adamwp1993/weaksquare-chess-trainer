"""Numbered SQL migrations with backup-first and newer-schema refusal (ARCHITECTURE §3 decision 2, NFR-3).

Migration files are `NNNN_name.sql` in one folder per database. Each runs in its own transaction
and bumps `schema_version`. Never edit a migration that has been applied: add a new file.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from weaksquare.adapters.db.connection import readonly_uri
from weaksquare.core.clock import Clock

log = logging.getLogger(__name__)

_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")
KEEP_BACKUPS = 5


class NewerSchemaError(RuntimeError):
    """The database was written by a newer version of the app. It is left untouched."""

    def __init__(self, path: Path, found: int, known: int) -> None:
        super().__init__(
            f"{path.name} has schema version {found}, but this version of WeakSquare only knows up to "
            f"{known}. It was probably written by a newer version. The file was not changed."
        )
        self.found = found
        self.known = known


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    version: int
    path: Path


@dataclass(frozen=True)
class MigrationResult:
    from_version: int
    to_version: int
    backup: Path | None


def load_migrations(folder: Path) -> list[Migration]:
    found: list[Migration] = []
    for f in sorted(folder.glob("*.sql")):
        m = _NAME.match(f.name)
        if not m:
            raise MigrationError(f"badly named migration file: {f.name}")
        found.append(Migration(int(m.group(1)), f))
    versions = [m.version for m in found]
    if versions != list(range(1, len(versions) + 1)):
        raise MigrationError(f"migrations in {folder} must be numbered 0001, 0002, … with no gaps")
    return found


def read_version(db_path: Path) -> int:
    """Schema version without writing anything (opened read-only). 0 for a new or empty file."""
    if not db_path.exists() or db_path.stat().st_size == 0:
        return 0
    conn = sqlite3.connect(readonly_uri(db_path), uri=True)
    try:
        has_table = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_version'").fetchone()
        if not has_table:
            return 0
        row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        return int(row[0] or 0)
    finally:
        conn.close()


def _backup(db_path: Path, backups_dir: Path, version: int, clock: Clock) -> Path:
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = clock.now().strftime("%Y%m%d-%H%M%S")
    stem = db_path.stem
    target = backups_dir / f"{stem}-{version}-{stamp}.db"
    n = 1
    while target.exists():
        target = backups_dir / f"{stem}-{version}-{stamp}-{n}.db"
        n += 1
    src = sqlite3.connect(readonly_uri(db_path), uri=True)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    old = sorted(backups_dir.glob(f"{stem}-*.db"), key=lambda p: p.stat().st_mtime_ns)
    for stale in old[:-KEEP_BACKUPS]:
        stale.unlink(missing_ok=True)
    log.info("Backed up %s (schema %d) to %s", db_path.name, version, target.name)
    return target


def migrate(db_path: Path, migrations_dir: Path, clock: Clock, backups_dir: Path | None = None) -> MigrationResult:
    """Bring `db_path` up to the newest migration.

    - newer schema than we know → NewerSchemaError, file untouched
    - existing data and pending migrations → backup first (when `backups_dir` is given)
    """
    migrations = load_migrations(migrations_dir)
    known = migrations[-1].version if migrations else 0
    current = read_version(db_path)
    if current > known:
        raise NewerSchemaError(db_path, current, known)
    pending = [m for m in migrations if m.version > current]
    if not pending:
        return MigrationResult(current, current, None)

    backup = None
    if current > 0 and backups_dir is not None:
        backup = _backup(db_path, backups_dir, current, clock)

    conn = sqlite3.connect(db_path, isolation_level=None)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        for m in pending:
            sql = m.path.read_text(encoding="utf-8")
            try:
                conn.execute("BEGIN IMMEDIATE")
                for statement in _split(sql):
                    conn.execute(statement)
                conn.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                    (m.version, clock.now().isoformat()),
                )
                conn.execute("COMMIT")
            except sqlite3.Error as e:
                conn.execute("ROLLBACK")
                raise MigrationError(f"migration {m.path.name} failed: {e}") from e
            log.info("Applied migration %s to %s", m.path.name, db_path.name)
    finally:
        conn.close()
    return MigrationResult(current, pending[-1].version, backup)


def _split(sql: str) -> list[str]:
    """Split a migration into statements (no triggers in our migrations, so `;` is safe)."""
    out, buf = [], []
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped.startswith("--") or not stripped:
            continue
        buf.append(line)
        if sqlite3.complete_statement("\n".join(buf)):
            out.append("\n".join(buf))
            buf = []
    if buf and "\n".join(buf).strip():
        raise MigrationError("migration ends with an incomplete statement")
    return out
