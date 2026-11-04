"""v0.3 Done-when: the rating display through the bridge, against the fake Lichess client (FR-6.11a–d).

Covers a positive change, a negative change, offline then synced, Rated off, already played, a 0 or
missing change, the session total, and that the header rating only ever comes from Lichess."""

from __future__ import annotations

import pytest

from tests.fakes.lichess import FAKE_TOKEN, FakeLichess, network_error
from tests.helpers import build_api
from weaksquare.bridge.api import Api

OPEN = {"min_popularity": None, "min_plays": None, "exclude_solved_here": False, "exclude_played_on_lichess": False}


@pytest.fixture
def setup(paths, clock, fixture_puzzles_db):  # type: ignore[no-untyped-def]
    import shutil

    from weaksquare import config
    from weaksquare.adapters.db.migrate import migrate

    shutil.copyfile(fixture_puzzles_db, paths.puzzles_db)
    migrate(paths.user_db, config.MIGRATIONS_DIR / "user", clock)
    lichess = FakeLichess()
    api = build_api(paths, clock, lichess=lichess)
    yield api, lichess
    api._sync._d.runner.cancel_all(2)


def sign_in(api: Api) -> None:
    api._account._d.secrets.set("lichess", FAKE_TOKEN)
    job = api._account.check()
    api._account._d.runner.wait(job, 5)
    settle(api)


def settle(api: Api) -> None:
    runner = api._sync._d.runner
    for _ in range(5):
        jobs = runner.active()
        if not jobs:
            return
        for j in jobs:
            runner.wait(j.id, 5)


def data(r: dict):  # type: ignore[no-untyped-def]
    assert r["ok"], r
    return r["data"]


def moves_of(api: Api, puzzle_id: str) -> list[str]:
    with api._sessions._puzzles._lichess._db.session() as c:
        return c.execute("SELECT moves FROM pz.puzzles WHERE id = ?", (puzzle_id,)).fetchone()[0].split()


def solve(api: Api, sid: int) -> dict:
    """Play the current puzzle's solution; returns the outcome."""
    view = data(api.next_puzzle(sid))
    moves = moves_of(api, view["puzzle_id"])
    fb = None
    for uci in moves[1::2]:
        fb = data(api.submit_move(sid, uci))
    assert fb is not None and fb["outcome"]["win"]
    return fb["outcome"]


def fail(api: Api, sid: int) -> dict:
    view = data(api.next_puzzle(sid))
    moves = moves_of(api, view["puzzle_id"])
    wrong = next(m for m in ("a2a3", "h2h3", "a7a6", "h7h6", "b2b3", "g7g6") if m != moves[1])
    fb = data(api.submit_move(sid, wrong))
    if fb["kind"] == "illegal":  # pick any legal non-solution move instead
        import chess

        board = chess.Board(view["fen"])
        board.push_uci(view["opponent_move"])
        wrong = next(m.uci() for m in board.legal_moves if m.uci() != moves[1])
        fb = data(api.submit_move(sid, wrong))
    assert fb["outcome"] and not fb["outcome"]["win"]
    return fb["outcome"]


def ratings(api: Api, *ids: int) -> dict[int, dict]:
    return {r["attempt_id"]: r for r in data(api.get_attempt_ratings(list(ids)))}


def test_positive_and_negative_changes_and_the_session_total(setup) -> None:  # type: ignore[no-untyped-def]
    api, lichess = setup
    sign_in(api)
    assert data(api.get_account_status())["rating"] == 1834
    sid = data(api.start_session(OPEN, True))["session_id"]
    won = solve(api, sid)
    assert won["lichess"]["status"] in ("syncing", "done")  # Syncing… until Lichess replies
    settle(api)
    lost = fail(api, sid)
    settle(api)
    r = ratings(api, won["attempt_id"], lost["attempt_id"])
    assert r[won["attempt_id"]] == {"attempt_id": won["attempt_id"], "status": "done", "diff": 8}
    assert r[lost["attempt_id"]] == {"attempt_id": lost["attempt_id"], "status": "done", "diff": -12}
    assert data(api.get_session_stats(sid))["rating_change"] == -4  # FR-6.11c
    # The header follows Lichess's glicko from each response: 1834 + 8 - 12 (the fake's own arithmetic).
    assert data(api.get_account_status())["rating"] == lichess.rating == 1830
    history = data(api.get_rating_history())
    assert [p["rating"] for p in history["points"]] == [1842, 1830]
    assert history["sessions"][0]["change"] == -4


def test_offline_then_synced(setup) -> None:  # type: ignore[no-untyped-def]
    api, lichess = setup
    sign_in(api)
    lichess.batch_errors = [network_error()]
    sid = data(api.start_session(OPEN, True))["session_id"]
    won = solve(api, sid)
    settle(api)
    assert ratings(api, won["attempt_id"])[won["attempt_id"]]["status"] == "offline"  # Will sync later
    assert data(api.get_sync_status())["pending"] == 1
    assert data(api.get_sync_status())["state"] == "offline"
    assert data(api.get_session_stats(sid))["rating_change"] is None
    # Reconnect: the scheduled retry drains the queue and the number fills in.
    scheduler = api._sync._d.scheduler
    scheduler.run_next()
    settle(api)
    assert ratings(api, won["attempt_id"])[won["attempt_id"]] == {
        "attempt_id": won["attempt_id"],
        "status": "done",
        "diff": 8,
    }
    assert data(api.get_sync_status())["pending"] == 0
    assert data(api.get_session_stats(sid))["rating_change"] == 8


