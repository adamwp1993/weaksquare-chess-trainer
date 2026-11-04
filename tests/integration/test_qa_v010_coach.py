"""QA v0.10 (qa/QA-v0.10.md): puzzles from your games, the Coach's subject separation, the Suggested-mix
rule and the AI prompt, through the wired services on a temp data folder (FakeEngine, fake HTTP, fake LLM)."""

from __future__ import annotations

import json

import chess
import pytest

from tests.fakes.engine import FakeEngine, plant_managed_install
from tests.integration.test_coach_run import ANY_GAME, _my_games, _run
from tests.integration.test_game_explain import configure, fake
from tests.integration.test_game_puzzles import Recorder, _game, _puzzles, _recorder, _rows
from weaksquare.adapters.db.repos.custom_puzzles import CustomPuzzlesRepo
from weaksquare.adapters.db.repos.game_analysis import GameAnalysisRepo
from weaksquare.adapters.db.repos.games import GamesRepo
from weaksquare.core.filters import FilterSpec
from weaksquare.core.games import GameRecord
from weaksquare.core.puzzle import NewCustomPuzzle

QUIET = "4k3/8/8/8/8/8/1n6/R3K3 w - - 0 1"  # the fake engine scores White's moves ±10 cp (test_my_puzzles)
MINE = FilterSpec(source="my", exclude_solved_here=False, exclude_played_on_lichess=False)


@pytest.fixture(autouse=True)
def _reset() -> None:
    FakeEngine.instances.clear()


OPENINGS = ("1. e4 e5 2. Nf3 Nc6", "1. d4 d5 2. c4 e6", "1. c4 e5 2. Nc3 Nf6", "1. Nf3 d5 2. g3 c5")


def _mine(services, cls: str = "blunder", n: int = 0) -> int:  # type: ignore[no-untyped-def]
    """One of your games with the planted rows; a different move list each time, so it's a new game."""
    services.game_puzzles._engine = services.game_puzzles._engine if isinstance(
        services.game_puzzles._engine, Recorder) else Recorder()  # fmt: skip
    pgn = f'[White "player_a"]\n[Black "opponent_b"]\n[Result "*"]\n\n{OPENINGS[n]} *\n'
    gid = int(services.games.import_pgn(pgn).game_id)
    services.games.set_user_color(gid, "white")
    GameAnalysisRepo(services.db).replace(gid, _rows(cls), "analyzed", 0.3, "Stockfish 19")
    return gid


def _other_game(services, subject: str = "lichess:someone_x") -> int:  # type: ignore[no-untyped-def]
    from tests.integration.test_game_analysis import MATE

    rec = GameRecord(
        source="lichess", source_game_id="QAGAME01", url=None, pgn=MATE, played_at="2026-01-02T10:00:00",
        time_control="180+0", time_class="blitz", rated=True, white="someone_x", black="opponent_q",
        white_rating=None, black_rating=None, result="1-0", eco=None, opening=None, accuracy_white=None,
        accuracy_black=None, lichess_analyzed=False, extra={},
    )  # fmt: skip
    gid, _ = GamesRepo(services.db).add(rec, "qa-hash-1", "white", "t", subject=subject)
    GameAnalysisRepo(services.db).replace(gid, _rows(), "analyzed", 0.3, "Stockfish 19")
    return gid


# ---- severity levels, archive and attempts (FR-10.40, 10.44) ----------------------------------------


LEVEL_SETS = {
    "blunders": {("A", 12), ("B", 12), ("C", 12), ("A", 14)},
    "mistakes": {("A", 12), ("B", 12), ("C", 12), ("A", 14), ("B", 14)},
    "inaccuracies": {("A", 12), ("B", 12), ("C", 12), ("A", 14), ("B", 14), ("C", 14)},
}


def _active(services, names: dict[int, str]) -> set[tuple[str, int]]:  # type: ignore[no-untyped-def]
    with services.db.session() as conn:
        rows = conn.execute("SELECT game_id, ply FROM custom_puzzles WHERE status = 'active'").fetchall()
    return {(names[g], p) for g, p in rows}


