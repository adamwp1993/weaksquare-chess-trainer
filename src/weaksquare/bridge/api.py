"""The JS-facing API (pywebview `js_api`). Thin: validate, delegate to services, return DTOs.

pywebview exposes every public method and every public nested object to JavaScript, so all
dependencies live in underscore attributes, and every public method is wrapped by `@bridge_call`.
`tests/contract/test_bridge_allowlist.py` pins the exact set of public names: adding a method
means updating that allowlist in the same commit (ARCHITECTURE §3 decision 13).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
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
from weaksquare.core.games import LibraryFilter
from weaksquare.core.ladder import LEVEL_NAMES, LEVELS, LadderStatus
from weaksquare.core.llm.cost import estimate
from weaksquare.core.llm.defaults import (
    DROPDOWN_KIND,
    FEATURE_LABELS,
    FEATURES,
    PROVIDER_LABELS,
    PROVIDERS,
    TYPICAL_PROMPT_CHARS,
    PriceRow,
)
from weaksquare.core.plan import PlanDraft
from weaksquare.core.preset_suggestion import validate_coach_preset
from weaksquare.core.reasons import REASONS
from weaksquare.core.themes import display_name
from weaksquare.jobs.runner import JobRunner
from weaksquare.services.account import AccountService
from weaksquare.services.analysis import AnalysisService
from weaksquare.services.coach import CoachService
from weaksquare.services.db_update import UpdateCheckService
from weaksquare.services.engine import Analysis as AnalysisResult
from weaksquare.services.engine import EngineService
from weaksquare.services.explain import ExplainService, ExplainView
from weaksquare.services.game_explain import GameExplainService, GameQuote, NarrativeView
from weaksquare.services.game_puzzles import GamePuzzlesService
from weaksquare.services.games import GameLibraryService
from weaksquare.services.journal import JournalService
from weaksquare.services.lichess_history import HistoryService
from weaksquare.services.llm_settings import LlmConfig, LlmSettingsService
from weaksquare.services.llm_usage import LlmUsageService
from weaksquare.services.mixer import MixerService
from weaksquare.services.plan import PlanService
from weaksquare.services.presets import Preset, PresetService
from weaksquare.services.puzzle_db import PuzzleDbService
from weaksquare.services.puzzle_import import PuzzleImportService
from weaksquare.services.reasons import ReasonsService
from weaksquare.services.review import ReviewService
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
        llm_settings: LlmSettingsService,
        llm_usage: LlmUsageService,
        explain: ExplainService,
        games: GameLibraryService,
        analysis: AnalysisService,
        review: ReviewService,
        puzzle_import: PuzzleImportService,
        game_explain: GameExplainService,
        game_puzzles: GamePuzzlesService,
        coach: CoachService,
        plan: PlanService,
        journal: JournalService,
    ) -> None:
        self._plan = plan
        self._journal = journal
        self._game_puzzles = game_puzzles
        self._coach = coach
        self._explain = explain
        self._game_explain = game_explain
        self._games = games
        self._analysis = analysis
        self._review = review
        self._puzzle_import = puzzle_import
        self._llm_settings = llm_settings
        self._llm_usage = llm_usage
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
            reasons_ask=s.reasons_ask if s.reasons_ask in ("game_review", "off") else "always",  # type: ignore[arg-type]
            rushed_s=s.rushed_s,
            show_best=s.show_best,
            lesson_sites=list(s.lesson_sites),  # type: ignore[arg-type]
            lesson_custom_url=s.lesson_custom_url,
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
            "review.show_best",
            "coach.lesson_sites",
            "coach.lesson_custom_url",
            "plan.params",
            "plan.carry_over",
        ],
        value: Any,
    ) -> None:
        self._ui_settings.set(key, value)

    # ---- the mixer (FR-3.1–3.5) -----------------------------------------------------------------
    @bridge_call
    def get_theme_catalog(self) -> list[dto.ThemeGroup]:
        st = self._puzzle_db.status()
        if not st.installed or st.needs_upgrade:
            return []  # v0.10-B7: no puzzle database yet (a fresh install): no themes, not a crash
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
            "my" if v.source == "my" else "lichess",
            v.strict_without_engine,
            v.solve_as_opponent,
            v.game_id,
            v.game_ply,
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
    def get_reason_stats(
        self, theme: str | None = None, mode: str | None = None, source: Literal["puzzles", "games", "all"] = "puzzles"
    ) -> dto.ReasonStats:
        """FR-9.7: the mistake-reason breakdown, optionally for one theme and/or one mode, for puzzles,
        your games (v0.8: game mistakes and Retry misses), or all."""
        r = self._stats.reasons(theme, mode, source)
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

    # ---- LLM settings and the cost guardrails (FR-1.2–1.4, 1.8, 1.10, §9.3) --------------------------
    # A key comes in once, from the masked field, and goes straight to Credential Manager. Nothing here
    # returns a key, and @bridge_call logs only the method name (SR-1, SR-7).
    @bridge_call
    def get_llm_settings(self) -> dto.LlmSettings:
        return self._llm_dto()

    @bridge_call
    def set_llm_settings(
        self,
        provider: Literal["none", "anthropic", "openai"],
        model: str,
        reasoning: Literal["low", "medium", "high"],
        run_cap_usd: float,
        monthly_budget_usd: float,
    ) -> dto.LlmSettings:
        self._llm_settings.update(provider, model, reasoning, run_cap_usd, monthly_budget_usd)
        return self._llm_dto()

    @bridge_call
    def set_llm_key(self, provider: Literal["anthropic", "openai"], key: str) -> dto.LlmSettings:
        self._llm_settings.set_key(provider, key)
        return self._llm_dto()

    @bridge_call
    def delete_llm_key(self, provider: Literal["anthropic", "openai"]) -> dto.LlmSettings:
        self._llm_settings.delete_key(provider)
        return self._llm_dto()

    @bridge_call
    def start_llm_key_test(self, provider: Literal["anthropic", "openai"], model: str) -> str:
        """Test key (FR-1.4): the provider's free model lookup, as a job. Returns the job ID."""
        return self._llm_settings.start_key_test(provider, model)

    @bridge_call
    def list_llm_prices(self) -> list[dto.LlmPrice]:
        return [_price_dto(p) for p in self._llm_settings.prices()]

    @bridge_call
    def save_llm_price(
        self,
        provider: Literal["anthropic", "openai"],
        model: str,
        input_per_m: float,
        output_per_m: float,
        long_ctx_threshold: int | None = None,
        long_input_per_m: float | None = None,
        long_output_per_m: float | None = None,
        as_of: str | None = None,
    ) -> list[dto.LlmPrice]:
        self._llm_settings.save_price(provider, model, input_per_m, output_per_m, long_ctx_threshold,
                                      long_input_per_m, long_output_per_m, as_of)  # fmt: skip
        return [_price_dto(p) for p in self._llm_settings.prices()]

    @bridge_call
    def delete_llm_price(self, provider: Literal["anthropic", "openai"], model: str) -> list[dto.LlmPrice]:
        self._llm_settings.delete_price(provider, model)
        return [_price_dto(p) for p in self._llm_settings.prices()]

    @bridge_call
    def get_llm_spend(self) -> dto.LlmSpend:
        return self._spend_dto(self._llm_settings.config())

    # ---- Explain (§7.2 step 3, FR-8.1–8.8) ----------------------------------------------------------
    @bridge_call
    def get_explain_quote(self, session_id: int) -> dto.ExplainQuote:
        q = self._explain.quote(session_id)
        e = q.estimate
        return dto.ExplainQuote(q.state, q.message, q.provider, q.model, round(e.typical_usd, 6) if e else None,
                                round(e.worst_usd, 6) if e else None)  # fmt: skip

    @bridge_call
    def start_explain(self, session_id: int) -> str:
        """Explain the puzzle that just ended, as a job. Returns the job ID; then call get_explanation."""
        return self._explain.start(session_id)

    @bridge_call
    def get_explanation(self, session_id: int) -> dto.Explanation | None:
        v = self._explain.result(session_id)
        return None if v is None else _explanation_dto(v)

    # ---- v0.9: a model per AI feature (FR-1.15) and Game Review AI (§11.4) --------------------------
    @bridge_call
    def set_llm_feature(
        self,
        feature: Literal["game_review", "coach"],
        provider: Literal["same", "anthropic", "openai"],
        model: str,
        reasoning: Literal["low", "medium", "high"],
    ) -> dto.LlmSettings:
        """A feature's own provider and model, or 'same' to follow Explain's; and its reasoning level."""
        self._llm_settings.update_feature(feature, provider, model, reasoning)
        return self._llm_dto()

    @bridge_call
    def get_game_move_quote(self, game_id: int, ply: int) -> dto.GameAiQuote:
        """Can Explain this move run for one of your analyzed moves, and about what would it cost?"""
        return _game_quote_dto(self._game_explain.quote_move(game_id, ply))

    @bridge_call
    def start_game_move_explain(self, game_id: int, ply: int) -> str:
        """Explain this move (FR-11.17), as a job. Then call get_game_move_explanation."""
        return self._game_explain.start_move(game_id, ply)

    @bridge_call
    def get_game_move_explanation(self, game_id: int, ply: int) -> dto.Explanation | None:
        """The explanation of this move under the current Game Review model (fresh or saved), if any."""
        v = self._game_explain.move_result(game_id, ply)
        return None if v is None else _explanation_dto(v)

    @bridge_call
    def get_game_narrative_quote(self, game_id: int, n: int | None = None) -> dto.GameAiQuote:
        """The estimate the Confirm dialog shows before Explain my game (FR-8.11, 11.21)."""
        return _game_quote_dto(self._game_explain.quote_narrative(game_id, n))

    @bridge_call
    def start_game_narrative(self, game_id: int, n: int | None = None) -> str:
        """Explain my game (FR-11.18), as a job, after you confirm. Then call get_game_narrative."""
        return self._game_explain.start_narrative(game_id, n)

    @bridge_call
    def get_game_narrative(self, game_id: int, n: int | None = None) -> dto.GameNarrative | None:
        v = self._game_explain.narrative_result(game_id, n)
        return None if v is None else _narrative_dto(v)

    def _spend_dto(self, cfg: LlmConfig) -> dto.LlmSpend:
        s = self._llm_usage.spend(cfg)
        return dto.LlmSpend(s.month, round(s.spent_usd, 6), s.budget_usd, s.level, cfg.configured)

    def _llm_dto(self) -> dto.LlmSettings:
        cfg = self._llm_settings.config()
        prices = self._llm_settings.prices()
        providers = []
        for p in PROVIDERS:
            options = [
                dto.LlmModelOption(r.model, round(estimate("explain", cfg.reasoning, TYPICAL_PROMPT_CHARS["explain"], r).typical_usd, 6))
                for r in sorted((r for r in prices if r.provider == p), key=lambda r: (r.input_per_m, r.model))
            ]  # fmt: skip
            providers.append(dto.LlmProviderInfo(p, PROVIDER_LABELS[p], cfg.keys[p], cfg.models[p], options))
        spend = self._llm_usage.spend(cfg)
        features = [self._feature_dto(f, prices, spend.by_feature.get(f, 0.0)) for f in FEATURES]
        return dto.LlmSettings(cfg.provider, cfg.reasoning, cfg.run_cap_usd, cfg.monthly_budget_usd,  # type: ignore[arg-type]
                               providers, self._spend_dto(cfg), *self._llm_settings.launch_check(), features)  # fmt: skip

    def _feature_dto(self, feature: str, prices: list[PriceRow], spent: float) -> dto.LlmFeature:
        cfg = self._llm_settings.config(feature)
        kind = DROPDOWN_KIND[feature]  # type: ignore[index]
        options = [
            dto.LlmModelChoice(r.provider, r.model,  # type: ignore[arg-type]
                               round(estimate(kind, cfg.reasoning, TYPICAL_PROMPT_CHARS[kind], r).typical_usd, 6))
            for r in sorted(prices, key=lambda r: (PROVIDERS.index(r.provider) if r.provider in PROVIDERS else 9,
                                                   r.input_per_m, r.model))
        ]  # fmt: skip
        if feature == "explain":
            choice, own_model = cfg.provider, cfg.model
        else:
            choice, own_model, _ = self._llm_settings.feature_choice(feature)
        ready = cfg.configured and bool(cfg.model) and self._llm_settings.price(cfg.provider, cfg.model) is not None
        return dto.LlmFeature(feature, FEATURE_LABELS[feature], choice, own_model, cfg.reasoning,  # type: ignore[arg-type, index]
                              cfg.provider, cfg.model, ready, round(spent, 6), options)  # type: ignore[arg-type]  # fmt: skip

    # ---- v0.8: linked accounts and the game library (§11.5) --------------------------------------
    def _games_settings_dto(self, job: str | None = None) -> dto.GamesSettings:
        g = self._games.settings()
        r = self._analysis.settings()
        p = self._game_puzzles.settings()
        t = r.thresholds
        return dto.GamesSettings(
            self._account.status().username, g.chesscom_username, g.sync_on_open, g.first_sync_days,
            g.first_sync_max, r.think_s, dto.ReviewThresholds(t.inaccuracy, t.mistake, t.blunder, t.decided),
            r.tolerance_cp, r.key_moments, p.level,  # type: ignore[arg-type]
            p.think_s, job,
        )  # fmt: skip

    @bridge_call
    def get_games_settings(self) -> dto.GamesSettings:
        return self._games_settings_dto()

    @bridge_call
    def set_games_settings(
        self,
        sync_on_open: bool | None = None,
        first_sync_days: int | None = None,
        first_sync_max: int | None = None,
        think_s: float | None = None,
        thresholds: dict | None = None,
        tolerance_cp: int | None = None,
        key_moments: int | None = None,
        puzzle_level: Literal["blunders", "mistakes", "inaccuracies"] | None = None,
        puzzle_think_s: float | None = None,
    ) -> dto.GamesSettings:
        self._games.set_settings(
            sync_on_open=sync_on_open, first_sync_days=first_sync_days, first_sync_max=first_sync_max
        )
        self._analysis.set_settings(
            think_s=think_s, thresholds=thresholds, tolerance_cp=tolerance_cp, key_moments=key_moments
        )
        job = None
        if puzzle_think_s is not None:
            self._game_puzzles.set_settings(think_s=puzzle_think_s)
        if puzzle_level is not None and puzzle_level != self._game_puzzles.settings().level:
            self._game_puzzles.set_settings(level=puzzle_level)  # FR-10.40: archives/restores, no re-analysis
            running = self._runner.active("game_puzzles")
            job = running[0].id if running else None
        return self._games_settings_dto(job)

    # ---- v0.10: Game Review additions, your puzzles, the Coach ------------------------------------------
    @bridge_call
    def analyze_game_position(
        self, game_id: int, fen: str, purpose: Literal["panel", "board"] = "board"
    ) -> dto.Analysis:
        """Analyze from here (FR-11.34): the interactive engine on any position of the free board."""
        return analysis_dto(self._review.analyze_position(game_id, fen, purpose))

    @bridge_call
    def archive_my_puzzle(self, puzzle_id: int) -> None:
        """FR-10.44: archive one of your puzzles you don't want. It's kept (with its attempts), never shown."""
        self._game_puzzles.archive(puzzle_id)

    @bridge_call
    def get_coach_defaults(self) -> dto.CoachDefaults:
        running = self._runner.active("coach_run")
        players = [dto.PlayerSubject(s, _player_label(s), n) for s, n in self._games.players()]
        return dto.CoachDefaults(
            self._coach.last_params().to_json(), self._games.usernames(), players, running[0].id if running else None
        )

    @bridge_call
    def start_coach_run(self, params: dict) -> str:
        """A Coach run (§10): sync, analyze on the background engine, tag, puzzles, report. A job."""
        return self._coach.start_run(params)

    @bridge_call
    def get_coach_run_result(self, job_id: str) -> int | None:
        """The report a finished run saved."""
        return self._coach.run_result(job_id)

    @bridge_call
    def list_coach_reports(self) -> list[dto.CoachReportSummary]:
        out = []
        for r in self._coach.reports():
            rep = r.report
            top = [str(w.get("label")) for w in (rep.get("weaknesses") or [])[:3] if isinstance(w, dict)]
            out.append(
                dto.CoachReportSummary(
                    r.id, r.created_at, r.subject_label, r.subject == "me", r.source_kind,  # type: ignore[arg-type]
                    int(rep.get("games") or 0), top,
                )
            )  # fmt: skip
        return out

    @bridge_call
    def get_coach_report(self, report_id: int) -> dto.CoachReport:
        row, _ = self._coach.report(report_id)
        rep = row.report
        preset = rep.get("preset")
        comparison = self._coach.comparison(row.id)  # FR-10.73: the guarded comparison replaces the bare trend
        changes = {c.key: c for c in comparison.weaknesses} if comparison is not None else {}

        def ws(group: str) -> list[dto.CoachWeakness]:
            return [_weakness_dto(w, changes) for w in rep.get(group) or [] if isinstance(w, dict)]

        return dto.CoachReport(
            row.id, row.created_at, row.subject_label, row.subject == "me", row.source_kind,  # type: ignore[arg-type]
            row.params, int(rep.get("games") or 0), rep.get("first_played"), rep.get("last_played"),
            dict(rep.get("per10") or {}), dict(rep.get("results") or {}),
            ws("missed"), ws("allowed"), ws("habits"), ws("puzzles"),
            [dto.CoachGapRow(**g) for g in rep.get("gap") or []], dict(rep.get("reasons") or {}),
            int(rep.get("low_clock_errors") or 0),
            _preset_dto("The report's mix", preset) if isinstance(preset, dict) else None,
            [str(n) for n in rep.get("notes") or []], ws("whole_game"), _measures_dto(rep.get("measures")),
            _comparison_dto(comparison),
        )  # fmt: skip

    @bridge_call
    def get_coach_ai_quote(self, report_id: int, options: dict | None = None) -> dto.CoachAiQuote:  # type: ignore[type-arg]
        """The estimate for Get AI coaching (FR-10.25) with this run's options (FR-10.56, 10.60)."""
        q = self._coach.quote_ai(report_id, options)
        c = q.compare
        compare = (
            dto.CoachAdvancedCompare(c.games_with_moves, c.token_ratio, c.standard_usd, c.budget_share, c.minutes)
            if c is not None
            else None
        )
        return dto.CoachAiQuote(_game_quote_dto(q.quote), compare, q.cached_run)

    @bridge_call
    def start_coach_ai(self, report_id: int, options: dict | None = None) -> str:  # type: ignore[type-arg]
        """Get AI coaching. The UI calls this only after you Confirm the estimate. Options are per run
        and never saved (FR-10.56)."""
        return self._coach.start_ai(report_id, options)

    @bridge_call
    def get_coach_ai_job_run(self, job_id: str) -> int | None:
        """The AI run a finished Get AI coaching job made (or showed again)."""
        return self._coach.ai_job_run(job_id)

    @bridge_call
    def list_coach_ai_runs(self, report_id: int) -> list[dto.CoachAiRunSummary]:
        out = []
        for r in self._coach.ai_runs(report_id):
            count = len(r.result.get("findings") or r.result.get("weaknesses") or [])
            out.append(
                dto.CoachAiRunSummary(
                    r.id, r.created_at, r.format, r.advanced, r.include_notes, r.game_cap,  # type: ignore[arg-type]
                    r.provider, r.model, round(r.cost_usd, 6), count, len(r.new), r.include_journal,
                )
            )  # fmt: skip
        return out

    @bridge_call
    def get_coach_ai_run(self, report_id: int, run_id: int) -> dto.CoachAiRun | None:
        runs = self._coach.ai_runs(report_id)
        run = next((r for r in runs if r.id == run_id), None)
        if run is None:
            return None
        row, _ = self._coach.report(report_id)
        labels = {
            str(w.get("key")): str(w.get("label"))
            for g in ("missed", "allowed", "habits", "puzzles", "whole_game")
            for w in row.report.get(g) or []
            if isinstance(w, dict)
        }
        res = run.result
        presets = []
        for p in res.get("presets") or []:
            v, _ = validate_coach_preset(p)
            if v is not None:
                presets.append(dto.CoachPresetView(v.name, v.spec().to_json(), v.mode, []))
        findings: list[dto.CoachFinding] = []
        if run.format == "keyed":
            for w in res.get("weaknesses") or []:
                key = str(w.get("key"))
                findings.append(
                    dto.CoachFinding(
                        key, labels.get(key, key), "tactical", labels.get(key, key), str(w.get("explanation") or ""),
                        str(w.get("drill") or ""), False, False, 0, False, [], None,
                    )
                )  # fmt: skip
        else:
            games = {str(k): int(v) for k, v in (res.get("labels") or {}).items()}
            moves: dict[int, list[str]] = {}
            seen = list(res.get("seen") or [])
            for i, f in enumerate(res.get("findings") or []):
                evidence = []
                for e in f.get("evidence") or []:
                    gid = games.get(str(e.get("game")))
                    ply = int(e.get("ply") or 0) - 1
                    if gid is None or ply < 0:
                        continue
                    sans = moves.setdefault(gid, self._coach.move_labels(gid))
                    if ply < len(sans):
                        evidence.append(dto.CoachEvidence(str(e["game"]), gid, ply, sans[ply]))
                key = f.get("key")
                topic = f.get("topic")
                lesson = self._lesson_dto(report_id, topic) if isinstance(topic, str) else None
                findings.append(
                    dto.CoachFinding(
                        key, labels.get(key) if key else None, f.get("category") or "other", str(f.get("title") or ""),
                        str(f.get("explanation") or ""), str(f.get("advice") or ""), bool(f.get("tentative")),
                        key is None, int(seen[i]) if i < len(seen) else 0, i in run.new, evidence, lesson,
                    )
                )  # fmt: skip
        return dto.CoachAiRun(
            run.id, run.created_at, run.format, run.advanced, run.include_notes, run.game_cap,  # type: ignore[arg-type]
            str(res.get("summary") or ""), findings, presets, bool(res.get("fallback_preset")),
            int(res.get("discarded") or 0), run.provider, run.model, round(run.cost_usd, 6), run.include_journal,
            [
                dto.CoachTrendNote(str(n["key"]), labels.get(str(n["key"]), str(n["key"])), n["change"], str(n["comment"]))
                for n in res.get("trend") or []
                if isinstance(n, dict)
            ],
            self._ai_plan_dto(res.get("plan")),
            dto.AiPlanCheck(**res["plan_check"]) if isinstance(res.get("plan_check"), dict) else None,
        )  # fmt: skip

    def _ai_plan_dto(self, raw: Any) -> dto.PlanPreview | None:
        if not isinstance(raw, dict):
            return None
        draft = PlanDraft.from_json(raw)
        return _draft_dto(draft, None, self._plan.preview_replaces())

    def _lesson_dto(self, report_id: int, topic: str) -> dto.CoachLesson | None:
        lv = self._coach.lesson(report_id, topic)
        if lv is None:
            return None
        drill = None
        if lv.drill is not None:
            v, _ = validate_coach_preset(lv.drill)
            if v is not None:
                drill = dto.CoachPresetView(v.name, v.spec().to_json(), v.mode, [])
        return dto.CoachLesson(lv.topic, lv.label, drill, list(lv.curated), list(lv.sites))  # type: ignore[arg-type]

    @bridge_call
    def get_coach_notes_preview(self, report_id: int) -> list[dto.CoachNote]:
        """FR-10.60: exactly the notes Include my notes would send."""
        row, _ = self._coach.report(report_id)
        out = []
        games: dict[str, int] = {}
        if row.game_ids:
            games = {f"G{n}": gid for n, (gid, _) in enumerate(self._coach.digests(row.game_ids, row.subject), start=1)}
        for n in self._coach.notes_preview(report_id):
            move = None
            if n.game in games and n.ply is not None:
                sans = self._coach.move_labels(games[n.game])
                move = sans[n.ply - 1] if 0 < n.ply <= len(sans) else None
            out.append(dto.CoachNote(n.game, n.ply, move, n.reason, n.text, n.source))  # type: ignore[arg-type]
        return out

    @bridge_call
    def get_coach_journal_preview(self, report_id: int) -> list[dto.CoachJournalLine]:
        """FR-10.71: exactly the entries Include my journal would send."""
        row, _ = self._coach.report(report_id)
        games: dict[str, int] = {}
        if row.game_ids:
            games = {f"G{n}": gid for n, (gid, _) in enumerate(self._coach.digests(row.game_ids, row.subject), start=1)}
        out = []
        for j in self._coach.journal_preview(report_id):
            move = None
            if j.game in games and j.ply is not None:
                sans = self._coach.move_labels(games[j.game])
                move = sans[j.ply - 1] if 0 < j.ply <= len(sans) else None
            out.append(dto.CoachJournalLine(j.text, j.kind, j.game, j.ply, move, j.weakness))  # type: ignore[arg-type]
        return out

    # ---- v0.12: the training plan (FR-10.61-10.66) --------------------------------------------------
    @bridge_call
    def get_plan_settings(self) -> dto.PlanSettings:
        p = self._plan.params()
        return dto.PlanSettings(p.weeks, list(p.weekdays), p.minutes, self._plan.carry_over(), self._plan.has_report())

    @bridge_call
    def preview_plan(self, params: dict | None = None) -> dto.PlanPreview:  # type: ignore[type-arg]
        """The plan these settings would make from your latest report. Nothing is saved."""
        pv = self._plan.preview(params)
        return _draft_dto(pv.draft, pv.dates, pv.replaces, pv.start_date)

    @bridge_call
    def create_plan(self, params: dict, confirmed: bool = False) -> dto.TrainingPlan:  # type: ignore[type-arg]
        """Start the deterministic plan. It replaces the current one only when you confirm (FR-10.65)."""
        self._plan.create(params, confirmed=bool(confirmed))
        view = self._plan.current()
        assert view is not None
        return _plan_dto(view)

    @bridge_call
    def use_ai_plan(self, run_id: int, confirmed: bool = False) -> dto.TrainingPlan:
        """Use this plan (FR-10.66): a stored AI plan becomes current."""
        self._coach.use_ai_plan(run_id, confirmed)
        view = self._plan.current()
        assert view is not None
        return _plan_dto(view)

    @bridge_call
    def get_current_plan(self) -> dto.TrainingPlan | None:
        view = self._plan.current()
        return _plan_dto(view) if view is not None else None

    @bridge_call
    def get_today_plan(self) -> dto.TodayPlan | None:
        t = self._plan.today()
        if t is None:
            return None
        return dto.TodayPlan(
            t.plan_id, t.today, _day_dto(t.day) if t.day is not None else None, t.next_date, t.finished
        )

    @bridge_call
    def list_plans(self) -> list[dto.TrainingPlan]:
        """Every plan, newest first, old ones with their completion (FR-10.65)."""
        return [_plan_dto(v) for v in self._plan.history()]

    @bridge_call
    def set_plan_task_tick(self, task_id: int, done: bool) -> None:
        """Your hand tick or untick, which always wins over what the app saw (FR-10.64)."""
        self._plan.set_tick(task_id, done)

    @bridge_call
    def skip_plan_task(self, task_id: int, skipped: bool = True) -> None:
        self._plan.skip(task_id, skipped)

    @bridge_call
    def swap_plan_task(self, task_id: int) -> int:
        return self._plan.swap(task_id)

    @bridge_call
    def start_plan_task(self, task_id: int, rated: bool = True) -> dto.PlanTaskAction:
        """Start (FR-10.63): a puzzle task's session uses its own filters, and your Mixer stays as it was."""
        return self._action_dto(self._plan.start_task(task_id, rated))

    @bridge_call
    def start_plan_lesson_drill(self, task_id: int, rated: bool = True) -> dto.PlanTaskAction:
        """A lesson task's drill, as a session of its own: your filters stay as they were."""
        return self._action_dto(self._plan.start_lesson_drill(task_id, rated))

    @bridge_call
    def open_plan_lesson(self, task_id: int, target: str) -> None:
        """Open one of a lesson task's links, which ticks the task. The backend builds the URL (FR-10.59)."""
        report_id, topic = self._plan.lesson_ref(task_id)
        self._desktop.open_in_browser(self._coach.lesson_url(report_id, topic, target))
        self._plan.lesson_opened(task_id)

    @bridge_call
    def mark_review_ply(self, game_id: int, ply: int) -> bool:
        """You looked at this move in Game Review (FR-10.64, 10.68). True when that completed the pass."""
        return self._review.mark_visited(game_id, ply)

    def _action_dto(self, a: Any) -> dto.PlanTaskAction:
        session = None
        if a.session is not None:
            i = a.session
            session = dto.SessionInfo(i.session_id, i.match_count, i.queue_size, i.empty_buckets, i.mode)
        lesson = self._lesson_dto(a.report_id, a.topic) if a.topic and a.report_id is not None else None
        return dto.PlanTaskAction(
            a.kind, a.task_id, session, a.remaining, a.mode, a.game_id, lesson, a.prompt, a.weakness_key, a.plan_day_id
        )

    # ---- v0.12: the journal (FR-10.67-10.70) ------------------------------------------------------
    @bridge_call
    def get_journal(self, filters: dict | None = None) -> dto.JournalTimeline:  # type: ignore[type-arg]
        t = self._journal.timeline(filters)
        items = [
            dto.JournalItem(i.date, self._entry_dto(i.entry) if i.entry is not None else None, _day_log_dto(i.log) if i.log is not None else None)
            for i in t.items
        ]  # fmt: skip
        return dto.JournalTimeline(items, t.window_start, t.older, self._journal_games(t.games))

    def _journal_games(self, ids: Any) -> list[dto.JournalGame]:
        """The Game filter's choices. QA v0.12-B28: with the date, so two games against one opponent differ, and with
        the id only for games that still look alike."""
        labels: dict[int, str] = {}
        for gid in ids:
            g = self._games.get(gid)
            played = (g.played_at or "")[:10]
            labels[gid] = self._game_label(gid) + (f" ({played})" if played else "")
        seen = list(labels.values())
        return [dto.JournalGame(gid, lb if seen.count(lb) == 1 else f"{lb} #{gid}") for gid, lb in labels.items()]

    def _game_label(self, game_id: int) -> str:
        g = self._games.get(game_id)
        return f"{g.white or '?'} – {g.black or '?'}"

    @bridge_call
    def add_journal_entry(self, entry: dict) -> dto.JournalEntry:  # type: ignore[type-arg]
        """A note, or with a game a reflection (FR-10.67, 10.69)."""
        if not isinstance(entry, dict) or set(entry) - JOURNAL_FIELDS:
            raise ValidationError("Unknown journal fields.")
        eid = self._journal.add(
            entry.get("text"), entry_date=entry.get("entry_date"), weakness_key=entry.get("weakness_key"),
            game_id=entry.get("game_id"), ply=entry.get("ply"), plan_day_id=entry.get("plan_day_id"),
            plan_task_id=entry.get("plan_task_id"),
        )  # fmt: skip
        return self._entry_dto(self._journal.get(eid))

    @bridge_call
    def edit_journal_entry(self, entry_id: int, text: str, weakness_key: str | None = None) -> dto.JournalEntry:
        self._journal.edit(entry_id, text, weakness_key)
        return self._entry_dto(self._journal.get(entry_id))

    @bridge_call
    def delete_journal_entry(self, entry_id: int) -> None:
        self._journal.delete(entry_id)

    @bridge_call
    def get_game_notes(self, game_id: int) -> list[dto.JournalEntry]:
        """FR-10.69: a game's notes, in order of the move they're on."""
        return [self._entry_dto(e) for e in self._journal.game_notes(game_id)]

    def _entry_dto(self, e: Any) -> dto.JournalEntry:
        move = label = None
        if e.game_id is not None:
            label = self._game_label(e.game_id)
            if e.ply is not None:
                sans = self._coach.move_labels(e.game_id)
                move = sans[e.ply] if 0 <= e.ply < len(sans) else None
        return dto.JournalEntry(
            e.id, e.created_at, e.updated_at, e.entry_date, e.kind, e.text, e.game_id, e.ply, move, label,
            e.weakness_key, e.plan_day_id, e.plan_task_id,
            self._journal.plan_day_date(e.plan_day_id) if e.plan_day_id is not None else None,
        )  # fmt: skip

    @bridge_call
    def open_lesson(self, report_id: int, topic: str, target: str) -> None:
        """FR-10.59: open a lesson pointer in your default browser. The screen sends only the topic and
        the target; the URL is built and checked here."""
        self._desktop.open_in_browser(self._coach.lesson_url(report_id, topic, target))

    @bridge_call
    def get_suggestion(self) -> dto.SuggestionView | None:
        return self._suggestion_dto(self._coach.suggestion())

    @bridge_call
    def apply_suggestion(self) -> dto.SuggestionView:
        """Apply: the Suggested mix becomes your filters and mode (FR-10.31). No saved preset changes."""
        view = self._suggestion_dto(self._coach.apply_suggestion())
        assert view is not None
        return view

    @bridge_call
    def dismiss_suggestion(self) -> dto.SuggestionView | None:
        return self._suggestion_dto(self._coach.dismiss_suggestion())

    def _suggestion_dto(self, s: Any) -> dto.SuggestionView | None:
        if s is None:
            return None
        day = s.created_at[:10]
        current = self._ui_settings.get().last_filters
        active = current is not None and self._coach.is_suggested(current.to_json())
        return dto.SuggestionView(
            s.report_id, s.number, s.created_at, f"Suggested — from Coach run #{s.number}, {day}", s.spec, s.mode,
            list(s.why), s.pending, s.previous, active,
        )  # fmt: skip

    @bridge_call
    def verify_chesscom(self, username: str) -> dto.ChesscomProfile:
        """FR-11.24: the public profile; `not_found` when there's no such player."""
        p = self._games.verify_chesscom(username)
        return dto.ChesscomProfile(p["username"], p["name"], p["url"], p["joined"])

    @bridge_call
    def set_chesscom_username(self, username: str | None) -> dto.GamesSettings:
        self._games.set_chesscom_username(username)
        return self._games_settings_dto()

    @bridge_call
    def start_games_sync(self) -> str | None:
        """FR-11.27: sync both linked accounts in the background (metadata and PGNs only)."""
        return self._games.start_sync()

    @bridge_call
    def list_games(self, filters: dict) -> dto.GamePage:
        rows, total = self._games.list_games(_library_filter(filters))
        return dto.GamePage([game_summary(r) for r in rows], total)

    # ---- v0.8: one-off imports (§11.1) --------------------------------------------------------------
    @bridge_call
    def import_game_pgn(self, text: str) -> dto.GameImport:
        return game_import(self._games.import_pgn(text))

    @bridge_call
    def choose_game_file(self) -> dto.GameImport | None:
        """A .pgn file from the Open dialog; None if you cancel."""
        chosen = self._desktop.choose_pgn_file()
        if chosen is None:
            return None
        return game_import(self._games.import_file(Path(chosen)))

    @bridge_call
    def pick_imported_game(self, token: str, index: int) -> dto.GameImport:
        return game_import(self._games.pick(token, index))

    @bridge_call
    def start_game_url_import(self, url: str, chesscom_username: str | None = None) -> str:
        """A Lichess or chess.com game URL, as a job; then call get_game_url_import with its id."""
        return self._games.start_url_import(url, chesscom_username)

    @bridge_call
    def get_game_url_import(self, job_id: str) -> dto.GameImport | None:
        out = self._games.url_result(job_id)
        return game_import(out) if out is not None else None

    @bridge_call
    def set_game_color(self, game_id: int, color: Literal["white", "black", "both"]) -> None:
        self._games.set_user_color(game_id, color)

    @bridge_call
    def open_game_online(self, game_id: int) -> None:
        """FR-11.29: the game's Lichess or chess.com page in your default browser."""
        self._desktop.open_in_browser(self._games.online_url(game_id))

    # ---- v0.8: analysis and Game Review (§11.2, §11.3) ---------------------------------------------
    @bridge_call
    def analyze_games(self, game_ids: list, force: bool = False) -> str | None:
        """FR-11.30/11.31: queue games for the background engine; the job id, or None if nothing to do."""
        return self._analysis.queue(game_ids, force=force)

    @bridge_call
    def get_analysis_queue(self) -> dto.AnalysisQueue:
        q = self._analysis.status()
        return dto.AnalysisQueue(q.job_id, q.current, list(q.waiting))

    @bridge_call
    def get_review(self, game_id: int) -> dto.GameReview:
        v = self._review.review(game_id)
        return dto.GameReview(
            game_summary(v.game), v.start_fen, [review_move(m) for m in v.moves], v.analyzed, v.current,
            [side_summary(s) for s in v.summaries], list(v.key_moments), list(v.retry_plies), v.ask_reasons,
        )  # fmt: skip

    @bridge_call
    def retry_move(self, game_id: int, ply: int, uci: str, think_ms: int | None = None) -> dto.RetryResult:
        """FR-11.15: your try at a mistake; the answer comes back only with the result."""
        r = self._review.retry_move(game_id, ply, uci, think_ms, self._ui_settings.rushed_s() * 1000)
        return dto.RetryResult(r.retry_id, r.found, r.played_san, r.played_score, r.best_san, list(r.best_line),
                               list(r.reply_line), r.suggested_reason, r.engine_checked)  # fmt: skip

    @bridge_call
    def save_game_puzzle(self, game_id: int, ply: int) -> dto.SavedPuzzle:
        """FR-11.16: the position before this move, as one of your puzzles (My puzzles)."""
        pid, created = self._review.save_as_puzzle(game_id, ply)
        return dto.SavedPuzzle(pid, created)

    @bridge_call
    def set_game_reason(self, game_id: int, ply: int, reason: str, note: str | None = None) -> None:
        self._review.set_game_reason(game_id, ply, reason, note)

    @bridge_call
    def set_retry_reason(self, retry_id: int, reason: str, note: str | None = None) -> None:
        self._review.set_retry_reason(retry_id, reason, note)

    @bridge_call
    def get_game_stats(self) -> dto.GameStats:
        s = self._stats.game_stats()
        return dto.GameStats(s.retry_found, s.retry_tried,
                             [dto.SourceAccuracy(src, n, w) for src, n, w in s.sources if src in ("lichess", "my")])  # type: ignore[arg-type]  # fmt: skip

    # ---- v0.8: puzzles from your own files (§10.10) ------------------------------------------------
    @bridge_call
    def choose_and_import_puzzles(self, label: str) -> str | None:
        """FR-10.46: pick a PGN / EPD / CSV file and import it as a set; the job id, or None if you cancel."""
        chosen = self._desktop.choose_puzzle_import_file()
        if chosen is None:
            return None
        return self._puzzle_import.start_import(Path(chosen), label)

    @bridge_call
    def get_puzzle_import_report(self, job_id: str) -> dto.PuzzleImportReport | None:
        r = self._puzzle_import.report(job_id)
        if r is None:
            return None
        return dto.PuzzleImportReport(r.label, r.file_name, r.format, r.entries, r.added, r.duplicates,  # type: ignore[arg-type]
                                      r.skipped, [dto.PuzzleImportError(e.n, e.reason) for e in r.errors])  # fmt: skip

    @bridge_call
    def list_puzzle_sets(self) -> list[dto.PuzzleSet]:
        return [dto.PuzzleSet(label, n) for label, n in self._puzzle_import.sets()]


