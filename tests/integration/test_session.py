"""Sessions end to end on the fixture DB: queue, moves, attempts in user.db, session stats."""

from __future__ import annotations

import sqlite3

import pytest

from weaksquare.core.errors import NotFoundError, ValidationError
from weaksquare.core.filters import FilterSpec


def attempts(services) -> list[sqlite3.Row]:  # type: ignore[no-untyped-def]
    with services.db.session() as conn:
        return conn.execute("SELECT * FROM attempts ORDER BY id").fetchall()


def solution(services, puzzle_id: str) -> list[str]:  # type: ignore[no-untyped-def]
    with services.db.session() as conn:
        return conn.execute("SELECT moves FROM pz.puzzles WHERE id = ?", (puzzle_id,)).fetchone()[0].split()


def solve(services, sid: int, view) -> object:  # type: ignore[no-untyped-def]
    moves = solution(services, view.puzzle_id)
    result = None
    for uci in moves[1::2]:
        result = services.sessions.submit_move(sid, uci)
    return result


def test_solve_fail_and_skip_are_recorded(services) -> None:  # type: ignore[no-untyped-def]
    info = services.sessions.start(FilterSpec(queue_size=3))
    sid = info.session_id

    first = services.sessions.next_puzzle(sid)
    assert first is not None and first.number == 1
    r = solve(services, sid, first)
    assert r.feedback.kind == "solved" and r.outcome is not None and r.outcome.win
    assert r.outcome.themes  # revealed only now

    second = services.sessions.next_puzzle(sid)
    moves = solution(services, second.puzzle_id)
    wrong = services.sessions.submit_move(sid, "a1a1")  # garbage: illegal, nothing recorded
    assert wrong.feedback.kind == "illegal" and wrong.outcome is None
    # Find a legal wrong move: any legal move that isn't the solution and doesn't mate.
    import chess

    board = chess.Board(second.fen)
    board.push_uci(second.opponent_move)
    bad = next(m.uci() for m in board.legal_moves if m.uci() != moves[1] and not board.gives_check(m))
    lost = services.sessions.submit_move(sid, bad)
    assert lost.feedback.kind == "wrong" and lost.outcome is not None and not lost.outcome.win

    third = services.sessions.next_puzzle(sid)
    assert third is not None and third.number == 3
    assert services.sessions.next_puzzle(sid) is None  # queue of 3 done; the third was skipped = loss

    rows = attempts(services)
    assert [r["win"] for r in rows] == [1, 0, 0]
    assert [r["puzzle_id"] for r in rows] == [first.puzzle_id, second.puzzle_id, third.puzzle_id]
    assert all(r["puzzle_source"] == "lichess" and r["mode"] == "standard" for r in rows)
    stats = services.sessions.stats(sid)
    assert (stats.solved, stats.failed, stats.played, stats.finished) == (1, 2, 3, True)
    assert stats.accuracy == pytest.approx(1 / 3)
    assert (stats.all_time_solved, stats.all_time_failed) == (1, 2)


def test_puzzles_follow_the_filters_and_never_repeat(services) -> None:  # type: ignore[no-untyped-def]
    spec = FilterSpec(themes=("mateIn1",), side="white", queue_size=None)
    sid = services.sessions.start(spec).session_id
    seen = []
    while (view := services.sessions.next_puzzle(sid)) is not None:
        seen.append(view.puzzle_id)
        assert view.player_color == "white"
        assert len(solution(services, view.puzzle_id)) == 2
    assert len(seen) == len(set(seen)) == services.mixer.count(spec)
    assert services.sessions.stats(sid).finished


def test_endless_session_refills(services) -> None:  # type: ignore[no-untyped-def]
    sid = services.sessions.start(FilterSpec(queue_size=None)).session_id
    ids = [services.sessions.next_puzzle(sid).puzzle_id for _ in range(120)]  # more than one refill of 50
    assert len(set(ids)) == 120


def test_same_seed_same_queue(services, paths, clock, fixture_puzzles_db) -> None:  # type: ignore[no-untyped-def]
    import random

    from weaksquare.app import build_services
    from weaksquare.jobs.runner import JobRunner

    def queue(seed: int) -> list[str]:
        s = build_services(paths, clock, JobRunner(), random.Random(seed))
        sid = s.sessions.start(FilterSpec(queue_size=10)).session_id
        out = [s.sessions.next_puzzle(sid).puzzle_id for _ in range(10)]
        s.close()
        return out

    assert queue(42) == queue(42)
    assert queue(42) != queue(43)


def test_no_matches_and_bad_sessions(services) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValidationError, match="No puzzles match"):
        services.sessions.start(FilterSpec(rating_min=3999))
    with pytest.raises(NotFoundError):
        services.sessions.next_puzzle(999)
    sid = services.sessions.start(FilterSpec()).session_id
    with pytest.raises(ValidationError):
        services.sessions.submit_move(sid, "e2e4")  # no puzzle served yet


def test_bridge_round_trip(services, paths, clock) -> None:  # type: ignore[no-untyped-def]
    from tests.helpers import build_api

    api = build_api(paths, clock)
    spec = {"themes": ["mateIn1"], "match": "any", "queue_size": 2}
    assert api.count_matches(spec)["data"] > 0
    assert api.count_matches({"themes": 5})["error"]["code"] == "invalid_argument"
    assert api.count_matches({"order": "easy_to_hard"})["error"]["code"] == "unsupported_in_this_version"
    sid = api.start_session(spec)["data"]["session_id"]
    view = api.next_puzzle(sid)["data"]
    assert "themes" not in view  # FR-3.14
    fb = api.submit_move(sid, solution(services, view["puzzle_id"])[1])["data"]
    assert fb["kind"] == "solved" and fb["outcome"]["themes"][0]["name"]
    assert fb["outcome"]["puzzle_url"].endswith(view["puzzle_id"])
    stats = api.get_session_stats(sid)["data"]
    assert stats["solved"] == 1 and stats["accuracy"] == 1.0
    catalog = api.get_theme_catalog()["data"]
    assert any(g["name"] == "Motifs" for g in catalog)
    assert api.set_setting("mixer.filters", spec)["ok"]
    assert api.get_settings()["data"]["last_filters"]["themes"] == ["mateIn1"]
    assert api.set_setting("other", 1)["error"]["code"] == "invalid_argument"
