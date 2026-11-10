"""The first-run wizard's state (v1.0, NFR-8): gathers the facts `core/setup.py` decides from, and records the few
things only you can decide (your choice on the first step, a skipped step, finishing). Every key is `setup.`, which
stays with this PC through a restore (FR-15.4)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from weaksquare.core.errors import ValidationError
from weaksquare.core.setup import CHOICES, DONE, SKIPPABLE, SetupFacts, shown, step

FINISHED_KEY = "setup.finished"
CHOICE_KEY = "setup.choice"
SKIPPED_KEY = "setup.skipped"  # a list of skipped steps


class Settings(Protocol):
    def get(self, key: str) -> Any | None: ...
    def set(self, key: str, value: Any) -> None: ...


@dataclass(frozen=True)
class SetupState:
    show: bool
    step: str
    facts: SetupFacts
    puzzle_job: str | None
    engine_job: str | None
    puzzles_need_upgrade: bool = False  # an older puzzles.db: the puzzle step upgrades it, no download


class SetupService:
    def __init__(
        self, settings: Settings, puzzle_db: Any, engine: Any, account: Any, has_data: Callable[[], bool]
    ) -> None:
        self._settings = settings
        self._puzzle_db = puzzle_db
        self._engine = engine
        self._account = account
        self._has_data = has_data

    def _skipped(self) -> set[str]:
        raw = self._settings.get(SKIPPED_KEY)
        return {s for s in raw if isinstance(s, str)} if isinstance(raw, list) else set()

    def state(self) -> SetupState:
        db = self._puzzle_db.status()
        eng = self._engine.status()
        acct = self._account.status()
        choice = self._settings.get(CHOICE_KEY)
        skipped = self._skipped()
        facts = SetupFacts(
            finished=self._settings.get(FINISHED_KEY) is True,
            choice=choice if choice in CHOICES else None,
            has_data=self._has_data(),
            puzzles_installed=bool(db.installed) and not db.needs_upgrade,
            engine_ready=getattr(eng, "state", None) == "ready",
            engine_skipped="engine" in skipped,
            signed_in=getattr(acct, "state", None) in ("signed_in", "offline"),
            lichess_skipped="lichess" in skipped,
        )
        return SetupState(shown(facts), step(facts), facts, db.import_job_id, getattr(eng, "install_job_id", None),
                          bool(db.installed) and bool(db.needs_upgrade))  # fmt: skip

    def choose(self, choice: Any) -> SetupState:
        """The welcome step's Start fresh. Restore isn't chosen here: it's recorded by `note_restored` only once a
        restore has actually swapped your data in (v1.0-B1), so a refused or failed one leaves the welcome step."""
        if choice != "fresh":
            raise ValidationError("Choose Start fresh, or restore a backup.")
        self._settings.set(CHOICE_KEY, choice)
        return self.state()

    def note_restored(self) -> None:
        """At startup, after a staged restore swapped in (FR-15.4): an unfinished wizard carries on after Welcome."""
        if self._settings.get(FINISHED_KEY) is not True:
            self._settings.set(CHOICE_KEY, "restore")

    def skip(self, which: Any) -> SetupState:
        if which not in SKIPPABLE:
            raise ValidationError("Only the Stockfish and Lichess steps can be skipped.")
        self._settings.set(SKIPPED_KEY, sorted(self._skipped() | {which}))
        return self.state()

    def finish(self) -> SetupState:
        """Ends the wizard once every step is done or skipped. It never shows again on this PC."""
        st = self.state()
        if st.step != DONE:
            raise ValidationError("Finish the remaining steps first, or skip them.")
        self._settings.set(FINISHED_KEY, True)
        return self.state()
