"""The first-run wizard (v1.0, NFR-8, FR-15.4): which step to show, decided from facts, never from a stored "current
step" that could go stale (v1.0 planning).

- **Shown** on a fresh install: setup isn't finished, and `user.db` has no data yet (a first launch, even after
  `setup.py` imported the puzzle database), or the puzzle database is missing, or you've already made a choice on the
  first step. An install that has your data and its puzzle database never sees it.
- **Steps**, in order, each skipped once its fact holds:
  1. **welcome**: Start fresh or Restore from a backup. Skipped once you've chosen, or when `user.db` already has
     data (an install whose puzzle database went missing).
  2. **puzzles**: the puzzle database download, until it's installed.
  3. **engine**: Stockfish, until it's ready or you skip it.
  4. **lichess**: signing in, until you're signed in or skip it.
  5. **done**: the wizard finishes and the app starts as usual.
- The `setup.` settings stay with this PC (`core.backup.PC_LOCAL_PREFIXES`). The choice "restore" is recorded only
  by the start that swapped a backup in (`SetupService.note_restored`, v1.0-B1), so the wizard then carries on after
  Welcome; a restore that was refused or failed leaves the welcome step.
"""

from __future__ import annotations

from dataclasses import dataclass

WELCOME, PUZZLES, ENGINE, LICHESS, DONE = "welcome", "puzzles", "engine", "lichess", "done"
STEPS = (WELCOME, PUZZLES, ENGINE, LICHESS, DONE)
CHOICES = ("fresh", "restore")
SKIPPABLE = (ENGINE, LICHESS)


@dataclass(frozen=True)
class SetupFacts:
    finished: bool
    choice: str | None  # "fresh" / "restore" once chosen on the welcome step
    has_data: bool  # user.db already holds games, puzzle attempts or Coach reports
    puzzles_installed: bool
    engine_ready: bool
    engine_skipped: bool
    signed_in: bool
    lichess_skipped: bool


def shown(f: SetupFacts) -> bool:
    return not f.finished and (not f.has_data or not f.puzzles_installed or f.choice is not None)


def step(f: SetupFacts) -> str:
    if f.finished:
        return DONE
    if f.choice is None and not f.has_data:
        return WELCOME
    if not f.puzzles_installed:
        return PUZZLES
    if not f.engine_ready and not f.engine_skipped:
        return ENGINE
    if not f.signed_in and not f.lichess_skipped:
        return LICHESS
    return DONE
