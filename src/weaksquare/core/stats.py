"""The basic Stats page (FR-9.1, FR-9.2): accuracy per theme, per length, per rating band and (v0.5) per mode, and the
"first move right, line wrong" rate. Pure: takes attempt rows, returns grouped tallies.

"First move right, line wrong" is measured among the attempts where your first move was right: the
share where the rest of the line then went wrong. That isolates calculation from spotting the idea.

v0.6:
- A miss tagged Misclick is left out of every tally and counted on its own (FR-5.10).
- Danger-spotting results are a different task from solving the puzzle (FR-4.4), so they count only in
  By mode and in the mode details, not overall or per theme, length or rating.
- Mode details (FR-9.3): Commit's calculation accuracy, Name the idea's ideas found / tags right, and
  Danger-spotting accuracy split by safe candidates and real blunders.
- The reason breakdown (FR-9.7, puzzles): counts per reason, filterable by theme and mode, by week.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from weaksquare.core.reasons import MISCLICK, REASONS, misclick_warning

BAND = 200
LENGTH_LABELS = {1: "1 move", 2: "2 moves", 3: "3 moves", 4: "4+ moves"}
# Training modes in the order the Modes control shows them (v0.5). An unknown mode keeps its key.
MODE_LABELS = {
    "standard": "Standard",
    "commit_line": "Commit the line",
    "name_idea": "Name the idea first",
    "danger_spotting": "Danger spotting",
    "spaced_repetition": "Spaced repetition",
}
DANGER = "danger_spotting"


@dataclass(frozen=True)
class AttemptRow:
    win: bool
    first_move_correct: bool
    line_correct: bool
    puzzle_rating: int | None  # the rating when you played it (None for old attempts it can't recover)
    themes: tuple[str, ...] | None  # None: the puzzle is no longer in the database (FR-2.4)
    length: int | None
    mode: str = "standard"
    reason: str | None = None  # the latest mistake reason (§7.3)
    finished_at: datetime | None = None  # for the reason trend (by local calendar week)
    replies_correct: int | None = None  # Commit the line (FR-4.2)
    replies_total: int | None = None
    idea_found: int | None = None  # Name the idea (FR-4.3); None: no tag score
    idea_total: int | None = None
    idea_extra: int | None = None
    danger_safe: bool | None = None  # Danger spotting (FR-4.4): the candidate was the safe move

    @property
    def misclick(self) -> bool:
        return not self.win and self.reason == MISCLICK


@dataclass(frozen=True)
class Tally:
    key: str
    label: str
    attempts: int
    solved: int
    first_right: int  # attempts where the first move was right
    first_right_line_wrong: int  # …and the line then went wrong

    @property
    def accuracy(self) -> float | None:
        return self.solved / self.attempts if self.attempts else None

    @property
    def line_wrong_rate(self) -> float | None:
        return self.first_right_line_wrong / self.first_right if self.first_right else None


@dataclass(frozen=True)
class ModeDetails:
    """FR-9.3: each mode's own measure. Counts, so the page can show "n/a" when there's nothing yet."""

    replies_correct: int = 0  # Commit the line: predicted replies that matched…
    replies_total: int = 0  # …of the solutions' replies
    ideas_found: int = 0  # Name the idea: your tags that were puzzle motifs…
    ideas_total: int = 0  # …of the puzzles' motifs (ideas found = found ÷ total)
    tags_named: int = 0  # …of your tags (tags right = found ÷ named)
    danger_safe: int = 0  # Danger spotting: safe candidates shown…
    danger_safe_right: int = 0  # …and called right
    danger_blunder: int = 0  # real blunders shown…
    danger_blunder_right: int = 0  # …and called right (and refuted)


@dataclass(frozen=True)
class Report:
    overall: Tally
    by_theme: list[Tally]  # most-played first
    by_length: list[Tally]  # 1, 2, 3, 4+
    by_rating: list[Tally]  # lowest band first; "unknown" last
    missing: int  # attempts on puzzles no longer in the database (counted overall, by rating and by mode only)
    by_mode: list[Tally]  # in MODE_LABELS order, only modes you've played
    misclicks: int = 0  # FR-5.10: left out of every tally above
    misclick_warning: bool = False  # an unusually high share of your tagged misses
    details: ModeDetails = field(default_factory=ModeDetails)


class _Acc:
    def __init__(self) -> None:
        self.attempts = self.solved = self.first_right = self.frlw = 0

    def add(self, r: AttemptRow) -> None:
        self.attempts += 1
        self.solved += r.win
        if r.first_move_correct:
            self.first_right += 1
            self.frlw += not r.line_correct

    def tally(self, key: str, label: str) -> Tally:
        return Tally(key, label, self.attempts, self.solved, self.first_right, self.frlw)


def band(rating: int) -> int:
    return rating // BAND * BAND


def band_label(start: int) -> str:
    return f"{start}–{start + BAND - 1}"


def length_key(length: int) -> int:
    return min(length, 4)


def build_report(rows: Iterable[AttemptRow], theme_name: Callable[[str], str]) -> Report:
    overall = _Acc()
    themes: dict[str, _Acc] = {}
    lengths: dict[int, _Acc] = {}
    ratings: dict[int | None, _Acc] = {}
    modes: dict[str, _Acc] = {}
    missing = 0
    misclicks = tagged = 0
    d = {k: 0 for k in ModeDetails.__dataclass_fields__}
    for r in rows:
        if not r.win and r.reason is not None:
            tagged += 1
        if r.misclick:
            misclicks += 1
            continue
        modes.setdefault(r.mode, _Acc()).add(r)
        if r.replies_total:
            d["replies_correct"] += r.replies_correct or 0
            d["replies_total"] += r.replies_total
        if r.idea_total:
            d["ideas_found"] += r.idea_found or 0
            d["ideas_total"] += r.idea_total
            d["tags_named"] += (r.idea_found or 0) + (r.idea_extra or 0)
        if r.mode == DANGER:
            if r.danger_safe is not None:
                kind = "danger_safe" if r.danger_safe else "danger_blunder"
                d[kind] += 1
                d[kind + "_right"] += r.win
            continue  # not a solve of the puzzle as served: By mode and the details only
        overall.add(r)
        ratings.setdefault(None if r.puzzle_rating is None else band(r.puzzle_rating), _Acc()).add(r)
        if r.themes is None:
            missing += 1
            continue
        for t in dict.fromkeys(r.themes):
            themes.setdefault(t, _Acc()).add(r)
        if r.length is not None:
            lengths.setdefault(length_key(r.length), _Acc()).add(r)

    by_theme = sorted((a.tally(k, theme_name(k)) for k, a in themes.items()), key=lambda t: (-t.attempts, t.label))
    by_length = [lengths[k].tally(str(k), LENGTH_LABELS[k]) for k in sorted(lengths)]
    known = sorted(k for k in ratings if k is not None)
    by_rating = [ratings[k].tally(str(k), band_label(k)) for k in known]
    if None in ratings:
        by_rating.append(ratings[None].tally("unknown", "Unknown"))
    known_modes = [m for m in MODE_LABELS if m in modes] + sorted(m for m in modes if m not in MODE_LABELS)
    by_mode = [modes[m].tally(m, MODE_LABELS.get(m, m)) for m in known_modes]
    return Report(overall.tally("all", "All puzzles"), by_theme, by_length, by_rating, missing, by_mode,
                  misclicks, misclick_warning(misclicks, tagged), ModeDetails(**d))  # fmt: skip


# ---- mistake reasons (FR-9.7, puzzles) ----------------------------------------------------------------


@dataclass(frozen=True)
class ReasonCount:
    key: str
    label: str
    gap: str
    count: int
    share: float | None  # of the tagged misses shown (misclicks aside)


@dataclass(frozen=True)
class ReasonWeek:
    week: date  # the Monday the week starts on
    counts: tuple[int, ...]  # per reason, in REASON order, misclick excluded


@dataclass(frozen=True)
class ReasonReport:
    reasons: list[ReasonCount]  # the five reasons other than misclick, in FR-5.6 order
    tagged: int  # misses with a reason, misclicks aside
    untagged: int  # misses with no reason
    misclicks: int
    misclick_warning: bool
    trend: list[ReasonWeek]  # oldest first; only weeks with a tagged miss


def week_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def reason_report(
    rows: Iterable[AttemptRow],
    local_date: Callable[[datetime], date],
    theme: str | None = None,
    mode: str | None = None,
) -> ReasonReport:
    """The breakdown of why you missed puzzles, optionally for one theme and/or one mode. `local_date`
    turns a stored time into your calendar day (the injected clock's)."""
    keys = [r.key for r in REASONS if r.key != MISCLICK]
    counts = dict.fromkeys(keys, 0)
    weeks: dict[date, list[int]] = {}
    untagged = misclicks = 0
    for r in rows:
        if r.win or (mode is not None and r.mode != mode):
            continue
        if theme is not None and (r.themes is None or theme not in r.themes):
            continue
        if r.reason is None:
            untagged += 1
        elif r.reason == MISCLICK:
            misclicks += 1
        elif r.reason in counts:
            counts[r.reason] += 1
            if r.finished_at is not None:
                week = week_of(local_date(r.finished_at))
                weeks.setdefault(week, [0] * len(keys))[keys.index(r.reason)] += 1
    tagged = sum(counts.values())
    reasons = [ReasonCount(i.key, i.label, i.gap, counts[i.key], counts[i.key] / tagged if tagged else None)
               for i in REASONS if i.key != MISCLICK]  # fmt: skip
    trend = [ReasonWeek(w, tuple(c)) for w, c in sorted(weeks.items())]
    return ReasonReport(reasons, tagged, untagged, misclicks, misclick_warning(misclicks, tagged + misclicks), trend)
