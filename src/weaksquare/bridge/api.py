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
from weaksquare.core.errors import ConflictError, NotFoundError, ValidationError
from weaksquare.core.filters import FilterSpec
from weaksquare.core.ladder import LEVEL_NAMES, LEVELS, LadderStatus
from weaksquare.core.reasons import REASONS
from weaksquare.core.themes import display_name
from weaksquare.jobs.runner import JobRunner
from weaksquare.services.account import AccountService
from weaksquare.services.db_update import UpdateCheckService
from weaksquare.services.engine import Analysis as AnalysisResult
from weaksquare.services.engine import EngineService
from weaksquare.services.lichess_history import HistoryService
from weaksquare.services.mixer import MixerService
from weaksquare.services.presets import Preset, PresetService
from weaksquare.services.puzzle_db import PuzzleDbService
from weaksquare.services.reasons import ReasonsService
from weaksquare.services.session import SessionService
from weaksquare.services.stats import StatsService
from weaksquare.services.sync import RatingInfo, SyncService
from weaksquare.services.ui_settings import UiSettingsService

log = logging.getLogger("weaksquare.frontend")

FRONTEND_ERRORS_PER_MINUTE = 20
MAX_RATING_IDS = 200


def ladder_info(s: LadderStatus) -> dto.LadderInfo:
    return dto.LadderInfo(s.level, LEVEL_NAMES[s.level], s.step, len(LEVELS), s.played, s.wins, s.window,
                          s.threshold, s.top)  # fmt: skip


