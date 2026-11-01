"""NFR-8a: the committed .ico has every size from 16 to 256 px, and matches what make_icon.py builds
from the SVG (the rebuild needs Playwright's Chromium, so it runs with -m e2e)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from make_icon import ICO, SIZES, SVG, pack_ico, read_ico_sizes  # noqa: E402


def test_ico_has_every_size_from_16_to_256() -> None:
    sizes = read_ico_sizes(ICO.read_bytes())
    assert sizes == sorted(SIZES) and sizes[0] == 16 and sizes[-1] == 256
    assert {16, 20, 24, 32, 40, 48, 64, 128, 256} <= set(sizes)


def test_entries_are_pngs_at_their_offsets() -> None:
    import struct

    ico = ICO.read_bytes()
    for i in range(len(SIZES)):
        _, _, _, _, _, bpp, length, offset = struct.unpack_from("<BBBBHHII", ico, 6 + 16 * i)
        assert bpp == 32 and ico[offset : offset + 8] == b"\x89PNG\r\n\x1a\n" and offset + length <= len(ico)


def test_pack_ico_round_trip() -> None:
    fake = {16: b"\x89PNG\r\n\x1a\nA", 256: b"\x89PNG\r\n\x1a\nBB"}
    assert read_ico_sizes(pack_ico(fake)) == [16, 256]


def test_svg_credits_the_queen() -> None:
    svg = SVG.read_text(encoding="utf-8")
    assert "cburnett" in svg and "Colin M. L. Burnett" in svg and "GPL-2.0-or-later" in svg


@pytest.mark.e2e
def test_committed_ico_matches_the_svg() -> None:
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "make_icon.py"), "--check"], capture_output=True)
    assert proc.returncode == 0, proc.stdout.decode() + proc.stderr.decode()
