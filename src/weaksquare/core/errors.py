"""Errors that carry a stable code and a user-facing message across the bridge (NFR-5)."""

from __future__ import annotations


class AppError(Exception):
    code = "error"
    retryable = False

    def __init__(self, message: str, *, code: str | None = None, retryable: bool | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if retryable is not None:
            self.retryable = retryable


class ValidationError(AppError):
    """Bad input from the UI (or from anything else untrusted)."""

    code = "invalid_argument"


class NotFoundError(AppError):
    code = "not_found"


class ConflictError(AppError):
    """The request is valid but can't run in the current state (e.g. an import is already running)."""

    code = "conflict"
    retryable = True


class StaleKeyError(Exception):
    """A puzzle key from before puzzles.db was replaced: keys don't survive a re-import (v0.2-B3).
    Not an AppError: the session follows the re-import and retries; it never reaches the UI."""

    def __init__(self, had: int, now: int) -> None:
        super().__init__(f"puzzle keys are from database version {had}, now {now}")
