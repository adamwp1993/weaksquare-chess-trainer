"""QA v0.8 (independent): edge cases of the game library, analysis, Review, Retry and My puzzles through the
wired services. Tests marked xfail(strict=True) document an open bug by its ID (qa/QA-v0.8.md)."""

from __future__ import annotations

import chess
import pytest

from tests.fakes.engine import FakeEngine, plant_managed_install
from tests.fakes.games import CC_BASE
from tests.integration.test_game_library import Rig, _sync, rig  # noqa: F401  (the fixture)
from tests.integration.test_review import ANALYSES, MOVES, SCHOLAR
from weaksquare.adapters.chesscom import ChesscomGone
from weaksquare.adapters.db.repos.custom_puzzles import CustomPuzzlesRepo, RetryRepo
from weaksquare.adapters.db.repos.game_analysis import GameAnalysisRepo
from weaksquare.adapters.http import RateLimited
from weaksquare.core.engine import EngineLine
from weaksquare.core.filters import FilterSpec
from weaksquare.core.game_review import grade_game
from weaksquare.core.games import LibraryFilter
from weaksquare.core.puzzle import NewCustomPuzzle

LOYD = (
    '[White "player_a"]\n[Black "opponent_b"]\n[Result "1/2-1/2"]\n\n'
    "1. e3 a5 2. Qh5 Ra6 3. Qxa5 h5 4. h4 Rah6 5. Qxc7 f6 6. Qxd7+ Kf7 7. Qxb7 Qd3 8. Qxb8 Qh7 "
    "9. Qxc8 Kg6 10. Qe6 1/2-1/2\n"
)
MINE = FilterSpec(source="my", exclude_solved_here=False, exclude_played_on_lichess=False)


@pytest.fixture(autouse=True)
def _reset() -> None:
    FakeEngine.instances.clear()


def _wait(services, job: str | None) -> str:  # type: ignore[no-untyped-def]
    assert job is not None
    st = services.analysis._runner.wait(job, 30)
    assert st is not None
    return st.state


def _analyzed_scholar(services) -> int:  # type: ignore[no-untyped-def]
    gid = services.games.import_pgn(SCHOLAR).game_id
    services.games.set_user_color(gid, "black")
    rows = grade_game(chess.STARTING_FEN, MOVES, ANALYSES)
    GameAnalysisRepo(services.db).replace(gid, rows, "analyzed", 0.3, "Stockfish 19")
    return int(gid)


# ---------------------------------------------------------------- analysis


def test_qa_a_stalemated_game_is_analyzed_and_its_final_position_never_searched(services, paths) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    gid = services.games.import_pgn(LOYD).game_id
    assert _wait(services, services.analysis.queue([gid])) == "done"
    rows = GameAnalysisRepo(services.db).rows(gid)
    assert len(rows) == 19 and rows[-1].eval_after.cp == 0 and rows[-1].eval_after.mate is None
    bg = next(e for e in FakeEngine.instances if e.calls)
    assert len(bg.calls) == 19  # 19 positions before a move; the stalemate needs no search
    assert services.review.review(gid).analyzed


def test_qa_a_400_ply_game_imports_and_analyzes_completely(services, paths) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    cycle = ["Nf3", "Nf6", "Ng1", "Ng8"] * 100
    body = " ".join(f"{i // 2 + 1}. {cycle[i]} {cycle[i + 1]}" for i in range(0, 400, 2))
    gid = services.games.import_pgn(f'[White "player_a"]\n[Black "opponent_b"]\n\n{body} *\n').game_id
    assert _wait(services, services.analysis.queue([gid])) == "done"
    assert len(GameAnalysisRepo(services.db).rows(gid)) == 400
    assert len(services.review.review(gid).moves) == 400


@pytest.mark.xfail(strict=True, reason="v0.8-B1: new grading thresholds never reach games already analyzed")
def test_qa_changed_thresholds_regrade_or_offer_analyze_again(services, paths) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)  # "Stockfish 19", the engine the stored analysis names
    gid = services.games.import_pgn(SCHOLAR).game_id
    services.games.set_user_color(gid, "black")
    analyses = list(ANALYSES)
    analyses[3] = [EngineLine(-60, None, ("g8f6",))]  # 2...Nc6 wasn't best: Black +0.6 → +0.5, 10 cp lost
    rows = grade_game(chess.STARTING_FEN, MOVES, analyses)
    GameAnalysisRepo(services.db).replace(gid, rows, "analyzed", 0.3, "Stockfish 19")
    before = services.review.review(gid)
    assert before.moves[3].classification == "good" and before.current
    services.analysis.set_settings(thresholds={"inaccuracy": 5, "mistake": 8, "blunder": 9})
    v = services.review.review(gid)
    # Expected: the review uses the new thresholds (the stored evals are enough), or at least says the
    # analysis isn't current, so Review shows **Analyze again**. Actual: still "good", and current.
    assert v.moves[3].classification != "good" or not v.current


# ---------------------------------------------------------------- Retry and Save


@pytest.mark.xfail(strict=True, reason="v0.8-B3: without Stockfish an unchecked Retry move is counted as a miss")
def test_qa_an_unchecked_retry_is_not_counted_as_a_miss(services) -> None:  # type: ignore[no-untyped-def]
    gid = _analyzed_scholar(services)  # no Stockfish installed in this test
    r = services.review.retry_move(gid, 5, "h7h6")  # not in the stored lines, so it can't be checked
    assert not r.engine_checked and not r.found
    _found, tried = RetryRepo(services.db).totals()
    assert tried == 0  # Expected: "Retry: found N of M" leaves out moves nobody could grade


