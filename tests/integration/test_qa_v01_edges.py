"""QA v0.1: edge cases beyond the builder's tests (sessions, attempts, re-import mid-session, app start).

Written by the independent QA pass (qa/QA-v0.1.md). Tests here that are marked xfail(strict=True)
document an open bug by its ID; they start passing (and then fail as XPASS) once it's fixed.
"""

from __future__ import annotations

import csv
import hashlib
import os
import random
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path

import chess

from weaksquare import config
from weaksquare.adapters.db.migrate import migrate
from weaksquare.adapters.db.repos.puzzle_import import PuzzleDbWriter
from weaksquare.core.clock import FixedClock
from weaksquare.core.csv_rows import header_index, parse_row
from weaksquare.core.filters import FilterSpec

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "puzzles_sample.csv"
ROOT = Path(__file__).resolve().parents[2]


def _solution(services, puzzle_id: str) -> list[str]:  # type: ignore[no-untyped-def]
    with services.db.session() as conn:
        return conn.execute("SELECT moves FROM pz.puzzles WHERE id = ?", (puzzle_id,)).fetchone()[0].split()


def _themes(services, puzzle_id: str) -> set[str]:  # type: ignore[no-untyped-def]
    with services.db.session() as conn:
        row = conn.execute("SELECT themes FROM pz.puzzles WHERE id = ?", (puzzle_id,)).fetchone()
    return set(row[0].split()) if row else set()


def _attempts(services) -> list[sqlite3.Row]:  # type: ignore[no-untyped-def]
    with services.db.session() as conn:
        return conn.execute("SELECT * FROM attempts ORDER BY id").fetchall()


def _wrong_move(view, solution: list[str]) -> str:  # type: ignore[no-untyped-def]
    board = chess.Board(view.fen)
    board.push_uci(view.opponent_move)
    expected = chess.Move.from_uci(solution[1])
    for m in board.legal_moves:
        if m == expected:
            continue
        after = board.copy()
        after.push(m)
        if not after.is_checkmate():
            return m.uci()
    raise AssertionError("no wrong move available")


# ---- FR-5.5: what an attempt records ----------------------------------------------------------


def test_attempt_fields_for_wrong_then_finished_line(services, clock: FixedClock) -> None:  # type: ignore[no-untyped-def]
    sid = services.sessions.start(FilterSpec(lengths=(2,), queue_size=1)).session_id
    view = services.sessions.next_puzzle(sid)
    sol = _solution(services, view.puzzle_id)
    clock.advance(seconds=7)
    r = services.sessions.submit_move(sid, _wrong_move(view, sol))
    assert r.feedback.kind == "wrong" and r.outcome is not None and not r.outcome.win
    # A second wrong move and then the whole line: nothing more is recorded.
    r2 = services.sessions.submit_move(sid, _wrong_move(view, sol))
    assert r2.feedback.kind == "wrong" and r2.outcome is None
    for uci in sol[1::2]:
        r3 = services.sessions.submit_move(sid, uci)
    assert r3.feedback.kind == "solved" and r3.outcome is None
    rows = _attempts(services)
    assert len(rows) == 1
    row = rows[0]
    assert (row["win"], row["first_move_correct"], row["line_correct"], row["help_used"]) == (0, 0, 0, "none")
    assert row["time_ms"] == 7000
    assert row["session_id"] == sid and row["puzzle_id"] == view.puzzle_id


def test_first_move_right_then_wrong_records_first_move_correct(services) -> None:  # type: ignore[no-untyped-def]
    sid = services.sessions.start(FilterSpec(lengths=(2,), queue_size=1)).session_id
    view = services.sessions.next_puzzle(sid)
    sol = _solution(services, view.puzzle_id)
    r = services.sessions.submit_move(sid, sol[1])
    assert r.feedback.kind == "correct" and r.feedback.reply == sol[2]
    board = chess.Board(view.fen)
    for uci in sol[:3]:
        board.push_uci(uci)
    expected = chess.Move.from_uci(sol[3])
    wrong = None
    for m in board.legal_moves:
        probe = board.copy()
        probe.push(m)
        if m != expected and not probe.is_checkmate():
            wrong = m.uci()
            break
    assert wrong is not None
    r = services.sessions.submit_move(sid, wrong)
    assert r.feedback.kind == "wrong"
    row = _attempts(services)[0]
    assert (row["win"], row["first_move_correct"], row["line_correct"]) == (0, 1, 0)


def test_moves_after_the_end_are_ignored(services) -> None:  # type: ignore[no-untyped-def]
    sid = services.sessions.start(FilterSpec(lengths=(1,), queue_size=2)).session_id
    view = services.sessions.next_puzzle(sid)
    sol = _solution(services, view.puzzle_id)
    assert services.sessions.submit_move(sid, sol[1]).outcome.win
    again = services.sessions.submit_move(sid, sol[1])
    assert again.feedback.finished and again.outcome is None
    assert len(_attempts(services)) == 1