def _explanation_dto(v: ExplainView) -> dto.Explanation:
    x = v.explanation
    steps = [
        dto.ExplainStep(s.ply, s.side, s.san, s.uci, s.text,
                        [dto.ExplainAnnotation(a.kind, a.orig, a.dest, a.color) for a in s.annotations],  # type: ignore[arg-type]
                        list(s.variation))
        for s in x.steps
    ]  # fmt: skip
    return dto.Explanation(x.summary, steps, list(x.key_ideas), x.discarded, v.provider, v.model,
                           round(v.cost_usd, 6), v.cached, v.start_fen, list(v.solution))  # fmt: skip


def _player_label(subject: str) -> str:
    platform, _, name = subject.partition(":")
    return f"{name} ({'Lichess' if platform == 'lichess' else 'chess.com'})"


JOURNAL_FIELDS = {"text", "entry_date", "weakness_key", "game_id", "ply", "plan_day_id", "plan_task_id"}


def _comparison_dto(c: Any) -> dto.CoachComparison | None:
    if c is None:
        return None

    def puzzle(p: Any) -> dto.CoachPuzzleChange | None:
        if p is None:
            return None
        return dto.CoachPuzzleChange(p.then, p.now, p.then_attempts, p.now_attempts, p.verdict)

    def measure(m: Any) -> dto.CoachMeasureChange:
        return dto.CoachMeasureChange(m.key, m.label, m.unit, m.then, m.now, m.delta, m.verdict)

    return dto.CoachComparison(
        c.earlier_id, c.earlier_created_at, c.days_between, c.new_games, c.shared_games, c.enough_new_games, c.settings,
        c.puzzle_history, len(c.history),
        [
            dto.CoachWeaknessChange(w.key, w.label, w.then, w.now, w.delta, w.flag, w.verdict, list(w.series), puzzle(w.puzzle))
            for w in c.weaknesses
        ],
        [measure(m) for m in c.health], [measure(m) for m in c.measures],
    )  # fmt: skip


