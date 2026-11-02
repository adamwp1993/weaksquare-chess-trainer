"""The shipped engine manifest is well formed and pinned (FR-7.5, SR-6)."""

from __future__ import annotations

import json

from weaksquare.config import ENGINE_MANIFEST
from weaksquare.core.engine import parse_manifest


def test_manifest_parses_and_pins_the_windows_build() -> None:
    m = parse_manifest(json.loads(ENGINE_MANIFEST.read_text(encoding="utf-8")))
    assert m.tag == "sf_19"
    assert set(m.assets) == {"windows-x86_64"}  # macOS and Linux arrive in v1.1
    a = m.asset_for("windows-x86_64")
    assert a.name == "stockfish-windows-x86-64-universal.zip"  # the universal build (FR-7.1)
    assert a.url == f"https://github.com/official-stockfish/Stockfish/releases/download/{m.tag}/{a.name}"
    assert len(a.sha256) == 64
    assert a.exe_member.endswith(".exe")


def test_manifest_never_says_latest() -> None:
    assert "latest" not in ENGINE_MANIFEST.read_text(encoding="utf-8").lower()
