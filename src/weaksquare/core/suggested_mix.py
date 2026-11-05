"""The Suggested puzzle mix (v0.10, REQUIREMENTS §10.7) and the report's recommended preset (FR-10.19).

Deterministic, from the Coach report. Until checkpoints arrive (v1.0) there are no weakness statuses,
so weaknesses are ranked by score (rate per 10 games × severity) and the label says *"from Coach run
#N"* (FR-10.28 note, v0.10 planning).

- **Ratios:** one group per top weakness (its drill themes, FR-10.27), weighted by its score, plus a
  **long combinations** group (Lichess's `long` and `veryLong` themes) sized by how often your Missed
  tactics took more than one move, plus a 10% exploration share (FR-10.29). Never left out.
- **Mode:** from the top weakness's mistake reasons once it has at least 5 tagged misses (FR-10.29);
  otherwise the weakness's own default (Danger spotting for Allowed and the habit tags that need it).
- **Your own puzzles:** with Standard or Commit the line, the source is **Both**, and the puzzles the
  Coach made from your games fill 20% of the slots (FR-10.44). Name the idea and Danger spotting are
  Lichess-only (FR-3.15), so those mixes stay on Lichess DB.
- **Rating band:** your puzzle rating ±150 (1500 when unknown), moved by 100 when your recent
  first-try accuracy is outside 65–85%, aiming for about 75%; −200 for an "unknown pattern" weakness.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from weaksquare.core.coach import Report, Weakness
from weaksquare.core.filters import RATING_CEILING, RATING_FLOOR, FilterSpec, RatioBucket

MAX_GROUPS = 4  # weakness groups; the long-combinations group comes on top
EXPLORATION = 10
MY_SHARE = 20
MIN_TAGGED = 5
BAND = 150
LOWER_BAND = 200  # FR-10.29: "unknown pattern" practises a lower band first
DEFAULT_RATING = 1500
LONG_THEMES = ("long", "veryLong")
PROCESS = ("didntLook", "missedResource")
MY_PUZZLE_MODES = ("standard", "commit_line")


@dataclass(frozen=True)
class Suggestion:
    spec: FilterSpec
    mode: str
    why: tuple[str, ...]
    weaknesses: tuple[str, ...]  # the keys the mix is built from, in order
    extra: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "spec": self.spec.to_json(),
            "mode": self.mode,
            "why": list(self.why),
            "weaknesses": list(self.weaknesses),
        }


def mode_for(w: Weakness) -> tuple[str, str | None]:
    """(mode, note) for a weakness, from its mistake reasons when there are enough (FR-10.29)."""
    tagged = sum(n for r, n in w.reasons.items() if r != "misclick")
    if tagged >= MIN_TAGGED:
        groups: Counter[str] = Counter()
        for r, n in w.reasons.items():
            if r in PROCESS:
                groups["process"] += n
            elif r in ("miscalculated", "unknownPattern", "rushed"):
                groups[r] += n
        if groups:
            top, _ = groups.most_common(1)[0]
            if top == "process":
                return "danger_spotting", "you mostly didn't look for it"
            if top == "miscalculated":
                return "commit_line", "you mostly saw it but miscalculated"
            if top == "unknownPattern":
                return "standard", "you mostly didn't know the pattern"
            if top == "rushed":
                return (w.mode or "standard"), "you mostly rushed: that's a time-use issue more than a pattern"
    return (w.mode or "standard"), None


def _weights(scores: Sequence[float], total: int) -> list[int]:
    """Whole-number weights adding up to ``total``, each at least 1, proportional to ``scores``."""
    s = sum(scores) or 1.0
    raw = [max(1, round(total * x / s)) for x in scores]
    diff = total - sum(raw)
    i = 0
    while diff != 0 and raw:
        j = i % len(raw)
        if diff > 0:
            raw[j] += 1
            diff -= 1
        elif raw[j] > 1:
            raw[j] -= 1
            diff += 1
        i += 1
        if i > 10_000:  # pragma: no cover - always converges for total >= len(raw)
            break
    return raw


def _band(center: int) -> tuple[int, int]:
    lo = max(RATING_FLOOR, center - BAND)
    hi = min(RATING_CEILING, center + BAND)
    return lo, hi


def build_suggestion(
    report: Report,
    *,
    puzzle_rating: int | None,
    recent_accuracy: float | None,
    has_game_puzzles: bool,
    base: FilterSpec | None = None,
) -> Suggestion | None:
    """The Suggested mix for this report, or None when there's nothing to build it from."""
    picked: list[Weakness] = []
    seen_themes: set[tuple[str, ...]] = set()
    for w in report.weaknesses:
        key = tuple(sorted(w.themes))
        if not w.themes or key in seen_themes:
            continue
        seen_themes.add(key)
        picked.append(w)
        if len(picked) == MAX_GROUPS:
            break
    if not picked:
        return None

    missed = report.missed
    total_missed = sum(w.count for w in missed)
    multi = sum(w.multi_move for w in missed)
    long_share = EXPLORATION + (round((100 - EXPLORATION) * multi / total_missed) if total_missed else 0)
    long_share = min(50, long_share)
    weights = _weights([w.score or 0.01 for w in picked], 100 - long_share)
    buckets = [RatioBucket(tuple(w.themes), wt) for w, wt in zip(picked, weights, strict=True)]
    buckets.append(RatioBucket(LONG_THEMES, long_share))

    top = picked[0]
    mode, note = mode_for(top)
    center = puzzle_rating or DEFAULT_RATING
    if recent_accuracy is not None:
        if recent_accuracy < 0.65:
            center -= 100
        elif recent_accuracy > 0.85:
            center += 100
    if note == "you mostly didn't know the pattern":
        center -= LOWER_BAND
    lo, hi = _band(center)

    use_mine = has_game_puzzles and mode in MY_PUZZLE_MODES
    start = base or FilterSpec()
    spec = FilterSpec(
        ratios=tuple(buckets),
        rating_min=lo,
        rating_max=hi,
        queue_size=start.queue_size,
        min_popularity=start.min_popularity,
        min_plays=start.min_plays,
        exclude_solved_here=start.exclude_solved_here,
        exclude_played_on_lichess=start.exclude_played_on_lichess,
        source="both" if use_mine else "lichess",
        my_origins=("coach",) if use_mine else (),
        my_share=MY_SHARE if use_mine else None,
    )
    spec.validate()

    why: list[str] = []
    for i, (w, wt) in enumerate(zip(picked, weights, strict=True)):
        rank = "your #1 leak" if i == 0 else f"#{i + 1}"
        if w.kind == "puzzle":
            acc = f"{round(100 * w.puzzle_accuracy)}%" if w.puzzle_accuracy is not None else "low"
            why.append(f"{w.label}: {acc} first-try accuracy, {rank} ({wt}% of the mix).")
        else:
            why.append(f"{w.label}: {w.per10:g} per 10 games, {rank} ({wt}% of the mix).")
    if total_missed and multi:
        why.append(f"Long combinations: {multi} of your {total_missed} missed tactics took more than one move.")
    why.append(f"Long and very long combinations get {long_share}%, including a {EXPLORATION}% exploration share.")
    mode_name = {"danger_spotting": "Danger spotting", "commit_line": "Commit the line", "standard": "Standard"}
    why.append(f"Mode: {mode_name.get(mode, mode)}" + (f", because {note}." if note else "."))
    if use_mine:
        why.append(f"{MY_SHARE}% of the puzzles come from your own games' mistakes.")
    why.append(f"Rating {lo}–{hi}, aiming for about 75% first-try accuracy.")
    low_clock = next((w for w in report.whole_game if w.key == "time:low_clock"), None)
    if low_clock is not None:  # FR-10.58: time is flagged here, not drilled with puzzles
        why.append(
            f"Time: {low_clock.per10:g} mistakes per 10 games under 10% of your clock. That's a time-use issue"
            " more than a pattern: keep more time for the end of the game."
        )
    return Suggestion(spec, mode, tuple(why), tuple(w.key for w in picked))


def report_preset(report: Report, puzzle_rating: int | None, recent_accuracy: float | None) -> Suggestion | None:
    """FR-10.19: the report's deterministic preset. The same rules, without your own puzzles (a preset
    should work the same for another player's report)."""
    return build_suggestion(
        report, puzzle_rating=puzzle_rating, recent_accuracy=recent_accuracy, has_game_puzzles=False
    )
