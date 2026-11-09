"""Backup files on disk (FR-15, v0.16): the snapshot, the zip, reading one back, and the startup swap.

- A snapshot uses SQLite's backup API, so it's consistent while the app writes (WAL readers never block).
- A zip is written to a temp name beside the target and renamed, so a half-written backup never has the
  real name.
- Reading a backup opens only `manifest.json` and `user.db` by name. Nothing is extracted by its own
  name (`extractall` is never used), and a zip holding anything else is refused.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import shutil
import sqlite3
import tempfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from weaksquare.adapters.db.connection import readonly_uri
from weaksquare.core.backup import (
    DB_NAME,
    MANIFEST_NAME,
    BackupError,
    Counts,
    Manifest,
    is_pc_local,
    manifest_json,
    parse_manifest,
    stale,
)
from weaksquare.core.errors import AppError

log = logging.getLogger(__name__)

CHUNK = 1024 * 1024
SPACE_MARGIN = 1.1  # room for the extracted copy plus a little


class NoSpaceError(AppError):
    code = "no_space"


@dataclass(frozen=True)
class DbFacts:
    schema_version: int
    counts: Counts


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def _count(conn: sqlite3.Connection, table: str) -> int:
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) if exists else 0


def check_db(path: Path) -> DbFacts:
    """Integrity check and schema read (FR-15.1). Anything wrong → `damaged`."""
    try:
        conn = sqlite3.connect(readonly_uri(path), uri=True)
        try:
            result = conn.execute("PRAGMA integrity_check").fetchall()
            if [tuple(r) for r in result] != [("ok",)]:
                raise BackupError("damaged")
            row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
            version = int(row[0] or 0)
            conn.execute("SELECT key, value FROM settings LIMIT 1").fetchall()
            counts = Counts(_count(conn, "games"), _count(conn, "attempts"), _count(conn, "coach_reports"))
        finally:
            conn.close()
    except sqlite3.Error:
        raise BackupError("damaged") from None
    if version < 1:
        raise BackupError("damaged")
    return DbFacts(version, counts)


def snapshot(user_db: Path, dest: Path) -> None:
    """A consistent copy of `user_db` at `dest`, taken with the backup API while the app keeps running."""
    src = sqlite3.connect(user_db, timeout=5.0)
    dst = sqlite3.connect(dest)
    try:
        # One step: a single read snapshot. Stepwise copies restart whenever another connection writes, so a busy app
        # (a running analysis) could keep one from ever finishing; in WAL mode this read never blocks the writers.
        src.backup(dst)
        dst.execute("PRAGMA journal_mode=DELETE")  # one self-contained file, no -wal beside it
    finally:
        dst.close()
        src.close()


def write_zip(target: Path, db_copy: Path, manifest: Manifest) -> None:
    """Write the backup beside `target` under a temp name, then rename it into place."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            zf.writestr(MANIFEST_NAME, manifest_json(manifest))
            zf.write(db_copy, DB_NAME)
        with tmp.open("rb+") as f:
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def make_backup(user_db: Path, target: Path, work_dir: Path, app_version: str, created_at: str) -> Manifest:
    """Snapshot, check, and write one backup file. Never changes `user_db`."""
    work_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tempfile.mkdtemp(prefix=".backup-", dir=work_dir))
    try:
        copy = tmp_dir / DB_NAME
        snapshot(user_db, copy)
        facts = check_db(copy)
        manifest = Manifest(app_version, facts.schema_version, created_at, facts.counts, sha256_of(copy),
                            copy.stat().st_size)  # fmt: skip
        write_zip(target, copy, manifest)
        return manifest
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _open(path: Path) -> zipfile.ZipFile:
    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError, ValueError):
        raise BackupError("not_backup") from None
    names = [i.filename for i in zf.infolist()]
    if sorted(names) != sorted([MANIFEST_NAME, DB_NAME]):
        zf.close()
        raise BackupError("not_backup")
    return zf


