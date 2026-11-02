"""The ONLY module that imports keyring (SR-7; a pre-commit hook enforces it).

Secrets (the Lichess token, later LLM keys) live only in Windows Credential Manager (SR-1, FR-6.5).
Callers fetch a secret per request and hand it straight to `adapters/http.py`; it never goes into a
DTO, a log line or an exception message. Errors from keyring are re-raised without the value.

Service names keep the real sign-in, dev runs and the live-test token apart:
`weaksquare` (normal runs), `weaksquare-dev` (`--dev`), `weaksquare-test` (live tests, SR-13).
"""

from __future__ import annotations

import os
import sys
import threading
from typing import Protocol

SERVICE_APP = "weaksquare"
SERVICE_DEV = "weaksquare-dev"
SERVICE_TEST = "weaksquare-test"
LICHESS = "lichess"

# Credential Manager holds at most 2,560 bytes per secret, and keyring stores UTF-16, so 1,280
# characters fit. Lichess tokens can grow without notice (FR-6.7 asks for at least 512).
MAX_SECRET_CHARS = 1200


class SecretStoreError(Exception):
    """Credential Manager failed. The message never contains the secret."""


class SecretStore(Protocol):
    def get(self, account: str) -> str | None: ...

    def set(self, account: str, secret: str) -> None: ...

    def delete(self, account: str) -> None:
        """Remove the secret; does nothing if there isn't one."""
        ...


def service_name(dev: bool) -> str:
    return SERVICE_DEV if dev else SERVICE_APP


def _check(secret: str) -> None:
    if not secret or len(secret) > MAX_SECRET_CHARS:
        raise SecretStoreError(f"The secret must be 1 to {MAX_SECRET_CHARS} characters long.")


def _under_pytest() -> bool:
    return "pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ


class KeyringSecretStore:
    """Windows Credential Manager through keyring. Under pytest only the live-test service is
    allowed, so a test can never read or overwrite your real sign-in."""

    def __init__(self, service: str) -> None:
        if _under_pytest() and service != SERVICE_TEST:
            raise SecretStoreError(f"tests may only use the {SERVICE_TEST!r} keyring entry")
        self._service = service

    def get(self, account: str) -> str | None:
        import keyring
        from keyring.errors import KeyringError

        try:
            return keyring.get_password(self._service, account)
        except KeyringError as e:
            raise SecretStoreError(f"Couldn't read from Windows Credential Manager ({type(e).__name__}).") from None

    def set(self, account: str, secret: str) -> None:
        import keyring
        from keyring.errors import KeyringError

        _check(secret)
        try:
            keyring.set_password(self._service, account, secret)
        except KeyringError as e:
            raise SecretStoreError(f"Couldn't save to Windows Credential Manager ({type(e).__name__}).") from None

    def delete(self, account: str) -> None:
        import keyring
        from keyring.errors import KeyringError, PasswordDeleteError

        try:
            keyring.delete_password(self._service, account)
        except PasswordDeleteError:
            return  # nothing stored
        except KeyringError as e:
            raise SecretStoreError(f"Couldn't remove from Windows Credential Manager ({type(e).__name__}).") from None


class MemorySecretStore:
    """In memory only: the store tests use (they never touch keyring, SR-12), and the default for
    scripts that don't need secrets."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}
        self._lock = threading.Lock()

    def get(self, account: str) -> str | None:
        with self._lock:
            return self._data.get(account)

    def set(self, account: str, secret: str) -> None:
        _check(secret)
        with self._lock:
            self._data[account] = secret

    def delete(self, account: str) -> None:
        with self._lock:
            self._data.pop(account, None)