def _draft_dto(draft: Any, dates: Any, replaces: bool, start: str | None = None) -> dto.PlanPreview:
    p = draft.params
    return dto.PlanPreview(
        p.weeks, list(p.weekdays), p.minutes, start, replaces,
        [
            dto.PlanPreviewDay(
                d.week, d.position, dates[i] if dates is not None and i < len(dates) else None,
                [dto.PlanPreviewTask(t.type, t.title, t.minutes, t.weakness_key) for t in d.tasks],
            )
            for i, d in enumerate(draft.days)
        ],
    )  # fmt: skip


def _task_dto(v: Any) -> dto.PlanTask:
    t = v.task
    count = t.params.get("count") if t.type in ("puzzles", "game_puzzles") else None
    return dto.PlanTask(
        t.id, t.type, t.title, t.weakness_key, t.minutes, v.status, v.auto, t.manual_state, v.progress,
        int(count) if isinstance(count, int) else None, v.minutes_spent, t.carried_from is not None,
    )  # fmt: skip


def _day_dto(v: Any) -> dto.PlanDay:
    d = v.day
    return dto.PlanDay(d.id, d.week, d.position, d.date, v.is_today, [_task_dto(t) for t in v.tasks])


def _plan_dto(v: Any) -> dto.TrainingPlan:
    p = v.plan
    return dto.TrainingPlan(
        p.id, p.created_at, p.source, p.status, p.params.weeks, list(p.params.weekdays), p.params.minutes, p.start_date,
        p.ended_at, v.done, v.skipped, v.left, v.minutes_spent, v.today, [_day_dto(d) for d in v.days],
    )  # fmt: skip