def read_manifest(path: Path) -> Manifest:
    with _open(path) as zf:
        try:
            raw = zf.read(MANIFEST_NAME)
        except (zipfile.BadZipFile, OSError, EOFError, zipfile.LargeZipFile):
            raise BackupError("damaged") from None
        manifest = parse_manifest(raw)
        if zf.getinfo(DB_NAME).file_size != manifest.db_size:
            raise BackupError("damaged")
        return manifest


def extract_db(path: Path, dest: Path, free_bytes: Callable[[Path], int] | None = None) -> Manifest:
    """Copy the backup's `user.db` to `dest`, checking size, free space, CRC, SHA-256 and integrity."""
    manifest = read_manifest(path)
    free = (free_bytes or (lambda p: shutil.disk_usage(p).free))(dest.parent)
    if free < manifest.db_size * SPACE_MARGIN:
        raise NoSpaceError("There isn't enough free disk space to restore this backup. Nothing was changed.")
    h = hashlib.sha256()
    written = 0
    try:
        with _open(path) as zf, zf.open(DB_NAME) as src, dest.open("wb") as out:
            while chunk := src.read(CHUNK):
                written += len(chunk)
                if written > manifest.db_size:
                    raise BackupError("damaged")
                h.update(chunk)
                out.write(chunk)
    except (zipfile.BadZipFile, OSError, EOFError):  # a CRC mismatch or a truncated file
        dest.unlink(missing_ok=True)
        raise BackupError("damaged") from None
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    if written != manifest.db_size or h.hexdigest() != manifest.db_sha256:
        dest.unlink(missing_ok=True)
        raise BackupError("damaged")
    try:
        facts = check_db(dest)
    except BackupError:
        dest.unlink(missing_ok=True)
        raise
    if facts.schema_version != manifest.schema_version:
        dest.unlink(missing_ok=True)
        raise BackupError("damaged")
    return manifest


def carry_pc_settings(staged: Path, current: Path) -> None:
    """Settings that belong to this PC keep this install's values (FR-15.2, v0.16 planning)."""
    keep: list[tuple[str, str]] = []
    if current.exists():
        src = sqlite3.connect(current, timeout=5.0)
        try:
            keep = [(k, v) for k, v in src.execute("SELECT key, value FROM settings") if is_pc_local(k)]
        finally:
            src.close()
    dst = sqlite3.connect(staged, isolation_level=None)
    try:
        dst.execute("BEGIN IMMEDIATE")
        doomed = [k for (k,) in dst.execute("SELECT key FROM settings") if is_pc_local(k)]
        dst.executemany("DELETE FROM settings WHERE key = ?", [(k,) for k in doomed])
        dst.executemany("INSERT INTO settings (key, value) VALUES (?, ?)", keep)
        dst.execute("COMMIT")
    finally:
        dst.close()


def list_backups(folder: Path, is_ours: Callable[[str], bool]) -> list[tuple[Path, Manifest]]:
    """Files in `folder` named like ours that really are backups (readable manifest). Anything else is ignored."""
    found: list[tuple[Path, Manifest]] = []
    for p in folder.iterdir():
        if not (p.is_file() and is_ours(p.name)):
            continue
        try:
            found.append((p, read_manifest(p)))
        except (BackupError, OSError):
            log.info("ignoring %s in the backups folder: not a readable backup", p.name)
    return found


def prune(folder: Path, is_ours: Callable[[str], bool], keep: int) -> list[str]:
    """Delete all but the newest `keep` of our backups in `folder`. Returns the names deleted."""
    found = list_backups(folder, is_ours)
    doomed = set(stale([(p.name, m.created_at) for p, m in found], keep))
    removed = []
    for p, _ in found:
        if p.name in doomed:
            try:
                p.unlink()
                removed.append(p.name)
            except OSError:
                log.warning("couldn't delete the old backup %s", p.name)
    return removed