def attempt_rating(r: RatingInfo | None) -> dto.AttemptRating | None:
    if r is None:
        return None
    return dto.AttemptRating(r.attempt_id, r.status, r.diff if r.status == "done" else None)


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
        stats: StatsService,
        ui_settings: UiSettingsService,
        db_update: UpdateCheckService,
        account: AccountService,
        sync: SyncService,
        history: HistoryService,
        engine: EngineService,
        reasons: ReasonsService,
    ) -> None:
        self._engine = engine
        self._reasons = reasons
        self._account = account
        self._sync = sync
        self._history = history
        self._db_update = db_update
        self._ui_settings = ui_settings
        self._stats = stats
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

    # ---- update check (FR-2.5) -----------------------------------------------------------------
    @bridge_call
    def check_for_db_update(self, force: bool = False) -> str:
        """Start the update check job (automatic at launch, or "Check for updates"). Returns the job ID."""
        return self._db_update.start_check(force)

    @bridge_call
    def get_update_offer(self) -> dto.UpdateOffer | None:
        o = self._db_update.current_offer()
        if o is None:
            return None
        return dto.UpdateOffer(o.export_date, o.current_export_date, o.size, o.approx_count, o.approx_new)

    @bridge_call
    def dismiss_update(self, kind: Literal["not_now", "skip"]) -> None:
        self._db_update.dismiss(kind)

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
        s = self._ui_settings.get()
        snd = s.sounds
        sound_set: Literal["sfx", "piano", "nes", "futuristic"] = (
            snd.set if snd.set in ("piano", "nes", "futuristic") else "sfx"  # type: ignore[assignment]
        )
        return dto.UiSettings(
            last_filters=s.last_filters,
            coordinates=s.coordinates,
            color_scheme=s.color_scheme,
            sounds=dto.SoundSettings(snd.on, snd.volume, sound_set),
            auto_check=s.auto_check,
            mode=s.mode,  # type: ignore[arg-type]
            show_length=s.show_length,
            ladder_threshold=s.ladder_threshold,
            ladder_window=s.ladder_window,
            srs_intervals=list(s.srs_intervals),
            filters_collapsed=s.filters_collapsed,
            time_offset_days=self._time_offset(),
            reasons_ask="off" if s.reasons_ask == "off" else "always",
            rushed_s=s.rushed_s,
        )

    def _time_offset(self) -> int | None:
        offset = getattr(self._clock, "offset_days", None)
        return offset if self._dev_mode and isinstance(offset, int) else None

    @bridge_call
    def set_setting(
        self,
        key: Literal[
            "mixer.filters",
            "ui.coordinates",
            "ui.color_scheme",
            "ui.sounds",
            "puzzle_db.auto_check",
            "trainer.mode",
            "commit.show_length",
            "ladder.threshold",
            "ladder.window",
            "srs.intervals",
            "ui.filters_collapsed",
            "reasons.ask",
            "reasons.rushed_s",
        ],
        value: Any,
    ) -> None:
        self._ui_settings.set(key, value)

    # ---- the mixer (FR-3.1–3.5) -----------------------------------------------------------------
    @bridge_call
    def get_theme_catalog(self) -> list[dto.ThemeGroup]:
        return [
            dto.ThemeGroup(g.name, [dto.ThemeOption(t.key, t.name, t.count) for t in g.themes])
            for g in self._mixer.theme_catalog()
        ]

    @bridge_call
    def count_matches(self, spec: dict) -> int:
        parsed = FilterSpec.from_json(spec)
        if parsed.depth_ladder:  # the current level's pool (FR-4.5), from one scan (v0.5-B7)
            return self._sessions.ladder_preview(parsed)[2]
        return self._mixer.count(parsed)

    @bridge_call
    def count_buckets(self, spec: dict) -> dto.BucketCounts:
        """A ratio mix's live counts (FR-3.10): the total and each group, in one call and one scan."""
        total, buckets = self._mixer.counts_with_buckets(FilterSpec.from_json(spec))
        return dto.BucketCounts(total, buckets)

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
    def set_time_offset(self, days: int) -> None:
        """FR-4.6 fast-forward time: move the app's clock ahead by whole days. `--dev` runs only."""
        setter = getattr(self._clock, "set_offset_days", None)
        if not self._dev_mode or setter is None:
            raise ConflictError("Fast-forward time is only available in --dev runs.")
        try:
            setter(days)
        except ValueError as e:
            raise ValidationError(str(e)) from None
        self._ui_settings.set_time_offset_days(days)

    @bridge_call
    def start_session(
        self,
        spec: dict,
        rated: bool = True,
        mode: dto.TrainingMode = "standard",
        show_length: bool = False,
    ) -> dto.SessionInfo:
        """`rated`: the session's Rated toggle (FR-1.9); off syncs every solve as rated: false.
        `mode` (v0.5, §6); `show_length`: Commit the line's Show move count (FR-4.2)."""
        info = self._sessions.start(FilterSpec.from_json(spec), rated, mode, show_length)
        return dto.SessionInfo(info.session_id, info.match_count, info.queue_size, info.empty_buckets,
                               info.mode)  # type: ignore[arg-type]  # fmt: skip

    @bridge_call
    def get_srs_status(self) -> dto.SrsStatus:
        s = self._sessions.srs_status()
        return dto.SrsStatus(s.due, s.next_due, s.scheduled)

    @bridge_call
    def get_ladder_status(self, spec: dict) -> dto.LadderPreview:
        """The level a depth-ladder session with these filters would start at, and its pool size (FR-4.5)."""
        st, _, count = self._sessions.ladder_preview(FilterSpec.from_json(spec))
        return dto.LadderPreview(ladder_info(st), count)

    @bridge_call
    def submit_line(self, session_id: int, moves: list) -> dto.CommitFeedback:
        """Commit the line (FR-4.2): grade the whole line you entered."""
        r = self._sessions.submit_line(session_id, moves[:200])
        c = r.result
        return dto.CommitFeedback(
            [dto.PlyGrade(g.played, g.expected, g.player, g.correct) for g in c.grades], list(c.extra),
            c.replies_correct, c.replies_total, c.win, self._outcome(r.outcome), list(c.line_sounds),
        )  # fmt: skip

    @bridge_call
    def next_puzzle(self, session_id: int) -> dto.PuzzleView | None:
        v = self._sessions.next_puzzle(session_id)
        if v is None:
            return None
        color: Literal["white", "black"] = "white" if v.player_color == "white" else "black"
        return dto.PuzzleView(
            v.number,
            v.puzzle_id,
            v.fen,
            v.opponent_move,
            color,
            v.rating,
            v.opponent_sound,
            v.already_played,
            v.mode,  # type: ignore[arg-type]
            v.solution_plies,
            v.max_plies,
            v.candidate,
        )

    @staticmethod
    def _outcome(o: Any) -> dto.Outcome | None:
        if o is None:
            return None
        return dto.Outcome(
            win=o.win,
            puzzle_id=o.puzzle_id,
            rating=o.rating,
            themes=[dto.ThemeLabel(t, display_name(t)) for t in o.themes],
            solution=o.solution,
            puzzle_url=f"https://lichess.org/training/{o.puzzle_id}",
            attempt_id=o.attempt_id,
            lichess=attempt_rating(o.lichess),
            level_up=ladder_info(o.level_up) if o.level_up else None,
            idea=idea_result(o.idea) if o.idea else None,
            danger=danger_reveal(o.danger) if o.danger else None,
        )

    @bridge_call
    def submit_move(self, session_id: int, uci: str) -> dto.MoveFeedback:
        r = self._sessions.submit_move(session_id, uci[:8])
        f = r.feedback
        return dto.MoveFeedback(f.kind, f.reply, f.finished, self._outcome(r.outcome), f.move_sound, f.reply_sound)

    @bridge_call
    def set_idea_tags(self, session_id: int, setup: list, payoff: list) -> None:
        """Name the idea first (FR-4.3): your setup and payoff tags, before your first move."""
        self._sessions.set_idea_tags(session_id, setup[:10], payoff[:10])

    @bridge_call
    def call_danger(self, session_id: int, call: Literal["safe", "unsafe"]) -> dto.DangerFeedback:
        """Danger spotting (FR-4.4): is the highlighted move safe?"""
        r = self._sessions.call_danger(session_id, call)
        c = r.result
        return dto.DangerFeedback(c.call, c.correct, c.refute, c.fen, c.blunder_sound,  # type: ignore[arg-type]
                                  self._outcome(r.outcome))  # fmt: skip

    @bridge_call
    def get_reason_prompt(self, session_id: int) -> dto.ReasonPrompt | None:
        """§7.3: after a lost puzzle, the reason chips and the suggested one (None: don't ask)."""
        p = self._sessions.reason_prompt(session_id)
        if p is None:
            return None
        return dto.ReasonPrompt(p.attempt_id, p.source, p.suggested,  # type: ignore[arg-type]
                                [dto.ReasonOption(r.key, r.label, r.gap) for r in REASONS])  # fmt: skip

    @bridge_call
    def set_mistake_reason(self, attempt_id: int, reason: str, note: str | None = None) -> None:
        """Save why you missed it (FR-5.6). Choosing again replaces it; the latest counts."""
        self._reasons.set_reason(attempt_id, reason, note)

    @bridge_call
    def request_help(self, session_id: int, kind: Literal["hint", "answer"]) -> dto.HelpResponse:
        """The stuck ladder (§7.2): Hint, then Show answer. Before the end, either is a loss."""
        r = self._sessions.request_help(session_id, kind)
        h = r.help
        return dto.HelpResponse(
            h.kind, h.hint_square, h.answer_fen, list(h.answer_moves), self._outcome(r.outcome), list(h.answer_sounds),
            h.refute,
        )  # fmt: skip

    # ---- stats (FR-9.1, 9.2) ---------------------------------------------------------------------
    @bridge_call
    def get_stats(self) -> dto.StatsReport:
        r = self._stats.report()

        def row(t: Any) -> dto.StatRow:
            return dto.StatRow(t.key, t.label, t.attempts, t.solved, t.accuracy, t.first_right, t.line_wrong_rate)

        d = r.details
        return dto.StatsReport(
            row(r.overall), [row(t) for t in r.by_theme], [row(t) for t in r.by_length],
            [row(t) for t in r.by_rating], r.missing, [row(t) for t in r.by_mode], r.misclicks, r.misclick_warning,
            dto.ModeDetails(d.replies_correct, d.replies_total, d.ideas_found, d.ideas_total, d.tags_named,
                            d.danger_safe, d.danger_safe_right, d.danger_blunder, d.danger_blunder_right),
        )  # fmt: skip

    @bridge_call
    def get_reason_stats(self, theme: str | None = None, mode: str | None = None) -> dto.ReasonStats:
        """FR-9.7: the mistake-reason breakdown, optionally for one theme and/or one mode."""
        r = self._stats.reasons(theme, mode)
        return dto.ReasonStats(
            [dto.ReasonStatRow(c.key, c.label, c.gap, c.count, c.share) for c in r.reasons],  # type: ignore[arg-type]
            r.tagged, r.untagged, r.misclicks, r.misclick_warning,
            [dto.ReasonWeek(w.week.isoformat(), list(w.counts)) for w in r.trend],
        )  # fmt: skip

    @bridge_call
    def retry_puzzle(self, session_id: int) -> None:
        """FR-5.12 Try again (not scored): replay the finished puzzle from its start; nothing is recorded."""
        self._sessions.retry(session_id)

    @bridge_call
    def get_session_stats(self, session_id: int) -> dto.SessionStats:
        s = self._sessions.stats(session_id)
        return dto.SessionStats(s.solved, s.failed, s.accuracy, s.played, s.queue_size, s.finished,
                                s.all_time_solved, s.all_time_failed, s.rating_change, s.mode,  # type: ignore[arg-type]
                                ladder_info(s.ladder) if s.ladder else None, s.misclicks)  # fmt: skip

    # ---- Lichess account and sync (FR-1.1, 1.6, 1.7, FR-6.1–6.17, FR-9.4) ------------------------
    # Nothing here ever returns a token (SR-1); the token stays inside the services.
    @bridge_call
    def get_account_status(self) -> dto.AccountStatus:
        s = self._account.status()
        return dto.AccountStatus(s.state, s.username, s.rating, s.provisional)

    @bridge_call
    def start_sign_in(self) -> str:
        """Opens Lichess in your default browser and waits for the callback. Returns the job ID."""
        return self._account.start_sign_in()

    @bridge_call
    def cancel_sign_in(self) -> None:
        self._account.cancel_sign_in()

    @bridge_call
    def sign_out(self, force_local: bool = False) -> None:
        """Revoke on Lichess, then delete the local copy (FR-6.6). `force_local` removes it from this PC
        even when Lichess can't be reached."""
        self._account.sign_out(force_local)

    @bridge_call
    def get_sync_status(self) -> dto.SyncStatus:
        s = self._sync.status()
        return dto.SyncStatus(s.state, s.pending, self._history.count())

    @bridge_call
    def get_attempt_ratings(self, attempt_ids: list) -> list[dto.AttemptRating]:
        if len(attempt_ids) > MAX_RATING_IDS or not all(
            isinstance(i, int) and not isinstance(i, bool) and i > 0 for i in attempt_ids
        ):
            raise ValidationError(f"attempt_ids must be up to {MAX_RATING_IDS} positive whole numbers")
        return [r for r in (attempt_rating(x) for x in self._sync.attempt_ratings(attempt_ids)) if r is not None]

    @bridge_call
    def get_rating_history(self) -> dto.RatingHistory:
        h = self._stats.rating_history()
        return dto.RatingHistory(
            [dto.RatingPoint(p.at, p.rating, p.session_id) for p in h.points],
            [dto.SessionChange(c.session_id, c.started_at, c.change, c.solves) for c in h.sessions],
        )

    # ---- engine (FR-7.1–7.7, §7.2 step 2) ----------------------------------------------------------
    # Engine output exists only after a puzzle ends; SessionService refuses earlier calls (FR-7.3).
    @bridge_call
    def get_engine_status(self) -> dto.EngineStatus:
        s = self._engine.status()
        return dto.EngineStatus(s.state, s.source, s.name, s.path, s.tag, s.install_job_id, s.message)

    @bridge_call
    def start_engine_install(self, force: bool = False) -> str:
        """Install (or with `force`, reinstall) the pinned Stockfish as a background job (FR-7.5)."""
        return self._engine.start_install(force)

    @bridge_call
    def get_engine_settings(self) -> dto.EngineSettings:
        return self._engine_settings()

    @bridge_call
    def set_engine_settings(
        self, think_s: float | None = None, threads: int | None = None, hash_mb: int | None = None
    ) -> dto.EngineSettings:
        self._engine.set_settings(think_s, threads, hash_mb)
        return self._engine_settings()

    def _engine_settings(self) -> dto.EngineSettings:
        s = self._engine.settings()
        return dto.EngineSettings(s.think_s, s.threads, s.hash_mb, s.custom_path, s.max_threads)

    @bridge_call
    def choose_engine_file(self) -> str | None:
        return self._desktop.choose_engine_file()

    @bridge_call
    def start_custom_engine_check(self, path: str) -> str:
        """Test your own engine and use it if it passes (FR-7.5 advanced setting). Returns the job ID."""
        if chr(0) in path:
            raise ValidationError("That isn't a valid file path.")
        return self._engine.start_custom_check(path)

    @bridge_call
    def clear_custom_engine(self) -> None:
        self._engine.clear_custom()

    @bridge_call
    def get_refutation(self, session_id: int) -> dto.Refutation:
        r = self._sessions.get_refutation(session_id)
        return dto.Refutation(r.fen_before, r.wrong_move, list(r.line), r.score, r.game_over)

    @bridge_call
    def analyze_position(
        self, session_id: int, fen: str, purpose: Literal["start", "panel", "board"] = "panel"
    ) -> dto.Analysis:
        """Eval and top lines after the puzzle (FR-7.2, 7.7). `purpose` keys latest-wins per view."""
        return analysis_dto(self._sessions.analyze(session_id, fen, purpose))


def _labels(keys: tuple[str, ...]) -> list[dto.ThemeLabel]:
    return [dto.ThemeLabel(k, display_name(k)) for k in keys]


def idea_result(i: Any) -> dto.IdeaResult:
    return dto.IdeaResult(i.found, i.total, i.extra, _labels(i.correct), _labels(i.wrong), _labels(i.missed))


def danger_reveal(d: Any) -> dto.DangerReveal:
    return dto.DangerReveal(d.candidate, d.is_safe, d.call, d.best_score, d.candidate_score, list(d.line))


def analysis_dto(a: AnalysisResult) -> dto.Analysis:
    return dto.Analysis(
        a.fen, [dto.EngineLine(x.score, x.cp, x.mate, list(x.pv)) for x in a.lines], a.game_over, a.superseded
    )
