"""QA v0.6 (qa/QA-v0.6.md): timings on the full puzzle DB with a realistic history that has mistake reasons. Every
Stats row, the session and all-time tallies and the history-filter counts now look up the latest reason per
attempt (LATEST_REASON); they must stay within the 500 ms live-count target. Also a Name-the-idea queue."""

from __future__ import annotations

import random
import time
from pathlib import Path

import pytest

from weaksquare import config
from weaksquare.adapters.db.connection import Database
from weaksquare.adapters.db.migrate import migrate
from weaksquare.adapters.db.repos.puzzles import LichessDbSource
from weaksquare.adapters.db.repos.stats import StatsRepo
from weaksquare.adapters.db.repos.user_data import AttemptsRepo, MistakeReasonsRepo, ModeFields, SessionsRepo
from weaksquare.core.clock import FixedClock
from weaksquare.core.filters import FilterSpec
from weaksquare.core.modes.base import AttemptResult
from weaksquare.core.puzzle import PuzzleRef
from weaksquare.core.stats import build_report, reason_report
from weaksquare.services.session import SessionService

pytestmark = pytest.mark.fulldb
LOSS = AttemptResult(win=False, first_move_correct=False, line_correct=False, help_used="none", time_ms=1)
WIN = AttemptResult(win=True, first_move_correct=True, line_correct=True, help_used="none", time_ms=1)
REASONS = ("didntLook", "missedResource", "miscalculated", "unknownPattern", "rushed", "misclick")


@pytest.fixture
def history(fulldb_path: Path, tmp_path: Path):  # type: ignore[no-untyped-def]
    clock = FixedClock()
    migrate(tmp_path / "user.db", config.MIGRATIONS_DIR / "user", clock)
    source = LichessDbSource(Database(tmp_path / "user.db", fulldb_path))
    attempts = AttemptsRepo(source._db)
    reasons = MistakeReasonsRepo(source._db)
    sid = SessionsRepo(source._db).create("2026-01-01T00:00:00+00:00", "standard", {}, None)
    with source._db.session() as conn:
        ids = [r[0] for r in conn.execute("SELECT id FROM pz.puzzles LIMIT 5000")]
    rnd = random.Random(7)
    modes = ("standard", "commit_line", "name_idea", "danger_spotting", "spaced_repetition")
    for pid in ids:
        mode = rnd.choice(modes)
        lost = rnd.random() < 0.5
        aid = attempts.append(PuzzleRef("lichess", pid), sid, mode, "t", "2026-01-01T10:00:00+00:00",
                              LOSS if lost else WIN, extra=ModeFields())  # fmt: skip
        if lost:
            for _ in range(rnd.randint(0, 2)):  # 0–2 reasons each: changed minds append rows
                reasons.add("danger" if mode == "danger_spotting" else "puzzle", str(aid), rnd.choice(REASONS),
                            None, None, "2026-01-01T10:00:01+00:00")  # fmt: skip
    yield source, attempts, sid, clock
    source._db.close_all()


def test_stats_with_reasons_on_five_thousand_attempts_is_fast(history) -> None:  # type: ignore[no-untyped-def]
    source, attempts, sid, clock = history
    t0 = time.perf_counter()
    rows = StatsRepo(source._db).attempt_rows()
    report = build_report(rows, lambda k: k)
    reasons = reason_report(rows, clock.local_date)
    elapsed = time.perf_counter() - t0
    assert len(rows) == 5000 and report.misclicks > 0 and reasons.tagged > 0
    print(f"\nQA-OBS stats rows+report+reasons (5000 attempts): {elapsed:.3f}s")
    assert elapsed < 0.5, f"{elapsed:.3f}s"
    t0 = time.perf_counter()
    s, a = attempts.session_tally(sid), attempts.all_time_tally()
    elapsed = time.perf_counter() - t0
    print(f"QA-OBS session + all-time tally: {elapsed:.3f}s")
    assert s.misclicks > 0 and a.misclicks == s.misclicks
    assert elapsed < 0.5


def test_history_filter_counts_with_danger_rows_are_fast(history) -> None:  # type: ignore[no-untyped-def]
    source, *_ = history
    for spec in (FilterSpec(), FilterSpec(only_my_misses=True), FilterSpec(themes=("fork",))):
        t0 = time.perf_counter()
        n = source.count(spec)
        elapsed = time.perf_counter() - t0
        print(f"\nQA-OBS count only_my_misses={spec.only_my_misses} themes={spec.themes}: {n} in {elapsed:.3f}s")
        assert elapsed < 0.5, f"{elapsed:.3f}s"


def test_name_the_idea_session_starts_and_serves_fast(full_source: LichessDbSource) -> None:
    service = SessionService(full_source, AttemptsRepo(full_source._db), SessionsRepo(full_source._db), FixedClock(),
                             random.Random(3), mode_fields=ModeFields)  # fmt: skip
    for spec in (FilterSpec(queue_size=50), FilterSpec(themes=("fork",), queue_size=50)):
        t0 = time.perf_counter()
        info = service.start(spec, mode="name_idea")
        view = service.next_puzzle(info.session_id)
        elapsed = time.perf_counter() - t0
        assert view is not None and view.mode == "name_idea"
        print(f"\nQA-OBS name_idea start+first puzzle {spec.themes}: {elapsed:.3f}s")
        assert elapsed < 0.5, f"{elapsed:.3f}s"