def _tally_dto(t: Any) -> dto.DayLogTally:
    return dto.DayLogTally(t.key, t.label, t.attempts, t.solved, t.accuracy)


def _day_log_dto(x: Any) -> dto.DayLog:
    f = x.facts
    return dto.DayLog(
        x.date, _tally_dto(x.overall), [_tally_dto(t) for t in x.by_mode], [_tally_dto(t) for t in x.by_source],
        list(x.missed_themes), x.misclicks, f.games_synced, f.games_analyzed, f.games_reviewed, f.retries,
        f.retries_found, f.plan_tasks_done, list(f.coach_runs),
    )  # fmt: skip


def _weakness_dto(w: dict[str, Any], changes: dict[str, Any]) -> dto.CoachWeakness:
    key = str(w.get("key"))
    c = changes.get(key)
    return dto.CoachWeakness(
        key, w.get("kind"), str(w.get("name")), str(w.get("label")), int(w.get("count") or 0),  # type: ignore[arg-type]
        float(w.get("per10") or 0.0), int(w.get("severity") or 0), float(w.get("score") or 0.0),
        [str(t) for t in w.get("themes") or []], w.get("mode"), dict(w.get("reasons") or {}),
        [dto.CoachExample(int(e["game_id"]), int(e["ply"]), int(e["cp_loss"])) for e in w.get("examples") or []],
        w.get("puzzle_accuracy"), c.delta if c is not None else None,
        (c.flag or c.verdict) if c is not None else None,
    )  # fmt: skip


