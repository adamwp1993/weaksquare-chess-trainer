"""core/ does no I/O, and neither core/ nor services/ read the clock or the global random (§3 decision 15)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "weaksquare"

FORBIDDEN_CALLS = {
    ("datetime", "now"),
    ("datetime", "utcnow"),
    ("datetime", "today"),
    ("date", "today"),
    ("time", "time"),
    ("time", "time_ns"),
    ("time", "monotonic"),
    ("time", "sleep"),
}
RANDOM_FUNCS = {"random", "randint", "choice", "choices", "shuffle", "sample", "uniform", "randrange", "seed"}
CORE_FORBIDDEN_IMPORTS = {"sqlite3", "httpx", "subprocess", "socket", "requests", "webview", "keyring", "os", "shutil"}


def _files(sub: str) -> list[Path]:
    return sorted((SRC / sub).rglob("*.py"))


def _violations(path: Path, *, core: bool) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            owner = node.func.value
            name = owner.id if isinstance(owner, ast.Name) else owner.attr if isinstance(owner, ast.Attribute) else None
            if (name, node.func.attr) in FORBIDDEN_CALLS:
                out.append(f"{path.name}:{node.lineno} calls {name}.{node.func.attr}()")
            if name == "random" and node.func.attr in RANDOM_FUNCS:
                out.append(f"{path.name}:{node.lineno} uses the global random.{node.func.attr}()")
        if core and isinstance(node, ast.Import | ast.ImportFrom):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for m in mods:
                if m.split(".")[0] in CORE_FORBIDDEN_IMPORTS:
                    out.append(f"{path.name}:{node.lineno} imports {m}")
        if core and isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
            out.append(f"{path.name}:{node.lineno} calls open()")
    return out


@pytest.mark.parametrize("path", _files("core"), ids=lambda p: p.relative_to(SRC).as_posix())
def test_core_is_pure(path: Path) -> None:
    assert _violations(path, core=True) == []


@pytest.mark.parametrize("path", _files("services") or [None], ids=lambda p: p.name if p else "none")
def test_services_use_injected_clock_and_rng(path: Path | None) -> None:
    if path is None:
        pytest.skip("no services yet")
    assert _violations(path, core=False) == []


def test_checker_catches_violations(tmp_path: Path) -> None:
    bad = tmp_path / "bad.py"
    bad.write_text(
        "import sqlite3\nimport random\nfrom datetime import datetime\nx = datetime.now()\ny = random.choice([1])\n"
    )
    found = _violations(bad, core=True)
    assert any("sqlite3" in v for v in found)
    assert any("datetime.now" in v for v in found)
    assert any("random.choice" in v for v in found)
