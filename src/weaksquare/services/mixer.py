"""The puzzle mixer: theme catalog, live match count, remembered filters (FR-3.1–3.5)."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import Any, Protocol

from weaksquare.core.errors import ValidationError
from weaksquare.core.filters import FilterSpec
from weaksquare.core.themes import GROUP_ORDER, info

LAST_FILTERS_KEY = "mixer.filters"
UI_SETTING_KEYS = (LAST_FILTERS_KEY,)


class PuzzleCounter(Protocol):
    def count(self, spec: FilterSpec) -> int: ...

    def theme_counts(self) -> dict[str, int]: ...


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

    def ui_settings(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        stored = self._settings.get(LAST_FILTERS_KEY)
        if stored is not None:
            # Stored by an older or newer version and no longer valid: fall back to the defaults.
            with contextlib.suppress(ValidationError):
                out[LAST_FILTERS_KEY] = FilterSpec.from_json(stored).to_json()
        return out

    def set_ui_setting(self, key: str, value: Any) -> None:
        if key == LAST_FILTERS_KEY:
            self._settings.set(key, FilterSpec.from_json(value).to_json())
        else:
            raise ValidationError(f"unknown setting: {key[:40]}")