def test_qa_each_level_gives_its_set_and_a_round_trip_runs_no_engine(services) -> None:  # type: ignore[no-untyped-def]
    rec = _recorder(services)
    services.game_puzzles._settings.set("coach.puzzle_level", "inaccuracies")
    names = {
        _mine(services, "blunder", 0): "A",
        _mine(services, "mistake", 1): "B",
        _mine(services, "inaccuracy", 2): "C",
    }
    assert len(names) == 3
    for gid in names:
        services.game_puzzles.process_game(gid)
    assert _active(services, names) == LEVEL_SETS["inaccuracies"]
    with services.db.session() as conn:
        before = conn.execute("SELECT id, game_id, ply FROM custom_puzzles ORDER BY id").fetchall()
    rec.calls.clear()
    queued: list[object] = []
    services.analysis.queue = lambda *a, **k: queued.append(a)  # type: ignore[method-assign]
    for level in ("mistakes", "blunders", "mistakes", "inaccuracies", "blunders", "inaccuracies"):
        services.game_puzzles.set_settings(level=level)
        assert _active(services, names) == LEVEL_SETS[level], level
    assert rec.calls == [] and queued == []  # stored checks only, no analysis
    with services.db.session() as conn:  # never deleted, never duplicated
        assert conn.execute("SELECT id, game_id, ply FROM custom_puzzles ORDER BY id").fetchall() == before


def test_qa_narrowing_keeps_the_attempts_and_the_archived_puzzle_is_not_served(services) -> None:  # type: ignore[no-untyped-def]
    _recorder(services)
    gid = _game(services, _rows("mistake"))
    services.game_puzzles.process_game(gid)
    with services.db.transaction() as conn:  # leave only the Allowed one (ply 14, a mistake) to be served
        conn.execute("UPDATE custom_puzzles SET status = 'hidden' WHERE ply = 12")
    sid = services.sessions.start(MINE).session_id
    view = services.sessions.next_puzzle(sid)
    assert view.game_ply == 14
    services.sessions.submit_move(sid, "a8a1")
    with services.db.session() as conn:
        pid = conn.execute("SELECT id FROM custom_puzzles WHERE ply = 14").fetchone()[0]
        n = conn.execute("SELECT COUNT(*) FROM attempts WHERE puzzle_source = 'my' AND puzzle_id = ?", (str(pid),))
        assert n.fetchone()[0] == 1
    services.game_puzzles.set_settings(level="blunders")
    with services.db.session() as conn:
        assert conn.execute("SELECT status FROM custom_puzzles WHERE id = ?", (pid,)).fetchone()[0] == "archived"
        n = conn.execute("SELECT COUNT(*) FROM attempts WHERE puzzle_source = 'my' AND puzzle_id = ?", (str(pid),))
        assert n.fetchone()[0] == 1  # the attempt is kept
    assert services.sessions._puzzles.count(MINE) == 0  # archived (and hidden) are not served
    services.game_puzzles.set_settings(level="mistakes")
    assert services.sessions._puzzles.count(MINE) == 1  # restored, same row


def test_qa_a_puzzle_you_archived_stays_archived_across_level_changes(services) -> None:  # type: ignore[no-untyped-def]
    _recorder(services)
    gid = _game(services)
    services.game_puzzles.process_game(gid)
    with services.db.session() as conn:
        pid = conn.execute("SELECT id FROM custom_puzzles WHERE ply = 12").fetchone()[0]
    services.game_puzzles.archive(pid)
    for level in ("blunders", "inaccuracies", "mistakes"):
        services.game_puzzles.set_settings(level=level)
    services.game_puzzles.process_game(gid)
    with services.db.session() as conn:
        assert conn.execute("SELECT status FROM custom_puzzles WHERE id = ?", (pid,)).fetchone()[0] == "hidden"


# ---- duplicates --------------------------------------------------------------------------------------


def test_qa_a_re_analysis_at_another_think_time_makes_no_duplicate(services) -> None:  # type: ignore[no-untyped-def]
    rec = _recorder(services)
    gid = _game(services)
    assert services.game_puzzles.process_game(gid) == 2
    GameAnalysisRepo(services.db).replace(gid, _rows(), "analyzed", 0.5, "Stockfish 19")  # a new analysis
    services.game_puzzles.process_game(gid)  # checked again (new check key) but not added again
    services.game_puzzles.rebuild()
    assert len(_puzzles(services)) == 2
    assert isinstance(rec, Recorder)


def test_qa_two_coach_runs_and_the_backfill_make_no_duplicates(services, paths) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    _mine(services, n=0), _mine(services, n=1)
    _run(services, {"source": "games", **ANY_GAME})
    n = len(_puzzles(services))
    assert n == 4
    _run(services, {"source": "both", **ANY_GAME})
    job = services.game_puzzles.start_backfill()
    if job is not None:
        assert services.game_puzzles._runner.wait(job, 10).state == "done"
    assert len(_puzzles(services)) == n


