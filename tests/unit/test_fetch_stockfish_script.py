"""scripts/fetch_stockfish.py: a thin CLI over the shared installer (FR-7.5)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_help_lists_dev_and_force() -> None:
    out = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "fetch_stockfish.py"), "--help"], capture_output=True, text=True
    )
    assert out.returncode == 0
    assert "--dev" in out.stdout and "--force" in out.stdout


def test_script_uses_the_shared_installer_only() -> None:
    src = (ROOT / "scripts" / "fetch_stockfish.py").read_text(encoding="utf-8")
    assert "build_engine_installer" in src
    assert "github.com" not in src and "sha256" not in src.lower()  # the URL and hash live in the manifest


def test_developer_guide_path_options_use_equals() -> None:
    """Regression (v0.4-B4): `--engine-path PATH` (a space) fails when PATH exists, because pytest takes
    the separate PATH as a test path before it knows the option. The guide must write `--opt=PATH`."""
    import re

    guide = (ROOT / "docs" / "DEVELOPER_GUIDE.md").read_text(encoding="utf-8")
    assert not re.search(r"--(engine|fulldb)-path [A-Z<]", guide)
    assert "--engine-path=PATH" in guide and "--fulldb-path=PATH" in guide