class BackupFiles:
    """The file side of `services/backup.py`, with this install's paths bound in."""

    def __init__(self, user_db: Path, work_dir: Path, staged: Path, staged_manifest: Path, app_version: str,
                 free_bytes: Callable[[Path], int] | None = None) -> None:  # fmt: skip
        self._user_db = user_db
        self._work_dir = work_dir
        self._staged = staged
        self._staged_manifest = staged_manifest
        self._app_version = app_version
        self._free_bytes = free_bytes

    def make_backup(self, target: Path, created_at: str) -> Manifest:
        return make_backup(self._user_db, target, self._work_dir, self._app_version, created_at)

    def read_manifest(self, path: Path) -> Manifest:
        return read_manifest(path)

    def stage_restore(self, path: Path) -> Manifest:
        """Check the whole backup and leave it staged for the next start, with this PC's settings carried in."""
        self.discard_staged()
        manifest = extract_db(path, self._staged, self._free_bytes)
        try:
            carry_pc_settings(self._staged, self._user_db)
            self._staged_manifest.write_text(manifest_json(manifest), encoding="utf-8")
        except BaseException:
            self.discard_staged()
            raise
        return manifest

    def discard_staged(self) -> None:
        _remove_db(self._staged)
        self._staged_manifest.unlink(missing_ok=True)

    def folder_exists(self, folder: Path) -> bool:
        return folder.is_dir()

    def prune(self, folder: Path, is_ours: Callable[[str], bool], keep: int) -> list[str]:
        return prune(folder, is_ours, keep)


# ---- the startup swap (FR-15.4) -------------------------------------------------------------------
SIDE_FILES = ("-wal", "-shm")


def _side(db: Path, suffix: str) -> Path:
    return db.with_name(db.name + suffix)


def _move_db(src: Path, dst: Path) -> None:
    os.replace(src, dst)
    for s in SIDE_FILES:
        if _side(src, s).exists():
            os.replace(_side(src, s), _side(dst, s))


def _remove_db(db: Path) -> None:
    for p in (db, *(_side(db, s) for s in SIDE_FILES)):
        p.unlink(missing_ok=True)


@dataclass(frozen=True)
class SwapResult:
    restored_from: Manifest | None  # the restored backup's manifest, when the swap succeeded
    saved_as: Path | None  # the before-restore copy of the data it replaced
    error: str | None  # what went wrong; the original data is back in place


def swap_in_staged(
    user_db: Path,
    staged: Path,
    staged_manifest: Path,
    save_current: Callable[[], Path | None],
    migrate: Callable[[], object],
) -> SwapResult:
    """Replace `user_db` with `staged`, then migrate. Any failure puts the original back.

    Called at startup, after the instance lock and before anything opens `user_db`."""
    try:
        manifest = parse_manifest(staged_manifest.read_bytes())
    except (OSError, BackupError):
        manifest = None
    try:
        saved = save_current()
    except Exception:
        log.exception("couldn't save the current data before a restore")
        _remove_db(staged)
        staged_manifest.unlink(missing_ok=True)
        return SwapResult(None, None, "Your data couldn't be saved aside first, so nothing was restored.")
    old = user_db.with_name(user_db.name + ".replaced")
    _remove_db(old)
    had_current = user_db.exists()
    try:
        if had_current:
            _move_db(user_db, old)
        os.replace(staged, user_db)
        migrate()
    except Exception:
        log.exception("restore failed; putting the original data back")
        with contextlib.suppress(OSError):
            _remove_db(user_db)
            if had_current:
                _move_db(old, user_db)
        _remove_db(staged)
        staged_manifest.unlink(missing_ok=True)
        return SwapResult(None, saved, "The restore didn't finish, and your data was put back as it was.")
    _remove_db(old)
    staged_manifest.unlink(missing_ok=True)
    log.info("restored user.db from a backup made %s", manifest.created_at if manifest else "?")
    return SwapResult(manifest, saved, None)
