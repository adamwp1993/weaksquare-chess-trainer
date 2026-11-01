"""The TrainingMode protocol (ARCHITECTURE §3 decision 6).

Standard (v0.1) is the first implementation; the other modes plug in from v0.5 without changing the
trainer view. `on_help(state, kind)` joins the protocol in v0.2, together with Hint and Show answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, TypeVar

from weaksquare.core.puzzle import Puzzle

HelpUsed = Literal["none", "hint", "answer", "explain"]
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


S = TypeVar("S")


class TrainingMode(Protocol[S]):
    name: str

    def start(self, puzzle: Puzzle, now_ms: int) -> S: ...

    def on_move(self, state: S, uci: str, now_ms: int) -> Feedback: ...

    def give_up(self, state: S, now_ms: int) -> AttemptResult | None:
        """Moving on before the attempt was decided: a loss. None if it was already decided."""
        ...
