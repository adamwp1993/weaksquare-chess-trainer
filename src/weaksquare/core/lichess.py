"""Lichess API shapes (v0.3): the `LichessClient` protocol, its result types, and parsers for the
JSON Lichess returns. Pure: the httpx implementation is `adapters/lichess.py`; tests use a fake.

Field names follow the lichess-org/api spec (PuzzleBatchSolveResponse, PuzzleActivity, the account
endpoint's `perfs.puzzle`). The live test (`-m live`) records real responses to confirm them.
Every field is read defensively: anything missing becomes None rather than an error.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Protocol

MAX_BATCH = 99  # FR-6.9: fewer than 100 solutions per request
_PUZZLE_ID = re.compile(r"^[A-Za-z0-9]{1,16}$")
_ANGLE = re.compile(r"^[A-Za-z0-9_]{1,64}$")


@dataclass(frozen=True)
class Account:
    id: str  # lower-case username: the stable key
    username: str
    rating: int | None  # perfs.puzzle.rating; None if you've never played a puzzle
    provisional: bool


@dataclass(frozen=True)
class Solution:
    id: str
    win: bool
    rated: bool


@dataclass(frozen=True)
class Round:
    id: str
    win: bool | None
    rating_diff: int | None


@dataclass(frozen=True)
class BatchResult:
    rounds: list[Round]
    rating: int | None  # glicko.rating after this batch
    provisional: bool | None


@dataclass(frozen=True)
class ActivityEntry:
    puzzle_id: str
    date_ms: int
    win: bool | None


class LichessClient(Protocol):
    def exchange_code(self, form: dict[str, str]) -> str:
        """POST /api/token; returns the access token (never logged)."""
        ...

    def revoke(self, token: str) -> None: ...

    def account(self, token: str) -> Account: ...

    def solve_batch(self, token: str, angle: str, solutions: list[Solution]) -> BatchResult: ...

    def activity(self, token: str, since_ms: int | None) -> Iterator[ActivityEntry]: ...

    def dashboard(self, token: str, days: int) -> Dashboard: ...


def valid_angle(angle: str) -> bool:
    return bool(_ANGLE.match(angle))


def valid_puzzle_id(pid: str) -> bool:
    return bool(_PUZZLE_ID.match(pid))


def batch_body(solutions: list[Solution]) -> dict[str, Any]:
    if not 0 < len(solutions) <= MAX_BATCH:
        raise ValueError(f"a batch holds 1 to {MAX_BATCH} solutions")
    return {"solutions": [{"id": s.id, "win": s.win, "rated": s.rated} for s in solutions]}


@dataclass(frozen=True)
class ThemeResults:
    """One theme on the puzzle dashboard (FR-10.15): `GET /api/puzzle/dashboard/{days}`."""

    nb: int
    first_wins: int
    replay_wins: int
    performance: int | None
    rating_avg: int | None


@dataclass(frozen=True)
class Dashboard:
    days: int
    overall: ThemeResults | None
    themes: dict[str, ThemeResults]  # theme key -> results


DASHBOARD_DAYS = (7, 30, 90)  # what the Coach offers; Lichess accepts 1 to 90 (v0.10)


def _results(data: Any) -> ThemeResults | None:
    if not isinstance(data, dict):
        return None
    nb = _int(data.get("nb"))
    if nb is None or nb < 0:
        return None
    return ThemeResults(
        nb, max(0, _int(data.get("firstWins")) or 0), max(0, _int(data.get("replayWins")) or 0),
        _int(data.get("performance")), _int(data.get("puzzleRatingAvg")),
    )  # fmt: skip


def parse_dashboard(data: Any) -> Dashboard:
    """The PuzzleDashboard schema: `days`, `global` and `themes.<key>.results`. Unknown or malformed
    themes are skipped."""
    if not isinstance(data, dict):
        raise ValueError("unexpected dashboard response")
    themes: dict[str, ThemeResults] = {}
    raw = data.get("themes")
    for key, entry in raw.items() if isinstance(raw, dict) else []:
        res = _results(entry.get("results")) if isinstance(entry, dict) else None
        if isinstance(key, str) and _ANGLE.match(key) and res is not None:
            themes[key] = res
    return Dashboard(_int(data.get("days")) or 0, _results(data.get("global")), themes)


def _int(v: Any) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return round(v)
    return None


def _bool(v: Any) -> bool | None:
    return v if isinstance(v, bool) else None


def parse_account(data: Any) -> Account:
    if not isinstance(data, dict) or not isinstance(data.get("username"), str):
        raise ValueError("unexpected account response")
    username = data["username"]
    raw_id = data.get("id")
    uid: str = raw_id if isinstance(raw_id, str) else username
    perfs = data.get("perfs")
    puzzle = perfs.get("puzzle") if isinstance(perfs, dict) else None
    rating = provisional = None
    if isinstance(puzzle, dict):
        rating = _int(puzzle.get("rating"))
        provisional = _bool(puzzle.get("prov"))
    return Account(uid.lower(), username, rating, bool(provisional))


def parse_batch(data: Any) -> BatchResult:
    if not isinstance(data, dict):
        raise ValueError("unexpected batch response")
    rounds = []
    for r in data.get("rounds") or []:
        if isinstance(r, dict) and isinstance(r.get("id"), str):
            rounds.append(Round(r["id"], _bool(r.get("win")), _int(r.get("ratingDiff"))))
    raw = data.get("glicko")
    glicko: dict[str, Any] = raw if isinstance(raw, dict) else {}
    return BatchResult(rounds, _int(glicko.get("rating")), _bool(glicko.get("provisional")))


def parse_activity(obj: Any) -> ActivityEntry | None:
    if not isinstance(obj, dict):
        return None
    puzzle = obj.get("puzzle")
    pid = puzzle.get("id") if isinstance(puzzle, dict) else None
    date = _int(obj.get("date"))
    if not isinstance(pid, str) or not valid_puzzle_id(pid) or date is None:
        return None
    return ActivityEntry(pid, date, _bool(obj.get("win")))
