"""UI settings that persist through the bridge into user.db `settings` (ARCHITECTURE §3 decision 14:
never browser storage). Only the keys listed here can be written, each through its validator.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from weaksquare.core.errors import ValidationError
from weaksquare.core.filters import SAVED_FILTERS_VERSION, FilterSpec, upgrade_saved

LAST_FILTERS_KEY = "mixer.filters"
FILTERS_VERSION_KEY = "mixer.filters_version"  # which version's defaults the saved filters have
COORDINATES_KEY = "ui.coordinates"
COLOR_SCHEME_KEY = "ui.color_scheme"  # FR-1.12
SOUNDS_KEY = "ui.sounds"  # FR-1.13

ColorScheme = Literal["light", "dark", "auto"]  # "auto" is Match system
COLOR_SCHEMES = ("light", "dark", "auto")
SOUND_SETS = ("sfx", "piano", "nes", "futuristic")  # Lichess's Enigmahack sets, AGPLv3+ (see CREDITS.md)


@dataclass(frozen=True)
class SoundSettings:
    on: bool = True
    volume: int = 70  # percent
    set: str = "sfx"


class SettingsStore(Protocol):
    def get(self, key: str) -> Any | None: ...

    def set(self, key: str, value: Any) -> None: ...


@dataclass(frozen=True)
class UiSettings:
    last_filters: FilterSpec | None
    coordinates: bool  # file and rank letters around the board (default on)
    color_scheme: ColorScheme  # default light
    sounds: SoundSettings


def _bool(name: str) -> Callable[[Any], Any]:
    def check(value: Any) -> Any:
        if not isinstance(value, bool):
            raise ValidationError(f"{name} must be true or false")
        return value

    return check


def _color_scheme(value: Any) -> Any:
    if value not in COLOR_SCHEMES:
        raise ValidationError("color scheme must be 'light', 'dark' or 'auto'")
    return value


def _sounds(value: Any) -> Any:
    if not isinstance(value, dict) or set(value) != {"on", "volume", "set"}:
        raise ValidationError("sounds needs on, volume and set")
    on, volume, sound_set = value["on"], value["volume"], value["set"]
    if not isinstance(on, bool):
        raise ValidationError("sounds.on must be true or false")
    if not isinstance(volume, int) or isinstance(volume, bool) or not 0 <= volume <= 100:
        raise ValidationError("sounds.volume must be a whole number from 0 to 100")
    if sound_set not in SOUND_SETS:
        raise ValidationError(f"sounds.set must be one of {', '.join(SOUND_SETS)}")
    return {"on": on, "volume": volume, "set": sound_set}


def _filters(value: Any) -> Any:
    return FilterSpec.from_json(value).to_json()


VALIDATORS: dict[str, Callable[[Any], Any]] = {
    LAST_FILTERS_KEY: _filters,
    COORDINATES_KEY: _bool("coordinates"),
    COLOR_SCHEME_KEY: _color_scheme,
    SOUNDS_KEY: _sounds,
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
        scheme = self._store.get(COLOR_SCHEME_KEY)
        return UiSettings(
            last_filters=self._last_filters(),
            coordinates=coordinates if isinstance(coordinates, bool) else True,
            color_scheme=scheme if scheme in COLOR_SCHEMES else "light",
            sounds=self._sounds(),
        )

    def _sounds(self) -> SoundSettings:
        stored = self._store.get(SOUNDS_KEY)
        try:
            return SoundSettings(**_sounds(stored)) if stored is not None else SoundSettings()
        except ValidationError:  # written by another version: fall back to the defaults
            return SoundSettings()

    def set(self, key: str, value: Any) -> None:
        validate = VALIDATORS.get(key)
        if validate is None:
            raise ValidationError(f"unknown setting: {key[:40]}")
        self._store.set(key, validate(value))
        if key == LAST_FILTERS_KEY:
            self._store.set(FILTERS_VERSION_KEY, SAVED_FILTERS_VERSION)