def test_concurrent_wrong_moves_record_one_attempt(services) -> None:  # type: ignore[no-untyped-def]
    """pywebview runs each bridge call on its own thread: a double-submitted move must not double-count."""
    sid = services.sessions.start(FilterSpec(lengths=(1,), queue_size=1)).session_id
    view = services.sessions.next_puzzle(sid)
    wrong = _wrong_move(view, _solution(services, view.puzzle_id))
    barrier = threading.Barrier(8)
    errors: list[BaseException] = []

    def go() -> None:
        try:
            barrier.wait()
            services.sessions.submit_move(sid, wrong)
        except BaseException as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=go) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(_attempts(services)) == 1


# ---- FR-3.12: queue edges --------------------------------------------------------------------


def test_fixed_queue_larger_than_pool_ends_when_exhausted(services) -> None:  # type: ignore[no-untyped-def]
    spec = FilterSpec(themes=("mateIn1",), side="black", queue_size=500)
    pool = services.mixer.count(spec)
    assert 0 < pool < 500
    sid = services.sessions.start(spec).session_id
    seen = []
    while (v := services.sessions.next_puzzle(sid)) is not None:
        seen.append(v.puzzle_id)
        assert "mateIn1" in _themes(services, v.puzzle_id)
    assert len(seen) == len(set(seen)) == pool
    st = services.sessions.stats(sid)
    assert st.finished and st.played == pool  # every served puzzle was skipped = a loss


def test_rating_filter_at_exact_dataset_bounds(services) -> None:  # type: ignore[no-untyped-def]
    with services.db.session() as conn:
        lo, hi = conn.execute("SELECT MIN(rating), MAX(rating) FROM pz.puzzles").fetchone()
    everything = services.mixer.count(FilterSpec())
    assert services.mixer.count(FilterSpec(rating_min=lo, rating_max=hi)) == everything
    assert services.mixer.count(FilterSpec(rating_min=lo, rating_max=lo)) >= 1
    assert services.mixer.count(FilterSpec(rating_min=hi, rating_max=hi)) >= 1
    assert services.mixer.count(FilterSpec(rating_max=lo - 1)) == 0
    assert services.mixer.count(FilterSpec(rating_min=hi + 1)) == 0


# ---- FR-2.4 / FR-2.3: a re-import while a session is running ------------------------------


