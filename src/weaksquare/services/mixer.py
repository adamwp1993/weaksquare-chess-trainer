"""The puzzle mixer: theme catalog, live match count, remembered filters (FR-3.1–3.5)."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import Any, Protocol

from weaksquare.core.errors import ValidationError
from weaksquare.core.filters import SAVED_FILTERS_VERSION, FilterSpec, upgrade_saved
from weaksquare.core.themes import GROUP_ORDER, info

LAST_FILTERS_KEY = "mixer.filters"
FILTERS_VERSION_KEY = "mixer.filters_version"  # which version's defaults the saved filters have
UI_SETTING_KEYS = (LAST_FILTERS_KEY,)


class PuzzleCounter(Protocol):
    def count(self, spec: FilterSpec) -> int: ...

    def theme_counts(self) -> dict[str, int]: ...

    def openings(self) -> list[tuple[str, str | None, int]]: ...


class SettingsStore(Protocol):
    def get(self, key: str) -> Any | None: ...

    def set(self, key: str, value: Any) -> None: ...


@dataclass(frozen=True)
class ThemeOption:
    key: str
    name: str
    count: int


@dataclass(frozen=True)
class ThemeGroup:
    name: str
    themes: list[ThemeOption]


@dataclass(frozen=True)
class OpeningOption:
    tag: str
    name: str
    count: int


@dataclass(frozen=True)
class OpeningFamily:
    family: OpeningOption
    variations: list[OpeningOption]


def opening_name(tag: str, family: str | None = None) -> str:
    """Lichess tags use underscores; a variation repeats its family's tag as a prefix, so under
    "Sicilian Defense" the variation reads "Najdorf Variation"."""
    if family and tag.startswith(family + "_"):
        tag = tag[len(family) + 1 :]
    return tag.replace("_", " ")


class MixerService:
    def __init__(self, puzzles: PuzzleCounter, settings: SettingsStore) -> None:
        self._puzzles = puzzles
        self._settings = settings

    def theme_catalog(self) -> list[ThemeGroup]:
        """Themes present in the imported database, grouped and ordered for the picker."""
        counts = self._puzzles.theme_counts()
        groups: dict[str, list[tuple[int, ThemeOption]]] = {g: [] for g in GROUP_ORDER}
        for key, n in counts.items():
            ti = info(key)
            groups[ti.group].append((ti.order, ThemeOption(key, ti.name, n)))
        return [
            ThemeGroup(g, [opt for _, opt in sorted(items, key=lambda x: (x[0], x[1].name))])
            for g, items in groups.items()
            if items
        ]

    def count(self, spec: FilterSpec) -> int:
        return self._puzzles.count(spec)

    def bucket_counts(self, spec: FilterSpec) -> list[int]:
        """The live count of each ratio group (FR-3.10): these filters with that group's themes."""
        return [self._puzzles.count(spec.bucket(i)) for i in range(len(spec.ratios))]

    def opening_catalog(self) -> list[OpeningFamily]:
        """Opening families A–Z, each with its variations (FR-3.7)."""
        families: dict[str, OpeningOption] = {}
        variations: dict[str, list[OpeningOption]] = {}
        for tag, family, n in self._puzzles.openings():
            if family is None:
                families[tag] = OpeningOption(tag, opening_name(tag), n)
            else:
                variations.setdefault(family, []).append(OpeningOption(tag, opening_name(tag, family), n))
        return [
            OpeningFamily(families[f], sorted(variations.get(f, []), key=lambda o: o.name.casefold()))
            for f in sorted(families, key=lambda f: families[f].name.casefold())
        ]

    def ui_settings(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        stored = self._settings.get(LAST_FILTERS_KEY)
        version = self._settings.get(FILTERS_VERSION_KEY) or 1
        if stored is not None and version < SAVED_FILTERS_VERSION:
            stored = upgrade_saved(stored, version)
            self._settings.set(LAST_FILTERS_KEY, stored)
            self._settings.set(FILTERS_VERSION_KEY, SAVED_FILTERS_VERSION)
        if stored is not None:
            # Stored by an older or newer version and no longer valid: fall back to the defaults.
            with contextlib.suppress(ValidationError):
                out[LAST_FILTERS_KEY] = FilterSpec.from_json(stored).to_json()
        return out

    def set_ui_setting(self, key: str, value: Any) -> None:
        if key == LAST_FILTERS_KEY:
            self._settings.set(key, FilterSpec.from_json(value).to_json())
            self._settings.set(FILTERS_VERSION_KEY, SAVED_FILTERS_VERSION)
        else:
            raise ValidationError(f"unknown setting: {key[:40]}")
