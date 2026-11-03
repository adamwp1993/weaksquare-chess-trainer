"""Depth ladder (FR-4.5, an order since v0.5 planning; FR-3.11). Pure: the level comes from the attempts log.

- Levels: short (2 moves), long (3), very long (4+): the `lengths` values 2, 3 and 4.
- Your level is kept per theme set (the selected themes, match mode and excluded themes) as
  `ladder_key` on each attempt, with the level it was played at.
- Current level = the highest level recorded for the key, moved up one when the last `window`
  attempts at that level reach `threshold` percent. It never drops.
- Levels with no puzzles under the current filters are skipped (v0.5-B2): you start at the first
  level that has puzzles, moving up goes to the next one that has, and the last one is the top. If
  the recorded level has none any more (the other filters changed), the nearest level above it with
  puzzles is used, or failing that the nearest below.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from weaksquare.core.errors import ValidationError
from weaksquare.core.filters import FilterSpec

LEVELS: tuple[int, ...] = (2, 3, 4)  # puzzle lengths; 4 means "4 or more"
LEVEL_NAMES = {2: "Short", 3: "Long", 4: "Very long"}
DEFAULT_THRESHOLD = 80  # percent
DEFAULT_WINDOW = 20  # attempts
THRESHOLD_RANGE = (10, 100)
WINDOW_RANGE = (3, 100)


@dataclass(frozen=True)
class LadderStatus:
    key: str
    level: int  # a value from LEVELS
    played: int  # attempts at this level counted in the window (at most `window`)
    wins: int
    window: int
    threshold: int
    top: bool = False  # no level above this one has puzzles

    @property
    def step(self) -> int:
        """1-based position on the ladder, for "Long (2/3)"."""
        return LEVELS.index(self.level) + 1


def ladder_key(spec: FilterSpec) -> str:
    """The theme set a ladder belongs to. Order doesn't matter, and the match mode only matters
    with two or more themes."""
    themes = sorted(spec.themes)
    match = spec.match if len(themes) > 1 else "any"
    return json.dumps({"themes": themes, "match": match, "exclude": sorted(spec.exclude_themes)},
                      separators=(",", ":"), sort_keys=True)  # fmt: skip


def status(
    key: str,
    max_recorded: int | None,
    recent: Sequence[bool],
    threshold: int,
    window: int,
    available: Sequence[int] = LEVELS,
) -> LadderStatus:
    """`max_recorded`: the highest level any attempt for `key` was played at (None: never climbed).
    `recent`: the results of the last attempts at that level, newest last (only the last `window` count).
    `available`: the levels that have puzzles under the current filters (all of them if omitted)."""
    open_levels = [lv for lv in LEVELS if lv in available] or [LEVELS[0]]  # none: the session says so
    level = max_recorded if max_recorded in LEVELS else open_levels[0]
    if level not in open_levels:
        above = [lv for lv in open_levels if lv > level]
        level = above[0] if above else max(open_levels)
        recent = []  # a different level: its own window starts empty
    higher = [lv for lv in open_levels if lv > level]
    counted = list(recent)[-window:]
    wins = sum(1 for r in counted if r)
    if higher and len(counted) >= window and wins * 100 >= threshold * window:
        nxt = higher[0]
        return LadderStatus(key, nxt, 0, 0, window, threshold, top=nxt == open_levels[-1])
    return LadderStatus(key, level, len(counted), wins, window, threshold, top=not higher)


def validate_threshold(value: Any) -> int:
    lo, hi = THRESHOLD_RANGE
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise ValidationError(f"The ladder threshold is a whole percentage from {lo} to {hi}.")
    return value


def validate_window(value: Any) -> int:
    lo, hi = WINDOW_RANGE
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise ValidationError(f"The ladder window is a whole number of puzzles from {lo} to {hi}.")
    return value