def test_rated_off(setup) -> None:  # type: ignore[no-untyped-def]
    api, lichess = setup
    sign_in(api)
    sid = data(api.start_session(OPEN, False))["session_id"]
    won = solve(api, sid)
    assert won["lichess"] == {"attempt_id": won["attempt_id"], "status": "unrated", "diff": None}
    settle(api)
    assert lichess.batch_calls[0].solutions[0].rated is False
    assert ratings(api, won["attempt_id"])[won["attempt_id"]]["status"] == "unrated"
    assert data(api.get_account_status())["rating"] == 1834  # unchanged: Lichess returned no change


def test_already_played(setup) -> None:  # type: ignore[no-untyped-def]
    api, lichess = setup
    sign_in(api)
    sid = data(api.start_session(OPEN, True))["session_id"]
    view = data(api.next_puzzle(sid))
    api._history._repo.add([(view["puzzle_id"], None, True)])
    lichess.diffs[view["puzzle_id"]] = 0  # Lichess doesn't rate a replay
    # The badge shows on the next puzzle you've played; the already-played state is decided at record time.
    moves = moves_of(api, view["puzzle_id"])
    fb = None
    for uci in moves[1::2]:
        fb = data(api.submit_move(sid, uci))
    assert fb["outcome"]["lichess"]["status"] == "already_played"
    settle(api)
    assert ratings(api, fb["outcome"]["attempt_id"])[fb["outcome"]["attempt_id"]]["status"] == "already_played"
    # A later puzzle that's in your history comes with the badge.
    sid2 = data(api.start_session({**OPEN, "queue_size": 500}, True))["session_id"]
    seen = None
    for _ in range(200):
        v = data(api.next_puzzle(sid2))
        if v is None:
            break
        if v["puzzle_id"] == view["puzzle_id"]:
            seen = v
            break
    assert seen is not None and seen["already_played"] is True


@pytest.mark.parametrize("diff", [0, None])
def test_zero_or_missing_change_is_not_rated(setup, diff) -> None:  # type: ignore[no-untyped-def]
    api, lichess = setup
    sign_in(api)
    sid = data(api.start_session(OPEN, True))["session_id"]
    view_id = None

    def before(call):  # type: ignore[no-untyped-def]
        for s in call.solutions:
            lichess.diffs[s.id] = diff

    lichess.on_batch = before
    won = solve(api, sid)
    view_id = won["attempt_id"]
    settle(api)
    r = ratings(api, view_id)[view_id]
    assert r == {"attempt_id": view_id, "status": "not_rated", "diff": None}
    assert data(api.get_session_stats(sid))["rating_change"] in (0, None)


def test_header_rating_only_from_lichess(setup) -> None:  # type: ignore[no-untyped-def]
    """FR-6.11a: never computed locally. Signed out: no rating; signed in: Lichess's; after each
    sync: the response's glicko; with no response (offline): unchanged."""
    api, lichess = setup
    assert data(api.get_account_status())["rating"] is None
    sid = data(api.start_session(OPEN, True))["session_id"]
    solve(api, sid)  # signed out: queued, nothing shown
    assert data(api.get_account_status())["rating"] is None
    lichess.rating = 2001  # whatever Lichess says is what's shown
    sign_in(api)  # the queued solve syncs now
    assert data(api.get_account_status())["rating"] == lichess.rating == 2009
    lichess.batch_errors = [network_error()]
    solve(api, sid)
    settle(api)
    assert data(api.get_account_status())["rating"] == 2009  # no response, no change
    lichess.rating = 1500  # Lichess recalculated: the next response wins, no local arithmetic
    api._sync._d.scheduler.run_next()
    settle(api)
    assert data(api.get_account_status())["rating"] == 1508


def test_no_token_ever_crosses_the_bridge(setup) -> None:  # type: ignore[no-untyped-def]
    api, _ = setup
    sign_in(api)
    sid = data(api.start_session(OPEN, True))["session_id"]
    out = [api.get_account_status(), api.get_sync_status(), api.get_rating_history(), api.get_settings()]
    out.append(api.submit_move(sid, "a1a1"))
    assert all(FAKE_TOKEN not in repr(x) for x in out)


def test_attempt_ratings_validates_ids(setup) -> None:  # type: ignore[no-untyped-def]
    api, _ = setup
    assert api.get_attempt_ratings([1, "x"])["error"]["code"] == "invalid_argument"
    assert api.get_attempt_ratings(list(range(1, 300)))["error"]["code"] == "invalid_argument"
    assert api.get_attempt_ratings([True])["error"]["code"] == "invalid_argument"
