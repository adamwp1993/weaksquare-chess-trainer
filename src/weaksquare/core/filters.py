"""FilterSpec: one serializable description of a puzzle selection (ARCHITECTURE §3 decision 5, REQUIREMENTS §5).

The whole §5 schema is defined in one place, because presets, the Coach and the angle rule all share it.
v0.1 implemented themes (ANY/ALL), excluded themes, rating, move count, side, random order and queue
size; v0.2 adds openings, quality, the history filters, ratios and the other orders; v0.3 adds
"exclude played on Lichess". Fields for later
versions are part of the schema but must keep their defaults: `validate()` rejects them with
`unsupported_in_this_version` instead of silently ignoring them.
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from typing import Any, Literal

from weaksquare.core.errors import ValidationError
from weaksquare.core.themes import is_valid_key

MatchMode = Literal["any", "all"]
Side = Literal["either", "white", "black"]
Order = Literal["random", "easy_to_hard", "by_theme", "depth_ladder"]  # depth_ladder: v0.5 (FR-4.5)
ORDERS = ("random", "easy_to_hard", "by_theme", "depth_ladder")
Source = Literal["lichess", "my", "both"]
SOURCES = ("lichess", "my", "both")
MY_ORIGINS = ("manual", "import", "coach")  # coach: v0.10 (FR-10.39)
MY_KINDS = ("missed", "allowed")
MY_PHASES = ("opening", "middlegame", "endgame")
MY_TIME_CLASSES = ("bullet", "blitz", "rapid", "classical", "daily")
MAX_SETS = 200

RATING_FLOOR = 0
RATING_CEILING = 4000
LENGTHS = (1, 2, 3, 4)  # 4 means "4 or more"
MAX_THEMES = 200
MAX_QUEUE = 500
DEFAULT_QUEUE = 20
# FR-3.8 quality defaults (decided at v0.2 planning): a light filter, adjustable; None turns one off.
DEFAULT_MIN_POPULARITY = 50
DEFAULT_MIN_PLAYS = 100
POPULARITY_RANGE = (-100, 100)  # Lichess popularity
MAX_MIN_PLAYS = 10_000_000
MAX_OPENINGS = 200
MAX_BUCKETS = 10
_OPENING_TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_'-]{0,99}$")


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
    order: Order = "random"  # FR-3.11
    queue_size: int | None = DEFAULT_QUEUE  # None = endless (FR-3.12)
    # --- v0.2 ---------------------------------------------------------------------------
    openings: tuple[str, ...] = ()  # FR-3.7: OpeningTags families or variations; empty = any
    min_popularity: int | None = DEFAULT_MIN_POPULARITY  # FR-3.8; None = no threshold
    min_plays: int | None = DEFAULT_MIN_PLAYS  # FR-3.8; None = no threshold
    exclude_solved_here: bool = True  # FR-3.9: hide puzzles you've won at least once here
    only_my_misses: bool = False  # FR-3.9: only puzzles whose latest attempt here was a loss
    ratios: tuple[RatioBucket, ...] = ()  # FR-3.10: replaces `themes` when set
    # --- v0.3 ---------------------------------------------------------------------------
    exclude_played_on_lichess: bool = True  # FR-3.9: hide puzzles in your Lichess history (on by default)
    # --- v0.8: the puzzle source (FR-3.15) ------------------------------------------------
    source: Source = "lichess"  # lichess / my (My puzzles: custom_puzzles) / both
    my_origins: tuple[str, ...] = ()  # manual (saved from your games) / import; empty = all
    my_sets: tuple[str, ...] = ()  # imported set labels; empty = all
    my_kinds: tuple[str, ...] = ()  # missed / allowed; empty = all
    my_phases: tuple[str, ...] = ()  # opening / middlegame / endgame; empty = all
    my_time_classes: tuple[str, ...] = ()  # bullet / blitz / rapid / classical / daily; empty = all

    @property
    def all_themes(self) -> bool:
        return not self.themes

    @property
    def all_lengths(self) -> bool:
        return not self.lengths or set(self.lengths) == set(LENGTHS)

    @property
    def excludes_solved(self) -> bool:
        """Only my misses wins over Exclude solved: a puzzle you won once and missed since is a miss."""
        return self.exclude_solved_here and not self.only_my_misses

    @property
    def excludes_played(self) -> bool:
        """Only my misses wins here too: a miss is a replay, and you've usually synced it to Lichess."""
        return self.exclude_played_on_lichess and not self.only_my_misses

    def bucket(self, index: int) -> FilterSpec:
        """The pool of ratio bucket `index`: these filters, with the bucket's themes (ANY) as the themes."""
        b = self.ratios[index]
        return dataclasses.replace(self, themes=b.themes, match="any", ratios=())

    # ---- JSON ---------------------------------------------------------------------------------
    def to_json(self) -> dict[str, Any]:
        def plain(v: Any) -> Any:  # tuples (also inside ratio buckets) become JSON lists
            if isinstance(v, (tuple, list)):
                return [plain(x) for x in v]
            if isinstance(v, dict):
                return {k: plain(x) for k, x in v.items()}
            return v

        return {k: plain(v) for k, v in dataclasses.asdict(self).items()}

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

    @property
    def depth_ladder(self) -> bool:
        return self.order == "depth_ladder"

    def at_ladder_level(self, level: int) -> FilterSpec:
        """The pool for one depth-ladder level (FR-4.5): the ladder sets the move count itself, and
        puzzles within a level come in random order. The angle rule then sees a narrowed move count,
        which is the truth: you know the length in advance (§8.3)."""
        return dataclasses.replace(self, lengths=(level,), order="random")

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
        if self.order not in ORDERS:
            raise ValidationError("order must be 'random', 'easy_to_hard', 'by_theme' or 'depth_ladder'")
        if self.order == "depth_ladder" and self.ratios:
            raise ValidationError("The depth ladder can't be combined with ratios: pick themes instead.")
        if len(self.openings) > MAX_OPENINGS or not all(_OPENING_TAG.match(o) for o in self.openings):
            raise ValidationError("openings contains an invalid opening")
        lo, hi = POPULARITY_RANGE
        if self.min_popularity is not None and not lo <= self.min_popularity <= hi:
            raise ValidationError(f"The minimum popularity must be between {lo} and {hi}.")
        if self.min_plays is not None and not 0 <= self.min_plays <= MAX_MIN_PLAYS:
            raise ValidationError(f"The minimum number of plays must be between 0 and {MAX_MIN_PLAYS:,}.")
        self._validate_ratios()
        self._validate_source()

    def _validate_source(self) -> None:
        """FR-3.15 (v0.8): the My-puzzles filters; ratios and the orders need Lichess's ratings and themes."""
        if self.source not in SOURCES:
            raise ValidationError("source must be 'lichess', 'my' or 'both'")
        for name, values, allowed in (
            ("my_origins", self.my_origins, MY_ORIGINS),
            ("my_kinds", self.my_kinds, MY_KINDS),
            ("my_phases", self.my_phases, MY_PHASES),
            ("my_time_classes", self.my_time_classes, MY_TIME_CLASSES),
        ):
            if not set(values) <= set(allowed) or len(set(values)) != len(values):
                raise ValidationError(f"{name} must be distinct values from {', '.join(allowed)}")
        if len(self.my_sets) > MAX_SETS or not all(isinstance(x, str) and 0 < len(x) <= 60 for x in self.my_sets):
            raise ValidationError("my_sets contains an invalid set label")
        if self.source != "lichess":
            if self.ratios:
                raise ValidationError("Ratios work with Lichess puzzles only. Choose Lichess DB as the source.")
            if self.order != "random":
                raise ValidationError("With My puzzles, the order is random. Choose Lichess DB for the other orders.")

    def _validate_ratios(self) -> None:
        if not self.ratios:
            return
        if self.themes:
            raise ValidationError("With ratios, the themes come from each ratio: clear the theme list.")
        if not 2 <= len(self.ratios) <= MAX_BUCKETS:
            raise ValidationError(f"Ratios need between 2 and {MAX_BUCKETS} groups.")
        for b in self.ratios:
            if not b.themes or len(b.themes) > MAX_THEMES or not all(is_valid_key(t) for t in b.themes):
                raise ValidationError("Each ratio needs at least one valid theme.")
            if not 1 <= b.weight <= 100:
                raise ValidationError("Each ratio's share must be between 1% and 100%.")
        total = sum(b.weight for b in self.ratios)
        if total != 100:
            raise ValidationError(f"The ratios must add up to 100% (they add up to {total}%).")


