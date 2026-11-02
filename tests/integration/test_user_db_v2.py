"""user.db schema v2 (v0.2): attempts record the puzzle's rating; older attempts are backfilled."""

from __future__ import annotations

from weaksquare.adapters.db.repos.user_data import AttemptsRepo
from weaksquare.core.filters import FilterSpec
from weaksquare.core.modes.base import AttemptResult
from weaksquare.core.puzzle import PuzzleRef


def test_attempt_records_the_puzzle_rating(services) -> None:  # type: ignore[no-untyped-def]
    sid = services.sessions.start(FilterSpec(queue_size=2, exclude_solved_here=False)).session_id
    view = services.sessions.next_puzzle(sid)
    services.sessions.next_puzzle(sid)  # skip: recorded as a loss
    with services.db.session() as conn:
        row = conn.execute("SELECT puzzle_id, puzzle_rating FROM attempts").fetchone()
    assert row["puzzle_id"] == view.puzzle_id and row["puzzle_rating"] == view.rating


def test_backfill_fills_old_attempts_where_the_puzzle_exists(services) -> None:  # type: ignore[no-untyped-def]
    repo = AttemptsRepo(services.db)
    result = AttemptResult(win=True, first_move_correct=True, line_correct=True, help_used="none", time_ms=1)
    with services.db.session() as conn:
        known = conn.execute("SELECT id, rating FROM pz.puzzles LIMIT 1").fetchone()
        sid = conn.execute(
            "INSERT INTO sessions (started_at, mode, filters_json) VALUES ('2026-10-01', 'standard', '{}')"
        ).lastrowid
    # As v0.1 recorded them: no rating.
    repo.append(PuzzleRef("lichess", known["id"]), sid, "standard", "t", "t", result)
    repo.append(PuzzleRef("lichess", "GONE1"), sid, "standard", "t", "t", result)  # dropped by a re-import

    assert repo.backfill_puzzle_ratings() == 1
    assert repo.backfill_puzzle_ratings() == 0  # idempotent
    with services.db.session() as conn:
        rows = dict(conn.execute("SELECT puzzle_id, puzzle_rating FROM attempts").fetchall())
    assert rows == {known["id"]: known["rating"], "GONE1": None}


def test_stats_report_from_real_attempts(services) -> None:  # type: ignore[no-untyped-def]
    """Attempts joined to puzzles.db, with a dropped puzzle counted as missing (FR-2.4)."""
    repo = AttemptsRepo(services.db)
    win = AttemptResult(win=True, first_move_correct=True, line_correct=True, help_used="none", time_ms=1)
    loss = AttemptResult(win=False, first_move_correct=True, line_correct=False, help_used="none", time_ms=1)
    with services.db.session() as conn:
        p = conn.execute(
            "SELECT id, rating, themes, length FROM pz.puzzles WHERE themes LIKE '%fork%' LIMIT 1"
        ).fetchone()
        sid = conn.execute(
            "INSERT INTO sessions (started_at, mode, filters_json) VALUES ('2026-10-01', 'standard', '{}')"
        ).lastrowid
    repo.append(PuzzleRef("lichess", p["id"]), sid, "standard", "t", "t", win)  # v0.1-style: no rating yet
    repo.append(PuzzleRef("lichess", p["id"]), sid, "standard", "t", "t", loss, p["rating"])
    repo.append(PuzzleRef("lichess", "GONE1"), sid, "standard", "t", "t", loss, 1500)

    r = services.stats.report()
    assert (r.overall.attempts, r.overall.solved, r.missing) == (3, 1, 1)
    assert r.overall.line_wrong_rate == 2 / 3
    fork = next(t for t in r.by_theme if t.key == "fork")
    assert fork.attempts == 2 and fork.label == "Fork"
    assert sum(t.attempts for t in r.by_rating) == 3  # the backfill gave the first attempt its rating
    assert all(t.key != "unknown" for t in r.by_rating)
