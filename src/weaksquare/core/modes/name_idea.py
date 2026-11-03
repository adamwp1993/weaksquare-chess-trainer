"""Name the idea first (FR-4.3): tag the idea, then solve as in Standard.

- Before your first move you tag setup and payoff motifs (at least one tag, at most 3 per slot),
  then press Start solving (`set_tags`). Until then the board takes no moves.
- Solving, help and scoring are Standard's (FR-4.1, FR-5.1–5.5); the angle and the sync too.
- After the end, your tags are graded against the puzzle's motif themes, whichever slot they're in
  (`grade_tags`): ideas found, out of the puzzle's motifs, plus extras that weren't motifs. A puzzle
  with no motif themes has no tag score. The grade is shown only after the end (FR-3.14).
- Think time for the mistake-reason suggestion (FR-5.9) starts when you press Start solving.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from weaksquare.core.errors import ConflictError, ValidationError
from weaksquare.core.modes.base import Feedback
from weaksquare.core.modes.standard import StandardMode, StandardState
from weaksquare.core.puzzle import Puzzle
from weaksquare.core.themes import IDEA_PAYOFF, IDEA_SETUP, motif_themes

MAX_PER_SLOT = 3


@dataclass(frozen=True)
class IdeaTags:
    setup: tuple[str, ...]
    payoff: tuple[str, ...]

    def all(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(self.setup + self.payoff))

    def to_json(self) -> dict[str, list[str]]:
        return {"setup": list(self.setup), "payoff": list(self.payoff)}


@dataclass(frozen=True)
class IdeaScore:
    found: int  # your tags that are puzzle motifs
    total: int  # the puzzle's motifs (0: no tag score)
    extra: int  # your tags that aren't
    correct: tuple[str, ...]  # your tags that were right…
    wrong: tuple[str, ...]  # …and the ones that weren't
    missed: tuple[str, ...]  # puzzle motifs you didn't name


def parse_tags(setup: Any, payoff: Any) -> IdeaTags:
    def slot(value: Any, allowed: tuple[str, ...], name: str) -> tuple[str, ...]:
        if value is None:
            return ()
        if not isinstance(value, list | tuple) or not all(isinstance(t, str) for t in value):
            raise ValidationError(f"{name} tags must be a list of theme keys.")
        tags = tuple(dict.fromkeys(value))
        if len(tags) > MAX_PER_SLOT:
            raise ValidationError(f"Pick at most {MAX_PER_SLOT} {name.lower()} tags.")
        unknown = [t for t in tags if t not in allowed]
        if unknown:
            raise ValidationError(f"Not a {name.lower()} motif: {unknown[0][:40]!r}.")
        return tags

    tags = IdeaTags(slot(setup, IDEA_SETUP, "Setup"), slot(payoff, IDEA_PAYOFF, "Payoff"))
    if not tags.all():
        raise ValidationError("Name at least one idea before you start solving.")
    return tags


def grade_tags(tags: IdeaTags, puzzle_themes: tuple[str, ...] | list[str]) -> IdeaScore:
    motifs = motif_themes(puzzle_themes)
    named = tags.all()
    correct = tuple(t for t in named if t in motifs)
    wrong = tuple(t for t in named if t not in motifs)
    missed = tuple(t for t in motifs if t not in named)
    return IdeaScore(len(correct), len(motifs), len(wrong), correct, wrong, missed)


@dataclass
class NameIdeaState(StandardState):
    tags: IdeaTags | None = None
    score: IdeaScore | None = field(default=None)


class NameIdeaMode(StandardMode):
    name = "name_idea"

    def start(self, puzzle: Puzzle, now_ms: int) -> NameIdeaState:
        base = super().start(puzzle, now_ms)
        return NameIdeaState(**{f: getattr(base, f) for f in base.__dataclass_fields__})

    def start_practice(self, puzzle: Puzzle, now_ms: int) -> NameIdeaState:
        """Try again (FR-5.12): your tags were already graded, so practice goes straight to solving."""
        state = super().start_practice(puzzle, now_ms)
        assert isinstance(state, NameIdeaState)
        state.tags = IdeaTags((), ())
        return state

    def set_tags(self, state: NameIdeaState, setup: Any, payoff: Any, now_ms: int) -> IdeaTags:
        if state.tags is not None:
            raise ConflictError("You've already named the idea for this puzzle.")
        if state.finished or state.attempt is not None:
            raise ConflictError("This puzzle is already decided.")
        state.tags = parse_tags(setup, payoff)
        state.position_ms = now_ms  # FR-5.9: think time starts when you start solving
        return state.tags

    def on_move(self, state: StandardState, uci: str, now_ms: int) -> Feedback:
        assert isinstance(state, NameIdeaState)
        if state.tags is None and not state.finished:
            raise ConflictError("Name the idea first, then press Start solving.")
        return super().on_move(state, uci, now_ms)

    def score(self, state: NameIdeaState) -> IdeaScore | None:
        """The tag grade, once the attempt is decided (None if you never tagged, or in practice)."""
        if state.tags is None or state.practice or not state.tags.all():
            return None
        if state.score is None:
            state.score = grade_tags(state.tags, state.puzzle.themes)
        return state.score
