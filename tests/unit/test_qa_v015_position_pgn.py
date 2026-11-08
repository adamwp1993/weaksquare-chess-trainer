"""QA v0.15 (independent). A test exposing an open bug is xfail (strict) with its ID. edge cases for FR-14.2 (core/position_setup) and FR-14.3 (core/analysis_pgn) that the
builder's tests don't cover. Invented data only."""

from __future__ import annotations

import chess
import pytest

from weaksquare.core.analysis_pgn import MAX_GAMES, parse_analysis_pgn
from weaksquare.core.games import GameError
from weaksquare.core.position_setup import check_fen
from weaksquare.core.study_pgn import walk

START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

# ---- FR-14.2 --------------------------------------------------------------------------------------------------


def test_qa_a_shredder_fen_of_a_standard_position_is_accepted_as_kqkq() -> None:
    c = check_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w HAha - 0 1")
    assert c.ok and c.fen == START


@pytest.mark.parametrize(
    "fen",
    [
        "bqnbrkrn/pppppppp/8/8/8/8/PPPPPPPP/BQNBRKRN w GEge - 0 1",  # Chess960 start, Shredder letters
        "bqnbrkrn/pppppppp/8/8/8/8/PPPPPPPP/BQNBRKRN w KQkq - 0 1",  # Chess960 start, X-FEN letters
    ],
)
def test_qa_chess960_castling_is_refused_with_the_castling_sentence(fen: str) -> None:
    c = check_fen(fen)
    assert not c.ok and c.fen is None and "castling right" in c.problems[0]


@pytest.mark.parametrize(
    "fen",
    [
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR[Qq] w KQkq - 0 1",  # Crazyhouse pocket
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 3+3 0 1",  # Three-check counter
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - -5 0",  # negative counters
        START + "‮",  # a bidi control
    ],
)
def test_qa_variant_and_malformed_fens_get_the_isnt_a_fen_message(fen: str) -> None:
    c = check_fen(fen)
    assert not c.ok and c.fen is None and "isn't a FEN" in c.problems[0]


def test_qa_an_en_passant_square_is_kept_only_when_the_capture_is_legal() -> None:
    can = check_fen("rnbqkbnr/ppp1pppp/8/3pP3/8/8/PPPP1PPP/RNBQKBNR w KQkq d6 0 3")
    assert can.ok and can.fen is not None and can.fen.split()[3] == "d6"
    cannot = check_fen("rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2")
    assert cannot.ok and cannot.fen is not None and cannot.fen.split()[3] == "-"


@pytest.mark.parametrize("fen", ["7k/5Q2/6K1/8/8/8/8/8 b - - 0 1", "7k/6Q1/6K1/8/8/8/8/8 b - - 0 1"])
def test_qa_stalemate_and_checkmate_are_legal_positions(fen: str) -> None:
    assert check_fen(fen).ok


def test_qa_every_problem_sentence_is_unique_and_ends_with_a_full_stop() -> None:
    from weaksquare.core.position_setup import _PROBLEMS

    texts = [t for _f, t in _PROBLEMS]
    assert len(set(texts)) == len(texts) and all(t.endswith(".") for t in texts)
    flags = [f for f, _t in _PROBLEMS]
    standard = (
        chess.STATUS_EMPTY | chess.STATUS_NO_WHITE_KING | chess.STATUS_NO_BLACK_KING | chess.STATUS_TOO_MANY_KINGS
        | chess.STATUS_TOO_MANY_WHITE_PAWNS | chess.STATUS_TOO_MANY_BLACK_PAWNS | chess.STATUS_PAWNS_ON_BACKRANK
        | chess.STATUS_TOO_MANY_WHITE_PIECES | chess.STATUS_TOO_MANY_BLACK_PIECES | chess.STATUS_BAD_CASTLING_RIGHTS
        | chess.STATUS_INVALID_EP_SQUARE | chess.STATUS_OPPOSITE_CHECK | chess.STATUS_TOO_MANY_CHECKERS
        | chess.STATUS_IMPOSSIBLE_CHECK
    )  # fmt: skip
    combined = 0
    for f in flags:
        combined |= f
    assert combined == standard  # every standard-chess status flag has its sentence


# ---- FR-14.3 --------------------------------------------------------------------------------------------------


def test_qa_nested_side_lines_and_glyphs_are_kept() -> None:
    games, skipped = parse_analysis_pgn(
        '[Event "x"]\n\n1. e4 $1 e5 (1... c5 2. Nf3 (2. c3 d5 (2... Nf6)) d6 $2) 2. Nf3 {ok [%clk 0:01:00] [%eval 0.3] move} Nc6 !? *'
    )
    assert skipped == []
    nodes = walk(games[0].root)
    sans = [n.san for n in nodes[1:]]
    assert sorted(sans) == sorted(["e4", "e5", "Nf3", "Nc6", "c5", "Nf3", "d6", "c3", "d5", "Nf6"])
    by_san = {n.san: n for n in nodes[1:]}
    assert by_san["e4"].nags == [1] and by_san["Nc6"].nags == [5]
    comments = " ".join(n.comment for n in nodes)
    assert "clk" not in comments and "eval" not in comments and "0:01:00" not in comments


