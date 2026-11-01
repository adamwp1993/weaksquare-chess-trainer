"""FR-1.13 / §15: every bundled sound file is credited with an AGPL-compatible license, and nothing
credited is missing. The files must be unmodified copies of what CREDITS.md records."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

SOUNDS = Path(__file__).resolve().parents[2] / "web" / "public" / "sounds"
ROW = re.compile(r"^\| `(?P<file>[^`]+)` \| (?P<author>[^|]+) \| (?P<license>[^|]+) \| `(?P<sha>[0-9a-f]+)…`")
AGPL_COMPATIBLE = {"AGPL-3.0-or-later", "GPL-3.0-or-later", "CC0-1.0", "MIT", "BSD-2-Clause", "Apache-2.0"}
SETS = {"sfx", "piano", "nes", "futuristic"}
EVENTS = {"Move", "Capture", "Check", "Checkmate", "Victory", "Defeat"}


def credits() -> dict[str, re.Match[str]]:
    rows = {}
    for line in (SOUNDS / "CREDITS.md").read_text(encoding="utf-8").splitlines():
        m = ROW.match(line)
        if m:
            rows[m["file"]] = m
    return rows


def test_every_file_is_credited_and_every_credit_exists() -> None:
    files = {p.relative_to(SOUNDS).as_posix() for p in SOUNDS.rglob("*") if p.is_file() and p.name != "CREDITS.md"}
    assert files == set(credits())


def test_licenses_are_agpl_compatible_and_hashes_match() -> None:
    for name, m in credits().items():
        assert m["license"].strip() in AGPL_COMPATIBLE, name
        digest = hashlib.sha256((SOUNDS / name).read_bytes()).hexdigest()
        assert digest.startswith(m["sha"]), f"{name} differs from the credited file"


def test_every_set_has_every_event_and_files_are_ogg() -> None:
    for s in SETS:
        for e in EVENTS:
            f = SOUNDS / s / f"{e}.ogg"
            assert f.is_file(), f
            assert f.read_bytes()[:4] == b"OggS", f"{f} isn't an Ogg file (a git symlink placeholder?)"


def test_the_ui_offers_exactly_the_bundled_sets() -> None:
    from weaksquare.services.ui_settings import SOUND_SETS

    assert set(SOUND_SETS) == SETS == {p.name for p in SOUNDS.iterdir() if p.is_dir()}
