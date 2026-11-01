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
