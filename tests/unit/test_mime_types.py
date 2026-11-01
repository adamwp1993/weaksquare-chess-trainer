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


def test_make_rng_logs_its_seed(caplog) -> None:  # type: ignore[no-untyped-def]
    """Regression for v0.1-B13: the seed is logged so a queue can be replayed."""
    import logging
    import random
    import re

    from weaksquare.adapters.system_clock import make_rng

    with caplog.at_level(logging.INFO, logger="weaksquare"):
        rng = make_rng()
    m = re.search(r"random seed: (\d+)", caplog.text)
    assert m
    assert random.Random(int(m.group(1))).random() == rng.random()
