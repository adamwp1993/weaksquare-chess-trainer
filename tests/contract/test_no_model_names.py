"""No hard-coded LLM model names outside the provider defaults module (CLAUDE.md, FR-1.3).

The mock client's fixed data (web/src/api/mock*.ts) is test data for the UI and screenshots, so it may
name models; nothing that runs in the real app may.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODEL = re.compile(r"\b(claude-(haiku|sonnet|opus|fable|mythos)[\w.-]*|gpt-\d[\w.-]*|o\d-(mini|pro)\b)", re.I)
ALLOWED = {ROOT / "src" / "weaksquare" / "core" / "llm" / "defaults.py"}


def _sources() -> list[Path]:
    files = [p for p in (ROOT / "src").rglob("*") if p.suffix in {".py", ".sql", ".json"}]
    web = ROOT / "web" / "src"
    files += [p for p in web.rglob("*") if p.suffix in {".ts", ".tsx"} and not p.name.startswith("mock")]
    return files


def test_model_names_only_in_the_defaults_module() -> None:
    offenders = []
    for path in _sources():
        if path in ALLOWED:
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if MODEL.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{n}: {line.strip()}")
    assert not offenders, "model names outside core/llm/defaults.py:\n" + "\n".join(offenders)


def test_the_defaults_module_does_name_models() -> None:
    """Guards the pattern itself: it must match the names the seed uses."""
    text = next(iter(ALLOWED)).read_text(encoding="utf-8")
    assert MODEL.search(text)
