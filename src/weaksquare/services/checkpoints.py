"""Checkpoints and fix tracking (v1.0, REQUIREMENTS §10.8).

**Triggers (FR-10.32):**
- **Count:** after a sync that brought new games, and at launch, a checkpoint runs once there are `every_games`
  new eligible games since the last one (eligible = your linked accounts' games matching the checkpoint filters).
- **Schedule:** optional, every N days or on a weekday. Checked at launch and then hourly, so it runs while the app
  is open or at the next launch. Due with no new eligible games, it does nothing (and isn't due again until next
  time).
- **Run checkpoint now.** One checkpoint at a time; a trigger while one runs is dropped.

**A checkpoint (one `checkpoint` job, FR-10.33):** syncs (schedule and manual; a count trigger comes from a sync
that just ran), takes the rolling window of your last eligible games, saves a normal Coach report on it through the
Coach's pipeline (analysis, tags, puzzles, digests), measures every weakness against its frozen baseline
(`core/fix_tracking.py`), saves the checkpoint, and rebuilds the Suggested mix with the statuses. It never creates
or changes your training plan (FR-10.65).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from weaksquare.core.clock import Clock
from weaksquare.core.coach import Report
from weaksquare.core.errors import ConflictError, ValidationError
from weaksquare.core.fix_tracking import (
    BASELINE_GAMES,
    FIXED,
    IMPROVING,
    REGRESSED,
    TRAINING,
    Change,
    CheckpointDraft,
    CheckpointSettings,
    Metric,
    PuzzleAccuracy,
    Tracked,
    checked_settings,
    game_health,
    group_by_game,
    mark_training,
    observations,
    puzzle_accuracy,
    schedule_due,
    step,
)
from weaksquare.core.games import GameRow, LibraryFilter
from weaksquare.core.stats import AttemptRow
from weaksquare.jobs.runner import CancelToken, JobCancelled, JobRunner, ProgressFn

log = logging.getLogger(__name__)

JOB_KIND = "checkpoint"
COACH_JOB = "coach_run"
SETTINGS_KEY = "checkpoints.settings"
SCHEDULE_ENABLED_AT_KEY = "checkpoints.schedule_enabled_at"
SCHEDULE_LAST_KEY = "checkpoints.schedule_last_at"
NOTICES_SEEN_KEY = "checkpoints.notices_seen"
CHECK_EVERY_S = 3600.0  # the schedule is looked at again at least hourly (sleep can't skip one)
RETRY_BUSY_S = 60.0  # a Coach run is going: look again in a minute
LINKED = ("lichess", "chesscom")
STATUS_ORDER = {REGRESSED: 0, TRAINING: 1, "new": 1, IMPROVING: 2, FIXED: 3}


class Settings(Protocol):
    def get(self, key: str) -> Any | None: ...
    def set(self, key: str, value: Any) -> None: ...


class Scheduler(Protocol):
    def call_later(self, delay_s: float, fn: Callable[[], None]) -> None: ...


class Library(Protocol):
    def start_sync(self) -> str | None: ...
    def list_games(self, f: LibraryFilter) -> tuple[list[GameRow], int]: ...


class Coach(Protocol):
    def checkpoint_report(
        self, game_ids: Sequence[int], number: int, progress: ProgressFn, cancel: CancelToken
    ) -> tuple[int, Report]: ...
    def measure_games(self, game_ids: Sequence[int], progress: ProgressFn, cancel: CancelToken) -> Report: ...
    def puzzle_sources(self) -> tuple[list[AttemptRow], dict[str, tuple[int, int]]]: ...
    def suggest_from_checkpoint(
        self, report_id: int | None, report: Report, statuses: dict[str, str],
        maintenance: Sequence[tuple[str, tuple[str, ...]]], checkpoint: int,
    ) -> Any: ...  # fmt: skip
    def report(self, report_id: int) -> tuple[Any, dict[str, float]]: ...


class Repo(Protocol):
    def last(self, *, live_only: bool = False) -> Any: ...
    def all(self) -> list[Any]: ...
    def next_number(self) -> int: ...
    def save(self, draft: Any, step: Any) -> None: ...
    def put_tracked(self, tracked: Any) -> None: ...
    def tracked(self) -> dict[str, Tracked]: ...
    def metrics(self) -> list[tuple[int, Metric]]: ...
    def my_moves(self, game_ids: Sequence[int], subject: str = "me") -> list[tuple[int, int, str, int]]: ...
    def my_ratings(self, game_ids: Sequence[int]) -> list[tuple[str, str | None, int | None]]: ...


@dataclass(frozen=True)
class Point:
    number: int
    created_at: str
    per10: float
    puzzle_accuracy: float | None
    guarded: bool
    reconstructed: bool


@dataclass(frozen=True)
class Example:
    game_id: int
    ply: int


@dataclass(frozen=True)
class WeaknessCard:
    key: str
    kind: str
    label: str
    status: str
    status_since: int
    baseline_per10: float
    baseline_games: int
    current_per10: float | None
    current_guarded: bool
    puzzle_accuracy: float | None
    puzzle_attempts: int
    reasons: dict[str, int]
    points: list[Point]
    examples: list[Example]


@dataclass(frozen=True)
class CheckpointView:
    number: int
    created_at: str
    trigger: str
    report_id: int | None
    reconstructed: bool
    games: int
    health: dict[str, Any]
    changes: list[Change]
    ai_run_id: int | None


@dataclass(frozen=True)
class ProgressView:
    settings: CheckpointSettings
    new_games: int  # new eligible games since the last checkpoint (capped at every_games)
    running_job: str | None
    weaknesses: list[WeaknessCard]
    checkpoints: list[CheckpointView]  # oldest first


@dataclass(frozen=True)
class Notice:
    number: int
    change: Change


@dataclass
class _Run:
    number: int | None = None
    notes: list[str] = field(default_factory=list)


class CheckpointService:
    def __init__(
        self, repo: Repo, coach: Coach, library: Library, runner: JobRunner, clock: Clock, settings: Settings,
        scheduler: Scheduler,
    ) -> None:  # fmt: skip
        self._repo = repo
        self._coach = coach
        self._library = library
        self._runner = runner
        self._clock = clock
        self._settings = settings
        self._scheduler = scheduler
        self._lock = threading.Lock()
        self._generation = 0
        self._runs: dict[str, _Run] = {}

    # ---- settings -------------------------------------------------------------------------------------------
    def settings(self) -> CheckpointSettings:
        raw = self._settings.get(SETTINGS_KEY)
        if not isinstance(raw, dict):
            return CheckpointSettings()
        try:
            return checked_settings(raw)
        except (ValidationError, TypeError, ValueError):
            return CheckpointSettings()

    def set_settings(self, data: Any) -> CheckpointSettings:
        new = checked_settings(data)
        old = self.settings()
        if new.schedule.kind != "off" and new.schedule != old.schedule:
            self._settings.set(SCHEDULE_ENABLED_AT_KEY, self._clock.now().isoformat())
            self._settings.set(SCHEDULE_LAST_KEY, None)
        self._settings.set(SETTINGS_KEY, new.to_json())
        self._schedule(1.0)
        return new

    # ---- what counts --------------------------------------------------------------------------------------
    def _eligible(self, s: CheckpointSettings, limit: int) -> list[GameRow]:
        """Your last eligible games, newest first (FR-10.32: linked accounts, the checkpoint filters)."""
        rows, _ = self._library.list_games(
            LibraryFilter(
                player="me", platforms=LINKED, time_classes=s.time_classes, rated=True if s.rated_only else None,
                colors=() if s.color == "both" else (s.color,), limit=limit,
            )
        )  # fmt: skip
        return [g for g in rows if g.user_color in ("white", "black", "both")]

    def new_games(self, s: CheckpointSettings | None = None) -> int:
        """New eligible games since the last checkpoint, counted up to `every_games`."""
        s = s or self.settings()
        last = self._repo.last()
        rows = self._eligible(s, s.every_games)
        if last is None or last.newest_played_at is None:
            return len(rows)
        return sum(1 for g in rows if g.played_at is not None and g.played_at > last.newest_played_at)

    # ---- triggers ------------------------------------------------------------------------------------------
    def start(self) -> None:
        """At launch: a schedule that came due while the app was closed, or enough new games, run now."""
        self._tick(self._generation)

    def after_new_games(self, n: int) -> None:
        """A sync brought new games (the library's hook, run on the sync job's thread)."""
        try:
            if n > 0 and self.new_games() >= self.settings().every_games:
                self._submit("count")
        except Exception:  # the sync itself succeeded: a failed check must not fail it
            log.exception("checkpoint count check failed")

    def run_now(self) -> str:
        if self._runner.active(JOB_KIND):
            raise ConflictError("A checkpoint is already running.")
        job = self._submit("manual")
        if job is None:
            raise ConflictError("A Coach run is going. Run the checkpoint when it's finished.")
        return job

    def running_job(self) -> str | None:
        active = self._runner.active(JOB_KIND)
        return active[0].id if active else None

    def _schedule(self, delay_s: float) -> None:
        with self._lock:
            self._generation += 1
            gen = self._generation
        self._scheduler.call_later(delay_s, lambda: self._tick(gen))

    def _time(self, key: str) -> datetime | None:
        v = self._settings.get(key)
        try:
            return datetime.fromisoformat(v) if isinstance(v, str) else None
        except ValueError:
            return None

    def schedule_is_due(self, s: CheckpointSettings | None = None) -> bool:
        s = s or self.settings()
        return schedule_due(s.schedule, self._time(SCHEDULE_LAST_KEY), self._time(SCHEDULE_ENABLED_AT_KEY),
                            self._clock.now(), self._clock.local_date)  # fmt: skip

    def _tick(self, gen: int) -> None:
        with self._lock:
            if gen != self._generation:
                return  # settings changed; a newer timer took over
        try:
            s = self.settings()
            if self.schedule_is_due(s):
                self._submit("schedule")
            elif self.new_games(s) >= s.every_games:
                self._submit("count")
        except Exception:
            log.exception("checkpoint check failed")
        self._schedule(CHECK_EVERY_S)

    def _submit(self, trigger: str) -> str | None:
        with self._lock:
            if self._runner.active(JOB_KIND):
                return None
            if self._runner.active(COACH_JOB):  # the same pipeline is busy: look again shortly
                self._scheduler.call_later(RETRY_BUSY_S, lambda: self._retry(trigger))
                return None
            run = _Run()
            job = self._runner.submit(JOB_KIND, lambda p, c: self._job(trigger, run, p, c))
            self._runs[job] = run
            return job

    def _retry(self, trigger: str) -> None:
        if trigger == "manual" or self.schedule_is_due() or self.new_games() >= self.settings().every_games:
            self._submit(trigger)

    def result(self, job_id: str) -> int | None:
        run = self._runs.get(job_id)
        return run.number if run else None

    # ---- the checkpoint ------------------------------------------------------------------------------------
    def _sync(self, progress: ProgressFn, cancel: CancelToken, run: _Run) -> None:
        job = self._library.start_sync()
        if job is None:
            return
        progress(None, "Syncing your games…")
        while True:
            if cancel.cancelled:
                raise JobCancelled()
            st = self._runner.wait(job, 0.5)
            if st is not None and st.state in ("done", "failed", "cancelled"):
                if st.state == "failed":
                    run.notes.append(f"Sync: {st.message}")
                return

    def _job(self, trigger: str, run: _Run, progress: ProgressFn, cancel: CancelToken) -> str:
        s = self.settings()
        if trigger in ("schedule", "manual"):
            self._sync(progress, cancel, run)
        if trigger == "schedule":
            self._settings.set(SCHEDULE_LAST_KEY, self._clock.now().isoformat())
        last = self._repo.last()
        tracked = self._repo.tracked()
        first = not tracked and last is None
        rows = self._eligible(s, max(s.window, BASELINE_GAMES) if first else s.window)
        window = rows[: s.window]
        newest = max((g.played_at for g in window if g.played_at), default=None)
        fresh = (len(window) if last is None or last.newest_played_at is None
                 else sum(1 for g in window if g.played_at is not None and g.played_at > last.newest_played_at))  # fmt: skip
        if not window:
            return "No eligible games yet: a checkpoint needs games from your linked accounts."
        if trigger == "schedule" and fresh == 0:
            return "No new games since the last checkpoint."
        if trigger == "count" and self.new_games(s) < s.every_games:
            return "Not enough new games yet."
        cancel.raise_if_cancelled()

        number = self._repo.next_number()
        run.number = number
        ids = [g.id for g in reversed(window)]  # oldest first
        baselines: dict[str, tuple[float, int]] | None = None
        if first and len(rows) > len(window):
            base_ids = [g.id for g in reversed(rows[:BASELINE_GAMES])]
            progress(None, f"Measuring your baseline over {len(base_ids)} games…")
            base = self._coach.measure_games(base_ids, progress, cancel)
            baselines = {k: (o.per10, len(base_ids)) for k, o in observations(base).items()}
        rid, report = self._coach.checkpoint_report(ids, number, progress, cancel)

        progress(None, "Tracking your weaknesses…")
        attempts, dash = self._coach.puzzle_sources()

        def puzzles(themes: tuple[str, ...]) -> PuzzleAccuracy:
            return puzzle_accuracy(themes, attempts, None, dash)

        in_mix = {k for k, t in tracked.items() if t.status == TRAINING}
        result = step(tracked, observations(report), report.games, number, puzzles, in_mix, s.thresholds, baselines)
        health = game_health(report, group_by_game(self._repo.my_moves(ids)), self._repo.my_ratings(ids))
        self._repo.save(
            CheckpointDraft(number, self._clock.now().isoformat(timespec="seconds"), trigger, rid, False, tuple(ids),
                            newest, health),
            result,
        )  # fmt: skip
        self._rebuild_mix(rid, report, result.tracked, number)
        moved = [c for c in result.changes if c.old is not None]
        msg = f"Checkpoint #{number} saved: {report.games} game{'s' if report.games != 1 else ''}"
        if moved:
            msg += f", {len(moved)} status change{'s' if len(moved) != 1 else ''}"
        return msg + (" · " + " ".join(run.notes) if run.notes else "")

    def _rebuild_mix(self, report_id: int | None, report: Report, tracked: dict[str, Tracked], number: int) -> None:
        statuses = {k: t.status for k, t in tracked.items()}
        maintenance = [(t.label, t.themes) for t in sorted(tracked.values(), key=lambda t: t.key)
                       if t.status == FIXED and t.themes]  # fmt: skip
        sug = self._coach.suggest_from_checkpoint(report_id, report, statuses, maintenance, number)
        if sug is not None:
            self._repo.put_tracked(mark_training(tracked, sug.weaknesses, number).values())

    # ---- notices (FR-10.38) --------------------------------------------------------------------------------
    def take_notices(self) -> list[Notice]:
        """Status changes from live checkpoints you haven't seen, once. Newly detected weaknesses and New ↔ Training
        aren't notices; backfilled checkpoints never make any."""
        seen = self._settings.get(NOTICES_SEEN_KEY)
        seen_n = seen if isinstance(seen, int) and not isinstance(seen, bool) else 0
        rows = [r for r in self._repo.all() if r.number > seen_n]
        if not rows:
            return []
        self._settings.set(NOTICES_SEEN_KEY, rows[-1].number)
        if not self.settings().notices:
            return []
        return [Notice(r.number, c) for r in rows if not r.reconstructed for c in r.changes if c.old is not None]

    # ---- the Progress page (FR-10.38) ----------------------------------------------------------------------
    def progress(self) -> ProgressView:
        s = self.settings()
        cps = self._repo.all()
        by_number = {c.number: c for c in cps}
        points: dict[str, list[tuple[int, Metric]]] = {}
        for n, m in self._repo.metrics():
            points.setdefault(m.key, []).append((n, m))
        examples = self._latest_examples(cps)
        cards = []
        for t in self._repo.tracked().values():
            ms = points.get(t.key, [])
            latest = ms[-1][1] if ms else None
            cards.append(WeaknessCard(
                t.key, t.kind, t.label, t.status, t.status_since, t.baseline_per10, t.baseline_games,
                latest.per10 if latest else None, latest.guarded if latest else False,
                latest.puzzle_accuracy if latest else None, latest.puzzle_attempts if latest else 0,
                dict(latest.reasons) if latest else {},
                [Point(n, by_number[n].created_at, m.per10, m.puzzle_accuracy, m.guarded, by_number[n].reconstructed)
                 for n, m in ms if n in by_number],
                examples.get(t.key, []),
            ))  # fmt: skip
        cards.sort(key=lambda c: (STATUS_ORDER.get(c.status, 9), -(c.current_per10 or 0), c.key))
        views = [CheckpointView(c.number, c.created_at, c.trigger, c.report_id, c.reconstructed, c.games, c.health,
                                c.changes, c.ai_run_id) for c in cps]  # fmt: skip
        try:
            new = self.new_games(s)
        except Exception:
            log.exception("couldn't count new games")
            new = 0
        return ProgressView(s, new, self.running_job(), cards, views)

    def _latest_examples(self, cps: list[Any]) -> dict[str, list[Example]]:
        """Each weakness's worst moments from the latest live checkpoint's report (click-through, FR-10.38)."""
        live = [c for c in cps if c.report_id is not None]
        if not live:
            return {}
        try:
            row, _ = self._coach.report(live[-1].report_id)
        except Exception:
            return {}
        out: dict[str, list[Example]] = {}
        data = row.report
        for group in ("missed", "allowed", "habits", "whole_game"):
            for w in data.get(group) or []:
                if isinstance(w, dict) and isinstance(w.get("key"), str):
                    out[w["key"]] = [Example(int(e["game_id"]), int(e["ply"])) for e in w.get("examples") or []
                                     if isinstance(e, dict)]  # fmt: skip
        return out
