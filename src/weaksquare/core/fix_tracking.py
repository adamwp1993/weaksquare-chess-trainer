"""Checkpoints and fix tracking (v1.0, REQUIREMENTS §10.8): pure rules, no I/O.

- **Metrics (FR-10.34):** each weakness's game rate per 10 games over the rolling window, against a frozen
  **baseline**: the rate when it was first identified. The first checkpoint takes baselines from your last
  `BASELINE_GAMES` eligible games (the window of a first Coach run at its defaults); a weakness that first appears
  later gets the rate it first appeared with.
- **Sample-size guard (Adam, 2026-11-10, v1.0 build):** fewer than 5 occurrences in the window while the baseline
  also expected fewer than 5 is "not enough data yet": shown, drawn hollow, and no status change is made from it.
  So a rare weakness can't change status on noise (3 → 1), while a common one that drops to 0 can reach Fixed. (The
  earlier wording, "expected at least 5", would have guarded every real improvement below 5.)
- **Statuses (FR-10.35):** New / Training / Improving / Fixed / Regressed, from the game rate. Fixed also needs the
  rate at ≤ 50% of baseline at 2 checkpoints in a row *and* ≥ 75% first-try puzzle accuracy over ≥ 20 attempts on
  its themes. Puzzle accuracy alone never makes Fixed. A weakness no puzzle theme trains (an opening, time use)
  is decided by its game rate alone (v1.0 planning).
- **Absent from a report:** a Missed / Allowed theme or a habit tag that doesn't appear had zero occurrences. A
  whole-game weakness (opening, endgame, conversion, time, castling) can be absent because its group had too few
  games or fell out of the top list, so it's *not measured* at that checkpoint: no point, no change.
- **Game health (FR-10.36):** per-10 error rates, average centipawn loss overall and by phase, habit rates, the
  mistake-reason mix in four groups, results and the latest rating on each platform.
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, timedelta
from typing import Any

from weaksquare.core.coach import LOSS_CAP, Report, Weakness
from weaksquare.core.errors import ValidationError
from weaksquare.core.filters import MY_TIME_CLASSES
from weaksquare.core.habits import HABITS
from weaksquare.core.reasons import MISCLICK, REASONS
from weaksquare.core.stats import AttemptRow

NEW, TRAINING, IMPROVING, FIXED, REGRESSED = "new", "training", "improving", "fixed", "regressed"
STATUSES = (NEW, TRAINING, IMPROVING, FIXED, REGRESSED)
STATUS_LABELS = {NEW: "New", TRAINING: "Training", IMPROVING: "Improving", FIXED: "Fixed", REGRESSED: "Regressed"}

BASELINE_GAMES = 50  # FR-10.34: the first Coach run's window at its default
TRIGGERS = ("count", "schedule", "manual", "backfill")
REASON_GROUPS = ("process", "calculation", "knowledge", "time")
PHASES = ("opening", "middlegame", "endgame")
SCHEDULE_KINDS = ("off", "days", "weekday")
COLORS = ("both", "white", "black")

EVERY_RANGE = (5, 200)
WINDOW_RANGE = (10, 100)
DAYS_RANGE = (1, 60)
STREAK_RANGE = (1, 5)
PUZZLE_ATTEMPTS_RANGE = (5, 200)


# ---- settings -------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Thresholds:
    """FR-10.35, as fractions of the baseline rate (all configurable)."""

    improving: float = 0.75
    fixed: float = 0.50
    regressed: float = 0.90
    fixed_streak: int = 2
    puzzle_accuracy: float = 0.75
    puzzle_attempts: int = 20
    guard_count: int = 5  # FR-10.34's sample-size guard


@dataclass(frozen=True)
class Schedule:
    """FR-10.32's optional time schedule: off, every N days, or on a weekday (0 = Monday)."""

    kind: str = "off"
    days: int = 7
    weekday: int = 6


@dataclass(frozen=True)
class CheckpointSettings:
    every_games: int = 10
    window: int = 30
    schedule: Schedule = field(default_factory=Schedule)
    rated_only: bool = True
    time_classes: tuple[str, ...] = ("rapid", "classical")
    color: str = "both"
    thresholds: Thresholds = field(default_factory=Thresholds)
    auto_ai: bool = True  # FR-10.37: on by default (Adam, 2026-11-10); still bound by the cap and budget
    notices: bool = True  # FR-10.38: status-change notices (v1.0 planning: on)

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        d["time_classes"] = list(self.time_classes)
        return d


