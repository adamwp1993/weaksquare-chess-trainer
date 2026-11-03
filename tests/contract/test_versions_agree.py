"""v0.2-B7 regression: the version the app reports (About screen, log banner) is the one in
pyproject.toml and web/package.json; bump them together at each version."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import weaksquare
from weaksquare.config import APP_VERSION

ROOT = Path(__file__).resolve().parents[2]


def test_versions_agree() -> None:
    py = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    web = json.loads((ROOT / "web" / "package.json").read_text(encoding="utf-8"))["version"]
    lock = json.loads((ROOT / "web" / "package-lock.json").read_text(encoding="utf-8"))["version"]
    assert APP_VERSION == weaksquare.__version__ == py == web == lock


def test_version_matches_the_branch_being_built() -> None:
    """While v0.x is built, the app says 0.x.0 (v0.2-B7: v0.2 still said 0.1.0)."""
    assert APP_VERSION == "0.6.0"
