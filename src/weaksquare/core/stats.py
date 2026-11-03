"""The basic Stats page (FR-9.1, FR-9.2): accuracy per theme, per length, per rating band and (v0.5) per mode, and the
"first move right, line wrong" rate. Pure: takes attempt rows, returns grouped tallies.

"First move right, line wrong" is measured among the attempts where your first move was right: the
share where the rest of the line then went wrong. That isolates calculation from spotting the idea.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

BAND = 200
LENGTH_LABELS = {1: "1 move", 2: "2 moves", 3: "3 moves", 4: "4+ moves"}
# Training modes in the order the Modes control shows them (v0.5). An unknown mode keeps its key.
MODE_LABELS = {"standard": "Standard", "commit_line": "Commit the line", "spaced_repetition": "Spaced repetition"}


@dataclass(frozen=True)
class AttemptRow:
    win: bool
    first_move_correct: bool
    line_correct: bool
    puzzle_rating: int | None  # the rating when you played it (None for old attempts it can't recover)
    themes: tuple[str, ...] | None  # None: the puzzle is no longer in the database (FR-2.4)
    length: int | None
    mode: str = "standard"


@dataclass(frozen=True)
class Tally:
    key: str
    label: str
    attempts: int
    solved: int
    first_right: int  # attempts where the first move was right
    first_right_line_wrong: int  # …and the line then went wrong

    @property
    def accuracy(self) -> float | None:
        return self.solved / self.attempts if self.attempts else None

    @property
    def line_wrong_rate(self) -> float | None:
        return self.first_right_line_wrong / self.first_right if self.first_right else None


@dataclass(frozen=True)
class Report:
    overall: Tally
    by_theme: list[Tally]  # most-played first
    by_length: list[Tally]  # 1, 2, 3, 4+
    by_rating: list[Tally]  # lowest band first; "unknown" last
    missing: int  # attempts on puzzles no longer in the database (counted overall, by rating and by mode only)
    by_mode: list[Tally]  # in MODE_LABELS order, only modes you've played


class _Acc:
    def __init__(self) -> None:
        self.attempts = self.solved = self.first_right = self.frlw = 0

    def add(self, r: AttemptRow) -> None:
        self.attempts += 1
        self.solved += r.win
        if r.first_move_correct:
            self.first_right += 1
            self.frlw += not r.line_correct

    def tally(self, key: str, label: str) -> Tally:
        return Tally(key, label, self.attempts, self.solved, self.first_right, self.frlw)


def band(rating: int) -> int:
    return rating // BAND * BAND


def band_label(start: int) -> str:
    return f"{start}–{start + BAND - 1}"


def length_key(length: int) -> int:
    return min(length, 4)


def build_report(rows: Iterable[AttemptRow], theme_name: Callable[[str], str]) -> Report:
    overall = _Acc()
    themes: dict[str, _Acc] = {}
    lengths: dict[int, _Acc] = {}
    ratings: dict[int | None, _Acc] = {}
    modes: dict[str, _Acc] = {}
    missing = 0
    for r in rows:
        overall.add(r)
        modes.setdefault(r.mode, _Acc()).add(r)
        ratings.setdefault(None if r.puzzle_rating is None else band(r.puzzle_rating), _Acc()).add(r)
        if r.themes is None:
            missing += 1
            continue
        for t in dict.fromkeys(r.themes):
            themes.setdefault(t, _Acc()).add(r)
        if r.length is not None:
            lengths.setdefault(length_key(r.length), _Acc()).add(r)

    by_theme = sorted((a.tally(k, theme_name(k)) for k, a in themes.items()), key=lambda t: (-t.attempts, t.label))
    by_length = [lengths[k].tally(str(k), LENGTH_LABELS[k]) for k in sorted(lengths)]
    known = sorted(k for k in ratings if k is not None)
    by_rating = [ratings[k].tally(str(k), band_label(k)) for k in known]
    if None in ratings:
        by_rating.append(ratings[None].tally("unknown", "Unknown"))
    known_modes = [m for m in MODE_LABELS if m in modes] + sorted(m for m in modes if m not in MODE_LABELS)
    by_mode = [modes[m].tally(m, MODE_LABELS.get(m, m)) for m in known_modes]
    return Report(overall.tally("all", "All puzzles"), by_theme, by_length, by_rating, missing, by_mode)
