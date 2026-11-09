"""Backup and restore (FR-15, v0.16).

- Back up now: one background job writes a checked backup file where you chose.
- Restore: refused while any job runs. A `backup_restore` job checks the whole file and stages it; then
  the app restarts, and the swap happens at startup before anything opens user.db (Adam, v0.16 planning).
- Automatic backups: off by default; checked at launch and then on a timer that looks again at least
  hourly. A missing folder is recorded and shown, and tried again next time (FR-15.3).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from weaksquare.core.backup import (
    AutoSettings,
    Manifest,
    auto_file_name,
    busy_message,
    check_restorable,
    checked_auto_settings,
    is_auto_name,
    is_due,
    next_due,
    seconds_until_check,
)
from weaksquare.core.clock import Clock
from weaksquare.core.errors import AppError, ConflictError, ValidationError
from weaksquare.jobs.runner import CancelToken, JobFailed, JobRunner, ProgressFn

log = logging.getLogger(__name__)

JOB_KIND = "backup"
RESTORE_JOB = "backup_restore"

AUTO_KEY = "backup.auto"
ENABLED_AT_KEY = "backup.enabled_at"
LAST_AUTO_KEY = "backup.last_auto_at"
LAST_KEY = "backup.last_at"
ERROR_KEY = "backup.last_error"

SAVE_FAILED = "The backup couldn't be saved there. Check the drive has room and you can write to that folder."
FOLDER_MISSING = "The automatic backup folder isn't available (is the drive plugged in?). It will try again next time."
WRITE_FAILED = "The last automatic backup couldn't be saved. It will try again next time."


class Settings(Protocol):
    def get(self, key: str) -> Any | None: ...
    def set(self, key: str, value: Any) -> None: ...


class Scheduler(Protocol):
    def call_later(self, delay_s: float, fn: Callable[[], None]) -> None: ...


class Files(Protocol):
    def make_backup(self, target: Path, created_at: str) -> Manifest: ...
    def read_manifest(self, path: Path) -> Manifest: ...
    def stage_restore(self, path: Path) -> Manifest: ...
    def discard_staged(self) -> None: ...
    def folder_exists(self, folder: Path) -> bool: ...
    def prune(self, folder: Path, is_ours: Callable[[str], bool], keep: int) -> list[str]: ...


@dataclass(frozen=True)
class RestoreNotice:
    """What the last start did with a staged restore, shown once in the UI."""

    created_at: str | None
    app_version: str | None
    error: str | None


@dataclass(frozen=True)
class BackupStatus:
    auto: AutoSettings
    last_at: str | None
    next_due: str | None
    last_error: str | None


class BackupService:
    def __init__(
        self,
        files: Files,
        settings: Settings,
        runner: JobRunner,
        clock: Clock,
        scheduler: Scheduler,
        known_schema: int,
        restart: Callable[[], None],
        notice: RestoreNotice | None = None,
    ) -> None:
        self._files = files
        self._settings = settings
        self._runner = runner
        self._clock = clock
        self._scheduler = scheduler
        self._known_schema = known_schema
        self._restart = restart
        self._notice = notice
        self._lock = threading.Lock()
        self._generation = 0

    # ---- settings and status --------------------------------------------------------------------
    def auto_settings(self) -> AutoSettings:
        raw = self._settings.get(AUTO_KEY)
        if not isinstance(raw, dict):
            return AutoSettings()
        try:
            return checked_auto_settings(
                bool(raw.get("enabled", False)), raw.get("folder") if isinstance(raw.get("folder"), str) else None,
                int(raw.get("interval_days", 7)), int(raw.get("keep", 5)),
            )  # fmt: skip
        except (ValidationError, TypeError, ValueError):
            return AutoSettings()

    def set_auto_settings(self, enabled: bool, folder: str | None, interval_days: int, keep: int) -> BackupStatus:
        new = checked_auto_settings(enabled, folder, interval_days, keep)
        old = self.auto_settings()
        if new.enabled and not (old.enabled and old.folder == new.folder):
            self._settings.set(ENABLED_AT_KEY, self._clock.now().isoformat())
        if new.folder != old.folder or not new.enabled:
            self._settings.set(ERROR_KEY, None)
        self._settings.set(AUTO_KEY, {"enabled": new.enabled, "folder": new.folder,
                                      "interval_days": new.interval_days, "keep": new.keep})  # fmt: skip
        self._schedule(1.0)
        return self.status()

    def _due(self, s: AutoSettings) -> datetime | None:
        if not s.enabled:
            return None
        return next_due(self._time(LAST_AUTO_KEY), s.interval_days, self._time(ENABLED_AT_KEY))

    def _time(self, key: str) -> datetime | None:
        v = self._settings.get(key)
        if not isinstance(v, str):
            return None
        try:
            return datetime.fromisoformat(v)
        except ValueError:
            return None

    def status(self) -> BackupStatus:
        s = self.auto_settings()
        due = self._due(s)
        err = self._settings.get(ERROR_KEY)
        last = self._time(LAST_KEY)
        return BackupStatus(s, last.isoformat() if last else None, due.isoformat() if due else None,
                            err if isinstance(err, str) else None)  # fmt: skip

    def take_notice(self) -> RestoreNotice | None:
        """The result of a restore at this start, once."""
        with self._lock:
            notice, self._notice = self._notice, None
        return notice

    # ---- back up now (FR-15.1) ------------------------------------------------------------------
    def _busy_with_backup(self) -> bool:
        return bool(self._runner.active(JOB_KIND) or self._runner.active(RESTORE_JOB))

    def backup_now(self, path: str) -> str:
        target = Path(path.strip())
        if not path.strip():
            raise ValidationError("Choose where to save the backup.")
        if target.suffix.lower() != ".zip":
            target = target.with_name(target.name + ".zip")
        if not self._files.folder_exists(target.parent):
            raise ValidationError("That folder doesn't exist. Choose another place to save the backup.")
        if self._busy_with_backup():
            raise ConflictError("A backup or restore is already running.")

        def run(progress: ProgressFn, token: CancelToken) -> str:
            progress(None, "Backing up your data…")
            try:
                m = self._files.make_backup(target, self._clock.now().isoformat())
            except AppError as e:
                raise JobFailed(e.code, e.message, e.retryable) from e
            except OSError as e:
                log.exception("backup failed")
                raise JobFailed("write_failed", SAVE_FAILED) from e
            self._settings.set(LAST_KEY, m.created_at)
            return f"Backed up {m.counts.games} games, {m.counts.attempts} puzzle attempts and {m.counts.coach_reports} Coach reports."

        return self._runner.submit(JOB_KIND, run)

    # ---- restore (FR-15.4) ----------------------------------------------------------------------
    def inspect(self, path: str) -> Manifest:
        """What's in a backup, or why it can't be restored. Reads only the manifest; the restore checks everything."""
        m = self._files.read_manifest(Path(path))
        check_restorable(m, self._known_schema)
        return m

    def restore(self, path: str) -> str:
        busy = [s.kind for s in self._runner.active()]
        if busy:
            raise ConflictError(busy_message(busy))
        source = Path(path)
        check_restorable(self._files.read_manifest(source), self._known_schema)

        def run(progress: ProgressFn, token: CancelToken) -> str:
            progress(None, "Checking the backup…")
            try:
                m = self._files.stage_restore(source)
                check_restorable(m, self._known_schema)
            except AppError as e:  # damaged, newer, no space: the reason reaches the UI (NFR-5)
                self._files.discard_staged()
                raise JobFailed(e.code, e.message, e.retryable) from e
            except BaseException:
                self._files.discard_staged()
                raise
            log.info("restore staged (backup from %s, schema %d); restarting", m.created_at, m.schema_version)
            self._restart()
            return "Restarting to finish the restore…"

        return self._runner.submit(RESTORE_JOB, run)

    # ---- automatic backups (FR-15.3) ------------------------------------------------------------
    def start(self) -> None:
        """At launch: a backup that came due while the app was closed runs now."""
        self._tick(self._generation)

    def _schedule(self, delay_s: float) -> None:
        with self._lock:
            self._generation += 1
            gen = self._generation
        self._scheduler.call_later(delay_s, lambda: self._tick(gen))

    def _tick(self, gen: int) -> None:
        with self._lock:
            if gen != self._generation:
                return  # settings changed; a newer timer took over
        s = self.auto_settings()
        due = self._due(s)
        if s.enabled and is_due(self._clock.now(), due) and not self._busy_with_backup():
            self._run_auto(s)
        if s.enabled:
            self._schedule(seconds_until_check(self._clock.now(), self._due(s)))

    def _run_auto(self, s: AutoSettings) -> None:
        assert s.folder is not None
        folder = Path(s.folder)
        if not self._files.folder_exists(folder):
            log.warning("automatic backup folder is missing")
            self._settings.set(ERROR_KEY, FOLDER_MISSING)
            return

        def run(progress: ProgressFn, token: CancelToken) -> str:
            now = self._clock.now()
            try:
                progress(None, "Automatic backup…")
                m = self._files.make_backup(folder / auto_file_name(now.astimezone()), now.isoformat())
                removed = self._files.prune(folder, is_auto_name, s.keep)
            except Exception:  # a full drive, a pulled USB stick, a snapshot that failed its check: all reported
                log.exception("automatic backup failed")
                self._settings.set(ERROR_KEY, WRITE_FAILED)
                return "The automatic backup couldn't be saved."
            self._settings.set(LAST_AUTO_KEY, m.created_at)
            self._settings.set(LAST_KEY, m.created_at)
            self._settings.set(ERROR_KEY, None)
            log.info("automatic backup saved; %d old ones removed", len(removed))
            return "Automatic backup saved."

        self._runner.submit(JOB_KIND, run)
