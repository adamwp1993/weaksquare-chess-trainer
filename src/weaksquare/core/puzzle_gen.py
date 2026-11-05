"""Puzzles from your games: the quality check and the solution line (FR-10.41).

The rules are ported from lichess-puzzler's generator (`generator/generator.py` and `util.py`,
AGPL-3.0, commit 8e24b6d5e2b9; Adam, v0.10 planning). Its code can't be reused: it needs MongoDB, a
tablebase server and 30-second searches. What changes here:

- The engine is a callback (the background engine at about 1 s per position, not 30 s), so this
  module stays pure.
- The first position's lines come from the stored game analysis (MultiPV 3), so the first check needs
  no engine call.
- Lichess skips mate-in-one and two-move puzzles from lower-rated games ("tiers"); these are your own
  games, so they're kept. One-move advantage puzzles are still dropped.
- FR-10.41's "already decided" rule (beyond ±500 cp before the opponent's move) is added, and lines are
  capped at ``MAX_SOLVER_MOVES`` of yours.
- There is no tablebase and no "seen position" store.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import chess

from weaksquare.core.engine import EngineLine

GEN_VERSION = 1  # bump when the rules change, so stored checks are redone
MATE_SOON = 15  # a mate within 15 moves is a mate puzzle
ADVANTAGE_CP = 200
CLEAR_CP = 400
PREV_WINNING_CP = 300
JUMP = 0.6  # the win-chance jump the opponent's move must give you
MATE_IN_ONE_NON_MATE = 0.6
MAX_SOLVER_MOVES = 8
DEFAULT_MARGIN = 0.7  # Lichess's only-move margin in win chances
MARGIN_RANGE = (0.3, 1.5)
MATE_SCORE = 100_000


# ---- scores, from the solver's view ----------------------------------------------------------------


@dataclass(frozen=True)
class PovScore:
    cp: int | None = None
    mate: int | None = None  # > 0: the solver mates; < 0: the solver is mated

    def key(self) -> int:
        """An order like python-chess's: mates for you first (sooner is better), mates against you last."""
        if self.mate is not None:
            return MATE_SCORE - self.mate if self.mate > 0 else -MATE_SCORE - self.mate
        return self.cp or 0

    def win_chances(self) -> float:
        """lichess-puzzler's `win_chances`: from -1 to 1."""
        if self.mate is not None:
            return 1.0 if self.mate > 0 else -1.0
        return 2 / (1 + math.exp(-0.00368208 * (self.cp or 0))) - 1


def pov(line: EngineLine, solver: chess.Color) -> PovScore:
    """An engine line's score (White-relative, as the engine gives it) from the solver's view."""
    sign = 1 if solver == chess.WHITE else -1
    if line.mate is not None:
        return PovScore(mate=line.mate * sign)
    return PovScore(cp=(line.cp or 0) * sign)


def cp_value(score: PovScore) -> int:
    return score.key() if score.mate is None else (MATE_SCORE if score.mate > 0 else -MATE_SCORE)


# ---- material ---------------------------------------------------------------------------------------

_VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9}


def material_diff(board: chess.Board, side: chess.Color) -> int:
    def count(c: chess.Color) -> int:
        return sum(len(board.pieces(p, c)) * v for p, v in _VALUES.items())

    return count(side) - count(not side)


def count_mates(board: chess.Board) -> int:
    n = 0
    for move in board.legal_moves:
        board.push(move)
        n += board.is_checkmate()
        board.pop()
    return n


# ---- the check ----------------------------------------------------------------------------------------

Analyse = Callable[[chess.Board, int], Sequence[EngineLine]]
"""The engine: the top ``multipv`` lines (White-relative scores) for a position."""


@dataclass(frozen=True)
class GenSettings:
    margin: float = DEFAULT_MARGIN
    decided_cp: int = 500


@dataclass(frozen=True)
class Verdict:
    passed: bool
    reason: str  # "ok", or why it was rejected
    line: tuple[str, ...] = ()  # UCI from the puzzle position, starting and ending on the solver's move
    cp: int | None = None  # the solver's eval at the end of the line (MATE_SCORE for a mate)


def reject(reason: str) -> Verdict:
    return Verdict(False, reason)


@dataclass(frozen=True)
class _Pair:
    best_move: str
    best: PovScore
    second: PovScore | None


def _pair(lines: Sequence[EngineLine], solver: chess.Color) -> _Pair | None:
    usable = [ln for ln in lines if ln.pv]
    if not usable:
        return None
    return _Pair(usable[0].pv[0], pov(usable[0], solver), pov(usable[1], solver) if len(usable) > 1 else None)


