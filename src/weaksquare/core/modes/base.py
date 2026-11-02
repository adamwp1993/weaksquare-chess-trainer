"""The TrainingMode protocol (ARCHITECTURE §3 decision 6).

Standard (v0.1) is the first implementation; the other modes plug in from v0.5 without changing the
trainer view. `on_help(state, kind)` joined the protocol in v0.2, with Hint and Show answer (§7.2).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, TypeVar

from weaksquare.core.move_sounds import MoveSound
from weaksquare.core.puzzle import Puzzle

HelpUsed = Literal["none", "hint", "answer", "explain"]
HelpKind = Literal["hint", "answer"]  # Explain joins in v0.7
FeedbackKind = Literal["correct", "solved", "wrong", "illegal"]


@dataclass(frozen=True)
class AttemptResult:
    """What gets appended to `attempts` (FR-5.5)."""

    win: bool
    first_move_correct: bool
    line_correct: bool
    help_used: HelpUsed
    time_ms: int


@dataclass(frozen=True)
class Feedback:
    kind: FeedbackKind
    reply: str | None  # the opponent's reply (UCI), played automatically
    finished: bool  # the whole line has been played
    attempt: AttemptResult | None  # set exactly once per puzzle, when the attempt is decided
    move_sound: MoveSound | None = None  # your move (also a wrong one, before it's taken back)
    reply_sound: MoveSound | None = None


@dataclass(frozen=True)
class HelpResult:
    """The stuck ladder (§7.2). Help before the attempt is decided makes it a loss (FR-5.2), and
    `attempt` is then set; after that, help is free (FR-5.4)."""

    kind: HelpKind
    hint_square: str | None  # Hint: the square of the piece that moves next
    answer_fen: str | None  # Show answer: the position the answer starts from…
    answer_moves: tuple[str, ...]  # …and every move from there (UCI, both sides)
    attempt: AttemptResult | None
    answer_sounds: tuple[MoveSound, ...] = ()  # one per answer move
    refute: bool = False  # Show answer after a wrong move: the engine's refutation comes first (§7.2)


S = TypeVar("S")


class TrainingMode(Protocol[S]):
    name: str

    def start(self, puzzle: Puzzle, now_ms: int) -> S: ...

    def on_move(self, state: S, uci: str, now_ms: int) -> Feedback: ...

    def on_help(self, state: S, kind: HelpKind, now_ms: int) -> HelpResult: ...

    def give_up(self, state: S, now_ms: int) -> AttemptResult | None:
        """Moving on before the attempt was decided: a loss. None if it was already decided."""
        ...