def _whole(v: Any, rng: tuple[int, int], what: str) -> int:
    if not isinstance(v, int) or isinstance(v, bool) or not rng[0] <= v <= rng[1]:
        raise ValidationError(f"{what} must be a whole number from {rng[0]} to {rng[1]}.")
    return v


def _share(v: Any, what: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 < v <= 1:
        raise ValidationError(f"{what} must be a percentage from 1 to 100.")
    return round(float(v), 4)


def checked_settings(data: Any) -> CheckpointSettings:
    """Settings from JSON (the bridge or `user.db`), checked. Unknown keys are refused."""
    if not isinstance(data, dict):
        raise ValidationError("Checkpoint settings must be an object.")
    known = set(CheckpointSettings.__dataclass_fields__)
    if set(data) - known:
        raise ValidationError("unknown checkpoint setting(s): " + ", ".join(sorted(set(data) - known))[:200])
    d = CheckpointSettings()
    sch_raw = data.get("schedule", asdict(d.schedule))
    th_raw = data.get("thresholds", asdict(d.thresholds))
    if not isinstance(sch_raw, dict) or not isinstance(th_raw, dict):
        raise ValidationError("Checkpoint settings must be an object.")
    kind = sch_raw.get("kind", "off")
    if kind not in SCHEDULE_KINDS:
        raise ValidationError("The schedule must be off, every N days or a weekday.")
    schedule = Schedule(
        kind, _whole(sch_raw.get("days", 7), DAYS_RANGE, "The number of days"),
        _whole(sch_raw.get("weekday", 6), (0, 6), "The weekday"),
    )  # fmt: skip
    th = Thresholds(
        improving=_share(th_raw.get("improving", d.thresholds.improving), "Improving"),
        fixed=_share(th_raw.get("fixed", d.thresholds.fixed), "Fixed"),
        regressed=_share(th_raw.get("regressed", d.thresholds.regressed), "Regressed"),
        fixed_streak=_whole(th_raw.get("fixed_streak", d.thresholds.fixed_streak), STREAK_RANGE, "Checkpoints in a row"),
        puzzle_accuracy=_share(th_raw.get("puzzle_accuracy", d.thresholds.puzzle_accuracy), "Puzzle accuracy"),
        puzzle_attempts=_whole(th_raw.get("puzzle_attempts", d.thresholds.puzzle_attempts), PUZZLE_ATTEMPTS_RANGE,
                               "Puzzle attempts"),
    )  # fmt: skip
    if not th.fixed < th.improving < th.regressed:
        raise ValidationError("The thresholds must go Fixed < Improving < Regressed.")
    tcs = data.get("time_classes", list(d.time_classes))
    if not isinstance(tcs, list) or not tcs or not all(isinstance(t, str) and t in MY_TIME_CLASSES for t in tcs):
        raise ValidationError("Choose at least one time control.")
    color = data.get("color", d.color)
    if color not in COLORS:
        raise ValidationError("The color must be white, black or both.")
    flags = {k: data.get(k, getattr(d, k)) for k in ("rated_only", "auto_ai", "notices")}
    if not all(isinstance(v, bool) for v in flags.values()):
        raise ValidationError("rated_only, auto_ai and notices must be true or false")
    return CheckpointSettings(
        every_games=_whole(data.get("every_games", d.every_games), EVERY_RANGE, "Games between checkpoints"),
        window=_whole(data.get("window", d.window), WINDOW_RANGE, "The rolling window"),
        schedule=schedule, rated_only=flags["rated_only"], time_classes=tuple(dict.fromkeys(tcs)), color=color,
        thresholds=th, auto_ai=flags["auto_ai"], notices=flags["notices"],
    )  # fmt: skip


def schedule_due(s: Schedule, last: datetime | None, enabled_at: datetime | None, now: datetime,
                 local_date: Callable[[datetime], date]) -> bool:  # fmt: skip
    """FR-10.32: has the time schedule come due? ``last`` is the last time the schedule was served (whether or not
    it found new games), ``enabled_at`` when it was turned on. Days count from either; a weekday is due once per
    week, on or after that day."""
    if s.kind == "off" or enabled_at is None:
        return False
    if last is not None and last > now:  # the clock was wrong when it was recorded: serve it now
        return True
    if s.kind == "days":
        return now >= (last or enabled_at) + timedelta(days=s.days)
    today = local_date(now)
    occurrence = today - timedelta(days=(today.weekday() - s.weekday) % 7)
    if local_date(enabled_at) > occurrence:
        return False
    return last is None or local_date(last) < occurrence


# ---- observations ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Observation:
    """One weakness as a report measured it."""

    key: str
    kind: str
    label: str
    themes: tuple[str, ...]
    per10: float
    count: int
    reasons: dict[str, int] = field(default_factory=dict)


def _obs(w: Weakness) -> Observation:
    return Observation(w.key, w.kind, w.label, tuple(w.themes), w.per10, w.count, dict(w.reasons))


def observations(report: Report) -> dict[str, Observation]:
    """Every game weakness of a report (Missed, Allowed, habits and v0.11's whole-game ones), by key."""
    out: dict[str, Observation] = {}
    for w in [*report.missed, *report.allowed, *report.habits, *report.whole_game]:
        out.setdefault(w.key, _obs(w))
    return out


def absent_means_zero(key: str) -> bool:
    """A Missed / Allowed theme or a habit tag absent from a report had no occurrences; a whole-game weakness absent
    from one just wasn't measured (module docstring)."""
    kind, _, name = key.partition(":")
    return kind in ("missed", "allowed") or (kind == "habit" and name in HABITS)


@dataclass(frozen=True)
class PuzzleAccuracy:
    accuracy: float | None
    attempts: int


def puzzle_accuracy(themes: Sequence[str], attempts: Iterable[AttemptRow], before: datetime | None = None,
                    dashboard: Mapping[str, tuple[int, int]] | None = None) -> PuzzleAccuracy:  # fmt: skip
    """First-try accuracy on a weakness's themes (FR-10.34): your local attempts (misclicks left out; only those
    finished before ``before`` when given) plus the Lichess dashboard's (`nb`, `firstWins`) per theme when known."""
    want = set(themes)
    if not want:
        return PuzzleAccuracy(None, 0)
    total = wins = 0
    for a in attempts:
        if a.misclick or a.finished_at is None or not a.themes or want.isdisjoint(a.themes):
            continue
        if before is not None and a.finished_at >= before:
            continue
        total += 1
        wins += int(a.win)
    for t in want:
        nb, first = (dashboard or {}).get(t, (0, 0))
        total += nb
        wins += first
    return PuzzleAccuracy(round(wins / total, 3) if total else None, total)


# ---- one checkpoint's step ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Tracked:
    key: str
    kind: str
    label: str
    themes: tuple[str, ...]
    baseline_per10: float
    baseline_games: int
    first_checkpoint: int
    status: str
    status_since: int
    fixed_streak: int = 0


@dataclass(frozen=True)
class Metric:
    key: str
    per10: float
    count: int
    puzzle_accuracy: float | None
    puzzle_attempts: int
    guarded: bool
    status: str
    reasons: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class Change:
    key: str
    label: str
    old: str | None  # None: newly detected
    new: str


@dataclass(frozen=True)
class CheckpointDraft:
    """A checkpoint about to be saved (the repository gives it its row)."""

    number: int
    created_at: str
    trigger: str
    report_id: int | None
    reconstructed: bool
    game_ids: tuple[int, ...]
    newest_played_at: str | None
    health: dict[str, Any]


@dataclass(frozen=True)
class Step:
    tracked: dict[str, Tracked]
    metrics: list[Metric]
    changes: list[Change]


def _base_status(key: str, in_mix: set[str]) -> str:
    return TRAINING if key in in_mix else NEW


def is_guarded(count: int, baseline_per10: float, window_games: int, th: Thresholds) -> bool:
    """FR-10.34: too few occurrences in the window while the baseline also expected too few to tell."""
    expected = baseline_per10 * window_games / 10
    return count < th.guard_count and expected < th.guard_count


def _passes_puzzles(t: Tracked, acc: PuzzleAccuracy, th: Thresholds) -> bool:
    if not t.themes:
        return True  # nothing trains it with puzzles: the game rate decides (v1.0 planning)
    return acc.attempts >= th.puzzle_attempts and acc.accuracy is not None and acc.accuracy >= th.puzzle_accuracy


def next_status(t: Tracked, per10: float, guarded: bool, acc: PuzzleAccuracy, in_mix: set[str],
                th: Thresholds) -> tuple[str, int]:  # fmt: skip
    """(status, fixed streak) after one checkpoint (FR-10.35)."""
    if guarded:
        return t.status, t.fixed_streak
    ratio = per10 / t.baseline_per10 if t.baseline_per10 > 0 else (0.0 if per10 == 0 else math.inf)
    streak = t.fixed_streak + 1 if ratio <= th.fixed else 0
    prev = t.status
    if prev in (FIXED, IMPROVING) and ratio >= th.regressed:
        return REGRESSED, 0
    if prev == FIXED:
        return FIXED, streak
    if streak >= th.fixed_streak and _passes_puzzles(t, acc, th):
        return FIXED, streak
    if ratio <= th.improving:
        return IMPROVING, streak
    if prev == REGRESSED:
        return REGRESSED, streak
    return _base_status(t.key, in_mix), streak


def step(
    tracked: Mapping[str, Tracked],
    seen: Mapping[str, Observation],
    window_games: int,
    checkpoint: int,
    puzzles: Callable[[tuple[str, ...]], PuzzleAccuracy],
    in_mix: set[str],
    th: Thresholds,
    baselines: Mapping[str, tuple[float, int]] | None = None,
) -> Step:
    """One checkpoint: measure every tracked weakness, start tracking new ones, and move statuses.

    ``baselines`` (key → per10, games) is used for weaknesses seen for the first time; without an entry their
    baseline is the rate they first appear with."""
    out: dict[str, Tracked] = dict(tracked)
    metrics: list[Metric] = []
    changes: list[Change] = []
    for key, t in sorted(tracked.items()):
        o = seen.get(key)
        if o is None and not absent_means_zero(key):
            continue  # not measured this time
        per10, count = (o.per10, o.count) if o else (0.0, 0)
        acc = puzzles(t.themes)
        guarded = is_guarded(count, t.baseline_per10, window_games, th)
        status, streak = next_status(t, per10, guarded, acc, in_mix, th)
        if status != t.status and {status, t.status} != {NEW, TRAINING}:
            changes.append(Change(key, t.label, t.status, status))
        out[key] = replace(t, status=status, fixed_streak=streak,
                           status_since=checkpoint if status != t.status else t.status_since,
                           label=o.label if o else t.label, themes=o.themes if o else t.themes)  # fmt: skip
        metrics.append(Metric(key, per10, count, acc.accuracy, acc.attempts, guarded, status,
                              dict(o.reasons) if o else {}))  # fmt: skip
    for key, o in sorted(seen.items()):
        if key in tracked or o.count <= 0:
            continue
        per10, games = (baselines or {}).get(key, (o.per10, window_games))
        if per10 <= 0:
            per10, games = o.per10, window_games
        status = _base_status(key, in_mix)
        out[key] = Tracked(key, o.kind, o.label, o.themes, per10, games, checkpoint, status, checkpoint)
        acc = puzzles(o.themes)
        metrics.append(Metric(key, o.per10, o.count, acc.accuracy, acc.attempts, False, status, dict(o.reasons)))
        changes.append(Change(key, o.label, None, status))
    return Step(out, metrics, changes)


def mark_training(tracked: Mapping[str, Tracked], picked: Iterable[str], checkpoint: int) -> dict[str, Tracked]:
    """FR-10.35: Training means "in the current Suggested mix". New and Training follow the mix; the other statuses
    are decided by the game rate and stay."""
    chosen = set(picked)
    out: dict[str, Tracked] = {}
    for key, t in tracked.items():
        if t.status in (NEW, TRAINING):
            s = TRAINING if key in chosen else NEW
            out[key] = t if s == t.status else replace(t, status=s, status_since=checkpoint)
        else:
            out[key] = t
    return out


# ---- game health (FR-10.36) -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class MyMove:
    ply: int
    phase: str
    cp_loss: int


def reason_groups(reasons: Mapping[str, int]) -> dict[str, float]:
    """The mistake-reason mix as shares of process / calculation / knowledge / time (misclicks left out)."""
    group_of: dict[str, str] = {r.key: r.gap for r in REASONS}
    counts: Counter[str] = Counter()
    for r, n in reasons.items():
        g = group_of.get(r)
        if r != MISCLICK and g in REASON_GROUPS:
            counts[g] += n
    total = sum(counts.values())
    return {g: round(counts[g] / total, 3) for g in REASON_GROUPS} if total else {}


def _acpl(moves: Iterable[MyMove]) -> float | None:
    losses = [min(max(m.cp_loss, 0), LOSS_CAP) for m in moves]
    return round(sum(losses) / len(losses), 1) if losses else None


def game_health(
    report: Report,
    my_moves: Mapping[int, Sequence[MyMove]],
    ratings: Sequence[tuple[str, str | None, int | None]],
) -> dict[str, Any]:
    """FR-10.36 for one checkpoint's window. ``my_moves`` are your graded moves per game (all of them, not only the
    errors); ``ratings`` are (platform, played_at, your rating) per game."""
    moves = [m for ms in my_moves.values() for m in ms]
    by_phase: dict[str, float | None] = {p: _acpl(m for m in moves if m.phase == p) for p in PHASES}
    latest: dict[str, tuple[str, int]] = {}
    for platform, played, rating in ratings:
        if platform not in ("lichess", "chesscom") or rating is None or not played:
            continue
        if platform not in latest or played > latest[platform][0]:
            latest[platform] = (played, rating)
    return {
        "games": report.games,
        "per10": dict(report.per10),
        "acpl": _acpl(moves),
        "acpl_by_phase": by_phase,
        "habits": {w.name: w.per10 for w in report.habits},
        "reasons": reason_groups(report.reasons),
        "results": dict(report.results),
        "ratings": {p: r for p, (_, r) in sorted(latest.items())},
    }


# ---- backfill (v1.0 planning) ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class BackfillPoint:
    """One reconstructed checkpoint: the window's game ids (oldest first) and the games used for baselines (only
    on the first point)."""

    window: tuple[int, ...]
    baseline: tuple[int, ...] = ()


def backfill_points(game_ids: Sequence[int], every: int, window: int) -> list[BackfillPoint]:
    """The reconstructed checkpoints for your analyzed eligible games, **oldest first**: none with fewer than
    `BASELINE_GAMES`; the first at the end of the baseline window, then one every ``every`` games, each over the
    last ``window`` games."""
    n = len(game_ids)
    if n < BASELINE_GAMES:
        return []
    first = tuple(game_ids[max(0, BASELINE_GAMES - window) : BASELINE_GAMES])
    out = [BackfillPoint(first, tuple(game_ids[:BASELINE_GAMES]))]
    end = BASELINE_GAMES + every
    while end <= n:
        out.append(BackfillPoint(tuple(game_ids[max(0, end - window) : end])))
        end += every
    return out


def group_by_game(rows: Iterable[tuple[int, int, str, int]]) -> dict[int, list[MyMove]]:
    """(game id, ply, phase, cp loss) rows → your moves per game."""
    out: dict[int, list[MyMove]] = defaultdict(list)
    for gid, ply, phase, loss in rows:
        out[gid].append(MyMove(ply, phase, loss))
    return dict(out)


# ---- the AI checkpoint summary (FR-10.37) ---------------------------------------------------------------------

CHECKPOINT_RULES = """
- This report is a checkpoint (FR-10.37). The "Checkpoint" part gives each tracked weakness's status, its frozen
  baseline and its rate now (per 10 games), the status changes at this checkpoint, and why the Suggested mix is
  built as it is. Make your "summary" a checkpoint commentary: what improved, what didn't, and why the mix changed,
  from those numbers only. Never give a weakness a status the part doesn't, and say "not enough data yet" where it
  says so.
"""


def prompt_part(ctx: Mapping[str, Any] | None) -> str:
    """The checkpoint's aggregates for the AI summary: labels, statuses and rates only (no games, names or dates)."""
    if not ctx:
        return ""
    return "\n".join(["", "Checkpoint (aggregates only):", json.dumps(ctx, separators=(",", ":"))])


def summary_context(number: int, window_games: int, tracked: Mapping[str, Tracked],
                    metrics: Sequence[Metric], changes: Sequence[Change], mix_why: Sequence[str]) -> dict[str, Any]:  # fmt: skip
    """What `prompt_part` sends for one checkpoint."""
    at = {m.key: m for m in metrics}
    rows = []
    for key, t in sorted(tracked.items(), key=lambda kv: (STATUSES.index(kv[1].status), kv[0])):
        m = at.get(key)
        rows.append({
            "key": key, "label": t.label, "status": t.status, "baseline_per10": round(t.baseline_per10, 2),
            "per10": round(m.per10, 2) if m else None, "not_enough_data": bool(m and m.guarded),
        })  # fmt: skip
    return {
        "checkpoint": number,
        "window_games": window_games,
        "weaknesses": rows,
        "status_changes": [{"label": c.label, "from": c.old, "to": c.new} for c in changes if c.old is not None],
        "suggested_mix": list(mix_why),
    }