def _measures_dto(m: Any) -> dto.CoachMeasures | None:
    """FR-10.53 as stored on a v0.11 report; None for older reports or anything malformed."""
    if not isinstance(m, dict):
        return None
    try:
        return dto.CoachMeasures(
            int(m["games"]), int(m.get("min_games") or 5), [dto.CoachOpeningRow(**o) for o in m.get("openings") or []],
            {str(k): float(v) for k, v in (m.get("errors_per10_by_phase") or {}).items()},
            dto.CoachRateRow(**m["conversion"]), dto.CoachRateRow(**m["saves"]),
            [dto.CoachEndgameRow(**e) for e in m.get("endgames") or []], dto.CoachTimeRow(**m["time"]),
            dto.CoachKingRow(**m["king"]), bool(m.get("phases_enough")),
        )  # fmt: skip
    except (KeyError, TypeError, ValueError):
        return None


def _preset_dto(name: str, p: dict[str, Any]) -> dto.CoachPresetView:
    return dto.CoachPresetView(name, dict(p.get("spec") or {}), str(p.get("mode") or "standard"),
                               [str(x) for x in p.get("why") or []])  # fmt: skip


def _game_quote_dto(q: GameQuote) -> dto.GameAiQuote:
    e = q.estimate
    return dto.GameAiQuote(
        q.state, q.message, q.provider, q.model,
        e.input_tokens if e else None, e.typical_output_tokens if e else None, e.max_output_tokens if e else None,
        round(e.typical_usd, 6) if e else None, round(e.worst_usd, 6) if e else None,
        q.run_cap_usd, round(q.spend.spent_usd, 6), q.spend.budget_usd,
    )  # fmt: skip