class _Generator:
    def __init__(self, analyse: Analyse, settings: GenSettings) -> None:
        self._analyse = analyse
        self._s = settings

    def valid_mate_in_one(self, board: chess.Board, pair: _Pair, solver: chess.Color) -> bool:
        if pair.best.mate != 1:
            return False
        if pair.second is None or pair.second.win_chances() <= MATE_IN_ONE_NON_MATE:
            return True
        if pair.second.mate == 1:
            # More than one mate in one: the best move that doesn't mate must be bad enough.
            lines = self._analyse(board, count_mates(board.copy(stack=False)) + 1)
            scores = [pov(ln, solver) for ln in lines]
            last = scores[-1] if scores else None
            return not (last is not None and last.mate != 1 and last.win_chances() > MATE_IN_ONE_NON_MATE)
        return False

    def valid_attack(self, board: chess.Board, pair: _Pair, solver: chess.Color) -> bool:
        return (
            pair.second is None
            or self.valid_mate_in_one(board, pair, solver)
            or pair.best.win_chances() > pair.second.win_chances() + self._s.margin
        )

    def next_pair(self, board: chess.Board, solver: chess.Color, given: Sequence[EngineLine] | None) -> _Pair | None:
        pair = _pair(given if given is not None else self._analyse(board, 2), solver)
        if pair is None or chess.Move.from_uci(pair.best_move) not in board.legal_moves:
            return None
        if board.turn == solver and not self.valid_attack(board, pair, solver):
            return None
        return pair

    def mate_line(self, board: chess.Board, solver: chess.Color, first: Sequence[EngineLine]) -> list[str] | None:
        moves: list[str] = []
        given: Sequence[EngineLine] | None = first
        while not board.is_game_over():
            if len(moves) > 2 * MAX_SOLVER_MOVES:
                return None
            if board.turn == solver:
                pair = self.next_pair(board, solver, given)
                if pair is None or pair.best.mate is None or not 0 < pair.best.mate <= MATE_SOON:
                    return None
                move = pair.best_move
            else:
                lines = self._analyse(board, 1)
                if not lines or not lines[0].pv:
                    return None
                move = lines[0].pv[0]
            given = None
            mv = chess.Move.from_uci(move)
            if mv not in board.legal_moves:
                return None
            board.push(mv)
            moves.append(move)
        return moves if board.is_checkmate() and board.turn != solver else None

    def advantage_line(
        self, board: chess.Board, solver: chess.Color, first: Sequence[EngineLine]
    ) -> list[_Pair] | None:
        pairs: list[_Pair] = []
        given: Sequence[EngineLine] | None = first
        while True:
            if board.is_repetition(2):
                return None
            if len(pairs) >= 2 * MAX_SOLVER_MOVES - 1:
                return pairs
            if board.is_game_over():
                return pairs
            pair = self.next_pair(board, solver, given)
            given = None
            if pair is None:
                return pairs
            if pair.best.key() < ADVANTAGE_CP:
                return None
            board.push(chess.Move.from_uci(pair.best_move))
            pairs.append(pair)


def check_position(
    fen: str,
    first_lines: Sequence[EngineLine],
    prev: PovScore | None,
    analyse: Analyse,
    settings: GenSettings = GenSettings(),  # noqa: B008 - frozen
) -> Verdict:
    """Whether the position (solver to move) makes a clean puzzle, and its line.

    - ``first_lines``: the stored MultiPV lines for ``fen`` (White-relative), best first.
    - ``prev``: the solver's eval before the opponent's move that led here (None at the start of a game).
    """
    try:
        board = chess.Board(fen)
    except ValueError:
        return reject("bad_position")
    solver = board.turn
    first = _pair(first_lines, solver)
    if first is None:
        return reject("no_engine_line")
    score = first.best
    previous = prev if prev is not None else PovScore(cp=20)
    if board.legal_moves.count() < 2:
        return reject("forced")
    mate_soon = score.mate is not None and 0 < score.mate <= MATE_SOON
    if previous.mate is None and abs(previous.cp or 0) > settings.decided_cp:
        return reject("decided")
    if previous.mate is not None:
        return reject("decided")
    if previous.key() > PREV_WINNING_CP and not mate_soon:
        return reject("already_winning")
    if material_diff(board, solver) > 0:
        return reject("up_in_material")
    gen = _Generator(analyse, settings)
    if mate_soon:
        moves = gen.mate_line(board.copy(), solver, first_lines)
        if moves is None:
            return reject("no_forced_mate")
        return Verdict(True, "ok", tuple(moves), MATE_SCORE)
    if not (score.key() >= ADVANTAGE_CP and score.win_chances() > previous.win_chances() + JUMP):
        return reject("no_tactic")
    if score.key() < CLEAR_CP and material_diff(board, solver) > -1:
        return reject("not_clear")
    pairs = gen.advantage_line(board.copy(), solver, first_lines)
    if not pairs:
        return reject("not_only_move")
    while pairs and (len(pairs) % 2 == 0 or pairs[-1].second is None):
        pairs = pairs[:-1]
    if len(pairs) <= 1:
        return reject("one_move")
    return Verdict(True, "ok", tuple(p.best_move for p in pairs), cp_value(pairs[-1].best))


def validate_margin(value: object) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ValueError("The only-move margin must be a number.")
    lo, hi = MARGIN_RANGE
    if not lo <= float(value) <= hi:
        raise ValueError(f"The only-move margin must be {lo}–{hi}.")
    return round(float(value), 2)
