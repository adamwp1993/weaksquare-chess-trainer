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


def test_each_data_folder_has_its_own_entry(tmp_path) -> None:  # type: ignore[no-untyped-def]
    real, dev = tmp_path / "WeakSquare", tmp_path / "WeakSquare-dev"
    assert service_name(real, real, dev) == SERVICE_APP
    assert service_name(dev, real, dev) == SERVICE_DEV
    other = service_name(tmp_path / "smoke-1", real, dev)
    assert other.startswith("weaksquare-") and other not in (SERVICE_APP, SERVICE_DEV)
    assert other != service_name(tmp_path / "smoke-2", real, dev)
    assert other == service_name(tmp_path / "SMOKE-1", real, dev)  # Windows paths ignore case


@pytest.mark.parametrize("service", [SERVICE_APP, SERVICE_DEV])
def test_tests_can_never_open_the_real_entries(service: str) -> None:
    with pytest.raises(SecretStoreError):
        KeyringSecretStore(service)