def _narrative_dto(v: NarrativeView) -> dto.GameNarrative:
    n = v.narrative
    moments = [
        dto.GameMoment(m.ply, m.played_san, m.text,
                       [dto.ExplainAnnotation(a.kind, a.orig, a.dest, a.color) for a in m.annotations],  # type: ignore[arg-type]
                       list(m.better_line), list(m.better_uci))
        for m in n.moments
    ]  # fmt: skip
    p = n.preset
    preset = dto.SuggestedPreset(list(p.themes), list(p.names), p.rating_min, p.rating_max) if p else None
    return dto.GameNarrative(v.game_id, v.n, list(v.moments), n.opening_summary, n.turning_point, list(n.themes),
                             list(n.takeaways), moments, preset, n.discarded, v.provider, v.model,
                             round(v.cost_usd, 6), v.cached)  # fmt: skip


def _price_dto(p: PriceRow) -> dto.LlmPrice:
    return dto.LlmPrice(p.provider, p.model, p.input_per_m, p.output_per_m, p.long_ctx_threshold,  # type: ignore[arg-type]
                        p.long_input_per_m, p.long_output_per_m, p.as_of)  # fmt: skip


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


def _library_filter(f: dict) -> LibraryFilter:
    """FR-11.26 from the UI: unknown keys are refused, values are type-checked."""
    lists = {"platforms", "time_classes", "results", "colors", "statuses"}
    texts = {"opponent", "opening"}
    known = lists | texts | {"rated", "date_from", "date_to", "limit", "offset", "player"}
    unknown = set(f) - known
    if unknown:
        raise ValidationError(f"unknown library filter: {sorted(unknown)[0]}")
    kw: dict[str, Any] = {}
    for k, v in f.items():
        if k in lists:
            if not isinstance(v, list) or not all(isinstance(x, str) and len(x) <= 20 for x in v) or len(v) > 10:
                raise ValidationError(f"{k} must be a short list of strings")
            kw[k] = tuple(v)
        elif k in texts:
            if not isinstance(v, str) or len(v) > 100:
                raise ValidationError(f"{k} must be text")
            kw[k] = v
        elif k == "rated":
            if v is not None and not isinstance(v, bool):
                raise ValidationError("rated must be true, false or null")
            kw[k] = v
        elif k == "player":  # v0.10: you ('me') or another player's subject (FR-10.3)
            if not isinstance(v, str) or not re.fullmatch(r"me|(lichess|chesscom):[A-Za-z0-9_-]{1,30}", v):
                raise ValidationError("player must be 'me' or another player's subject")
            kw[k] = v.lower() if v != "me" else v
        elif k in ("date_from", "date_to"):
            if v is not None and (not isinstance(v, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v)):
                raise ValidationError(f"{k} must be a YYYY-MM-DD date")
            kw[k] = v
        else:
            if not isinstance(v, int) or isinstance(v, bool) or v < 0 or v > 100_000:
                raise ValidationError(f"{k} must be a whole number")
            kw[k] = v
    return LibraryFilter(**kw)