def test_qa_review_both_sides_lists_moments_and_retries_for_each_color(services) -> None:  # type: ignore[no-untyped-def]
    gid = _analyzed_scholar(services)
    services.games.set_user_color(gid, "both")
    v = services.review.review(gid)
    mine = {m.ply for m in v.moves if m.classification in ("inaccuracy", "mistake", "blunder")}
    assert set(v.key_moments) <= mine and 5 in v.key_moments
    assert services.review.retry_move(gid, 5, "d8e7").found  # Black's mistake can be retried


def test_qa_save_as_puzzle_for_black_is_served_with_black_to_move(services) -> None:  # type: ignore[no-untyped-def]
    gid = _analyzed_scholar(services)
    pid, created = services.review.save_as_puzzle(gid, 5)
    assert created
    sid = services.sessions.start(MINE).session_id
    view = services.sessions.next_puzzle(sid)
    assert (view.source, view.puzzle_id, view.player_color, view.opponent_move) == ("my", str(pid), "black", "")
    assert view.fen == services.review.review(gid).moves[5].fen_before
    r = services.sessions.submit_move(sid, "d8e7")  # the stored best move
    assert r.feedback.kind in ("solved", "correct")


def test_qa_a_tolerance_puzzle_accepts_any_mate_and_ends_there(services, paths) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    fen = "6k1/5ppp/8/8/8/8/8/RR4K1 w - - 0 1"  # Ra8# and Rb8#
    CustomPuzzlesRepo(services.db).add(
        NewCustomPuzzle(fen=fen, solution=("g1f2", "g8f8", "f2e3"), player_color="white", origin="manual",
                        strict=False),
        "2026-01-01T00:00:00+00:00",
    )  # fmt: skip
    sid = services.sessions.start(MINE).session_id
    services.sessions.next_puzzle(sid)
    r = services.sessions.submit_move(sid, "b1b8")
    assert r.feedback.kind == "solved" and r.outcome.win and r.outcome.solution == ["b1b8"]


def test_qa_my_puzzles_never_reach_the_lichess_sync_queue(services, paths) -> None:  # type: ignore[no-untyped-def]
    gid = _analyzed_scholar(services)
    services.review.save_as_puzzle(gid, 5)
    sid = services.sessions.start(MINE).session_id
    services.sessions.next_puzzle(sid)
    services.sessions.submit_move(sid, "a7a6")  # a miss
    with services.db.session() as c:
        rows = c.execute("SELECT puzzle_source, sync_status, puzzle_rating FROM attempts").fetchall()
    assert [tuple(r) for r in rows] == [("my", "local", None)]


# ---------------------------------------------------------------- sync: 410, 429, account changes


def test_qa_a_gone_month_is_skipped_now_and_never_asked_for_again(rig: Rig) -> None:  # noqa: F811
    rig.svc.set_chesscom_username("player_a")
    original = rig.chesscom.archive

    def archive(url: str, etag: str | None):  # type: ignore[no-untyped-def]
        if url.endswith("2026/08"):
            rig.chesscom.calls.append((url, etag))
            raise ChesscomGone("HTTP 410", status=410, retryable=False)
        return original(url, etag)

    rig.chesscom.archive = archive  # type: ignore[method-assign]
    _sync(rig)
    _, total = rig.svc.list_games(LibraryFilter(platforms=("chesscom",)))
    assert total >= 1  # September still arrived
    rig.chesscom.months[CC_BASE + "2026/10"] = []
    rig.chesscom.calls.clear()
    _sync(rig)
    assert not any(u.endswith("2026/08") for u, _ in rig.chesscom.calls)


def test_qa_chesscom_rate_limited_to_the_end_still_syncs_lichess(rig: Rig) -> None:  # noqa: F811
    rig.svc.set_chesscom_username("player_a")

    def archives(username: str) -> list[str]:
        raise RateLimited("HTTP 429", status=429, retryable=True)

    rig.chesscom.archives = archives  # type: ignore[method-assign]
    msg = _sync(rig)
    _, lichess = rig.svc.list_games(LibraryFilter(platforms=("lichess",)))
    assert lichess >= 1 and "chess.com" in msg


def test_qa_relinking_another_chesscom_user_starts_a_fresh_first_sync(rig: Rig) -> None:  # noqa: F811
    rig.svc.set_chesscom_username("player_a")
    _sync(rig)
    rig.chesscom.usernames.add("player_b")
    rig.svc.set_chesscom_username("player_b")
    rig.chesscom.calls.clear()
    _sync(rig)
    months = [u for u, _ in rig.chesscom.calls if "/games/2026/" in u]
    assert months and all(etag is None for u, etag in rig.chesscom.calls if "/games/2026/" in u)
    rig.svc.set_chesscom_username("PLAYER_B")  # only the case changed: the position is kept
    rig.chesscom.calls.clear()
    _sync(rig)
    assert any(etag is not None for _, etag in rig.chesscom.calls)


@pytest.mark.xfail(
    strict=True, reason="v0.8-B5: the chess.com username typed for a URL import is used once, then forgotten"
)
def test_qa_the_username_given_for_a_chesscom_url_finds_your_color_and_is_kept(rig: Rig) -> None:  # noqa: F811
    rig.acct.id = None  # not signed in to Lichess: only the typed chess.com name says who you are
    job = rig.svc.start_url_import("https://www.chess.com/game/live/100000001", chesscom_username="player_a")
    st = rig.runner.wait(job, 5)
    assert st is not None and st.state == "done", st
    res = rig.svc.url_result(job)
    assert res is not None and res.game_id
    # Expected (FR-11.4 "ask once", FR-11.5): you just said you're player_a, who played Black in that game.
    assert not res.needs_color and rig.svc.get(res.game_id).user_color == "black"
    assert rig.svc.settings().chesscom_username == "player_a"
