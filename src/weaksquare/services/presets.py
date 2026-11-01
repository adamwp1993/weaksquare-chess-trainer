"""Presets: save, load, rename and delete named filter sets (FR-3.13).

A preset is validated through `FilterSpec.from_json` when it's saved and again when it's loaded.
One stored by another version that this version can't use is listed with the reason, and never
changed or deleted unless you ask.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Any, Protocol

from weaksquare.core.clock import Clock
from weaksquare.core.errors import ConflictError, NotFoundError, ValidationError
from weaksquare.core.filters import FilterSpec

MAX_NAME = 60
MAX_PRESETS = 500


class PresetStore(Protocol):
    def list(self) -> list[Any]: ...

    def find(self, name: str) -> Any | None: ...

    def upsert(self, name: str, filters: dict[str, Any], now: str) -> None: ...

    def rename(self, old: str, new: str, now: str) -> bool: ...

    def delete(self, name: str) -> bool: ...


@dataclass(frozen=True)
class Preset:
    name: str
    spec: FilterSpec | None  # None when this version can't use it
    error: str | None
    updated_at: str


def clean_name(name: Any) -> str:
    """Trimmed, 1–60 characters, no control characters."""
    if not isinstance(name, str):
        raise ValidationError("A preset name must be text.")
    name = " ".join(name.split())
    if not name:
        raise ValidationError("Give the preset a name.")
    if len(name) > MAX_NAME:
        raise ValidationError(f"Preset names can be at most {MAX_NAME} characters.")
    if any(unicodedata.category(c).startswith("C") for c in name):
        raise ValidationError("A preset name can't contain control characters.")
    return name


class PresetService:
    def __init__(self, store: PresetStore, clock: Clock) -> None:
        self._store = store
        self._clock = clock

    def _now(self) -> str:
        return self._clock.now().isoformat(timespec="seconds")

    @staticmethod
    def _load(row: Any) -> Preset:
        try:
            spec = FilterSpec.from_json(row.filters)
        except ValidationError as e:
            return Preset(row.name, None, f"This preset can't be used in this version: {e}", row.updated_at)
        return Preset(row.name, spec, None, row.updated_at)

    def list(self) -> list[Preset]:
        return [self._load(r) for r in self._store.list()]

    def save(self, name: Any, spec: FilterSpec, overwrite: bool = False) -> Preset:
        name = clean_name(name)
        existing = self._store.find(name)
        if existing is not None and not overwrite:
            raise ConflictError(f'A preset called "{existing.name}" already exists. Replace it, or pick another name.')
        if existing is None and len(self._store.list()) >= MAX_PRESETS:
            raise ValidationError(f"You can keep up to {MAX_PRESETS} presets. Delete one first.")
        self._store.upsert(name, spec.to_json(), self._now())
        return Preset(name, spec, None, self._now())

    def rename(self, old: Any, new: Any) -> None:
        old, new = clean_name(old), clean_name(new)
        clash = self._store.find(new)
        if clash is not None and clash.name.casefold() != old.casefold():
            raise ConflictError(f'A preset called "{clash.name}" already exists.')
        if not self._store.rename(old, new, self._now()):
            raise NotFoundError(f'There\'s no preset called "{old}".')

    def delete(self, name: Any) -> None:
        name = clean_name(name)
        if not self._store.delete(name):
            raise NotFoundError(f'There\'s no preset called "{name}".')
