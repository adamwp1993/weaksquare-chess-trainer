"""Mistake reasons: saving why you missed a puzzle (REQUIREMENTS §7.3, FR-5.6–5.10).

The prompt and its suggestion come from the session (`SessionService.reason_prompt`), which knows the
puzzle you just played. Saving goes through here: the attempt must exist and be a loss, the reason one
of the six, and the note short plain text. Reasons are append-only: picking another chip adds a row,
and the latest one counts. A misclick changes nothing in the Lichess sync (FR-5.10).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from weaksquare.core.clock import Clock
from weaksquare.core.errors import ConflictError, NotFoundError, ValidationError
from weaksquare.core.modes.danger import MODE as DANGER
from weaksquare.core.reasons import reason_info, validate_note


class AttemptLookup(Protocol):
    def brief(self, attempt_id: int) -> Any: ...  # AttemptBrief(id, mode, win) | None


class ReasonStore(Protocol):
    def add(
        self, source: str, ref_id: str, reason: str, suggested: str | None, note: str | None, created_at: str
    ) -> None: ...


class ReasonsService:
    def __init__(
        self,
        attempts: AttemptLookup,
        store: ReasonStore,
        clock: Clock,
        suggestion_for: Callable[[int], str | None] = lambda _id: None,
    ) -> None:
        self._attempts = attempts
        self._store = store
        self._clock = clock
        self._suggestion_for = suggestion_for

    def set_reason(self, attempt_id: Any, reason: Any, note: Any = None) -> None:
        if isinstance(attempt_id, bool) or not isinstance(attempt_id, int) or attempt_id <= 0:
            raise ValidationError("attempt_id must be a positive whole number.")
        if not isinstance(reason, str):
            raise ValidationError("Unknown mistake reason.")
        key = reason_info(reason).key
        text = validate_note(note)
        attempt = self._attempts.brief(attempt_id)
        if attempt is None:
            raise NotFoundError("That attempt doesn't exist.")
        if attempt.win:
            raise ConflictError("You solved that one: there's no miss to explain.")
        source = "danger" if attempt.mode == DANGER else "puzzle"
        self._store.add(source, str(attempt_id), key, self._suggestion_for(attempt_id), text,
                        self._clock.now().isoformat(timespec="seconds"))  # fmt: skip
