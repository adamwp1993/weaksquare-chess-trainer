"""A shared AI plan answer for the v0.12 integration tests: one good task and one invented one."""

from __future__ import annotations

from typing import Any


def _task(type_: str, minutes: int = 10, **kw: Any) -> dict[str, Any]:
    base = {
        "type": type_, "minutes": minutes, "weakness_key": None, "themes": [], "mode": None, "count": None,
        "rating_min": None, "rating_max": None, "severities": [], "game": None, "topic": None, "prompt": None,
    }  # fmt: skip
    return {**base, **kw}


def plan_answer() -> dict[str, Any]:
    good = _task("puzzles", themes=["mateIn1"], mode="standard", count=5)
    invented = _task("puzzles", themes=["invented"], mode="standard")
    return {"weeks": [{"days": [{"tasks": [good, invented]}]}]}