def _subset_db(out: Path, keep) -> Path:  # type: ignore[no-untyped-def]
    writer = PuzzleDbWriter(out, FixedClock())
    writer.open()
    with FIXTURE.open(encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        idx = header_index(next(reader))
        rows = [r for r in (parse_row(idx, row) for row in reader) if r is not None]
    writer.add([r for r in rows if keep(r)])
    writer.finish({"export_date": "2026-11-01", "source": "qa-subset"})
    return out


def test_reimport_mid_session_keeps_serving_matching_puzzles(services, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """Regression for v0.1-B2. User Guide: 'You can keep training while it runs; the new puzzles are
    switched in when it's finished.' After the swap, the running session must still serve only puzzles
    that match its filters, skip puzzles the new export dropped (FR-2.4), and never repeat one."""
    spec = FilterSpec(themes=("mateIn1",), match="any", queue_size=None)
    sid = services.sessions.start(spec).session_id
    first = services.sessions.next_puzzle(sid)
    assert first is not None
    # A newer export that dropped every third puzzle (so the dense keys shift).
    counter = {"i": 0}

    def keep(_row) -> bool:  # type: ignore[no-untyped-def]
        counter["i"] += 1
        return counter["i"] % 3 != 0

    new = _subset_db(tmp_path / "puzzles.new.db", keep)
    services.db.swap_puzzles_db(new)
    served = [first.puzzle_id]
    for _ in range(10):
        v = services.sessions.next_puzzle(sid)
        if v is None:
            break
        served.append(v.puzzle_id)
        assert "mateIn1" in _themes(services, v.puzzle_id), f"{v.puzzle_id} doesn't match the session's filters"
    assert len(served) == len(set(served))


# ---- NFR-3 at the app level: a newer user.db stops the app and stays untouched ---------------


def test_app_refuses_newer_schema_user_db_untouched(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    db = data / "user.db"
    migrate(db, config.MIGRATIONS_DIR / "user", FixedClock())
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO schema_version (version, applied_at) VALUES (999, 'future')")
    conn.commit()
    conn.close()
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    mtime = db.stat().st_mtime_ns
    env = dict(os.environ, WEAKSQUARE_DATA_DIR=str(data), WEAKSQUARE_NO_DIALOGS="1")
    env.pop("PYTEST_CURRENT_TEST", None)
    env.pop("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", None)
    proc = subprocess.run(
        [sys.executable, "-m", "weaksquare", "--dev"], cwd=ROOT, env=env, capture_output=True, timeout=60
    )
    assert proc.returncode == 1, proc.stderr
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before
    assert db.stat().st_mtime_ns == mtime
    assert not (data / "user.db-wal").exists()
    assert not any((data / "backups").glob("*")) if (data / "backups").exists() else True
    assert b"999" in proc.stderr or b"newer" in proc.stderr.lower()


# ---- SR-2: the bridge validates what JS sends -------------------------------------------------


def test_bridge_rejects_bad_arguments_without_crashing(services, paths, clock) -> None:  # type: ignore[no-untyped-def]
    from tests.helpers import build_api

    api = build_api(paths, clock)
    bad_calls = [
        lambda: api.count_matches("not a dict"),
        lambda: api.count_matches({"rating_min": 1600, "rating_max": 1200}),
        lambda: api.count_matches({"lengths": [5]}),
        lambda: api.count_matches({"themes": ["<script>"]}),
        lambda: api.count_matches({"queue_size": True}),
        lambda: api.start_session({"queue_size": 0}),
        lambda: api.start_session({"queue_size": 501}),
        lambda: api.next_puzzle("1"),
        lambda: api.submit_move(1, 5),
        lambda: api.open_folder("C:/Windows"),
        lambda: api.get_job(None),
        lambda: api.start_puzzle_import("x" * 2000),
        lambda: api.set_setting("mixer.filters", {"source": "my"}),
    ]
    for call in bad_calls:
        r = call()
        assert r["ok"] is False, r
        assert r["error"]["code"] != "internal", r
        assert "Traceback" not in r["error"]["message"]


def test_rng_used_for_queue_is_the_injected_one(services, paths, clock, fixture_puzzles_db) -> None:  # type: ignore[no-untyped-def]
    """Two services with the same seed and spec give the same endless queue (ARCHITECTURE §3 decision 15)."""
    from weaksquare.app import build_services
    from weaksquare.jobs.runner import JobRunner

    def ids(seed: int) -> list[str]:
        s = build_services(paths, clock, JobRunner(), random.Random(seed))
        sid = s.sessions.start(FilterSpec(queue_size=None)).session_id
        out = [s.sessions.next_puzzle(sid).puzzle_id for _ in range(60)]
        s.close()
        return out

    assert ids(5) == ids(5)


# ---- round 2 (2026-11-01): edges of the B2 fix ------------------------------------------------


def test_puzzle_in_progress_survives_a_swap_that_drops_it(services, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """The puzzle on the board is dropped by the new export: it can still be finished, then the
    session moves on to puzzles that exist and match."""
    spec = FilterSpec(themes=("mateIn1",), queue_size=None)
    sid = services.sessions.start(spec).session_id
    current = services.sessions.next_puzzle(sid)
    sol = _solution(services, current.puzzle_id)
    services.db.swap_puzzles_db(_subset_db(tmp_path / "a.db", lambda r: r.id != current.puzzle_id))
    r = services.sessions.submit_move(sid, sol[1])
    assert r.outcome is not None and r.outcome.win
    nxt = services.sessions.next_puzzle(sid)
    assert nxt is not None and nxt.puzzle_id != current.puzzle_id
    assert "mateIn1" in _themes(services, nxt.puzzle_id)
    rows = _attempts(services)
    assert [(x["puzzle_id"], x["win"]) for x in rows] == [(current.puzzle_id, 1)]


def test_two_swaps_in_one_session_never_repeat(services, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    spec = FilterSpec(themes=("mateIn1",), queue_size=None, min_popularity=None, min_plays=None)
    sid = services.sessions.start(spec).session_id
    served = [services.sessions.next_puzzle(sid).puzzle_id for _ in range(5)]
    services.db.swap_puzzles_db(_subset_db(tmp_path / "a.db", lambda r: sum(map(ord, r.id)) % 5 != 0))
    served += [services.sessions.next_puzzle(sid).puzzle_id for _ in range(5)]
    services.db.swap_puzzles_db(_subset_db(tmp_path / "b.db", lambda r: True))  # the full set again
    while (v := services.sessions.next_puzzle(sid)) is not None:
        served.append(v.puzzle_id)
        assert "mateIn1" in _themes(services, v.puzzle_id)
    assert len(served) == len(set(served))
    assert set(served) == {r[0] for r in _ids_with(services, "mateIn1")}


def _ids_with(services, theme: str) -> list[tuple[str]]:  # type: ignore[no-untyped-def]
    with services.db.session() as conn:
        return conn.execute("SELECT id FROM pz.puzzles WHERE ' ' || themes || ' ' LIKE ?", (f"% {theme} %",)).fetchall()


def test_swap_to_an_export_with_no_matches_ends_the_session(services, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    spec = FilterSpec(themes=("mateIn1",), queue_size=None, min_popularity=None, min_plays=None)
    sid = services.sessions.start(spec).session_id
    assert services.sessions.next_puzzle(sid) is not None
    services.db.swap_puzzles_db(_subset_db(tmp_path / "a.db", lambda r: "mateIn1" not in r.themes))
    assert services.sessions.next_puzzle(sid) is None
    assert services.sessions.stats(sid).finished
