"""Standard mode (FR-4.1): you move, the opponent's reply plays automatically.

- A win is the whole line with no wrong move and no help (FR-5.1).
- A wrong move is a loss, decided at that moment (FR-5.3). The move is taken back and you can keep
  going to see the line through, with nothing more to lose: the attempt is recorded once.
- Any checkmating move is accepted where the solution mates (§4.2).
- Moving on before the attempt is decided counts as a loss.
- Help (§7.2): Hint shows the piece that moves next; Show answer gives the rest of the line and ends
  the puzzle. Mid-puzzle, Show answer unlocks only after Hint. Either one before the attempt is
  decided makes it a loss (FR-5.2), recorded with the help used; after that, help is free (FR-5.4).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import chess

from weaksquare.core.chess_rules import is_acceptable, parse_move, start_position
from weaksquare.core.errors import ConflictError, ValidationError
from weaksquare.core.modes.base import AttemptResult, Feedback, HelpKind, HelpResult, HelpUsed
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
    hinted: bool = False
    start_fen: str = ""  # after the opponent's first move: where you start solving


class StandardMode:
    name = "standard"

    def start(self, puzzle: Puzzle, now_ms: int) -> StandardState:
        board, _ = start_position(puzzle.fen, puzzle.moves)  # raises PuzzleDataError if the line is illegal
        return StandardState(puzzle=puzzle, board=board, next_index=1, started_ms=now_ms, start_fen=board.fen())

    def _decide(self, state: StandardState, win: bool, now_ms: int, help_used: HelpUsed = "none") -> AttemptResult:
        result = AttemptResult(
            win=win,
            first_move_correct=bool(state.first_move_correct),
            line_correct=win,
            help_used=help_used,
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

    def on_help(self, state: StandardState, kind: HelpKind, now_ms: int) -> HelpResult:
        if kind == "hint":
            if state.finished:
                raise ConflictError("The puzzle is over: there's nothing left to hint.")
            decided = None if state.attempt else self._decide(state, win=False, now_ms=now_ms, help_used="hint")
            state.failed = True
            state.hinted = True
            square = state.puzzle.moves[state.next_index][:2]
            return HelpResult("hint", square, None, (), decided)

        if kind != "answer":
            raise ValidationError("Help must be 'hint' or 'answer'.")
        if state.finished:  # free after the end (FR-5.4): replay the whole line from the start
            return HelpResult("answer", None, state.start_fen, tuple(state.puzzle.moves[1:]), None)
        if state.attempt is None and not state.hinted:
            raise ConflictError("Try a Hint first: Show answer unlocks after it.")
        decided = None if state.attempt else self._decide(state, win=False, now_ms=now_ms, help_used="answer")
        fen = state.board.fen()
        rest = tuple(state.puzzle.moves[state.next_index :])
        state.failed = True
        state.finished = True  # the answer ends the puzzle
        return HelpResult("answer", None, fen, rest, decided)

    def give_up(self, state: StandardState, now_ms: int) -> AttemptResult | None:
        if state.attempt is not None:
            return None
        state.failed = True
        return self._decide(state, win=False, now_ms=now_ms)