# ---- the tolerance on a puzzle from the Coach (FR-10.43) ----------------------------------------------


def test_qa_a_coach_allowed_puzzle_takes_a_move_within_tolerance_and_the_engine_continues(services, paths) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    CustomPuzzlesRepo(services.db).add(
        NewCustomPuzzle(fen=QUIET, solution=("e1e2", "e8d7", "e2e3"), player_color="white", origin="coach",
                        strict=False, kind="allowed", severity="blunder", solve_as="opponent"),
        "2026-01-01T00:00:00+00:00",
    )  # fmt: skip
    sid = services.sessions.start(MINE).session_id
    view = services.sessions.next_puzzle(sid)
    assert view.solve_as_opponent and view.player_color == "white" and view.fen == QUIET
    r = services.sessions.submit_move(sid, "a1a3")  # not the stored move; within 30 cp for the fake engine
    assert r.feedback.kind == "correct" and r.feedback.reply
    state = services.sessions._sessions[sid].current.state
    assert state.puzzle.moves[1] == "a1a3" and len(state.puzzle.moves) == 4  # continued from your move
    board = chess.Board(QUIET)
    for uci in state.puzzle.moves[1:]:  # [0] is the empty premove of a My puzzle
        assert chess.Move.from_uci(uci) in board.legal_moves
        board.push_uci(uci)
    done = services.sessions.submit_move(sid, state.puzzle.moves[state.next_index])
    assert done.feedback.kind == "solved" and done.outcome.win
    interactive = [e for e in FakeEngine.instances if e.calls]
    assert interactive and all(e.options[0] == 7 for e in interactive)  # the interactive engine only


# ---- another player stays out of your data (FR-10.3; Adam, v0.10 planning) ---------------------------


def test_qa_another_players_game_mistakes_stay_out_of_your_mistake_reason_stats(services) -> None:  # type: ignore[no-untyped-def]
    before = services.stats.reasons(source="games").untagged
    _other_game(services)
    assert services.stats.reasons(source="games").untagged == before  # "never counts in your stats"


def test_qa_your_trend_skips_another_players_report(services, paths) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    _my_games(services, 1)
    _run(services, {"source": "games", **ANY_GAME})
    _run(services, {"source": "games", "player": "opponent_b", "platform": "lichess", **ANY_GAME})
    rid = _run(services, {"source": "games", **ANY_GAME})
    _, tr = services.coach.report(rid)
    assert tr and all(v == 0 for v in tr.values()), tr  # the same games as your previous report


def test_qa_another_players_run_leaves_your_filters_mode_and_suggestion(services, paths) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    _my_games(services, 1)
    _run(services, {"source": "games", **ANY_GAME})
    sug = services.coach.suggestion()
    filters = services.coach._settings.get("mixer.filters")
    mode = services.coach._settings.get("trainer.mode")
    with services.db.session() as conn:
        n = conn.execute("SELECT COUNT(*) FROM custom_puzzles").fetchone()[0]
    _run(services, {"source": "games", "player": "https://lichess.org/@/opponent_b", **ANY_GAME})
    assert services.coach.suggestion() == sug
    assert services.coach._settings.get("mixer.filters") == filters
    assert services.coach._settings.get("trainer.mode") == mode
    with services.db.session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM custom_puzzles").fetchone()[0] == n


def test_qa_your_own_username_as_another_player_counts_as_you(services, paths) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    services.coach._library.usernames = lambda: ["Player_A"]  # type: ignore[method-assign]
    _other_game(services, subject="me")  # a Lichess game of yours
    rid = _run(services, {"source": "games", "player": "player_a", "platform": "lichess", **ANY_GAME})
    row, _ = services.coach.report(rid)
    assert row.subject == "me"


# ---- the Suggested mix rule (FR-10.31) ---------------------------------------------------------------


def test_qa_filters_changed_after_an_applied_suggestion_are_never_overwritten(services, paths) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    _my_games(services, 1)
    _run(services, {"source": "games", **ANY_GAME})
    applied = services.coach._settings.get("mixer.filters")
    tweaked = dict(applied, rating_max=applied["rating_max"] - 50)
    services.ui_settings.set("mixer.filters", tweaked)  # through the same path as the Mixer
    services.coach._settings.set("trainer.mode", "standard")
    _run(services, {"source": "games", **ANY_GAME})
    assert services.coach._settings.get("mixer.filters") == FilterSpec.from_json(tweaked).to_json()
    assert services.coach.suggestion().pending


