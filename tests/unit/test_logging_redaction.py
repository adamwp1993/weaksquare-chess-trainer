"""SR-5 / SR-10: token-like values never reach the log file."""

from __future__ import annotations

import logging
from pathlib import Path

from weaksquare.adapters.logging_setup import RedactingFilter, redact

# Built at runtime so no secret-looking literal sits in the repo.
FAKE_LICHESS = "lip_" + "FAKE" * 5
FAKE_ANTHROPIC = "sk-ant-" + "FAKE" * 6
FAKE_BEARER = "Bearer " + "FAKE" * 6


def test_redacts_known_patterns() -> None:
    text = f"token {FAKE_LICHESS} key {FAKE_ANTHROPIC} hdr Authorization: {FAKE_BEARER} url ?code=abc123&state=1"
    out = redact(text)
    assert FAKE_LICHESS not in out
    assert FAKE_ANTHROPIC not in out
    assert "FAKEFAKEFAKEFAKEFAKEFAKE" not in out
    assert "code=abc123" not in out
    assert "state=1" in out


def test_filter_redacts_args_and_tracebacks(tmp_path: Path) -> None:
    logger = logging.getLogger("redaction-test")
    logger.propagate = False
    handler = logging.FileHandler(tmp_path / "x.log", encoding="utf-8")
    handler.addFilter(RedactingFilter())
    logger.addHandler(handler)
    try:
        logger.error("sending %s", FAKE_LICHESS)
        try:
            raise ValueError(f"bad header Authorization: {FAKE_BEARER}")
        except ValueError:
            logger.exception("request failed")
    finally:
        handler.close()
        logger.removeHandler(handler)
    content = (tmp_path / "x.log").read_text(encoding="utf-8")
    assert FAKE_LICHESS not in content
    assert "FAKEFAKEFAKEFAKEFAKEFAKE" not in content
    assert "[REDACTED]" in content
