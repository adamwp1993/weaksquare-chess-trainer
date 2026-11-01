"""ARCHITECTURE §3 decision 14: the front end never uses browser storage or cookies."""

from __future__ import annotations

import re
from pathlib import Path

WEB_SRC = Path(__file__).resolve().parents[2] / "web" / "src"
FORBIDDEN = re.compile(r"\b(localStorage|sessionStorage|indexedDB)\b|document\s*\.\s*cookie")


def test_no_browser_storage_in_web_src() -> None:
    hits = []
    for f in WEB_SRC.rglob("*.ts*"):
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if FORBIDDEN.search(line):
                hits.append(f"{f.relative_to(WEB_SRC)}:{n}: {line.strip()}")
    assert hits == []


def test_color_scheme_is_kept_through_the_bridge() -> None:
    """FR-1.12: Mantine's default color-scheme manager uses localStorage. The provider must be given
    the bridge-backed one, and Mantine's storage manager must never be imported."""
    main = (WEB_SRC / "main.tsx").read_text(encoding="utf-8")
    assert re.search(r"<MantineProvider[^>]*colorSchemeManager=\{bridgeColorSchemeManager\(", main)
    for f in WEB_SRC.rglob("*.ts*"):
        assert "localStorageColorSchemeManager" not in f.read_text(encoding="utf-8"), f
