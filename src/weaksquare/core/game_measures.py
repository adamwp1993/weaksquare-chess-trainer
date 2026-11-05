"""Whole-game measures (v0.11, FR-10.53) and the whole-game weaknesses they produce (FR-10.57). Pure:
built from the game digests (`core/digest.py`), no engine, no LLM.

**Sample-size guard** (v0.11 planning): every group (an opening family, an endgame type, the games you
held +2 in, …) needs at least `MIN_GAMES` games. Below that the measure is shown with
``enough = False`` (*not enough data yet*) and never becomes a weakness.

**Weaknesses** use the v0.10 shape (`core/coach.Weakness`): a count of occurrences, a rate per 10 games
over all the report's games, a severity (the average eval lost in the related moments, capped at
1000 cp; `DEFAULT_SEVERITY` when a game has no such moment) and the score, rate × severity. Statuses
come with checkpoints (v1.0).

Occurrences per kind (REQUIREMENTS FR-10.57, v0.11 planning):
- ``opening:<family>``: you leave the opening (ply 30) at −100 or worse, or make a mistake or blunder in
  the first 15 moves
- ``endgame:<type>``: a game of that endgame type with a mistake or blunder in the endgame
- ``phase:conversion``: a game where you held +2 or better and didn't win
- ``time:low_clock``: a mistake or blunder under 10% of your time, only when that error rate is above
  your rate the rest of the time
- ``habit:castledLate``: castling after move 12, or never, with the opponent's queen on the board, only
  when you score worse in those games than when you castle in time
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from weaksquare.core.coach import LOSS_CAP, Example, Weakness
from weaksquare.core.digest import (
    LATE_CASTLE_MOVE,
    OPENING_END_PLY,
    OPENING_ERROR_MOVES,
    Digest,
    Moment,
)

MIN_GAMES = 5
OPENING_BAD_CP = -100
DEFAULT_SEVERITY = 100
LOW_CLOCK_PCT = 10
MAX_GAME_WEAKNESSES = 10
PHASES = ("opening", "middlegame", "endgame")

ENDGAME_LABELS = {
    "pawn": "King and pawn endgames",
    "rook": "Rook endgames",
    "minor": "Minor-piece endgames",
    "queen": "Queen endgames",
    "mixed": "Mixed endgames",
}
ENDGAME_THEMES: dict[str, tuple[str, ...]] = {
    "pawn": ("pawnEndgame",),
    "rook": ("rookEndgame",),
    "minor": ("bishopEndgame", "knightEndgame"),
    "queen": ("queenEndgame",),
    "mixed": ("endgame",),
}
GAME_KINDS = ("opening", "endgame", "phase", "time", "habit")


@dataclass(frozen=True)
class OpeningRow:
    family: str
    games: int
    score: float  # % (a win 1, a draw ½)
    avg_eval_end: int | None  # your view at move 15
    errors_first15: int  # your mistakes and blunders in the first 15 moves, all games together
    enough: bool


@dataclass(frozen=True)
class EndgameRow:
    type: str
    label: str
    games: int
    wins: int
    draws: int
    losses: int
    errors: int  # your mistakes and blunders in the endgame
    enough: bool


@dataclass(frozen=True)
class RateRow:
    """Conversion (games you held +2 in, won) or saves (games you were held at −2 in, not lost)."""

    games: int
    hits: int
    rate: float | None  # %
    enough: bool


@dataclass(frozen=True)
class TimeRow:
    games: int  # games with clock data that reached your last 10%
    low_moves: int
    low_errors: int
    low_blunders: int
    low_error_rate: float | None  # mistakes and blunders per 100 moves
    other_moves: int
    other_errors: int
    other_blunders: int
    other_error_rate: float | None
    enough: bool


@dataclass(frozen=True)
class KingRow:
    games: int  # games that reached your move 12
    late: int
    late_score: float | None  # %
    on_time_score: float | None
    enough: bool


@dataclass(frozen=True)
class Measures:
    games: int
    openings: list[OpeningRow]
    errors_per10_by_phase: dict[str, float]
    conversion: RateRow
    saves: RateRow
    endgames: list[EndgameRow]
    time: TimeRow
    king: KingRow
    min_games: int = MIN_GAMES

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def _score(results: Iterable[str | None]) -> float | None:
    rs = [r for r in results if r]
    if not rs:
        return None
    return round(100 * (sum(r == "win" for r in rs) + 0.5 * sum(r == "draw" for r in rs)) / len(rs), 1)


def _rate10(count: int, games: int) -> float:
    return round(10 * count / games, 2) if games else 0.0


def _per100(count: int, moves: int) -> float | None:
    return round(100 * count / moves, 2) if moves else None


def build_measures(digests: Sequence[tuple[int, Digest]]) -> Measures:
    """FR-10.53 over the games of one report. ``digests`` is ``(game_id, digest)`` pairs."""
    ds = [d for _, d in digests]
    n = len(ds)
    by_family: dict[str, list[Digest]] = defaultdict(list)
    by_endgame: dict[str, list[Digest]] = defaultdict(list)
    for d in ds:
        by_family[d.family].append(d)
        if d.endgame:
            by_endgame[d.endgame].append(d)
    openings = []
    for fam, group in by_family.items():
        evals = [d.eval_opening_end for d in group if d.eval_opening_end is not None]
        openings.append(
            OpeningRow(
                family=fam,
                games=len(group),
                score=_score(d.result for d in group) or 0.0,
                avg_eval_end=round(sum(evals) / len(evals)) if evals else None,
                errors_first15=sum(d.opening_errors for d in group),
                enough=len(group) >= MIN_GAMES,
            )
        )
    openings.sort(key=lambda o: (-o.games, o.family))
    endgames = [
        EndgameRow(
            type=t,
            label=ENDGAME_LABELS[t],
            games=len(g),
            wins=sum(d.result == "win" for d in g),
            draws=sum(d.result == "draw" for d in g),
            losses=sum(d.result == "loss" for d in g),
            errors=sum(d.endgame_errors for d in g),
            enough=len(g) >= MIN_GAMES,
        )
        for t, g in sorted(by_endgame.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    ]
    plus = [d for d in ds if d.held_plus2]
    minus = [d for d in ds if d.held_minus2]
    won = sum(d.result == "win" for d in plus)
    saved = sum(d.result in ("win", "draw") for d in minus)
    clocked = [d for d in ds if d.time.clock_known and d.time.low_moves]
    lm = sum(d.time.low_moves for d in clocked)
    le = sum(d.time.low_errors for d in clocked)
    om = sum(d.time.other_moves for d in ds if d.time.clock_known)
    oe = sum(d.time.other_errors for d in ds if d.time.clock_known)
    reached = [d for d in ds if d.castled_late is not None]
    late = [d for d in reached if d.castled_late]
    on_time = [d for d in reached if not d.castled_late]
    return Measures(
        games=n,
        openings=openings,
        errors_per10_by_phase={p: _rate10(sum(d.errors_by_phase.get(p, 0) for d in ds), n) for p in PHASES},
        conversion=RateRow(len(plus), won, round(100 * won / len(plus), 1) if plus else None, len(plus) >= MIN_GAMES),
        saves=RateRow(
            len(minus), saved, round(100 * saved / len(minus), 1) if minus else None, len(minus) >= MIN_GAMES
        ),
        endgames=endgames,
        time=TimeRow(
            games=len(clocked),
            low_moves=lm,
            low_errors=le,
            low_blunders=sum(d.time.low_blunders for d in clocked),
            low_error_rate=_per100(le, lm),
            other_moves=om,
            other_errors=oe,
            other_blunders=sum(d.time.other_blunders for d in ds if d.time.clock_known),
            other_error_rate=_per100(oe, om),
            enough=len(clocked) >= MIN_GAMES,
        ),
        king=KingRow(
            games=len(reached),
            late=len(late),
            late_score=_score(d.result for d in late),
            on_time_score=_score(d.result for d in on_time),
            enough=len(reached) >= MIN_GAMES and len(late) >= 1,
        ),
    )


@dataclass
class _Acc:
    losses: list[int] = field(default_factory=list)
    examples: list[Example] = field(default_factory=list)
    reasons: Counter[str] = field(default_factory=Counter)

    def add(self, game_id: int, moments: Sequence[Moment], fallback_ply: int) -> None:
        """One occurrence: its severity is the worst related moment (or the default), and it links to
        that moment (or to `fallback_ply`, 0-based)."""
        worst = max(moments, key=lambda m: m.swing, default=None)
        loss = min(LOSS_CAP, worst.swing) if worst else DEFAULT_SEVERITY
        self.losses.append(loss)
        self.examples.append(Example(game_id, (worst.ply - 1) if worst else max(0, fallback_ply), loss))
        for m in moments:
            if m.reason:
                self.reasons[m.reason] += 1


def _weakness(key: str, label: str, acc: _Acc, games: int, drill: tuple[str, ...]) -> Weakness:
    kind, name = key.split(":", 1)
    per10 = _rate10(len(acc.losses), games)
    severity = round(sum(acc.losses) / len(acc.losses)) if acc.losses else 0
    return Weakness(
        key=key,
        kind=kind,
        name=name,
        label=label,
        count=len(acc.losses),
        per10=per10,
        severity=severity,
        score=round(per10 * severity / 100, 3),
        themes=drill,
        mode=None,
        reasons=dict(acc.reasons),
        examples=tuple(sorted(acc.examples, key=lambda e: -e.cp_loss)[:5]),
    )


def _my_twelfth_ply(color: str) -> int:
    return 2 * (LATE_CASTLE_MOVE - 1) + (0 if color == "white" else 1)


def game_weaknesses(digests: Sequence[tuple[int, Digest]], measures: Measures) -> list[Weakness]:
    """FR-10.57: the measurable whole-game weaknesses, best first, at most `MAX_GAME_WEAKNESSES`. A group
    without enough games makes none."""
    n = measures.games
    out: list[Weakness] = []
    families = {o.family: o for o in measures.openings}
    endgames = {e.type: e for e in measures.endgames}
    open_acc: dict[str, _Acc] = defaultdict(_Acc)
    end_acc: dict[str, _Acc] = defaultdict(_Acc)
    conv, time_acc, king = _Acc(), _Acc(), _Acc()
    for gid, d in digests:
        early = [
            m for m in d.moments if m.ply <= 2 * OPENING_ERROR_MOVES and m.classification in ("mistake", "blunder")
        ]
        bad_out = d.eval_opening_end is not None and d.eval_opening_end <= OPENING_BAD_CP
        if families[d.family].enough and (early or bad_out or d.opening_errors):
            open_acc[d.family].add(gid, early, OPENING_END_PLY - 1)
        if d.endgame and endgames[d.endgame].enough and d.endgame_errors:
            end_acc[d.endgame].add(gid, [m for m in d.moments if m.phase == "endgame"], d.plies - 1)
        if measures.conversion.enough and d.held_plus2 and d.result != "win":
            conv.add(gid, list(d.moments), d.plies - 1)
        if d.time.clock_known and d.time.low_errors:
            low = [m for m in d.moments if m.clock_pct is not None and m.clock_pct < LOW_CLOCK_PCT]
            for _ in range(d.time.low_errors):
                time_acc.add(gid, low[:1], d.plies - 1)
        if d.castled_late:
            king.add(gid, [], _my_twelfth_ply(d.color))
    for fam, acc in open_acc.items():
        out.append(_weakness(f"opening:{fam}", f"Opening: {fam}", acc, n, ()))
    for eg, acc in end_acc.items():
        out.append(_weakness(f"endgame:{eg}", ENDGAME_LABELS[eg], acc, n, ENDGAME_THEMES[eg]))
    if conv.losses:
        out.append(_weakness("phase:conversion", "Winning positions not won (+2 or better)", conv, n, ("crushing",)))
    t = measures.time
    worse = t.low_error_rate is not None and (t.other_error_rate is None or t.low_error_rate > t.other_error_rate)
    if t.enough and worse and time_acc.losses:
        out.append(_weakness("time:low_clock", "Mistakes under 10% of your clock", time_acc, n, ()))
    k = measures.king
    late_worse = k.late_score is not None and (k.on_time_score is None or k.late_score < k.on_time_score)
    if k.enough and late_worse and king.losses:
        out.append(_weakness("habit:castledLate", f"Castled after move {LATE_CASTLE_MOVE} or never", king, n, ()))
    out.sort(key=lambda w: (-w.score, -w.count, w.key))
    return out[:MAX_GAME_WEAKNESSES]
