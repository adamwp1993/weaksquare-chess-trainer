"""QA v0.8 (independent): edge cases of the pure game and puzzle-file code that the builder's tests don't
pin. Tests marked xfail(strict=True) document an open bug by its ID (qa/QA-v0.8.md)."""

from __future__ import annotations

import chess
import pytest

from weaksquare.core.chesscom import months_to_fetch, parse_archive_game
from weaksquare.core.engine import EngineLine
from weaksquare.core.game_review import Score, grade_game
from weaksquare.core.games import (
    MAX_PLIES,
    GameError,
    ParsedGame,
    Skip,
    parse_lichess_game,
    parse_lichess_url,
    parse_pgn,
    parse_single_pgn,
)
from weaksquare.core.puzzle_files import EntryError, ImportedPuzzle, parse_csv, parse_epd, parse_pgn_puzzles
from weaksquare.core.tolerance import within_tolerance

# Sam Loyd's 10-move stalemate: White's last move stalemates Black.
LOYD = (
    '[White "player_a"]\n[Black "opponent_b"]\n[Result "1/2-1/2"]\n\n'
    "1. e3 a5 2. Qh5 Ra6 3. Qxa5 h5 4. h4 Rah6 5. Qxc7 f6 6. Qxd7+ Kf7 7. Qxb7 Qd3 8. Qxb8 Qh7 "
    "9. Qxc8 Kg6 10. Qe6 1/2-1/2\n"
)
CYCLE = ["Nf3", "Nf6", "Ng1", "Ng8"]


