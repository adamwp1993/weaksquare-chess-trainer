"""The Coach's free report (v0.10, REQUIREMENTS §10.3–10.5): pure aggregation, no I/O, no LLM.

Inputs are the graded errors of one subject's own moves (the `game_errors` view), the games they come
from, the latest mistake reason per error, and the puzzle history (local attempts per theme plus the
Lichess dashboard). Outputs are JSON-ready dataclasses.

- **Weaknesses** are Missed themes, Allowed themes and habits (FR-10.16, 10.27). Each has a count, a
  rate **per 10 games** (never per game, FR-10.38), a severity (average eval lost, capped at 1000 cp)
  and a score, rate × severity, which ranks them (FR-10.19, 10.29).
- Only the motif-like themes count as weaknesses: phases, goals and lengths describe a tactic, they
  aren't one.
- Errors before move 7 (ply 12) are skipped (FR-10.10, v0.10 planning).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from weaksquare.core import themes
from weaksquare.core.habits import HABIT_DRILLS, HABITS

OPENING_PLIES = 12
LOSS_CAP = 1000
WEAKNESS_GROUPS = ("Motifs", "Advanced", "Mates", "Mate patterns", "Special moves")
MAX_EXAMPLES = 5
MIN_PUZZLE_ATTEMPTS = 10  # a puzzle theme needs this many attempts to count as a weakness
TOP_WEAKNESSES = 10


@dataclass(frozen=True)
class ErrorRow:
    game_id: int
    ply: int
    classification: str  # inaccuracy / mistake / blunder
    kind: str | None  # missed / allowed / other / None (inaccuracies)
    phase: str
    cp_loss: int
    themes: tuple[str, ...]
    habits: tuple[str, ...]
    low_clock: bool | None


@dataclass(frozen=True)
class GameInfo:
    game_id: int
    played_at: str | None
    time_class: str | None
    result: str | None  # win / loss / draw / None, from the subject's side


@dataclass(frozen=True)
class PuzzleTheme:
    """One theme in the puzzle history: local first tries plus the Lichess dashboard (FR-10.15)."""

    theme: str
    attempts: int
    first_try_wins: int
    lichess_nb: int = 0
    lichess_first_wins: int = 0
    lichess_performance: int | None = None

    @property
    def total(self) -> int:
        return self.attempts + self.lichess_nb

    @property
    def accuracy(self) -> float | None:
        n = self.total
        return (self.first_try_wins + self.lichess_first_wins) / n if n else None


@dataclass(frozen=True)
class Example:
    game_id: int
    ply: int
    cp_loss: int


@dataclass(frozen=True)
class Weakness:
    key: str  # "missed:fork", "allowed:fork", "habit:hungPiece", "puzzle:pin"
    kind: str  # missed / allowed / habit / puzzle
    name: str  # theme or habit key
    label: str
    count: int
    per10: float  # occurrences per 10 games (games source); 0 for puzzle-only weaknesses
    severity: int  # average eval lost, cp
    score: float
    themes: tuple[str, ...]  # the puzzle themes that train it
    mode: str | None  # a drill mode that suits it (habits), else None
    reasons: dict[str, int]  # latest mistake reason → count (FR-10.21)
    multi_move: int = 0  # Missed only: how many of its lines are longer than one move (FR-10.29)
    examples: tuple[Example, ...] = ()
    puzzle_accuracy: float | None = None


@dataclass(frozen=True)
class GapRow:
    """FR-10.18: a theme you solve as a puzzle but still miss or allow in games."""

    theme: str
    label: str
    puzzle_accuracy: float | None
    puzzle_attempts: int
    missed_per10: float
    allowed_per10: float


@dataclass(frozen=True)
class Report:
    source: str  # puzzles / games / both
    games: int
    first_played: str | None
    last_played: str | None
    per10: dict[str, float]  # blunders / mistakes / inaccuracies per 10 games
    results: dict[str, int]
    missed: list[Weakness]
    allowed: list[Weakness]
    habits: list[Weakness]
    puzzles: list[Weakness]
    gap: list[GapRow]
    reasons: dict[str, int]  # the reason mix over every tagged error (FR-10.36)
    low_clock_errors: int
    weaknesses: list[Weakness] = field(default_factory=list)  # all of them, best first (top 10)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def _is_weakness_theme(theme: str) -> bool:
    return themes.is_known(theme) and themes.info(theme).group in WEAKNESS_GROUPS


def _avg(values: Sequence[int]) -> int:
    return round(sum(min(v, LOSS_CAP) for v in values) / len(values)) if values else 0


def _rate(count: int, games: int) -> float:
    return round(10 * count / games, 2) if games else 0.0


@dataclass
class _Acc:
    losses: list[int] = field(default_factory=list)
    examples: list[Example] = field(default_factory=list)
    reasons: Counter[str] = field(default_factory=Counter)
    multi: int = 0

    def add(self, e: ErrorRow, reason: str | None, multi: bool = False) -> None:
        self.losses.append(e.cp_loss)
        self.examples.append(Example(e.game_id, e.ply, e.cp_loss))
        if reason:
            self.reasons[reason] += 1
        self.multi += int(multi)


def _weakness(kind: str, name: str, acc: _Acc, games: int, puzzle_acc: float | None) -> Weakness:
    per10 = _rate(len(acc.losses), games)
    severity = _avg(acc.losses)
    if kind == "habit":
        drill_themes, mode = HABIT_DRILLS[name]
        label = HABIT_LABELS[name]
    else:
        drill_themes, mode = (name,), ("danger_spotting" if kind == "allowed" else None)
        label = f"{'Missed' if kind == 'missed' else 'Allowed'}: {themes.display_name(name)}"
    examples = sorted(acc.examples, key=lambda x: -x.cp_loss)[:MAX_EXAMPLES]
    return Weakness(
        key=f"{kind}:{name}", kind=kind, name=name, label=label, count=len(acc.losses), per10=per10,
        severity=severity, score=round(per10 * severity / 100, 3), themes=drill_themes, mode=mode,
        reasons=dict(acc.reasons), multi_move=acc.multi, examples=tuple(examples), puzzle_accuracy=puzzle_acc,
    )  # fmt: skip


HABIT_LABELS = {
    "hungPiece": "Hung a piece",
    "missedFreeCapture": "Missed a free capture",
    "ignoredThreat": "Ignored a threat",
    "movedDefender": "Moved a defender away",
}


def _ranked(items: Iterable[Weakness]) -> list[Weakness]:
    return sorted(items, key=lambda w: (-w.score, -w.count, w.key))


def build_report(
    source: str,
    games: Sequence[GameInfo],
    errors: Sequence[ErrorRow],
    reasons: Mapping[tuple[int, int], str],
    puzzle_themes: Sequence[PuzzleTheme] = (),
) -> Report:
    """The free report for one subject (FR-10.16–10.19). ``source`` is puzzles / games / both."""
    use_games = source in ("games", "both")
    use_puzzles = source in ("puzzles", "both")
    n = len(games) if use_games else 0
    game_ids = {g.game_id for g in games}
    errs = [e for e in errors if e.game_id in game_ids and e.ply >= OPENING_PLIES] if use_games else []
    accuracy = {p.theme: p.accuracy for p in puzzle_themes}

    missed: dict[str, _Acc] = defaultdict(_Acc)
    allowed: dict[str, _Acc] = defaultdict(_Acc)
    habits: dict[str, _Acc] = defaultdict(_Acc)
    reason_mix: Counter[str] = Counter()
    for e in errs:
        reason = reasons.get((e.game_id, e.ply))
        if reason:
            reason_mix[reason] += 1
        if e.classification in ("mistake", "blunder") and e.kind in ("missed", "allowed"):
            bucket = missed if e.kind == "missed" else allowed
            multi = e.kind == "missed" and any(t in ("long", "veryLong", "short") for t in e.themes)
            for t in dict.fromkeys(e.themes):
                if _is_weakness_theme(t):
                    bucket[t].add(e, reason, multi)
        for h in e.habits:
            if h in HABITS:
                habits[h].add(e, reason)

    per10 = {
        label: _rate(sum(1 for e in errs if e.classification == c), n)
        for c, label in (("blunder", "blunders"), ("mistake", "mistakes"), ("inaccuracy", "inaccuracies"))
    }
    results = Counter(g.result for g in games if g.result) if use_games else Counter()
    played = sorted(g.played_at for g in games if g.played_at) if use_games else []

    w_missed = _ranked(_weakness("missed", t, a, n, accuracy.get(t)) for t, a in missed.items())
    w_allowed = _ranked(_weakness("allowed", t, a, n, accuracy.get(t)) for t, a in allowed.items())
    w_habits = _ranked(_weakness("habit", h, a, n, None) for h, a in habits.items())

    w_puzzles: list[Weakness] = []
    if use_puzzles:
        for p in puzzle_themes:
            acc = p.accuracy
            if acc is None or p.total < MIN_PUZZLE_ATTEMPTS or not _is_weakness_theme(p.theme):
                continue
            miss_rate = 1 - acc
            w_puzzles.append(
                Weakness(
                    key=f"puzzle:{p.theme}",
                    kind="puzzle",
                    name=p.theme,
                    label=f"Puzzles: {themes.display_name(p.theme)}",
                    count=p.total - round(acc * p.total),
                    per10=0.0,
                    severity=0,
                    score=round(miss_rate * min(p.total, 50) / 10, 3),
                    themes=(p.theme,),
                    mode=None,
                    reasons={},
                    puzzle_accuracy=round(acc, 3),
                )
            )
        w_puzzles = _ranked(w_puzzles)

    gap: list[GapRow] = []
    if source == "both":
        by_theme = {p.theme: p for p in puzzle_themes}
        for t in sorted({w.name for w in w_missed + w_allowed}):
            hist = by_theme.get(t)
            gap.append(
                GapRow(
                    t, themes.display_name(t),
                    round(hist.accuracy, 3) if hist and hist.accuracy is not None else None,
                    hist.total if hist else 0, next((w.per10 for w in w_missed if w.name == t), 0.0),
                    next((w.per10 for w in w_allowed if w.name == t), 0.0),
                )
            )  # fmt: skip
        gap.sort(key=lambda g: (-(g.missed_per10 + g.allowed_per10) * (g.puzzle_accuracy or 0), g.theme))

    every = _ranked(w_missed + w_allowed + w_habits + (w_puzzles if source == "puzzles" else []))
    return Report(
        source=source,
        games=n,
        first_played=played[0] if played else None,
        last_played=played[-1] if played else None,
        per10=per10,
        results=dict(results),
        missed=w_missed,
        allowed=w_allowed,
        habits=w_habits,
        puzzles=w_puzzles,
        gap=gap,
        reasons=dict(reason_mix),
        low_clock_errors=sum(1 for e in errs if e.low_clock),
        weaknesses=every[:TOP_WEAKNESSES],
    )


def trend(current: Report, previous: Report | Mapping[str, Any] | None) -> dict[str, float]:
    """FR-10.20: each current weakness's rate change against the previous report (per 10 games)."""
    if previous is None:
        return {}
    prev = previous.to_json() if isinstance(previous, Report) else previous
    old: dict[str, float] = {}
    for group in ("missed", "allowed", "habits"):
        for w in prev.get(group) or []:
            if isinstance(w, dict) and isinstance(w.get("key"), str):
                old[w["key"]] = float(w.get("per10") or 0.0)
    out: dict[str, float] = {}
    for w in current.missed + current.allowed + current.habits:
        out[w.key] = round(w.per10 - old.get(w.key, 0.0), 2)
    return out
