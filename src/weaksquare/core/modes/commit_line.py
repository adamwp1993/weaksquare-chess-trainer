"""Commit the line (FR-4.2): you enter the whole line, both sides, with nothing checked, then Submit.

- The front end only checks that each move is legal. Nothing is graded until Submit (`on_submit`);
  `on_move` is refused. The line is re-checked for legality here.
- Grading compares your line with the solution move by move, by position in the line:
  - every **player** move must match for a win (FR-5.1); missing ones are wrong, and moves after
    the end of the solution are ignored
  - where every earlier move matched exactly (so it's the real position), any mating move is
    accepted where the solution mates (§4.2), and the line ends there
  - the predicted opponent replies are scored separately (calculation accuracy) and don't affect the win
- The solution's length is hidden by default. With Show move count (`length_shown`) the line may not
  be longer than the solution, and the angle treats the length as known (§8.3).
- Help (§7.2) before Submit is a loss, as in Standard: Hint shows the piece that makes your first
  move, and Show answer (after Hint) ends the puzzle. After the end, help is free (FR-5.4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import chess

from weaksquare.core.chess_rules import is_acceptable, parse_move, start_position
from weaksquare.core.errors import ConflictError, ValidationError
from weaksquare.core.modes.base import AttemptResult, Feedback, HelpKind, HelpResult, HelpUsed
from weaksquare.core.move_sounds import sounds_for_line
from weaksquare.core.puzzle import Puzzle

MAX_PLIES = 60


@dataclass(frozen=True)
class PlyGrade:
    """One move of your submitted line, against the solution."""

    played: str | None  # your move (UCI); None if your line stopped before this point
    expected: str  # the solution's move here
    player: bool  # your move (True) or a predicted reply (False)
    correct: bool


@dataclass(frozen=True)
class CommitResult:
    grades: tuple[PlyGrade, ...]  # up to the end of the solution (or an accepted mate)
    extra: tuple[str, ...]  # your moves after the end: ignored
    replies_correct: int
    replies_total: int
    win: bool
    attempt: AttemptResult | None  # set when Submit decided the attempt
    line_sounds: tuple[Any, ...] = ()  # one per submitted move, for replaying your line


@dataclass
class CommitState:
    puzzle: Puzzle
    board: chess.Board  # where you start entering: after the opponent's first move
    started_ms: int
    start_fen: str
    length_shown: bool = False
    finished: bool = False
    attempt: AttemptResult | None = None
    hinted: bool = False
    submitted: CommitResult | None = None
    first_wrong: tuple[str, str] | None = None  # (FEN before, UCI), only in the real position
    practice: bool = False  # Try again (FR-5.12): never recorded
    played: list[str] = field(default_factory=list)


def max_plies(puzzle: Puzzle, length_shown: bool) -> int:
    """How long a submitted line may be: the solution's length with Show move count, otherwise the
    same fixed cap for every puzzle, so reaching it says nothing about the length (v0.5-B3)."""
    return len(puzzle.moves) - 1 if length_shown else MAX_PLIES


def grade(
    start: chess.Board, solution: list[str] | tuple[str, ...], line: list[chess.Move]
) -> tuple[list[PlyGrade], list[str], tuple[str, str] | None]:
    """Pure grading. Returns the grades, the ignored extra moves and the first wrong player move
    in the real position (for Stockfish's refutation), if there is one."""
    grades: list[PlyGrade] = []
    first_wrong: tuple[str, str] | None = None
    same = True  # every earlier move matched exactly: `board` is the real position
    board = start.copy(stack=False)
    end = len(solution)
    for i, sol in enumerate(solution):
        expected = chess.Move.from_uci(sol)
        mine = line[i] if i < len(line) else None
        is_player = i % 2 == 0
        if is_player:
            if mine is None:
                ok = False
            elif same:
                ok = is_acceptable(board, mine, expected)
            else:
                ok = mine == expected
            if not ok and same and mine is not None and first_wrong is None:
                first_wrong = (board.fen(), mine.uci())
        else:
            ok = mine == expected
        grades.append(PlyGrade(mine.uci() if mine else None, sol, is_player, ok))
        if same and mine is not None and ok and mine != expected:
            end = i + 1  # another mating move (§4.2): the line ends here
            break
        if same and mine == expected:
            board.push(expected)
        else:
            same = False
    extra = [m.uci() for m in line[end:]]
    return grades, extra, first_wrong


class CommitLineMode:
    name = "commit_line"

    def start(self, puzzle: Puzzle, now_ms: int, length_shown: bool = False) -> CommitState:
        board, _ = start_position(puzzle.fen, puzzle.moves)  # raises PuzzleDataError if the line is illegal
        return CommitState(puzzle=puzzle, board=board, started_ms=now_ms, start_fen=board.fen(),
                           length_shown=length_shown)  # fmt: skip

    def start_practice(self, puzzle: Puzzle, now_ms: int, length_shown: bool = False) -> CommitState:
        state = self.start(puzzle, now_ms, length_shown)
        state.practice = True
        state.attempt = AttemptResult(
            win=False, first_move_correct=False, line_correct=False, help_used="none", time_ms=0
        )
        return state

    def _decide(
        self, state: CommitState, win: bool, first_ok: bool, now_ms: int, help_used: HelpUsed = "none"
    ) -> AttemptResult:
        result = AttemptResult(win=win, first_move_correct=first_ok, line_correct=win, help_used=help_used,
                               time_ms=max(0, now_ms - state.started_ms))  # fmt: skip
        state.attempt = result
        return result

    def on_move(self, state: CommitState, uci: str, now_ms: int) -> Feedback:
        raise ConflictError("In Commit the line, enter the whole line and press Submit.")

    def parse_line(self, state: CommitState, line: Any) -> list[chess.Move]:
        """The submitted line, checked: a list of legal UCI moves from the start, not too long."""
        if not isinstance(line, list | tuple):
            raise ValidationError("The line must be a list of moves.")
        if not line:
            raise ValidationError("Enter at least one move before you submit.")
        limit = max_plies(state.puzzle, state.length_shown)
        if len(line) > limit:
            raise ValidationError(f"That line is too long: at most {limit} moves.")
        board = state.board.copy(stack=False)
        moves: list[chess.Move] = []
        for uci in line:
            move = parse_move(board, uci)
            if move is None:
                raise ValidationError("The line contains an illegal move.")
            board.push(move)
            moves.append(move)
        return moves

    def on_submit(self, state: CommitState, line: Any, now_ms: int) -> CommitResult:
        if state.finished:
            raise ConflictError("This puzzle is over: there's nothing to submit.")
        moves = self.parse_line(state, line)
        solution = state.puzzle.moves[1:]
        grades, extra, first_wrong = grade(state.board, solution, moves)
        player_ok = all(g.correct for g in grades if g.player)
        replies = [g for g in grades if not g.player]
        replies_correct = sum(1 for g in replies if g.correct)
        state.first_wrong = first_wrong
        state.played = [m.uci() for m in moves]
        state.finished = True
        decided = None
        if state.attempt is None:  # Hint before Submit already decided it (a loss), or a practice run
            decided = self._decide(state, player_ok, grades[0].correct, now_ms)
        result = CommitResult(
            tuple(grades),
            tuple(extra),
            replies_correct,
            len(replies),
            player_ok and decided is not None and decided.win,
            decided,
            tuple(sounds_for_line(state.start_fen, state.played)),
        )
        state.submitted = result
        return result

    def on_help(self, state: CommitState, kind: HelpKind, now_ms: int) -> HelpResult:
        line = tuple(state.puzzle.moves[1:])
        if kind == "hint":
            if state.finished:
                raise ConflictError("The puzzle is over: there's nothing left to hint.")
            decided = None if state.attempt else self._decide(state, False, False, now_ms, "hint")
            state.hinted = True
            return HelpResult("hint", line[0][:2], None, (), decided)
        if kind != "answer":
            raise ValidationError("Help must be 'hint' or 'answer'.")
        sounds = tuple(sounds_for_line(state.start_fen, line))
        if state.finished:  # free after the end (FR-5.4)
            return HelpResult("answer", None, state.start_fen, line, None, sounds,
                              refute=state.first_wrong is not None)  # fmt: skip
        if state.attempt is None and not state.hinted:
            raise ConflictError("Try a Hint first: Show answer unlocks after it.")
        decided = None if state.attempt else self._decide(state, False, False, now_ms, "answer")
        state.finished = True  # the answer ends the puzzle, before anything was submitted
        return HelpResult("answer", None, state.start_fen, line, decided, sounds)

    def give_up(self, state: CommitState, now_ms: int) -> AttemptResult | None:
        if state.attempt is not None:
            return None
        return self._decide(state, False, False, now_ms)
