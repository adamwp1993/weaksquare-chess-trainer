"""The engine tolerance (v0.8): Retry mode (FR-11.15) and puzzles saved from your games (FR-10.43) accept
any move within `tol_cp` of the best move. Pure: the caller gets both scores from the interactive engine,
each from the solver's side after the move.
"""

from __future__ import annotations

from weaksquare.core.game_review import Score

DEFAULT_TOLERANCE_CP = 30
TOLERANCE_RANGE = (0, 300)


def within_tolerance(best: Score, played: Score, tol_cp: int = DEFAULT_TOLERANCE_CP) -> bool:
    """True when the played move is as good as the best one, give or take `tol_cp`. Any forced mate counts
    when the best move mates too (like "any mate counts" in puzzles). A move that delivers mate is always
    found. Scores are clamped like the review's cp loss."""
    if played.mate is not None and played.mate >= 0:
        return True  # it mates, or forces mate
    if best.mate is not None and best.mate > 0:
        return False  # the best move forced mate and this one doesn't
    return best.value() - played.value() <= tol_cp


def validate_tolerance(tol_cp: int) -> int:
    lo, hi = TOLERANCE_RANGE
    if not isinstance(tol_cp, int) or isinstance(tol_cp, bool) or not lo <= tol_cp <= hi:
        raise ValueError(f"the tolerance must be a whole number of centipawns from {lo} to {hi}")
    return tol_cp
