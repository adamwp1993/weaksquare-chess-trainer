"""Mistake reasons: why you missed it (REQUIREMENTS §7.3, FR-5.6–5.10). Pure.

Themes say *what* went wrong; a reason says *why*, so a knowledge gap (learn the pattern) can be told
from a process gap (you knew it but didn't look).

- `REASONS` is the fixed set in FR-5.6 order; the chips' keyboard shortcuts 1–6 follow it.
- `suggest` pre-highlights a likely reason (FR-5.9). It's only a suggestion: nothing is saved until
  you click a chip. The first rule that matches wins, in this order:
    1. `rushed`: the deciding move (or Submit, or the Danger-spotting call) came less than the
       threshold after its position appeared
    2. `miscalculated`: your first move was right and a later one was wrong
    3. `missedResource`: Stockfish's refutation of your move starts with a check or a capture, or
       mates you; or, in Danger spotting, you called the real blunder Safe
    4. `unknownPattern`: in Name the idea, none of your tags was one of the puzzle's motifs
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import chess

from weaksquare.core.errors import ValidationError

Reason = Literal["didntLook", "missedResource", "miscalculated", "unknownPattern", "rushed", "misclick"]
GapType = Literal["process", "calculation", "knowledge", "time", "noise"]
Source = Literal["puzzle", "danger"]  # 'game' and 'retry' arrive in v0.8


@dataclass(frozen=True)
class ReasonInfo:
    key: Reason
    label: str
    gap: GapType


REASONS: tuple[ReasonInfo, ...] = (
    ReasonInfo("didntLook", "Didn't look for it", "process"),
    ReasonInfo("missedResource", "Missed their reply / defense / threat", "process"),
    ReasonInfo("miscalculated", "Saw the idea, calculated it wrong", "calculation"),
    ReasonInfo("unknownPattern", "Didn't know this pattern", "knowledge"),
    ReasonInfo("rushed", "Rushed / time pressure", "time"),
    ReasonInfo("misclick", "Misclick", "noise"),
)
REASON_KEYS: tuple[str, ...] = tuple(r.key for r in REASONS)
MISCLICK = "misclick"
MAX_NOTE = 200
DEFAULT_RUSHED_S = 3
RUSHED_RANGE = (1, 30)
# FR-5.10: say so when misclicks are an unusually high share of your tagged misses.
MISCLICK_WARN_SHARE = 0.25
MISCLICK_WARN_MIN_TAGGED = 8


def reason_info(key: str) -> ReasonInfo:
    for r in REASONS:
        if r.key == key:
            return r
    raise ValidationError("Unknown mistake reason.")


def validate_note(note: object) -> str | None:
    """An optional short note: plain text, trimmed, at most MAX_NOTE characters. Empty means none."""
    if note is None:
        return None
    if not isinstance(note, str):
        raise ValidationError("The note must be text.")
    text = note.strip()
    if len(text) > MAX_NOTE:
        raise ValidationError(f"Keep the note under {MAX_NOTE} characters.")
    return text or None


def validate_rushed_s(value: object) -> int:
    lo, hi = RUSHED_RANGE
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise ValidationError(f"The rushed threshold must be a whole number of seconds from {lo} to {hi}.")
    return value


def is_forcing_reply(fen_after_your_move: str, reply_uci: str) -> bool:
    """The opponent's reply gives check or captures (for `missedResource`). False if it can't be read."""
    try:
        board = chess.Board(fen_after_your_move)
        move = chess.Move.from_uci(reply_uci)
    except ValueError:
        return False
    if move not in board.legal_moves:
        return False
    return board.is_capture(move) or board.gives_check(move)


@dataclass(frozen=True)
class ReasonContext:
    """What the suggestion rules look at, for one lost attempt."""

    decisive_ms: int | None  # think time of the deciding move, Submit or call; None if help decided it
    rushed_ms: int  # the threshold (setting `reasons.rushed_s`)
    first_right_later_wrong: bool = False
    reply_forcing: bool = False  # the refutation's first reply is a check or a capture
    reply_mates: bool = False  # the refutation mates you
    idea_found: int | None = None  # Name the idea: tags that were puzzle motifs…
    idea_total: int | None = None  # …and how many motifs the puzzle has (None or 0: no tag score)
    called_blunder_safe: bool = False  # Danger spotting: you called the real blunder Safe


def suggest(ctx: ReasonContext) -> Reason | None:
    if ctx.decisive_ms is not None and ctx.decisive_ms < ctx.rushed_ms:
        return "rushed"
    if ctx.first_right_later_wrong:
        return "miscalculated"
    if ctx.called_blunder_safe or ctx.reply_forcing or ctx.reply_mates:
        return "missedResource"
    if ctx.idea_total and ctx.idea_found == 0:
        return "unknownPattern"
    return None


def misclick_warning(misclicks: int, tagged_misses: int) -> bool:
    """FR-5.10: an unusually high share of your tagged misses are misclicks."""
    return tagged_misses >= MISCLICK_WARN_MIN_TAGGED and misclicks >= MISCLICK_WARN_SHARE * tagged_misses
