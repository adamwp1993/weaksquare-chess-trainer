"""FilterSpec: one serializable description of a puzzle selection (ARCHITECTURE §3 decision 5, REQUIREMENTS §5).

The whole §5 schema is defined now, because presets, the Coach and the angle rule will all share it.
v0.1 implements themes (ANY/ALL), excluded themes, rating, move count, side to move, random order
and queue size. Fields for later versions are part of the schema but must keep their defaults:
`validate()` rejects them with `unsupported_in_this_version` instead of silently ignoring them.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any, Literal

from weaksquare.core.errors import ValidationError
from weaksquare.core.themes import is_valid_key

MatchMode = Literal["any", "all"]
Side = Literal["either", "white", "black"]
Order = Literal["random", "easy_to_hard", "by_theme"]
Source = Literal["lichess", "my", "both"]

RATING_FLOOR = 0
RATING_CEILING = 4000
LENGTHS = (1, 2, 3, 4)  # 4 means "4 or more"
MAX_THEMES = 200
MAX_QUEUE = 500
DEFAULT_QUEUE = 20


class UnsupportedInThisVersion(ValidationError):
    code = "unsupported_in_this_version"


@dataclass(frozen=True)
class RatioBucket:
    """FR-3.10 (v0.2): draw `weight` percent of puzzles from these themes."""

    themes: tuple[str, ...]
    weight: int


@dataclass(frozen=True)
class FilterSpec:
    # --- v0.1 ---------------------------------------------------------------------------
    themes: tuple[str, ...] = ()  # empty = all themes (FR-3.1)
    match: MatchMode = "any"
    exclude_themes: tuple[str, ...] = ()  # FR-3.2
    rating_min: int | None = None  # None = the dataset's bound (FR-3.3)
    rating_max: int | None = None
    lengths: tuple[int, ...] = ()  # empty = All; values from LENGTHS (FR-3.4)
    side: Side = "either"  # FR-3.5
    order: Order = "random"  # FR-3.11 (random only in v0.1)
    queue_size: int | None = DEFAULT_QUEUE  # None = endless (FR-3.12)
    # --- later versions (schema only; must stay at the defaults in v0.1) ----------------
    openings: tuple[str, ...] = ()  # FR-3.7 (v0.2)
    min_popularity: int | None = None  # FR-3.8 (v0.2)
    min_plays: int | None = None  # FR-3.8 (v0.2)
    exclude_solved_here: bool = False  # FR-3.9 (v0.2)
    exclude_played_on_lichess: bool = False  # FR-3.9 (v0.3)
    only_my_misses: bool = False  # FR-3.9 (v0.2)
    ratios: tuple[RatioBucket, ...] = ()  # FR-3.10 (v0.2)
    source: Source = "lichess"  # FR-3.15 (v0.8)

    @property
    def all_themes(self) -> bool:
        return not self.themes

    @property
    def all_lengths(self) -> bool:
        return not self.lengths or set(self.lengths) == set(LENGTHS)

    # ---- JSON ---------------------------------------------------------------------------------
    def to_json(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        return {k: list(v) if isinstance(v, tuple) else v for k, v in d.items()}

    @classmethod
    def from_json(cls, data: Any) -> FilterSpec:
        """Parse untrusted JSON (from the UI or a stored preset) strictly, then validate."""
        if not isinstance(data, dict):
            raise ValidationError("filters must be an object")
        known = {f.name for f in dataclasses.fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ValidationError(f"unknown filter field(s): {', '.join(sorted(unknown))[:200]}")
        kwargs: dict[str, Any] = {}
        for key, value in data.items():
            kwargs[key] = _coerce(key, value)
        spec = cls(**kwargs)
        spec.validate()
        return spec

    # ---- rules --------------------------------------------------------------------------------
    def validate(self) -> None:
        for name, items in (("themes", self.themes), ("exclude_themes", self.exclude_themes)):
            if len(items) > MAX_THEMES or not all(is_valid_key(t) for t in items):
                raise ValidationError(f"{name} contains an invalid theme")
        if self.match not in ("any", "all"):
            raise ValidationError("match must be 'any' or 'all'")
        for bound in (self.rating_min, self.rating_max):
            if bound is not None and not RATING_FLOOR <= bound <= RATING_CEILING:
                raise ValidationError(f"rating must be between {RATING_FLOOR} and {RATING_CEILING}")
        if self.rating_min is not None and self.rating_max is not None and self.rating_min > self.rating_max:
            raise ValidationError("The minimum rating is above the maximum.")
        if not set(self.lengths) <= set(LENGTHS) or len(set(self.lengths)) != len(self.lengths):
            raise ValidationError("lengths must be distinct values from 1, 2, 3, 4 (4 = 4 or more)")
        if self.side not in ("either", "white", "black"):
            raise ValidationError("side must be 'either', 'white' or 'black'")
        if self.queue_size is not None and not 1 <= self.queue_size <= MAX_QUEUE:
            raise ValidationError(f"The number of puzzles must be between 1 and {MAX_QUEUE}.")
        later = {
            "order": self.order != "random",
            "openings": bool(self.openings),
            "min_popularity": self.min_popularity is not None,
            "min_plays": self.min_plays is not None,
            "exclude_solved_here": self.exclude_solved_here,
            "exclude_played_on_lichess": self.exclude_played_on_lichess,
            "only_my_misses": self.only_my_misses,
            "ratios": bool(self.ratios),
            "source": self.source != "lichess",
        }
        used = [k for k, v in later.items() if v]
        if used:
            raise UnsupportedInThisVersion(f"This version doesn't support the filter(s): {', '.join(used)}.")


def _coerce(key: str, value: Any) -> Any:
    """Convert JSON values to the field's type, rejecting anything else."""
    str_lists = {"themes", "exclude_themes", "openings"}
    optional_ints = {"rating_min", "rating_max", "queue_size", "min_popularity", "min_plays"}
    bools = {"exclude_solved_here", "exclude_played_on_lichess", "only_my_misses"}
    strings = {"match", "side", "order", "source"}
    if key in str_lists:
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ValidationError(f"{key} must be a list of strings")
        return tuple(value)
    if key == "lengths":
        if not isinstance(value, list) or not all(isinstance(v, int) and not isinstance(v, bool) for v in value):
            raise ValidationError("lengths must be a list of integers")
        return tuple(sorted(value))
    if key in optional_ints:
        if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
            raise ValidationError(f"{key} must be a whole number or null")
        return value
    if key in bools:
        if not isinstance(value, bool):
            raise ValidationError(f"{key} must be true or false")
        return value
    if key in strings:
        if not isinstance(value, str):
            raise ValidationError(f"{key} must be a string")
        return value
    if key == "ratios":
        if not isinstance(value, list):
            raise ValidationError("ratios must be a list")
        buckets = []
        for b in value:
            if not isinstance(b, dict) or set(b) != {"themes", "weight"}:
                raise ValidationError("each ratio needs themes and weight")
            themes, weight = b["themes"], b["weight"]
            if (
                not isinstance(themes, list)
                or not all(isinstance(t, str) for t in themes)
                or not isinstance(weight, int)
            ):
                raise ValidationError("each ratio needs a list of themes and a whole-number weight")
            buckets.append(RatioBucket(tuple(themes), weight))
        return tuple(buckets)
    raise ValidationError(f"unknown filter field: {key}")  # pragma: no cover
