"""Standard mode (FR-4.1): you move, the opponent's reply plays automatically.

- A win is the whole line with no wrong move and no help (FR-5.1).
- A wrong move is a loss, decided at that moment (FR-5.3). The move is taken back and you can keep
  going to see the line through, with nothing more to lose: the attempt is recorded once.
- Any checkmating move is accepted where the solution mates (§4.2).
- Moving on before the attempt is decided counts as a loss.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import chess

from weaksquare.core.chess_rules import is_acceptable, parse_move, start_position
from weaksquare.core.modes.base import AttemptResult, Feedback
from weaksquare.core.puzzle import Puzzle


@dataclass
class StandardState:
    puzzle: Puzzle
    board: chess.Board
    next_index: int  # index into puzzle.moves of the next expected player move
    started_ms: int
    failed: bool = False
    first_move_correct: bool | None = None
    finished: bool = False
    attempt: AttemptResult | None = None
    played: list[str] = field(default_factory=list)


class StandardMode:
    name = "standard"

    def start(self, puzzle: Puzzle, now_ms: int) -> StandardState:
        board, _ = start_position(puzzle.fen, puzzle.moves)  # raises PuzzleDataError if the line is illegal
        return StandardState(puzzle=puzzle, board=board, next_index=1, started_ms=now_ms)

    def _decide(self, state: StandardState, win: bool, now_ms: int) -> AttemptResult:
        result = AttemptResult(
            win=win,
            first_move_correct=bool(state.first_move_correct),
            line_correct=win,
            help_used="none",
            time_ms=max(0, now_ms - state.started_ms),
        )
        state.attempt = result
        return result

    def on_move(self, state: StandardState, uci: str, now_ms: int) -> Feedback:
        if state.finished:
            return Feedback("illegal", None, True, None)
        move = parse_move(state.board, uci)
        if move is None:
            return Feedback("illegal", None, False, None)
        expected = chess.Move.from_uci(state.puzzle.moves[state.next_index])
        first_move = state.next_index == 1

        if not is_acceptable(state.board, move, expected):
            decided = None
            if first_move and state.first_move_correct is None:
                state.first_move_correct = False
            if not state.failed:
                state.failed = True
                decided = self._decide(state, win=False, now_ms=now_ms)
            return Feedback("wrong", None, False, decided)

        if first_move and state.first_move_correct is None:
            state.first_move_correct = True
        state.board.push(move)
        state.played.append(move.uci())
        state.next_index += 1

        if state.next_index >= len(state.puzzle.moves) or state.board.is_checkmate():
            state.finished = True
            decided = None if state.attempt else self._decide(state, win=not state.failed, now_ms=now_ms)
            return Feedback("solved", None, True, decided)

        reply = chess.Move.from_uci(state.puzzle.moves[state.next_index])
        state.board.push(reply)
        state.next_index += 1
        return Feedback("correct", reply.uci(), False, None)

    def give_up(self, state: StandardState, now_ms: int) -> AttemptResult | None:
        if state.attempt is not None:
            return None
        state.failed = True
        return self._decide(state, win=False, now_ms=now_ms)
