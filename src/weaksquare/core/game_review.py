"""Game Review grading (v0.8, REQUIREMENTS §11.2–11.3). Pure: the analysis service asks the engine for the
top lines of every position, and this module turns them into per-move rows, symbols, key moments and
the per-side summary.

**Scores** are `Score(cp, mate)` from one side's view, positive = good for that side. In an `eval_after`,
`mate == 0` means the mover has just delivered checkmate (the mover can't be mated by their own move).
For cp loss, scores are clamped to ±1000 and a mate counts as ±1000 (plan v0.8).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal

import chess

from weaksquare.core.engine import EngineLine, score_for

Classification = Literal["best", "good", "inaccuracy", "mistake", "blunder"]
Kind = Literal["missed", "allowed", "other"]
Phase = Literal["opening", "middlegame", "endgame"]
CLASSIFICATIONS: tuple[str, ...] = ("best", "good", "inaccuracy", "mistake", "blunder")
ERRORS: tuple[str, ...] = ("inaccuracy", "mistake", "blunder")
SYMBOLS = {"inaccuracy": "?!", "mistake": "?", "blunder": "??"}
CLAMP = 1000
EDGE = 150  # Missed / Allowed: "a winning edge" (plan v0.8, refined in v0.10)
MAX_SAVED_PLAYER_MOVES = 3  # plan v0.8: a saved line is cut to at most 3 of your moves


@dataclass(frozen=True)
class Score:
    cp: int | None = None
    mate: int | None = None

    def value(self) -> int:
        """Centipawns clamped to ±CLAMP; a mate (or a delivered mate, `mate == 0`) is ±CLAMP."""
        if self.mate is not None:
            return -CLAMP if self.mate < 0 else CLAMP
        return max(-CLAMP, min(CLAMP, self.cp or 0))

    def negate(self) -> Score:
        if self.mate is not None:
            return Score(None, -self.mate)
        return Score(-(self.cp or 0), None)

    def to_json(self) -> dict[str, int]:
        return {"mate": self.mate} if self.mate is not None else {"cp": self.cp or 0}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Score:
        if isinstance(data.get("mate"), int):
            return cls(None, int(data["mate"]))
        return cls(int(data.get("cp") or 0), None)


@dataclass(frozen=True)
class Thresholds:
    """FR-11.9, shared with the Coach: configurable."""

    inaccuracy: int = 50
    mistake: int = 100
    blunder: int = 200
    decided: int = 500

    def validate(self) -> None:
        if not (0 < self.inaccuracy < self.mistake < self.blunder <= 2000) or not (100 <= self.decided <= CLAMP):
            raise ValueError("thresholds must rise: inaccuracy < mistake < blunder, and 'decided' within 100–1000")


DEFAULT_THRESHOLDS = Thresholds()


@dataclass(frozen=True)
class MoveRow:
    """One graded move: a `game_analysis` row. `lines` are the top lines from `fen_before`."""

    ply: int  # 0-based index into the game's moves
    fen_before: str
    move_uci: str
    move_san: str
    mover: str
    eval_before: Score
    eval_after: Score
    best_move: str | None
    lines: tuple[EngineLine, ...]
    refutation: tuple[str, ...]  # FR-11.14: the best line after the move
    cp_loss: int
    classification: str
    kind: str | None
    phase: str
    low_clock: bool | None
    clock_s: float | None


def _is_decided(before: int, after: int, th: Thresholds) -> bool:
    """FR-11.9: positions already decided aren't penalized: still winning after the move, or lost
    before it."""
    return (before >= th.decided and after >= th.decided) or (before <= -th.decided and after <= -th.decided)


def _mate_swing(before: Score, after: Score, th: Thresholds) -> bool:
    """Walking into a forced mate from a position that wasn't lost, or giving up your own forced mate
    for a position that isn't winning."""
    allowed_mate = after.mate is not None and after.mate < 0 and not (before.mate is not None and before.mate < 0)
    lost_mate = before.mate is not None and before.mate > 0 and after.value() < th.decided
    return (allowed_mate and before.value() > -th.decided) or lost_mate


