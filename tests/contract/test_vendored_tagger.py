"""The vendored lichess-puzzler tagger stays pure and pinned (REQUIREMENTS §15, ARCHITECTURE §7).

It may import only python-chess, a few standard-library typing modules and its own files, so it can
run in core/ (no I/O, no logging set-up on import).
"""

from __future__ import annotations

import ast
from pathlib import Path

VENDOR = Path(__file__).resolve().parents[2] / "src" / "weaksquare" / "vendor" / "lichess_puzzler"
ALLOWED_TOP = {"chess", "typing", "dataclasses"}
PIN = "8e24b6d5e2b9618e41581a327926e4ac67c610a2"


def test_vendored_files_are_there_with_the_licence() -> None:
    names = {p.name for p in VENDOR.iterdir()}
    assert {"cook.py", "util.py", "model.py", "LICENSE", "__init__.py"} <= names
    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in (VENDOR / "LICENSE").read_text(encoding="utf-8")


def test_imports_are_chess_stdlib_typing_or_relative() -> None:
    bad: list[str] = []
    for path in sorted(VENDOR.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                bad += [f"{path.name}: import {a.name}" for a in node.names if a.name.split(".")[0] not in ALLOWED_TOP]
            elif (
                isinstance(node, ast.ImportFrom)
                and node.level == 0
                and (node.module or "").split(".")[0] not in ALLOWED_TOP
            ):
                bad.append(f"{path.name}: from {node.module}")
    assert bad == []


def test_no_logging_set_up_on_import() -> None:
    text = (VENDOR / "cook.py").read_text(encoding="utf-8")
    assert "basicConfig" not in text and "lichess.org" not in text


def test_pin_is_recorded_in_the_readme_and_requirements() -> None:
    root = VENDOR.parents[3]
    assert PIN in (VENDOR.parent / "README.md").read_text(encoding="utf-8")
    assert PIN[:12] in (root / "REQUIREMENTS.md").read_text(encoding="utf-8")
