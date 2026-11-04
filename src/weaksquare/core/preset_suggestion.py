"""A puzzle preset recommended by an LLM (FR-11.18 in v0.9; FR-10.23's validation, reused by the Coach in v0.10).

Pure. The LLM's suggestion is **untrusted**: theme keys must be known motif or mate themes, and the rating
range must be valid. Invalid fields are dropped. With no valid theme left there's no preset at all. The
result is only ever *offered*: the UI applies it when you click Train these (never silently, CLAUDE.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from weaksquare.core.errors import ValidationError
from weaksquare.core.filters import FilterSpec
from weaksquare.core.themes import IDEA_GROUPS, display_name, info, keys_in_groups

MAX_PRESET_THEMES = 3  # Adam, v0.9 planning
PRESET_GROUPS = (*IDEA_GROUPS, "Mates")


def preset_themes() -> tuple[str, ...]:
    """The theme keys a suggestion may use, in catalog order (they're listed in the prompt)."""
    return keys_in_groups(PRESET_GROUPS)


@dataclass(frozen=True)
class SuggestedPreset:
    themes: tuple[str, ...]
    rating_min: int | None
    rating_max: int | None

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(display_name(t) for t in self.themes)

    def to_json(self) -> dict[str, Any]:
        return {"themes": list(self.themes), "rating_min": self.rating_min, "rating_max": self.rating_max}

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> SuggestedPreset:
        return cls(tuple(d["themes"]), d.get("rating_min"), d.get("rating_max"))


def _rating(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def validate_preset(raw: Any) -> tuple[SuggestedPreset | None, int]:
    """(the preset or None, how many fields were dropped)."""
    if not isinstance(raw, dict):
        return None, 0
    dropped = 0
    themes: list[str] = []
    raw_themes = raw.get("themes")
    for t in raw_themes if isinstance(raw_themes, list) else []:
        if (
            isinstance(t, str)
            and info(t).group in PRESET_GROUPS
            and t not in themes
            and len(themes) < MAX_PRESET_THEMES
        ):
            themes.append(t)
        else:
            dropped += 1
    if not themes:
        return None, dropped
    lo, hi = _rating(raw.get("rating_min")), _rating(raw.get("rating_max"))
    dropped += (raw.get("rating_min") is not None and lo is None) + (raw.get("rating_max") is not None and hi is None)
    try:
        FilterSpec(themes=tuple(themes), rating_min=lo, rating_max=hi).validate()
    except ValidationError:
        dropped += (lo is not None) + (hi is not None)
        lo = hi = None  # a bad range: keep the themes, use the full range
    return SuggestedPreset(tuple(themes), lo, hi), dropped
