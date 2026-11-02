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
