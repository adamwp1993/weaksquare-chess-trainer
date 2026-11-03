"""Angle reporting for Lichess sync (REQUIREMENTS §8.3, FR-6.13–6.15).

Lichess weights a rating change by the reported angle, because a theme known in advance hints at
the answer: `mix` counts fully, a motif much less. The app reports truthfully:

- `mix` only when the theme filter is All, the move-count filter is All and there are no ratios.
- Otherwise the selected theme this puzzle matched. With ratios, the selected themes are every
  group's themes, in group order. When several match, the first by priority tier wins, then by
  selection order:
    1. Motifs, Advanced, Mates, Mate patterns, Special moves (and themes this app doesn't know)
    2. Phases, Goals, Origin
    3. Lengths (oneMove, short, long, veryLong)
- When the themes are All but the move count isn't, the angle is the puzzle's length theme
  (decided at v0.3 planning): that's what you knew in advance.

Excluded themes, openings, rating, side, quality and history filters don't change the angle.
"""

from __future__ import annotations

from typing import Literal

from weaksquare.core.filters import FilterSpec
from weaksquare.core.themes import info

MIX = "mix"
LENGTH_THEMES = {1: "oneMove", 2: "short", 3: "long"}  # 4 or more: veryLong
_TIER = {
    "Motifs": 0,
    "Advanced": 0,
    "Mates": 0,
    "Mate patterns": 0,
    "Special moves": 0,
    "Other": 0,
    "Phases": 1,
    "Goals": 1,
    "Origin": 1,
    "Lengths": 2,
}


def length_theme(length: int) -> str:
    return LENGTH_THEMES.get(length, "veryLong")


def selected_themes(spec: FilterSpec) -> tuple[str, ...]:
    """The themes the selection named: the theme list, or every ratio group's themes in order."""
    if spec.ratios:
        seen: dict[str, None] = {}
        for bucket in spec.ratios:
            for t in bucket.themes:
                seen.setdefault(t, None)
        return tuple(seen)
    return spec.themes


def angle_for(
    spec: FilterSpec, puzzle_themes: tuple[str, ...] | list[str], length: int, length_known: bool = False
) -> str:
    """The angle to report for one puzzle served by `spec` (FR-6.13, 6.14). `length_known`: the move
    count was shown in advance some other way (Commit the line's Show move count, v0.5), which counts
    as a narrowed move count. The depth ladder narrows `spec.lengths` itself (`at_ladder_level`)."""
    chosen = selected_themes(spec)
    if not chosen and spec.all_lengths and not length_known:
        return MIX
    has = set(puzzle_themes)
    matched = [t for t in chosen if t in has]
    if matched:
        order = {t: i for i, t in enumerate(chosen)}
        return min(matched, key=lambda t: (_TIER.get(info(t).group, 0), order[t]))
    # Only the move count was narrowed (or, with odd data, no selected theme matched).
    return length_theme(length)


RatingStatus = Literal["syncing", "offline", "unrated", "already_played", "not_rated", "done"]


def rating_status(
    *,
    rated: bool | None,
    already_played: bool | None,
    sync_status: str | None,
    rating_diff: int | None,
    online: bool,
) -> RatingStatus:
    """What the result panel says about one attempt's rating change (FR-6.11b).

    A change Lichess returned is always shown. Otherwise it says why there's no number: Rated was
    off, Lichess had already seen the puzzle from you, or Lichess returned 0 or nothing. While the
    solve waits in the queue it's *Syncing…* when Lichess is reachable, else *Will sync later*."""
    if sync_status == "synced" and rating_diff:
        return "done"
    if rated is False:
        return "unrated"
    if already_played:
        return "already_played"
    if sync_status == "pending":
        return "syncing" if online else "offline"
    return "not_rated"
