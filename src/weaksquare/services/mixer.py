"""The puzzle mixer: theme and opening catalogs, live match counts (FR-3.1–3.10)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from weaksquare.core.filters import FilterSpec
from weaksquare.core.themes import GROUP_ORDER, info


class PuzzleCounter(Protocol):
    def count(self, spec: FilterSpec) -> int: ...

    def theme_counts(self) -> dict[str, int]: ...

    def openings(self) -> list[tuple[str, str | None, int]]: ...


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
    def __init__(self, puzzles: PuzzleCounter) -> None:
        self._puzzles = puzzles

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
