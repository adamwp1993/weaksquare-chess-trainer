"""UI settings that persist through the bridge into user.db `settings` (ARCHITECTURE §3 decision 14:
never browser storage). Only the keys listed here can be written, each through its validator.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from weaksquare.core.errors import ValidationError
from weaksquare.core.filters import SAVED_FILTERS_VERSION, FilterSpec, upgrade_saved

LAST_FILTERS_KEY = "mixer.filters"
FILTERS_VERSION_KEY = "mixer.filters_version"  # which version's defaults the saved filters have
COORDINATES_KEY = "ui.coordinates"


class SettingsStore(Protocol):
    def get(self, key: str) -> Any | None: ...

    def set(self, key: str, value: Any) -> None: ...


@dataclass(frozen=True)
class UiSettings:
    last_filters: FilterSpec | None
    coordinates: bool  # file and rank letters around the board (default on)


def _bool(name: str) -> Callable[[Any], Any]:
    def check(value: Any) -> Any:
        if not isinstance(value, bool):
            raise ValidationError(f"{name} must be true or false")
        return value

    return check


def _filters(value: Any) -> Any:
    return FilterSpec.from_json(value).to_json()


VALIDATORS: dict[str, Callable[[Any], Any]] = {
    LAST_FILTERS_KEY: _filters,
    COORDINATES_KEY: _bool("coordinates"),
}


class UiSettingsService:
    def __init__(self, store: SettingsStore) -> None:
        self._store = store

    def _last_filters(self) -> FilterSpec | None:
        stored = self._store.get(LAST_FILTERS_KEY)
        version = self._store.get(FILTERS_VERSION_KEY) or 1
        if stored is not None and version < SAVED_FILTERS_VERSION:
            stored = upgrade_saved(stored, version)  # v0.1 filters get the v0.2 defaults once
            self._store.set(LAST_FILTERS_KEY, stored)
            self._store.set(FILTERS_VERSION_KEY, SAVED_FILTERS_VERSION)
        if stored is None:
            return None
        # Stored by an older or newer version and no longer valid: fall back to the defaults.
        with contextlib.suppress(ValidationError):
            return FilterSpec.from_json(stored)
        return None

    def get(self) -> UiSettings:
        coordinates = self._store.get(COORDINATES_KEY)
        return UiSettings(
            last_filters=self._last_filters(),
            coordinates=coordinates if isinstance(coordinates, bool) else True,
        )

    def set(self, key: str, value: Any) -> None:
        validate = VALIDATORS.get(key)
        if validate is None:
            raise ValidationError(f"unknown setting: {key[:40]}")
        self._store.set(key, validate(value))
        if key == LAST_FILTERS_KEY:
            self._store.set(FILTERS_VERSION_KEY, SAVED_FILTERS_VERSION)
