"""SR-7 / FR-6.5 / FR-6.7: the secret store. Tests never touch keyring itself (SR-12)."""

from __future__ import annotations

import pytest

from weaksquare.adapters.secret_store import (
    LICHESS,
    MAX_SECRET_CHARS,
    SERVICE_APP,
    SERVICE_DEV,
    KeyringSecretStore,
    MemorySecretStore,
    SecretStoreError,
    service_name,
)

FAKE = "lip_" + "FAKE" * 4


def test_memory_store_round_trip() -> None:
    s = MemorySecretStore()
    assert s.get(LICHESS) is None
    s.set(LICHESS, FAKE)
    assert s.get(LICHESS) == FAKE
    s.delete(LICHESS)
    assert s.get(LICHESS) is None
    s.delete(LICHESS)  # deleting nothing is fine


def test_long_tokens_fit() -> None:
    """FR-6.7: tokens of at least 512 characters (Lichess may lengthen them)."""
    s = MemorySecretStore()
    long_token = "lip_FAKE" + "x" * 992
    s.set(LICHESS, long_token)
    assert s.get(LICHESS) == long_token


def test_too_long_or_empty_is_refused_without_echoing_it() -> None:
    s = MemorySecretStore()
    too_long = "lip_FAKE" + "y" * MAX_SECRET_CHARS
    with pytest.raises(SecretStoreError) as e:
        s.set(LICHESS, too_long)
    assert "yyyy" not in str(e.value)
    with pytest.raises(SecretStoreError):
        s.set(LICHESS, "")


def test_dev_runs_use_their_own_entry() -> None:
    assert service_name(dev=False) == SERVICE_APP
    assert service_name(dev=True) == SERVICE_DEV != SERVICE_APP


@pytest.mark.parametrize("service", [SERVICE_APP, SERVICE_DEV])
def test_tests_can_never_open_the_real_entries(service: str) -> None:
    with pytest.raises(SecretStoreError):
        KeyringSecretStore(service)