def test_qa_a_set_up_fen_with_black_to_move_starts_there() -> None:
    games, _ = parse_analysis_pgn('[SetUp "1"]\n[FEN "4k3/4p3/8/8/8/8/8/4K3 b - - 0 1"]\n\n1... e5 2. Kd2 *')
    assert games[0].start_fen == "4k3/4p3/8/8/8/8/8/4K3 b - - 0 1" and games[0].move_count == 2


@pytest.mark.parametrize(
    ("text", "says"),
    [
        (
            '[Variant "Chess960"]\n[SetUp "1"]\n[FEN "bqnbrkrn/pppppppp/8/8/8/8/PPPPPPPP/BQNBRKRN w GEge - 0 1"]\n\n1. e4 *',
            "Chess960",
        ),
        ('[SetUp "1"]\n[FEN "bqnbrkrn/pppppppp/8/8/8/8/PPPPPPPP/BQNBRKRN w GEge - 0 1"]\n\n1. e4 *', "Chess960"),
        ('[Variant "Crazyhouse"]\n\n1. e4 d5 2. exd5 Qxd5 3. N@c3 *', "Crazyhouse"),
        ('[Variant "Atomic"]\n\n1. e4 *', "Atomic"),
        ('[SetUp "1"]\n[FEN "nonsense"]\n\n1. e4 *', "valid FEN"),
        ('[SetUp "1"]\n[FEN "4k3/8/8/8/8/8/8/4K2R w KQ - 0 1"]\n\n1. Kd1 *', "impossible position"),
        ("1. e4 e5 (1... Ke7 2. Ke3) 2. Nf3 *", "illegal or unreadable"),  # in a side line
        ("1. " + " ".join(["Nf3 Nf6 Ng1 Ng8"] * 1500), "too large"),
        ("{only a comment} *", "isn't a PGN"),
    ],
)
def test_qa_unusable_pgns_get_one_clear_message(text: str, says: str) -> None:
    with pytest.raises(GameError) as e:
        parse_analysis_pgn(text)
    assert says in e.value.reason


def test_qa_a_variant_header_of_from_position_is_standard_chess() -> None:
    games, _ = parse_analysis_pgn('[Variant "From Position"]\n[FEN "4k3/8/8/8/8/8/4P3/4K3 w - - 0 1"]\n\n1. e4 *')
    assert games[0].move_count == 1


def test_qa_a_bom_and_crlf_line_ends_are_read() -> None:
    games, _ = parse_analysis_pgn('﻿[Event "x"]\r\n\r\n1. e4 e5\r\n*')
    assert games[0].move_count == 2


def test_qa_markup_in_a_comment_stays_text_and_control_characters_go() -> None:
    games, _ = parse_analysis_pgn("1. e4 {<script>alert(1)</script> abc‮def\x00} *")
    comment = walk(games[0].root)[1].comment
    assert "<script>" in comment  # kept as text; the UI escapes it
    assert "‮" not in comment and "\x00" not in comment


def test_qa_five_hundred_games_list_the_first_two_hundred_and_say_so() -> None:
    many = "\n\n".join(f'[Event "g{i}"]\n[White "A{i}"]\n[Black "B"]\n\n1. e4 e5 *' for i in range(500))
    games, skipped = parse_analysis_pgn(many)
    assert len(games) == MAX_GAMES and any("more than 200" in s for s in skipped)


def test_qa_b1_a_null_move_that_leaves_a_king_in_check_is_refused() -> None:
    """v0.15-B1: a null move ("--") while in check lets the PGN capture the king; every move must be legal."""
    with pytest.raises(GameError):
        parse_analysis_pgn("1. e4 e5 2. Qh5 Nc6 3. Qxf7+ -- 4. Qxe8 *")


def test_qa_b1_no_position_in_an_imported_tree_is_illegal() -> None:
    """v0.15-B1: every node of an accepted game must be a position python-chess calls valid (else the board shows a
    position with no king, or one where the side not to move is in check)."""
    for text in ("1. e4 e5 2. Qh5 Nc6 3. Qxf7+ -- *", "1. e4 -- 2. d4 *"):
        try:
            games, _ = parse_analysis_pgn(text)
        except GameError:
            continue  # refusing the whole PGN is fine too
        start = chess.Board(games[0].start_fen)
        stack = [(games[0].root, start)]
        while stack:
            node, board = stack.pop()
            assert board.is_valid(), (text, board.fen())
            for child in node.children:
                b = board.copy()
                b.push(chess.Move.from_uci(child.uci))
                stack.append((child, b))


def test_qa_b5_the_pick_lists_move_count_is_the_main_line_only() -> None:
    """v0.15-B5: "N moves" in the pick list counts side-line moves too (the mock counts the main line only)."""
    games, _ = parse_analysis_pgn("1. e4 e5 (1... c5 2. Nf3 Nc6 3. Bb5) 2. Nf3 *")
    assert games[0].move_count == 3
