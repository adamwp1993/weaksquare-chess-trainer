"""Danger spotting (FR-4.4): is the highlighted move safe?

- You see the **pre-blunder position** (the puzzle's raw FEN) from the side about to blunder, with a
  candidate move highlighted. About half the candidates are the real blunder (`moves[0]`), half a
  Stockfish-verified safe move.
- You call **Safe** or **Unsafe** (`on_call`):
  - right about a safe move → a win; wrong either way → a loss, and the puzzle ends
  - **Unsafe** on the real blunder → it's played and you play the **first move of the refutation**
    from the punishing side (`on_move`): the puzzle's `moves[1]`, or any mating move where it mates
    (§4.2). Right → a win; anything else → a loss. The puzzle ends either way (Adam, v0.6 planning).
- Help (§7.2): before the call there's no Hint (it would give the answer away) and Show answer is a
  loss that reveals the truth; while you refute, Hint and Show answer work as in Standard; after the
  end, help is free (FR-5.4).
- `first_move_correct` records whether the call was right, `line_correct` the win.

Safe candidates (`safe_candidates`): from Stockfish's top lines (MultiPV 5, from the blunderer's side),
any move that isn't the real blunder, doesn't allow a mate, and is at most `MAX_LOSS_CP` worse than
the best line. One is picked at random. When none qualifies the puzzle shows the blunder, and the
next one is owed a safe candidate (`wants_safe`), so the mix stays about 50/50.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Literal

import chess

from weaksquare.core.chess_rules import is_acceptable, parse_move, start_position
from weaksquare.core.errors import ConflictError, ValidationError
from weaksquare.core.modes.base import AttemptResult, Feedback, HelpKind, HelpResult, HelpUsed
from weaksquare.core.move_sounds import sound_for, sounds_for_line
from weaksquare.core.puzzle import Puzzle

MODE = "danger_spotting"
MULTIPV = 5
MAX_LOSS_CP = 50
_MATE = 100_000
Call = Literal["safe", "unsafe"]
Phase = Literal["call", "refute", "done"]


@dataclass(frozen=True)
class ScoredMove:
    """One of the engine's top lines, scored from the mover's (blunderer's) side."""

    move: str  # UCI
    cp: int | None
    mate: int | None  # > 0: the mover mates; < 0: the mover is mated


def _value(m: ScoredMove) -> int | None:
    if m.mate is not None:
        return _MATE - abs(m.mate) if m.mate > 0 else None  # a mate against the mover is never safe
    return m.cp


def safe_candidates(lines: list[ScoredMove], blunder: str, max_loss_cp: int = MAX_LOSS_CP) -> list[ScoredMove]:
    """The moves that count as safe: not the blunder, no mate against the mover, and at most
    `max_loss_cp` worse than the best line (which is the best of all lines, not necessarily the first)."""
    values = [(m, _value(m)) for m in lines]
    known = [v for _, v in values if v is not None]
    if not known:
        return []
    best = max(known)
    return [m for m, v in values if v is not None and m.move != blunder and best - v <= max_loss_cp]


def wants_safe(rng: random.Random, owed: bool) -> bool:
    """Whether this puzzle's candidate should be a safe move: owed after a puzzle that had none,
    otherwise a fair coin."""
    return owed or rng.random() < 0.5


def pick_safe(rng: random.Random, safe: list[ScoredMove]) -> ScoredMove | None:
    return rng.choice(safe) if safe else None


@dataclass(frozen=True)
class CallResult:
    call: Call
    correct: bool  # your call was right
    is_safe: bool  # the truth, revealed now
    refute: bool  # Unsafe on the real blunder: now play the refutation
    fen: str  # the position after the call (after the blunder when you refute)
    blunder_sound: object | None
    attempt: AttemptResult | None


@dataclass
class DangerState:
    puzzle: Puzzle
    board: chess.Board  # the position you're looking at (the raw FEN; after the blunder while refuting)
    candidate: str  # UCI
    is_safe: bool
    started_ms: int
    start_fen: str  # the raw FEN: evals are worded from the blunderer's side
    position_ms: int = 0
    phase: Phase = "call"
    call: Call | None = None
    finished: bool = False
    attempt: AttemptResult | None = None
    hinted: bool = False
    first_wrong: tuple[str, str] | None = None  # (FEN before, UCI): a wrong refutation move
    practice: bool = False
    decisive_ms: int | None = None
    safe_info: object | None = None  # the service's note on the safe move (engine scores), shown after the end


class DangerMode:
    name = MODE

    def start(self, puzzle: Puzzle, now_ms: int, candidate: str, is_safe: bool) -> DangerState:
        start_position(puzzle.fen, puzzle.moves)  # raises PuzzleDataError if the line is illegal
        board = chess.Board(puzzle.fen)
        move = parse_move(board, candidate)
        if move is None:
            raise ValidationError("The candidate move isn't legal here.")
        if is_safe == (candidate == puzzle.moves[0]):
            raise ValidationError("A safe candidate can't be the real blunder.")
        return DangerState(puzzle, board, candidate, is_safe, now_ms, board.fen(), position_ms=now_ms)

    def start_practice(self, puzzle: Puzzle, now_ms: int, candidate: str, is_safe: bool) -> DangerState:
        """Try again (FR-5.12): the same candidate; nothing can be decided or recorded."""
        state = self.start(puzzle, now_ms, candidate, is_safe)
        state.practice = True
        state.attempt = AttemptResult(False, False, False, "none", 0)
        return state

    def _decide(self, state: DangerState, win: bool, now_ms: int, help_used: HelpUsed = "none") -> AttemptResult:
        result = AttemptResult(
            win=win,
            first_move_correct=state.call is not None and (state.call == "safe") == state.is_safe,
            line_correct=win,
            help_used=help_used,
            time_ms=max(0, now_ms - state.started_ms),
        )
        state.attempt = result
        return result

    def on_call(self, state: DangerState, call: object, now_ms: int) -> CallResult:
        if call not in ("safe", "unsafe"):
            raise ValidationError("Call it 'safe' or 'unsafe'.")
        if state.phase != "call":
            raise ConflictError("You've already made your call for this puzzle.")
        state.call = call  # type: ignore[assignment]
        correct = (call == "safe") == state.is_safe
        think = max(0, now_ms - state.position_ms)
        if call == "unsafe" and not state.is_safe:
            blunder = chess.Move.from_uci(state.candidate)
            sound = sound_for(state.board, blunder)
            state.board.push(blunder)
            state.phase = "refute"
            state.position_ms = now_ms
            return CallResult("unsafe", True, False, True, state.board.fen(), sound, None)
        state.phase = "done"
        state.finished = True
        decided = None
        if state.attempt is None:
            state.decisive_ms = think
            decided = self._decide(state, win=correct, now_ms=now_ms)
        return CallResult(call, correct, state.is_safe, False, state.board.fen(), None, decided)  # type: ignore[arg-type]

    def on_move(self, state: DangerState, uci: str, now_ms: int) -> Feedback:
        if state.phase != "refute":
            if state.finished:
                return Feedback("illegal", None, True, None)
            raise ConflictError("Make your call first: Safe or Unsafe.")
        move = parse_move(state.board, uci)
        if move is None:
            return Feedback("illegal", None, False, None)
        expected = chess.Move.from_uci(state.puzzle.moves[1])
        sound = sound_for(state.board, move)
        ok = is_acceptable(state.board, move, expected)
        decided = None
        if state.attempt is None:
            if not ok:
                state.decisive_ms = max(0, now_ms - state.position_ms)
            decided = self._decide(state, win=ok, now_ms=now_ms)
        if ok:
            state.board.push(move)
        else:
            state.first_wrong = (state.board.fen(), move.uci())
        state.phase = "done"
        state.finished = True
        return Feedback("solved" if ok else "wrong", None, True, decided, sound)

    def _reveal(self, state: DangerState) -> tuple[str, tuple[str, ...]]:
        """The answer: the real blunder and its refutation line, or the safe move alone (the service
        adds Stockfish's line after it from the analysis it kept)."""
        if state.is_safe:
            return state.start_fen, (state.candidate,)
        return state.start_fen, tuple(state.puzzle.moves)

    def on_help(self, state: DangerState, kind: HelpKind, now_ms: int) -> HelpResult:
        if kind not in ("hint", "answer"):
            raise ValidationError("Help must be 'hint' or 'answer'.")
        if kind == "hint":
            if state.phase != "refute" or state.finished:
                raise ConflictError("Hint is only offered while you look for the refutation.")
            decided = None if state.attempt else self._decide(state, win=False, now_ms=now_ms, help_used="hint")
            state.hinted = True
            return HelpResult("hint", state.puzzle.moves[1][:2], None, (), decided)
        if not state.finished and state.phase == "refute" and state.attempt is None and not state.hinted:
            raise ConflictError("Try a Hint first: Show answer unlocks after it.")
        decided = None
        if state.attempt is None:
            decided = self._decide(state, win=False, now_ms=now_ms, help_used="answer")
        state.phase = "done"
        state.finished = True
        fen, line = self._reveal(state)
        return HelpResult(
            "answer", None, fen, line, decided, tuple(sounds_for_line(fen, line)), refute=state.first_wrong is not None
        )

    def give_up(self, state: DangerState, now_ms: int) -> AttemptResult | None:
        if state.attempt is not None:
            return None
        return self._decide(state, win=False, now_ms=now_ms)
