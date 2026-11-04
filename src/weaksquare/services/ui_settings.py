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
from weaksquare.core.ladder import DEFAULT_THRESHOLD, DEFAULT_WINDOW, validate_threshold, validate_window
from weaksquare.core.reasons import DEFAULT_RUSHED_S, validate_rushed_s
from weaksquare.core.srs import DEFAULT_INTERVALS, validate_intervals

LAST_FILTERS_KEY = "mixer.filters"
FILTERS_VERSION_KEY = "mixer.filters_version"  # which version's defaults the saved filters have
COORDINATES_KEY = "ui.coordinates"
COLOR_SCHEME_KEY = "ui.color_scheme"  # FR-1.12
SOUNDS_KEY = "ui.sounds"  # FR-1.13
AUTO_CHECK_KEY = "puzzle_db.auto_check"  # FR-2.5: the daily update check (default on)
# v0.5
MODE_KEY = "trainer.mode"  # the Modes control (§6): the last mode used
SHOW_LENGTH_KEY = "commit.show_length"  # Commit the line's Show move count (FR-4.2), default off
LADDER_THRESHOLD_KEY = "ladder.threshold"  # FR-4.5, percent
LADDER_WINDOW_KEY = "ladder.window"  # FR-4.5, attempts
SRS_INTERVALS_KEY = "srs.intervals"  # FR-4.6, days per box
FILTERS_COLLAPSED_KEY = "ui.filters_collapsed"  # FR-1.14
TIME_OFFSET_KEY = "debug.time_offset_days"  # FR-4.6 fast-forward, --dev runs only (written by the bridge)
# v0.6
REASONS_ASK_KEY = "reasons.ask"  # FR-5.8: when to ask why you missed: always / game_review (v0.8) / off
RUSHED_S_KEY = "reasons.rushed_s"  # FR-5.9: a deciding move faster than this suggests Rushed
REASONS_ASK = ("always", "game_review", "off")
TRAINING_MODES = ("standard", "commit_line", "name_idea", "danger_spotting", "spaced_repetition")

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
    auto_check: bool
    mode: str = "standard"
    show_length: bool = False
    ladder_threshold: int = DEFAULT_THRESHOLD
    ladder_window: int = DEFAULT_WINDOW
    srs_intervals: tuple[int, ...] = DEFAULT_INTERVALS
    filters_collapsed: bool = False
    reasons_ask: str = "always"
    rushed_s: int = DEFAULT_RUSHED_S


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


def _mode(value: Any) -> Any:
    if value not in TRAINING_MODES:
        raise ValidationError("unknown training mode")
    return value


def _reasons_ask(value: Any) -> Any:
    if value not in REASONS_ASK:
        raise ValidationError("reasons.ask must be 'always', 'game_review' or 'off'")
    return value


def _filters(value: Any) -> Any:
    return FilterSpec.from_json(value).to_json()


VALIDATORS: dict[str, Callable[[Any], Any]] = {
    LAST_FILTERS_KEY: _filters,
    COORDINATES_KEY: _bool("coordinates"),
    COLOR_SCHEME_KEY: _color_scheme,
    SOUNDS_KEY: _sounds,
    AUTO_CHECK_KEY: _bool("auto_check"),
    MODE_KEY: _mode,
    SHOW_LENGTH_KEY: _bool("show_length"),
    LADDER_THRESHOLD_KEY: validate_threshold,
    LADDER_WINDOW_KEY: validate_window,
    SRS_INTERVALS_KEY: lambda v: list(validate_intervals(v)),
    FILTERS_COLLAPSED_KEY: _bool("filters_collapsed"),
    REASONS_ASK_KEY: _reasons_ask,
    RUSHED_S_KEY: validate_rushed_s,
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
            auto_check=self._store.get(AUTO_CHECK_KEY) is not False,
            mode=self._valid(MODE_KEY, "standard"),
            show_length=self._valid(SHOW_LENGTH_KEY, False),
            ladder_threshold=self.ladder_threshold(),
            ladder_window=self.ladder_window(),
            srs_intervals=self.srs_intervals(),
            filters_collapsed=self._valid(FILTERS_COLLAPSED_KEY, False),
            reasons_ask=self.reasons_ask(),
            rushed_s=self.rushed_s(),
        )

    def _valid(self, key: str, default: Any) -> Any:
        """A stored value, or the default if it's missing or was written by another version."""
        stored = self._store.get(key)
        if stored is None:
            return default
        try:
            return VALIDATORS[key](stored)
        except ValidationError:
            return default

    # FR-4.6 fast-forward (--dev runs only; the bridge checks that before calling these)
    def time_offset_days(self) -> int:
        stored = self._store.get(TIME_OFFSET_KEY)
        return stored if isinstance(stored, int) and not isinstance(stored, bool) and stored >= 0 else 0

    def set_time_offset_days(self, days: int) -> None:
        self._store.set(TIME_OFFSET_KEY, days)

    # TrainingPrefs (services/session.py)
    def srs_intervals(self) -> tuple[int, ...]:
        return tuple(self._valid(SRS_INTERVALS_KEY, list(DEFAULT_INTERVALS)))

    def ladder_threshold(self) -> int:
        return int(self._valid(LADDER_THRESHOLD_KEY, DEFAULT_THRESHOLD))

    def ladder_window(self) -> int:
        return int(self._valid(LADDER_WINDOW_KEY, DEFAULT_WINDOW))

    def reasons_ask(self) -> str:
        return str(self._valid(REASONS_ASK_KEY, "always"))

    def rushed_s(self) -> int:
        return int(self._valid(RUSHED_S_KEY, DEFAULT_RUSHED_S))

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