def test_qa_a_mode_change_alone_isnt_a_filter_change(services, paths) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    _my_games(services, 1)
    _run(services, {"source": "games", **ANY_GAME})
    services.ui_settings.set("mixer.filters", FilterSpec().to_json())  # back to the default broad mix
    _run(services, {"source": "games", **ANY_GAME})
    assert not services.coach.suggestion().pending  # the default mix is replaced again


# ---- the AI prompt (FR-8.16, FR-10.21) --------------------------------------------------------------


LEAKY_PGN = (
    '[Event "Rated Rapid game"]\n[Site "https://lichess.org/QAGAME77"]\n[Date "2026.03.14"]\n'
    '[White "qa_real_looking_name"]\n[Black "qa_rival_name"]\n[Result "1-0"]\n[WhiteElo "1733"]\n'
    '[BlackElo "1688"]\n[UTCTime "19:22:01"]\n[Annotator "qa_annotator"]\n[TimeControl "600+0"]\n\n'
    "1. e4 { qa_comment_text [%clk 0:09:59] } e5 { [%clk 0:09:58] } 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7# 1-0\n"
)
MARKERS = ("qa_real_looking_name", "qa_rival_name", "qa_annotator", "qa_comment_text", "QAGAME77", "lichess.org",
           "2026.03.14", "2026-03-14", "1733", "1688", "19:22", "[%clk", "Site", "WhiteElo", "Event", "http")  # fmt: skip


def test_qa_a_metadata_heavy_game_leaves_no_trace_in_the_coach_prompt(services, paths) -> None:  # type: ignore[no-untyped-def]
    plant_managed_install(paths)
    services.game_puzzles._engine = Recorder()
    gid = int(services.games.import_pgn(LEAKY_PGN).game_id)
    services.games.set_user_color(gid, "white")
    GameAnalysisRepo(services.db).replace(gid, _rows(), "analyzed", 0.3, "Stockfish 19")
    rid = _run(services, {"source": "both", "detail": "detailed", "game_ids": [gid], **ANY_GAME})
    configure(services)
    fake(services).queue(json.dumps({"summary": "s", "weaknesses": [], "presets": []}))
    job = services.coach.start_ai(rid)
    services.coach._runner.wait(job, 10)
    req = fake(services).requests[-1]
    text = req.system + "\n" + req.user + "\n" + json.dumps(req.schema if hasattr(req, "schema") else {})
    for m in MARKERS:
        assert m not in text, m
    assert "game_id" not in text and '"ply"' not in text  # examples are labels, never game ids
    assert req.max_tokens == 5000  # FR-8.14: Coach Detailed


# ---- rapid repeated clicks ------------------------------------------------------------------------------


def test_qa_a_second_run_while_one_is_going_is_refused(services, paths) -> None:  # type: ignore[no-untyped-def]
    from weaksquare.core.errors import ValidationError

    plant_managed_install(paths)
    _mine(services, n=0)
    job = services.coach.start_run({"source": "games", **ANY_GAME})
    with pytest.raises(ValidationError, match="already going"):
        services.coach.start_run({"source": "games", **ANY_GAME})
    assert services.coach._runner.wait(job, 20).state == "done"
    with services.db.session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM coach_reports").fetchone()[0] == 1


def test_qa_level_and_think_time_bounds_are_checked(services) -> None:  # type: ignore[no-untyped-def]
    from weaksquare.core.errors import ValidationError

    for bad in ({"level": "all"}, {"level": ""}, {"think_s": 0.1}, {"think_s": 5.01}, {"think_s": True},
                {"think_s": "1"}, {"margin": 0.2}, {"margin": 2}):  # fmt: skip
        with pytest.raises(ValidationError):
            services.game_puzzles.set_settings(**bad)
    assert services.game_puzzles.set_settings(think_s=0.2).think_s == 0.2
    assert services.game_puzzles.set_settings(think_s=5.0).think_s == 5.0


def test_b1_another_players_game_records_nothing_as_yours(services) -> None:  # type: ignore[no-untyped-def]
    """v0.10-B1 regression: reviewing another player's game offers no Retry and no reason chips."""
    from weaksquare.core.errors import ValidationError

    gid = _other_game(services)
    view = services.review.review(gid)
    assert view.retry_plies == () and not view.ask_reasons
    with pytest.raises(ValidationError):
        services.review.set_game_reason(gid, view.key_moments[0] if view.key_moments else 5, "didntLook")
