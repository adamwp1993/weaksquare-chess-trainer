"""SR-3: local assets only, with a strict Content Security Policy in the built page."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VITE_CONFIG = ROOT / "web" / "vite.config.ts"
INDEX = ROOT / "web" / "index.html"
DIST_INDEX = ROOT / "web" / "dist" / "index.html"


def test_csp_is_strict() -> None:
    config = VITE_CONFIG.read_text(encoding="utf-8")
    assert "\"default-src 'self'\"" in config
    assert "\"script-src 'self'\"" in config
    assert "unsafe-eval" not in config


def test_source_index_has_no_remote_urls() -> None:
    assert not re.search(r"(src|href)=\"(https?:)?//", INDEX.read_text(encoding="utf-8"))


def test_web_src_loads_nothing_remote() -> None:
    pattern = re.compile(r"""(import\s.*from\s+|import\(|url\()\s*['"]?https?://""")
    for f in (ROOT / "web" / "src").rglob("*.ts*"):
        assert not pattern.search(f.read_text(encoding="utf-8")), f


def test_built_index_has_csp_and_local_assets() -> None:
    if not DIST_INDEX.exists():
        pytest.skip("web/dist not built")
    html = DIST_INDEX.read_text(encoding="utf-8")
    assert 'http-equiv="Content-Security-Policy"' in html
    assert not re.search(r"(src|href)=\"(https?:)?//", html)
