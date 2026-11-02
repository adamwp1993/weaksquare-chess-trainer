"""Opt-in tests against the real Stockfish (`uv run pytest -m engine`).

They use the dev data folder's managed install (`uv run python scripts/fetch_stockfish.py --dev`)
or `--engine-path`, read-only, and skip when there's none.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from weaksquare import config


@pytest.fixture(scope="session")
def stockfish_path(request: pytest.FixtureRequest) -> str:
    given = request.config.getoption("--engine-path")
    path = Path(given) if given else config.default_data_dir(dev=True) / "engines" / "sf_19" / "stockfish.exe"
    if not path.is_file():
        pytest.skip(f"no Stockfish at {path}: run uv run python scripts/fetch_stockfish.py --dev")
    return str(path)
