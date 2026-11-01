"""ARCHITECTURE §3 decision 8: web/src/api/types.ts matches bridge/dto.py."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_generated_types_are_current() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "gen_types.py"), "--check"], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