def grade(before: Score, after: Score, played_best: bool, th: Thresholds) -> tuple[int, str]:
    """(cp loss, classification) for one move, both scores from the mover's view (FR-11.9)."""
    b, a = before.value(), after.value()
    if played_best:
        return 0, "best"
    if _mate_swing(before, after, th):
        return max(0, b - a), "blunder"
    if _is_decided(b, a, th):
        return 0, "good"
    loss = max(0, b - a)
    if loss >= th.blunder:
        return loss, "blunder"
    if loss >= th.mistake:
        return loss, "mistake"
    if loss >= th.inaccuracy:
        return loss, "inaccuracy"
    return loss, "good"


def missed_or_allowed(before: Score, after: Score, classification: str) -> str | None:
    """FR-10.11 for mistakes and blunders (plan v0.8's simple rule): **Missed** when your best move kept a
    winning edge; otherwise **Allowed** when the opponent's best reply is winning for them; else Other."""
    if classification not in ("mistake", "blunder"):
        return None
    if before.value() >= EDGE:
        return "missed"
    if after.value() <= -EDGE or (after.mate is not None and after.mate < 0):
        return "allowed"
    return "other"


def _pieces(board: chess.Board) -> int:
    """Non-pawn, non-king pieces on the board (both sides; 14 at the start)."""
    return sum(
        len(board.pieces(t, c)) for t in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN) for c in chess.COLORS
    )


def phase_of(board: chess.Board, ply: int, division: dict[str, int] | None) -> str:
    """Lichess's `division` (the plies where the middlegame and endgame start) when the export has it;
    otherwise a rule (plan v0.8): the opening is moves 1–10 while at least 13 pieces remain; the endgame
    has 6 or fewer pieces; everything else is the middlegame."""
    if division:
        end, middle = division.get("end"), division.get("middle")
        if end is not None and ply + 1 >= end:
            return "endgame"
        if middle is not None and ply + 1 < middle:
            return "opening"
        if middle is not None or end is not None:
            return "middlegame"
    n = _pieces(board)
    if n <= 6:
        return "endgame"
    if ply // 2 + 1 <= 10 and n >= 13:
        return "opening"
    return "middlegame"


def _position_score(lines: Sequence[EngineLine] | None, board: chess.Board, view: str) -> Score:
    """The score of `board` from `view`'s side. With no lines, the game is over: a checkmate is a mate
    delivered by the side that just moved; anything else (stalemate, draw) is 0."""
    if lines:
        cp, mate = score_for(lines[0], "white" if view == "white" else "black")
        return Score(cp, mate)
    if board.is_checkmate():
        mated = "white" if board.turn == chess.WHITE else "black"
        return Score(None, 0) if mated != view else Score(None, -1)
    return Score(0, None)


def grade_game(
    start_fen: str,
    moves: Sequence[str],
    analyses: Sequence[Sequence[EngineLine] | None],
    *,
    clocks: Sequence[float | None] = (),
    low_clock_of: Any = None,
    division: dict[str, int] | None = None,
    th: Thresholds = DEFAULT_THRESHOLDS,
) -> list[MoveRow]:
    """Every move graded. `analyses[i]` holds the top lines of the position before move i, and
    `analyses[len(moves)]` those of the final position (None when the game is over there).
    `low_clock_of(seconds)` decides whether a clock reading is low (None without clock data)."""
    if len(analyses) != len(moves) + 1:
        raise ValueError("need one analysis per position, the final one included")
    board = chess.Board(start_fen)
    rows: list[MoveRow] = []
    for i, uci in enumerate(moves):
        move = chess.Move.from_uci(uci)
        mover = "white" if board.turn == chess.WHITE else "black"
        lines = tuple(analyses[i] or ())
        fen = board.fen()
        san = board.san(move)
        phase = phase_of(board, i, division)
        before = _position_score(lines, board, mover)
        best = lines[0].pv[0] if lines and lines[0].pv else None
        board.push(move)
        after = _position_score(analyses[i + 1], board, mover)
        nxt = analyses[i + 1]
        refutation = tuple(nxt[0].pv) if nxt and nxt[0].pv else ()
        loss, cls = grade(before, after, best == uci, th)
        clock = clocks[i] if i < len(clocks) else None
        rows.append(
            MoveRow(
                ply=i,
                fen_before=fen,
                move_uci=uci,
                move_san=san,
                mover=mover,
                eval_before=before,
                eval_after=after,
                best_move=best,
                lines=lines,
                refutation=refutation,
                cp_loss=loss,
                classification=cls,
                kind=missed_or_allowed(before, after, cls),
                phase=phase,
                low_clock=low_clock_of(clock) if low_clock_of is not None else None,
                clock_s=clock,
            )
        )
    return rows


