"""Backup files: the manifest, the checks, the automatic schedule and retention (FR-15, v0.16). No I/O.

A backup is a `.zip` holding `manifest.json` and a consistent copy of `user.db`. Everything here works
on values: the adapter reads and writes the files, the service decides when.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from weaksquare.core.errors import AppError, ValidationError

FORMAT = "weaksquare-backup"
FORMAT_VERSION = 1
MANIFEST_NAME = "manifest.json"
DB_NAME = "user.db"
MANIFEST_MAX_BYTES = 64 * 1024

AUTO_PREFIX = "weaksquare-backup-"
BEFORE_RESTORE_PREFIX = "before-restore-"
KEEP_BEFORE_RESTORE = 5

DEFAULT_INTERVAL_DAYS = 7
DEFAULT_KEEP = 5
INTERVAL_RANGE = (1, 90)
KEEP_RANGE = (1, 50)
RECHECK_S = 3600.0  # while the app is open, look again at least hourly (sleep and hibernate stop timers)
MIN_WAIT_S = 60.0  # a backup that's due but couldn't start (another one running) is looked at again in a minute

# Settings that describe this PC, not your data (FR-15.2, v0.16 planning). A restore keeps this install's values.
PC_LOCAL_KEYS = frozenset({
    "puzzle_db.last_check",  # this PC's puzzles.db
    "puzzle_db.skipped_export",
    "lichess.account",  # the sign-in itself is in this PC's Credential Manager
    "lichess.scopes",
    "debug.time_offset_days",  # --dev runs only
    "engine.custom_path",  # your own engine's .exe, on this PC (FR-7.5)
    "engine.custom_name",
    "engine.threads",  # sized to this PC's CPU and memory (FR-7.4); think time is a preference and travels
    "engine.hash_mb",
})  # fmt: skip
PC_LOCAL_PREFIXES = ("backup.",)  # the automatic-backup folder is a path on this PC

BackupErrorCode = Literal["not_backup", "damaged", "newer_backup"]

NOT_BACKUP_MESSAGE = "This file isn't a WeakSquare backup. Nothing was changed."
DAMAGED_MESSAGE = "This backup is damaged and can't be restored. Nothing was changed."
NEWER_MESSAGE = "This backup was made by a newer version of WeakSquare. Update the app first."


class BackupError(AppError):
    """A file that can't be restored: not a backup, damaged, or from a newer version (FR-15.4)."""

    def __init__(self, code: BackupErrorCode, message: str | None = None) -> None:
        default = {"not_backup": NOT_BACKUP_MESSAGE, "damaged": DAMAGED_MESSAGE, "newer_backup": NEWER_MESSAGE}[code]
        super().__init__(message or default, code=code, retryable=False)


def is_pc_local(key: str) -> bool:
    return key in PC_LOCAL_KEYS or key.startswith(PC_LOCAL_PREFIXES)


@dataclass(frozen=True)
class Counts:
    games: int
    attempts: int
    coach_reports: int


@dataclass(frozen=True)
class Manifest:
    app_version: str
    schema_version: int
    created_at: str  # ISO 8601 with offset, from the injected Clock
    counts: Counts
    db_sha256: str
    db_size: int


_SHA = re.compile(r"^[0-9a-f]{64}$")


def manifest_json(m: Manifest) -> str:
    data = {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "app_version": m.app_version,
        "schema_version": m.schema_version,
        "created_at": m.created_at,
        "counts": {"games": m.counts.games, "attempts": m.counts.attempts, "coach_reports": m.counts.coach_reports},
        "db_sha256": m.db_sha256,
        "db_size": m.db_size,
    }
    return json.dumps(data, indent=2)


def _int(data: dict[str, Any], key: str) -> int:
    v = data.get(key)
    if not isinstance(v, int) or isinstance(v, bool) or v < 0:
        raise BackupError("damaged")
    return v


def parse_manifest(raw: bytes) -> Manifest:
    """Read a manifest. Not ours → `not_backup`; ours but unreadable → `damaged`; a newer format → `newer_backup`."""
    if len(raw) > MANIFEST_MAX_BYTES:
        raise BackupError("not_backup")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise BackupError("not_backup") from None
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise BackupError("not_backup")
    fv = data.get("format_version")
    if not isinstance(fv, int) or isinstance(fv, bool):
        raise BackupError("damaged")
    if fv > FORMAT_VERSION:
        raise BackupError("newer_backup")
    counts = data.get("counts")
    app_version, created_at, sha = data.get("app_version"), data.get("created_at"), data.get("db_sha256")
    if not (isinstance(counts, dict) and isinstance(app_version, str) and isinstance(created_at, str)):
        raise BackupError("damaged")
    if not (isinstance(sha, str) and _SHA.match(sha)):
        raise BackupError("damaged")
    try:
        datetime.fromisoformat(created_at)
    except ValueError:
        raise BackupError("damaged") from None
    return Manifest(
        app_version=app_version[:40],
        schema_version=_int(data, "schema_version"),
        created_at=created_at,
        counts=Counts(_int(counts, "games"), _int(counts, "attempts"), _int(counts, "coach_reports")),
        db_sha256=sha,
        db_size=_int(data, "db_size"),
    )


