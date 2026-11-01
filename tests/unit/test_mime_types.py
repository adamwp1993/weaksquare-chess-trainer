"""Regression: Windows can map .js to text/plain, which left the real window blank (found in v0.1a)."""

from __future__ import annotations

import mimetypes

from weaksquare.app import fix_mime_types


def test_bundle_types_are_pinned(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(mimetypes, "types_map", dict(mimetypes.types_map, **{".js": "text/plain"}))
    mimetypes.add_type("text/plain", ".js")
    fix_mime_types()
    assert mimetypes.guess_type("index-abc.js")[0] == "text/javascript"
    assert mimetypes.guess_type("index-abc.css")[0] == "text/css"