def game_summary(g: Any) -> dto.GameSummary:
    mine = g.user_color in ("white", "black")
    white = g.user_color == "white"
    return dto.GameSummary(
        g.id, g.source, g.url, g.played_at, g.time_class, g.time_control, g.rated, g.white, g.black,
        g.white_rating, g.black_rating, g.user_color,
        (g.black if white else g.white) if mine else None,
        (g.black_rating if white else g.white_rating) if mine else None,
        (g.white_rating if white else g.black_rating) if mine else None,
        g.result, g.user_result, g.eco, g.opening,
        (g.accuracy_white if white else g.accuracy_black) if mine else None,
        (g.accuracy_black if white else g.accuracy_white) if mine else None,
        g.lichess_analyzed, g.analysis_status if g.analysis_status in ("analyzed", "ai_reviewed") else "none",
    )  # fmt: skip


def game_import(o: Any) -> dto.GameImport:
    return dto.GameImport(o.game_id, o.created, o.needs_color, o.analyzed,
                          [dto.GameChoice(c.index, c.label, c.error) for c in o.choices], o.token)  # fmt: skip


def review_move(m: Any) -> dto.ReviewMove:
    return dto.ReviewMove(
        m.ply, m.san, m.uci, m.mover, m.fen_before, m.classification, m.symbol, m.cp_loss, m.eval_white,
        m.eval_text, m.best_move, m.best_san, [dto.ReviewLine(x.score, list(x.pv), list(x.sans)) for x in m.lines],
        list(m.refutation), m.kind, m.phase, m.low_clock, m.reason, m.suggested_reason, m.saved,
    )  # fmt: skip


def side_summary(s: Any) -> dto.SideSummary:
    phases = [dto.PhaseSummary(p, x.moves, x.inaccuracies, x.mistakes, x.blunders, x.avg_cp_loss)  # type: ignore[arg-type]
              for p, x in s.by_phase.items()]  # fmt: skip
    return dto.SideSummary(s.color, s.moves, s.inaccuracies, s.mistakes, s.blunders, s.avg_cp_loss,
                           s.platform_accuracy, phases, s.low_clock_errors)  # fmt: skip