def check_restorable(m: Manifest, known_schema: int) -> None:
    """NFR-3: a backup from a newer schema is refused untouched; an older one is migrated after the restore."""
    if m.schema_version > known_schema:
        raise BackupError("newer_backup")
    if m.schema_version < 1:
        raise BackupError("damaged")


# ---- names --------------------------------------------------------------------------------------
def manual_file_name(local: datetime) -> str:
    """The Save dialog's suggestion (FR-15.1)."""
    return f"{AUTO_PREFIX}{local:%Y-%m-%d}.zip"


def auto_file_name(local: datetime) -> str:
    """Automatic backups carry the time too, so two on one day never collide."""
    return f"{AUTO_PREFIX}{local:%Y-%m-%d-%H%M%S}.zip"


def before_restore_name(local: datetime) -> str:
    return f"{BEFORE_RESTORE_PREFIX}{local:%Y-%m-%d-%H%M%S}.zip"


_AUTO_NAME = re.compile(rf"^{re.escape(AUTO_PREFIX)}\d{{4}}-\d{{2}}-\d{{2}}(-\d{{6}})?(-\d+)?\.zip$")
_BEFORE_NAME = re.compile(rf"^{re.escape(BEFORE_RESTORE_PREFIX)}\d{{4}}-\d{{2}}-\d{{2}}-\d{{6}}(-\d+)?\.zip$")


def is_auto_name(name: str) -> bool:
    return bool(_AUTO_NAME.match(name))


def is_before_restore_name(name: str) -> bool:
    return bool(_BEFORE_NAME.match(name))


# ---- automatic backups (FR-15.3) ----------------------------------------------------------------
@dataclass(frozen=True)
class AutoSettings:
    enabled: bool = False
    folder: str | None = None
    interval_days: int = DEFAULT_INTERVAL_DAYS
    keep: int = DEFAULT_KEEP


def checked_auto_settings(enabled: bool, folder: str | None, interval_days: int, keep: int) -> AutoSettings:
    lo, hi = INTERVAL_RANGE
    if not lo <= interval_days <= hi:
        raise ValidationError(f"How often must be between {lo} and {hi} days.")
    lo, hi = KEEP_RANGE
    if not lo <= keep <= hi:
        raise ValidationError(f"How many to keep must be between {lo} and {hi}.")
    folder = folder.strip() if folder else None
    if enabled and not folder:
        raise ValidationError("Choose a folder for automatic backups first.")
    return AutoSettings(enabled, folder or None, interval_days, keep)


def next_due(last_at: datetime | None, interval_days: int, enabled_at: datetime | None) -> datetime | None:
    """When the next automatic backup is due. With none made yet, it's due as soon as automatic backups are on."""
    if last_at is not None:
        return last_at + timedelta(days=interval_days)
    return enabled_at


def is_due(now: datetime, due: datetime | None) -> bool:
    return due is not None and now >= due


def seconds_until_check(now: datetime, due: datetime | None) -> float:
    """How long the timer waits: until the due time, but at least a minute and never more than RECHECK_S."""
    if due is None:
        return RECHECK_S
    return max(MIN_WAIT_S, min(RECHECK_S, (due - now).total_seconds()))


def stale(found: list[tuple[str, str]], keep: int) -> list[str]:
    """Which backups to delete, given (name, created_at) of the files that are ours. The newest `keep` stay."""
    ordered = sorted(found, key=lambda f: (_instant(f[1]), f[0]))
    return [name for name, _ in ordered[: max(0, len(ordered) - keep)]]


def _instant(iso: str) -> datetime:
    at = datetime.fromisoformat(iso)
    return at if at.tzinfo is not None else at.replace(tzinfo=UTC)


# ---- restore while jobs run (FR-15.4) -----------------------------------------------------------
_JOB_NAMES = {
    "game_analysis": "the game analysis",
    "game_puzzles": "the game analysis",
    "coach_run": "the Coach report",
    "coach_ai": "the AI coaching",
    "puzzle_import": "the puzzle database import",
    "puzzle_file_import": "the puzzle file import",
    "games_sync": "the game sync",
    "game_url_import": "the game import",
    "lichess_sync": "the Lichess sync",
    "lichess_history_import": "the Lichess history import",
    "stockfish_install": "the Stockfish install",
    "repertoire_build": "the repertoire build",
    "study_add": "the study download",
    "study_update": "the study update",
    "explain": "the AI explanation",
    "backup": "the backup",
}


def busy_message(kinds: list[str]) -> str:
    names = sorted({_JOB_NAMES.get(k, "a background task") for k in kinds})
    what = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    return f"Wait for {what} to finish, or cancel it, then restore."