def _coerce(key: str, value: Any) -> Any:
    """Convert JSON values to the field's type, rejecting anything else."""
    str_lists = {
        "themes",
        "exclude_themes",
        "openings",
        "my_origins",
        "my_sets",
        "my_kinds",
        "my_phases",
        "my_time_classes",
    }
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
                or isinstance(weight, bool)
            ):
                raise ValidationError("each ratio needs a list of themes and a whole-number weight")
            buckets.append(RatioBucket(tuple(themes), weight))
        return tuple(buckets)
    raise ValidationError(f"unknown filter field: {key}")  # pragma: no cover


SAVED_FILTERS_VERSION = 3


def upgrade_saved(data: Any, version: int) -> Any:
    """Filters saved by an older version, brought to this version's defaults once (v0.2 planning).

    v0.1 stored the quality thresholds as null and Exclude solved as false, because it didn't have
    them; v0.2 turns them on by default. After this upgrade, whatever you set is kept."""
    if not isinstance(data, dict) or version >= SAVED_FILTERS_VERSION:
        return data
    out = dict(data)
    if version < 2:
        if out.get("min_popularity") is None:
            out["min_popularity"] = DEFAULT_MIN_POPULARITY
        if out.get("min_plays") is None:
            out["min_plays"] = DEFAULT_MIN_PLAYS
        out["exclude_solved_here"] = True
    if version < 3:
        out["exclude_played_on_lichess"] = True  # v0.3 planning: on by default
    return out
