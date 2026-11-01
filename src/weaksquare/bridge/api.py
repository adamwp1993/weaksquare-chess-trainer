"""The JS-facing API (pywebview `js_api`). Thin: validate, delegate to services, return DTOs.

pywebview exposes every public method and every public nested object to JavaScript, so all
dependencies live in underscore attributes, and every public method is wrapped by `@bridge_call`.
`tests/contract/test_bridge_allowlist.py` pins the exact set of public names: adding a method
means updating that allowlist in the same commit (ARCHITECTURE §3 decision 13).
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from weaksquare.adapters.desktop import Desktop
from weaksquare.bridge import dto
from weaksquare.bridge.dto import AppInfo, Job, PuzzleDbStatus
from weaksquare.bridge.errors import bridge_call
from weaksquare.bridge.events import job_dto
from weaksquare.config import APP_VERSION, LICENSE_NAME, REPO_URL, Paths
from weaksquare.core.clock import Clock
from weaksquare.core.errors import NotFoundError, ValidationError
from weaksquare.core.filters import FilterSpec
from weaksquare.core.themes import display_name
from weaksquare.jobs.runner import JobRunner
from weaksquare.services.mixer import LAST_FILTERS_KEY, MixerService
from weaksquare.services.presets import Preset, PresetService
from weaksquare.services.puzzle_db import PuzzleDbService
from weaksquare.services.session import SessionService

log = logging.getLogger("weaksquare.frontend")

FRONTEND_ERRORS_PER_MINUTE = 20


class Api:
    def __init__(
        self,
        *,
        paths: Paths,
        desktop: Desktop,
        clock: Clock,
        dev_mode: bool,
        runner: JobRunner,
        puzzle_db: PuzzleDbService,
        mixer: MixerService,
        sessions: SessionService,
        presets: PresetService,
    ) -> None:
        self._presets = presets
        self._mixer = mixer
        self._sessions = sessions
        self._paths = paths
        self._runner = runner
        self._puzzle_db = puzzle_db
        self._desktop = desktop
        self._clock = clock
        self._dev_mode = dev_mode
        self._fe_window_start = 0
        self._fe_count = 0

    @bridge_call
    def get_app_info(self) -> AppInfo:
        status = self._puzzle_db.status()
        return AppInfo(
            version=APP_VERSION,
            data_dir=str(self._paths.data_dir),
            logs_dir=str(self._paths.logs_dir),
            dev_mode=self._dev_mode,
            license=LICENSE_NAME,
            source_url=REPO_URL,
            puzzle_db_export_date=status.export_date,
            puzzle_count=status.puzzle_count,
        )

    @bridge_call
    def open_folder(self, kind: Literal["data", "logs"]) -> None:
        self._desktop.open_folder(self._paths.data_dir if kind == "data" else self._paths.logs_dir)

    @bridge_call
    def log_frontend_error(self, message: str, source: str) -> None:
        """Front-end errors (window.onerror, unhandled rejections), rate-limited (NFR-4)."""
        now = self._clock.monotonic_ms()
        if now - self._fe_window_start > 60_000:
            self._fe_window_start, self._fe_count = now, 0
        self._fe_count += 1
        if self._fe_count <= FRONTEND_ERRORS_PER_MINUTE:
            log.error("front end [%s]: %s", source[:200], message[:2000])
        elif self._fe_count == FRONTEND_ERRORS_PER_MINUTE + 1:
            log.error("front end: more errors this minute were dropped")

    # ---- puzzle database (FR-2.1–2.3) -------------------------------------------------------
    @bridge_call
    def get_puzzle_db_status(self) -> PuzzleDbStatus:
        s = self._puzzle_db.status()
        return PuzzleDbStatus(
            s.installed, s.puzzle_count, s.export_date, s.imported_at, s.rating_min, s.rating_max, s.import_job_id,
            s.needs_upgrade,
        )  # fmt: skip

    @bridge_call
    def choose_puzzle_file(self) -> str | None:
        return self._desktop.choose_puzzle_file()

    @bridge_call
    def start_puzzle_import(self, local_path: str | None = None) -> str:
        """Start the import job: download from Lichess, or import `local_path`. Returns the job ID."""
        if local_path is not None and (len(local_path) > 1000 or chr(0) in local_path):
            raise ValidationError("That isn't a valid file path.")
        return self._puzzle_db.start_import(local_path)

    @bridge_call
    def start_puzzle_db_upgrade(self) -> str:
        """Rebuild an older-schema puzzles.db from its own rows (no download). Returns the job ID."""
        return self._puzzle_db.start_upgrade()

    # ---- jobs -----------------------------------------------------------------------------------
    @bridge_call
    def get_job(self, job_id: str) -> Job:
        status = self._runner.status(job_id)
        if status is None:
            raise NotFoundError("No such job.")
        return job_dto(status)

    @bridge_call
    def cancel_job(self, job_id: str) -> bool:
        return self._runner.cancel(job_id)

    # ---- settings (UI state persists here, never in browser storage) ---------------------------
    @bridge_call
    def get_settings(self) -> dto.UiSettings:
        stored = self._mixer.ui_settings().get(LAST_FILTERS_KEY)
        return dto.UiSettings(last_filters=FilterSpec.from_json(stored) if stored else None)

    @bridge_call
    def set_setting(self, key: Literal["mixer.filters"], value: Any) -> None:
        self._mixer.set_ui_setting(key, value)

    # ---- the mixer (FR-3.1–3.5) -----------------------------------------------------------------
    @bridge_call
    def get_theme_catalog(self) -> list[dto.ThemeGroup]:
        return [
            dto.ThemeGroup(g.name, [dto.ThemeOption(t.key, t.name, t.count) for t in g.themes])
            for g in self._mixer.theme_catalog()
        ]

    @bridge_call
    def count_matches(self, spec: dict) -> int:
        return self._mixer.count(FilterSpec.from_json(spec))

    @bridge_call
    def count_buckets(self, spec: dict) -> list[int]:
        """The live count of each ratio group (FR-3.10)."""
        return self._mixer.bucket_counts(FilterSpec.from_json(spec))

    @bridge_call
    def get_opening_catalog(self) -> list[dto.OpeningFamily]:
        def opt(o: Any) -> dto.OpeningOption:
            return dto.OpeningOption(o.tag, o.name, o.count)

        return [dto.OpeningFamily(opt(f.family), [opt(v) for v in f.variations]) for f in self._mixer.opening_catalog()]

    # ---- presets (FR-3.13) ------------------------------------------------------------------
    @staticmethod
    def _preset(p: Preset) -> dto.Preset:
        return dto.Preset(p.name, p.spec, p.error, p.updated_at)

    @bridge_call
    def list_presets(self) -> list[dto.Preset]:
        return [self._preset(p) for p in self._presets.list()]

    @bridge_call
    def save_preset(self, name: str, spec: dict, overwrite: bool = False) -> dto.Preset:
        return self._preset(self._presets.save(name, FilterSpec.from_json(spec), overwrite))

    @bridge_call
    def rename_preset(self, old_name: str, new_name: str) -> None:
        self._presets.rename(old_name, new_name)

    @bridge_call
    def delete_preset(self, name: str) -> None:
        self._presets.delete(name)

    # ---- sessions (FR-3.11, 3.12, 3.14, FR-4.1, FR-5.1, 5.3) -----------------------------------
    @bridge_call
    def start_session(self, spec: dict) -> dto.SessionInfo:
        info = self._sessions.start(FilterSpec.from_json(spec))
        return dto.SessionInfo(info.session_id, info.match_count, info.queue_size, info.empty_buckets)

    @bridge_call
    def next_puzzle(self, session_id: int) -> dto.PuzzleView | None:
        v = self._sessions.next_puzzle(session_id)
        if v is None:
            return None
        color: Literal["white", "black"] = "white" if v.player_color == "white" else "black"
        return dto.PuzzleView(v.number, v.puzzle_id, v.fen, v.opponent_move, color, v.rating)

    @bridge_call
    def submit_move(self, session_id: int, uci: str) -> dto.MoveFeedback:
        r = self._sessions.submit_move(session_id, uci[:8])
        outcome = None
        if r.outcome is not None:
            o = r.outcome
            outcome = dto.Outcome(
                win=o.win,
                puzzle_id=o.puzzle_id,
                rating=o.rating,
                themes=[dto.ThemeLabel(t, display_name(t)) for t in o.themes],
                solution=o.solution,
                puzzle_url=f"https://lichess.org/training/{o.puzzle_id}",
            )
        f = r.feedback
        return dto.MoveFeedback(f.kind, f.reply, f.finished, outcome)

    @bridge_call
    def get_session_stats(self, session_id: int) -> dto.SessionStats:
        s = self._sessions.stats(session_id)
        return dto.SessionStats(s.solved, s.failed, s.accuracy, s.played, s.queue_size, s.finished,
                                s.all_time_solved, s.all_time_failed)  # fmt: skip
