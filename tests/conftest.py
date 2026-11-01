"""Shared fixtures. Every test runs with a temp data folder (NFR-2), a fixed clock and a seeded rng."""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from weaksquare import config
from weaksquare.core.clock import FixedClock


@pytest.fixture(autouse=True)
def temp_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data = tmp_path / "data"
    monkeypatch.setenv(config.DATA_DIR_ENV, str(data))
    return data


@pytest.fixture
def paths(temp_data_dir: Path) -> config.Paths:
    p = config.resolve_paths(dev=True)
    p.ensure()
    return p


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock()


@pytest.fixture
def rng() -> random.Random:
    return random.Random(1234)