def regrade(row: MoveRow, th: Thresholds) -> MoveRow:
    """The same move graded with other thresholds (v0.8-B1): only the stored evals are needed."""
    loss, cls = grade(row.eval_before, row.eval_after, row.best_move == row.move_uci, th)
    return replace(row, cp_loss=loss, classification=cls, kind=missed_or_allowed(row.eval_before, row.eval_after, cls))


def saved_line(pv: Sequence[str], max_player_moves: int = MAX_SAVED_PLAYER_MOVES) -> tuple[str, ...]:
    """The solution of a saved puzzle: the engine's best line from your position, cut to whole moves of
    yours (it ends on your move) and at most `max_player_moves` of them."""
    line = tuple(pv[: 2 * max_player_moves - 1])
    if len(line) % 2 == 0:
        line = line[:-1]
    return line


def white_eval(row: MoveRow) -> int:
    """The eval after the move from White's side, clamped: one point of the eval graph (FR-11.12)."""
    v = row.eval_after.value()
    return v if row.mover == "white" else -v


def key_moments(rows: Sequence[MoveRow], color: str, n: int = 5) -> list[MoveRow]:
    """FR-11.13: the side's `n` largest cp losses that are at least inaccuracies, in game order."""
    errs = [r for r in rows if r.mover == color and r.classification in ERRORS]
    top = sorted(errs, key=lambda r: (-r.cp_loss, r.ply))[: max(0, n)]
    return sorted(top, key=lambda r: r.ply)


@dataclass(frozen=True)
class PhaseSummary:
    moves: int
    inaccuracies: int
    mistakes: int
    blunders: int
    avg_cp_loss: float | None


@dataclass(frozen=True)
class SideSummary:
    """FR-11.11 for one side."""

    color: str
    moves: int
    inaccuracies: int
    mistakes: int
    blunders: int
    avg_cp_loss: float | None
    platform_accuracy: float | None
    by_phase: dict[str, PhaseSummary]
    low_clock_errors: int | None  # mistakes and blunders on a low clock; None without clock data


def _phase_summary(rows: list[MoveRow]) -> PhaseSummary:
    return PhaseSummary(
        moves=len(rows),
        inaccuracies=sum(r.classification == "inaccuracy" for r in rows),
        mistakes=sum(r.classification == "mistake" for r in rows),
        blunders=sum(r.classification == "blunder" for r in rows),
        avg_cp_loss=round(sum(r.cp_loss for r in rows) / len(rows), 1) if rows else None,
    )


def side_summary(rows: Sequence[MoveRow], color: str, platform_accuracy: float | None = None) -> SideSummary:
    mine = [r for r in rows if r.mover == color]
    total = _phase_summary(mine)
    clocked = [r for r in mine if r.low_clock is not None]
    return SideSummary(
        color=color,
        moves=total.moves,
        inaccuracies=total.inaccuracies,
        mistakes=total.mistakes,
        blunders=total.blunders,
        avg_cp_loss=total.avg_cp_loss,
        platform_accuracy=platform_accuracy,
        by_phase={p: _phase_summary([r for r in mine if r.phase == p]) for p in ("opening", "middlegame", "endgame")},
        low_clock_errors=(
            sum(1 for r in clocked if r.low_clock and r.classification in ("mistake", "blunder")) if clocked else None
        ),
    )