def _shuffle_game(plies: int) -> str:
    moves = (CYCLE * (plies // 4 + 1))[:plies]
    parts = []
    for i in range(0, plies, 2):
        parts.append(f"{i // 2 + 1}. {moves[i]}" + (f" {moves[i + 1]}" if i + 1 < plies else ""))
    return '[White "player_a"]\n[Black "opponent_b"]\n\n' + " ".join(parts) + " *\n"


# ---------------------------------------------------------------- PGN edge cases (FR-11.6)


def test_qa_a_game_of_exactly_400_plies_is_accepted_and_401_is_refused() -> None:
    ok = parse_pgn(_shuffle_game(MAX_PLIES))[0]
    assert isinstance(ok, ParsedGame) and len(ok.moves) == 400
    too_long = parse_pgn(_shuffle_game(MAX_PLIES + 1))[0]
    assert isinstance(too_long, GameError) and "400 plies" in too_long.reason


@pytest.mark.parametrize(
    "header",
    ['[Variant "Chess960"]', '[Variant "Crazyhouse"]', '[Variant "Atomic"]', '[Variant "King of the Hill"]'],
)
def test_qa_every_variant_header_is_refused_with_a_reason(header: str) -> None:
    out = parse_pgn(f"{header}\n\n1. e4 e5 *\n")[0]
    assert isinstance(out, GameError) and "only standard chess" in out.reason


def test_qa_a_from_position_game_with_black_to_move_starts_with_blacks_move() -> None:
    fen = "4k3/8/8/8/8/8/4P3/4K3 b - - 0 40"
    g = parse_single_pgn(f'[Variant "From Position"]\n[SetUp "1"]\n[FEN "{fen}"]\n\n40... Kd7 41. e4 *\n')
    assert g.start_fen == fen and g.moves == ("e8d7", "e2e4")


def test_qa_an_illegal_from_position_start_is_refused() -> None:
    out = parse_pgn('[SetUp "1"]\n[FEN "8/8/8/8/8/8/8/8 w - - 0 1"]\n\n1. e4 *\n')[0]
    assert isinstance(out, GameError) and "starting position" in out.reason


def test_qa_null_moves_headers_only_and_crlf_bom_pastes() -> None:
    null = parse_pgn("1. e4 -- 2. d4 *")[0]
    assert isinstance(null, GameError) and "illegal move" in null.reason
    empty = parse_pgn('[Event "x"]\n[Result "*"]\n\n*')[0]
    assert isinstance(empty, GameError) and "no moves" in empty.reason
    crlf = "﻿" + LOYD.replace("\n", "\r\n")
    g = parse_single_pgn(crlf)
    assert len(g.moves) == 19 and g.result == "1/2-1/2"


def test_qa_lichess_urls_with_a_player_suffix_and_ply_anchor() -> None:
    assert parse_lichess_url("https://lichess.org/abcdefghWXYZ") == "abcdefgh"  # the player's 12-char URL
    assert parse_lichess_url("lichess.org/abcdefgh/black#32") == "abcdefgh"
    assert parse_lichess_url("https://lichess.org/@/someone") is None
    assert parse_lichess_url("https://lichess.org/study/abcdefgh") is None


def test_qa_lichess_from_position_games_are_accepted_but_chess960_is_skipped() -> None:
    base = {"id": "GAMEID99", "pgn": LOYD}
    assert parse_lichess_game({**base, "variant": "fromPosition"}).source_game_id == "GAMEID99"
    with pytest.raises(Skip):
        parse_lichess_game({**base, "variant": "chess960"})


# ---------------------------------------------------------------- grading games that end without a mate


def _lines_for(board: chess.Board, cp: int, played: str | None = None) -> list[EngineLine]:
    """One line with a White-relative score and a legal move other than the one played."""
    legal = list(board.legal_moves)
    move = next((m for m in legal if m.uci() != played), legal[0])  # a forced move has no alternative
    return [EngineLine(cp, None, (move.uci(),))]


def test_qa_stalemating_a_won_position_is_a_blunder_and_the_final_eval_is_level() -> None:
    g = parse_single_pgn(LOYD)
    board = chess.Board(g.start_fen)
    analyses: list[list[EngineLine] | None] = []
    for uci in g.moves:
        analyses.append(_lines_for(board, 900, uci))  # White is winning throughout
        board.push(chess.Move.from_uci(uci))
    assert board.is_stalemate()
    analyses.append(None)  # the game is over: no search
    rows = grade_game(g.start_fen, g.moves, analyses)
    last = rows[-1]
    assert last.mover == "white" and last.eval_after == Score(0, None)
    assert last.classification == "blunder" and last.cp_loss == 900  # +9 thrown away for a draw


def test_qa_a_resigned_game_grades_every_move_including_the_last() -> None:
    pgn = '[Result "0-1"]\n\n1. e4 e5 2. Qh5 Nc6 3. Qxf7+ Kxf7 0-1\n'  # White resigns after losing the queen
    g = parse_single_pgn(pgn)
    board = chess.Board(g.start_fen)
    analyses: list[list[EngineLine] | None] = []
    evals = [30, 30, 30, 30, -50, -800, -800]  # before each move, then the final (resigned) position
    for i, uci in enumerate(g.moves):
        analyses.append(_lines_for(board, evals[i], uci))
        board.push(chess.Move.from_uci(uci))
    analyses.append(_lines_for(board, evals[-1]))
    rows = grade_game(g.start_fen, g.moves, analyses)
    assert len(rows) == 6 and rows[-1].eval_after == Score(800, None)  # Black's view: +8
    assert rows[4].classification == "blunder"  # Qxf7+?? from -0.5 to -8 for White


# ---------------------------------------------------------------- chess.com optional fields (FR-11.28)


def _cc(**over: object) -> dict:
    g: dict = {
        "url": "https://www.chess.com/game/live/100000077",
        "pgn": '[White "player_a"]\n[Black "opponent_x"]\n[Result "1-0"]\n[TimeControl "180+2"]\n\n1. e4 e5 1-0',
        "rules": "chess",
    }
    g.update(over)
    return {k: v for k, v in g.items() if v is not None}


def test_qa_chesscom_rules_chess960_and_other_variants_are_skipped() -> None:
    for rules in ("chess960", "bughouse", "kingofthehill", "threecheck", "crazyhouse"):
        with pytest.raises(Skip):
            parse_archive_game(_cc(rules=rules))


def test_qa_chesscom_names_and_time_class_fall_back_to_the_pgn() -> None:
    rec = parse_archive_game(_cc(rules=None))  # no rules, no players, no time_control, no end_time
    assert (rec.white, rec.black, rec.time_control, rec.time_class) == ("player_a", "opponent_x", "180+2", "blitz")
    assert rec.played_at is None and rec.accuracy_white is None and rec.rated is None and rec.result == "1-0"
    assert parse_archive_game(_cc(time_control="1/259200")).time_class == "daily"


def test_qa_chesscom_months_on_the_first_sync_start_at_the_window_month() -> None:
    base = "https://api.chess.com/pub/player/player_a/games/"
    archives = [base + m for m in ("2026/06", "2026/07", "2026/08", "2026/09", "2026/10")]
    assert months_to_fetch(archives, None, "2026/08") == [base + "2026/10", base + "2026/09", base + "2026/08"]
    assert months_to_fetch(archives, "2026/10", "2026/01") == [base + "2026/10"]  # a later sync: last month on


# ---------------------------------------------------------------- the tolerance (FR-10.43, FR-11.15)


def test_qa_tolerance_mates_and_bounds() -> None:
    assert within_tolerance(Score(None, 2), Score(None, 5))  # a slower forced mate still counts
    assert not within_tolerance(Score(20, None), Score(None, -3))  # walking into a mate never counts
    assert within_tolerance(Score(40, None), Score(10, None), 30)  # exactly 30 cp worse: found
    assert not within_tolerance(Score(40, None), Score(9, None), 30)  # 31 cp worse: not found
    assert within_tolerance(Score(50, None), Score(50, None), 0)
    assert within_tolerance(Score(2000, None), Score(1100, None), 30)  # both clamped to +10


# ---------------------------------------------------------------- puzzle files (FR-10.46–10.49)


def test_qa_a_black_to_move_pgn_puzzle_is_solved_by_black() -> None:
    fen = "4k3/8/8/8/8/8/r7/4K3 b - - 0 1"
    out = parse_pgn_puzzles(f'[Event "Rook check"]\n[SetUp "1"]\n[FEN "{fen}"]\n\n1... Ra1+ 2. Kd2 *\n')
    assert isinstance(out[0], ImportedPuzzle) and out[0].player_color == "black"
    assert out[0].solution == ("a2a1",)  # cut to end on the solver's move


def test_qa_csv_quotes_and_move_numbers_in_the_solution() -> None:
    text = 'name,fen,solution\n"Mate, two rooks",6k1/5ppp/8/8/8/8/8/RR4K1 w - - 0 1,1. Ra8#\n'
    out = parse_csv(text)
    assert isinstance(out[0], ImportedPuzzle) and out[0].solution == ("a1a8",) and out[0].name == "Mate, two rooks"


def test_qa_an_epd_with_an_illegal_bm_is_reported_not_imported() -> None:
    out = parse_epd("6k1/5ppp/8/8/8/8/8/RR4K1 w - - bm Qh7#;\n6k1/5ppp/8/8/8/8/8/RR4K1 w - - bm Rb8#;\n")
    assert isinstance(out[0], EntryError) and out[0].n == 1
    assert isinstance(out[1], ImportedPuzzle) and out[1].solution == ("b1b8",)


@pytest.mark.xfail(strict=True, reason="v0.8-B2: entries past the 20,000-entry cap are dropped without a word")
def test_qa_entries_past_the_cap_are_reported() -> None:
    line = "6k1/5ppp/8/8/8/8/8/RR4K1 w - - bm Ra8#;"
    out = parse_epd("\n".join([line] * 5), max_entries=3)
    # Expected: the report says the file had more entries than the app takes (an error entry, or a count).
    assert len(out) > 3 and any(isinstance(e, EntryError) for e in out)
