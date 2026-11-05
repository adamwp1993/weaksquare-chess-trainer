"""Puzzles from your games (v0.10, §10.9): levels, the quality-check cache, archive, orientation,
duplicates, other players and manual saves. The analysis rows are written by hand, so the expected
positions are known exactly."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

import chess

from tests.integration.test_game_analysis import MATE
from weaksquare.adapters.db.repos.game_analysis import GameAnalysisRepo
from weaksquare.adapters.db.repos.games import GamesRepo
from weaksquare.core.engine import EngineLine
from weaksquare.core.game_review import MoveRow, Score
from weaksquare.core.games import GameRecord

MISSED_FEN = "6k1/5ppp/7q/8/8/8/5PPP/3R2K1 w - - 0 1"  # Rd8# was there
MISSED_PREV = "6k1/5ppp/6q1/8/8/8/5PPP/3R2K1 b - - 0 1"  # ...Qg6-h6 led to it
ALLOWED_FEN = "r5k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1"  # Ra1?? allows ...Rxa1#
MATE_IN_ONE = [EngineLine(None, 1, ("d1d8",)), EngineLine(0, None, ("g1f1",))]


def _row(
    ply: int,
    fen: str,
    uci: str,
    *,
    cls: str = "best",
    kind: str | None = None,
    before: Score | None = None,
    after: Score | None = None,
    lines: Sequence[EngineLine] = (),
) -> MoveRow:
    board = chess.Board(fen)
    move = chess.Move.from_uci(uci)
    return MoveRow(
        ply=ply, fen_before=fen, move_uci=uci, move_san=board.san(move),
        mover="white" if board.turn == chess.WHITE else "black", eval_before=before or Score(0),
        eval_after=after or Score(0), best_move=lines[0].pv[0] if lines else uci, lines=tuple(lines),
        refutation=(), cp_loss=0 if cls == "best" else 300, classification=cls, kind=kind, phase="middlegame",
        low_clock=None, clock_s=None,
    )  # fmt: skip


def _filler(ply: int) -> MoveRow:
    board = chess.Board()
    if ply % 2:
        board.push_uci("e2e4")
    return _row(ply, board.fen(), "g1f3" if ply % 2 == 0 else "g8f6")


def _rows(allowed_cls: str = "blunder") -> list[MoveRow]:
    rows = [_filler(p) for p in range(16)]
    rows[11] = _row(11, MISSED_PREV, "g6h6")
    rows[12] = _row(12, MISSED_FEN, "g1f1", cls="blunder", kind="missed", before=Score(mate=1), lines=MATE_IN_ONE)
    rows[14] = _row(14, ALLOWED_FEN, "d1a1", cls=allowed_cls, kind="allowed", after=Score(mate=-1))
    rows[14] = replace(rows[14], refutation=("a8a1",))  # the pipeline stores the next position's best line
    after = chess.Board(ALLOWED_FEN)
    after.push_uci("d1a1")
    rows[15] = _row(15, after.fen(), "a8a1", lines=[EngineLine(None, -1, ("a8a1",)), EngineLine(0, None, ("g8f8",))])
    return rows


class Recorder:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def analyse_background(self, board: chess.Board, think_s: float, multipv: int = 3) -> list[EngineLine]:
        self.calls.append(board.fen())
        return []


def _game(services, rows: list[MoveRow] | None = None, color: str = "white") -> int:  # type: ignore[no-untyped-def]
    gid = int(services.games.import_pgn(MATE).game_id)
    services.games.set_user_color(gid, color)
    GameAnalysisRepo(services.db).replace(gid, rows or _rows(), "analyzed", 0.3, "Stockfish 19")
    return gid


def _puzzles(services) -> list[tuple]:  # type: ignore[no-untyped-def,type-arg]
    with services.db.session() as conn:
        return conn.execute(
            "SELECT ply, fen, solution_uci, player_color, solve_as, kind, severity, status, origin, strict, themes"
            " FROM custom_puzzles ORDER BY ply"
        ).fetchall()


def _recorder(services) -> Recorder:  # type: ignore[no-untyped-def]
    rec = Recorder()
    services.game_puzzles._engine = rec
    return rec


def test_missed_and_allowed_become_puzzles_with_the_right_side(services) -> None:  # type: ignore[no-untyped-def]
    _recorder(services)
    gid = _game(services)
    assert services.game_puzzles.process_game(gid) == 2
    missed, allowed = _puzzles(services)
    assert missed[:7] == (12, MISSED_FEN, "d1d8", "white", "you", "missed", "blunder")
    assert chess.Board(allowed[1]).turn == chess.BLACK  # the position after your move: your opponent to move
    assert allowed[2:7] == ("a8a1", "black", "opponent", "allowed", "blunder")
    assert missed[7:10] == ("active", "coach", 0) and allowed[7:10] == ("active", "coach", 0)  # 30 cp tolerance
    assert "mateIn1" in missed[10].split() and "mateIn1" in allowed[10].split()


def test_re_runs_make_no_duplicates(services) -> None:  # type: ignore[no-untyped-def]
    _recorder(services)
    gid = _game(services)
    services.game_puzzles.process_game(gid)
    assert services.game_puzzles.process_game(gid) == 0
    assert len(_puzzles(services)) == 2


def test_levels_archive_and_restore_without_the_engine(services) -> None:  # type: ignore[no-untyped-def]
    rec = _recorder(services)
    gid = _game(services, _rows(allowed_cls="mistake"))
    services.game_puzzles.process_game(gid)
    with services.db.session() as conn:
        ids = conn.execute("SELECT id FROM custom_puzzles ORDER BY ply").fetchall()
    rec.calls.clear()
    services.game_puzzles.set_settings(level="blunders")
    assert [(p[0], p[7]) for p in _puzzles(services)] == [(12, "active"), (14, "archived")]
    services.game_puzzles.set_settings(level="mistakes")
    assert [(p[0], p[7]) for p in _puzzles(services)] == [(12, "active"), (14, "active")]
    assert rec.calls == []  # stored checks only
    with services.db.session() as conn:  # the same rows: attempts (keyed by puzzle id) stay attached
        assert conn.execute("SELECT id FROM custom_puzzles ORDER BY ply").fetchall() == ids


def test_a_level_change_runs_no_game_analysis(services) -> None:  # type: ignore[no-untyped-def]
    _recorder(services)
    gid = _game(services)
    services.game_puzzles.process_game(gid)
    queued: list[object] = []
    services.analysis.queue = lambda *a, **k: queued.append(a)  # type: ignore[method-assign]
    assert services.game_puzzles.set_settings(level="inaccuracies").level == "inaccuracies"
    assert queued == []


def test_widening_to_inaccuracies_checks_only_new_candidates(services) -> None:  # type: ignore[no-untyped-def]
    rec = _recorder(services)
    gid = _game(services, _rows(allowed_cls="inaccuracy"))
    services.game_puzzles.process_game(gid)
    assert [p[0] for p in _puzzles(services)] == [12]  # the inaccuracy is outside "mistakes"
    services.game_puzzles.set_settings(level="blunders")
    job = services.game_puzzles.rebuild()
    assert job is None  # nothing new to check
    services.game_puzzles._settings.set("coach.puzzle_level", "inaccuracies")
    job = services.game_puzzles.rebuild()
    assert job is not None
    assert services.game_puzzles._runner.wait(job, 10).state == "done"
    assert [(p[0], p[7]) for p in _puzzles(services)] == [(12, "active"), (14, "active")]
    assert rec.calls == []  # a clean mate in one needs no extra search


def test_another_players_game_makes_no_puzzles(services) -> None:  # type: ignore[no-untyped-def]
    _recorder(services)
    rec = GameRecord(
        source="lichess", source_game_id="zzzz0001", url=None, pgn=MATE, played_at=None, time_control=None,
        time_class="rapid", rated=True, white="someone", black="other", white_rating=None, black_rating=None,
        result="1-0", eco=None, opening=None, accuracy_white=None, accuracy_black=None, lichess_analyzed=False,
        extra={},
    )  # fmt: skip
    gid, _ = GamesRepo(services.db).add(rec, "hash-z", "white", "t", subject="lichess:someone")
    GameAnalysisRepo(services.db).replace(gid, _rows(), "analyzed", 0.3, "Stockfish 19")
    assert services.game_puzzles.process_game(gid) == 0
    assert _puzzles(services) == []


def test_your_own_save_at_that_move_wins(services) -> None:  # type: ignore[no-untyped-def]
    _recorder(services)
    gid = _game(services)
    services.review.save_as_puzzle(gid, 12)
    services.game_puzzles.process_game(gid)
    assert [(p[0], p[8]) for p in _puzzles(services)] == [(12, "manual"), (14, "coach")]


def test_opening_mistakes_are_skipped(services) -> None:  # type: ignore[no-untyped-def]
    _recorder(services)
    rows = [_filler(p) for p in range(16)]
    rows[3] = _row(3, MISSED_PREV, "g6h6")
    rows[4] = _row(4, MISSED_FEN, "g1f1", cls="blunder", kind="missed", before=Score(mate=1), lines=MATE_IN_ONE)
    gid = _game(services, rows)
    assert services.game_puzzles.process_game(gid) == 0


def test_the_backfill_tags_old_puzzles_and_runs_once(services) -> None:  # type: ignore[no-untyped-def]
    _recorder(services)
    gid = _game(services)
    services.review.save_as_puzzle(gid, 12)
    with services.db.transaction() as conn:
        conn.execute("UPDATE custom_puzzles SET themes = NULL")
    job = services.game_puzzles.start_backfill()
    assert job is not None
    assert services.game_puzzles._runner.wait(job, 10).state == "done"
    assert "mateIn1" in _puzzles(services)[0][10].split()
    assert services.game_puzzles.start_backfill() is None


def test_an_allowed_puzzle_is_served_as_your_opponent_with_its_game_link(services) -> None:  # type: ignore[no-untyped-def]
    from weaksquare.core.filters import FilterSpec

    _recorder(services)
    gid = _game(services)
    services.game_puzzles.process_game(gid)
    with services.db.transaction() as conn:
        conn.execute("UPDATE custom_puzzles SET status = 'archived' WHERE ply = 12")
    spec = FilterSpec(source="my", exclude_solved_here=False, exclude_played_on_lichess=False)
    view = services.sessions.next_puzzle(services.sessions.start(spec).session_id)
    assert view.player_color == "black" and view.solve_as_opponent
    assert (view.game_id, view.game_ply) == (gid, 14)


def test_any_analysis_calls_the_puzzle_hook(services, paths) -> None:  # type: ignore[no-untyped-def]
    from tests.fakes.engine import plant_managed_install
    from tests.integration.test_game_analysis import _wait

    plant_managed_install(paths)
    seen: list[int] = []
    services.analysis.add_listener(lambda gid, progress, cancel: seen.append(gid))
    gid = services.games.import_pgn(MATE).game_id
    assert _wait(services, services.analysis.queue([gid])) == "done"
    assert seen == [gid]


def test_r2_the_backfill_applies_the_b2_rule_to_old_analysis(services) -> None:  # type: ignore[no-untyped-def]
    """QA round 2 observation: a move stored as Missed by v0.9's rule, which walked into a mate, becomes
    Allowed when the v0.10 backfill runs."""
    from dataclasses import replace as dc_replace

    _recorder(services)
    rows = _rows()
    rows[12] = dc_replace(rows[12], eval_after=Score(mate=-1), kind="missed")  # v0.9: Missed came first
    gid = _game(services, rows)
    job = services.game_puzzles.start_backfill()
    assert job is not None and services.game_puzzles._runner.wait(job, 10).state == "done"
    assert GameAnalysisRepo(services.db).rows(gid)[12].kind == "allowed"
