"""v0.5 timings on the full puzzle DB: the depth-ladder count at a level (FR-4.5) and the Spaced
repetition status with a realistic history of misses (FR-4.6). The live count target is 500 ms."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from weaksquare import config
from weaksquare.adapters.db.connection import Database
from weaksquare.adapters.db.migrate import migrate
from weaksquare.adapters.db.repos.puzzles import LichessDbSource
from weaksquare.adapters.db.repos.user_data import AttemptsRepo, ModeFields, SessionsRepo
from weaksquare.core.clock import FixedClock
from weaksquare.core.filters import FilterSpec
from weaksquare.core.modes.base import AttemptResult
from weaksquare.core.puzzle import PuzzleRef
from weaksquare.services.session import SessionService

pytestmark = pytest.mark.fulldb
LOSS = AttemptResult(win=False, first_move_correct=False, line_correct=False, help_used="none", time_ms=1)
WIN = AttemptResult(win=True, first_move_correct=True, line_correct=True, help_used="none", time_ms=1)


def _service(source: LichessDbSource, clock: FixedClock) -> SessionService:
    import random

    return SessionService(source, AttemptsRepo(source._db), SessionsRepo(source._db), clock, random.Random(5),
                          mode_fields=ModeFields)  # fmt: skip


def test_ladder_count_at_a_level_is_fast(full_source: LichessDbSource) -> None:
    service = _service(full_source, FixedClock())
    spec = FilterSpec(themes=("fork",), order="depth_ladder")
    t0 = time.perf_counter()
    level = service.pool_spec(spec)
    n = full_source.count(level)
    elapsed = time.perf_counter() - t0
    assert level.lengths == (2,) and n > 1000
    assert elapsed < 0.5, f"ladder count took {elapsed:.3f}s"


def test_srs_status_with_two_thousand_misses_is_fast(fulldb_path: Path, tmp_path: Path) -> None:
    """On its own user.db: the session-wide one is shared with the count oracles, which assume no history."""
    clock = FixedClock()
    migrate(tmp_path / "user.db", config.MIGRATIONS_DIR / "user", clock)
    full_source = LichessDbSource(Database(tmp_path / "user.db", fulldb_path))
    attempts = AttemptsRepo(full_source._db)
    sid = SessionsRepo(full_source._db).create("2026-01-01T00:00:00+00:00", "standard", {}, None)
    with full_source._db.session() as conn:
        ids = [r[0] for r in conn.execute("SELECT id FROM pz.puzzles LIMIT 2000")]
    for i, pid in enumerate(ids):
        attempts.append(PuzzleRef("lichess", pid), sid, "standard", "t", "2026-01-01T10:00:00+00:00", LOSS)
        if i % 3 == 0:
            attempts.append(PuzzleRef("lichess", pid), sid, "spaced_repetition", "t", "2026-01-02T10:00:00+00:00", WIN)
    clock.advance(days=2)
    service = _service(full_source, clock)
    t0 = time.perf_counter()
    status = service.srs_status()
    elapsed = time.perf_counter() - t0
    assert status.due == 2000 - len(ids[::3]) and status.scheduled == 2000
    assert elapsed < 0.5, f"SRS status took {elapsed:.3f}s"
    full_source._db.close_all()
