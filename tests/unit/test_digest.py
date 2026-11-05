"""Game digests (v0.11, FR-10.52): each field on small fixture games built with python-chess and
synthetic evals (no engine)."""

from __future__ import annotations

from collections.abc import Sequence

import chess
import pytest

from weaksquare.core.digest import (
    Digest,
    build_digest,
    endgame_type,
    held,
    opening_family,
    pawn_structure,
)
from weaksquare.core.engine import EngineLine
from weaksquare.core.game_review import MoveRow, grade_game


def make_rows(
    sans: Sequence[str],
    white_evals: Sequence[int] | None = None,
    *,
    fen: str = chess.STARTING_FEN,
    clocks: Sequence[float | None] = (),
    base: int | None = None,
) -> list[MoveRow]:
    """Graded rows for a SAN move list. `white_evals[i]` is the White-view eval of the position before
    move i (one more than the moves); the default is 0 everywhere."""
    board = chess.Board(fen)
    moves: list[str] = []
    for san in sans:
        move = board.parse_san(san)
        moves.append(move.uci())
        board.push(move)
    evals = list(white_evals) if white_evals is not None else [0] * (len(moves) + 1)
    assert len(evals) == len(moves) + 1
    analyses = [(EngineLine(cp=e, mate=None, pv=()),) for e in evals]
    low = (lambda s: s is not None and base is not None and s < 0.1 * base) if base else None
    return grade_game(fen, moves, analyses, clocks=clocks, low_clock_of=low)


def digest(rows: list[MoveRow], color: str = "white", result: str = "1-0", **kw: object) -> Digest:
    args: dict[str, object] = {"eco": "C50", "opening": "Italian Game: Giuoco Piano", "base_seconds": None}
    args.update(kw)
    return build_digest(rows=rows, color=color, result=result, **args)  # type: ignore[arg-type]


ITALIAN = ["e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5", "O-O", "Nf6", "d3", "O-O"]


def test_castling_move_and_moves_before_castling() -> None:
    d = digest(make_rows(ITALIAN))
    assert d.castled_ply == 7  # 4. O-O is White's 4th move: ply 7, 1-based
    assert d.opp_castled_ply == 10
    assert d.moves_before_castling == 3
    black = digest(make_rows(ITALIAN), color="black", result="0-1")
    assert black.castled_ply == 10 and black.moves_before_castling == 4 and black.result == "win"


def test_never_castled_has_no_count() -> None:
    d = digest(make_rows(["e4", "e5", "Nf3", "Nc6"]))
    assert d.castled_ply is None and d.moves_before_castling is None


def _late(castle: bool) -> list[str]:
    """Twelve White moves: knight shuffles with no castling, or castling on move 4 then rook shuffles."""
    if castle:
        return ["e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5", "O-O", "Nf6"] + ["Re1", "Rb8", "Rf1", "Ra8"] * 4
    return ["Nf3", "Nf6", "Ng1", "Ng8"] * 6


def test_castled_late_needs_twelve_moves_and_the_opponents_queen() -> None:
    assert digest(make_rows(_late(False))).castled_late is True
    assert digest(make_rows(_late(True))).castled_late is False
    assert digest(make_rows(["e4", "e5"])).castled_late is None  # over before move 12


def test_development_and_early_queen_moves() -> None:
    sans = ["e4", "e5", "Qh5", "Nc6", "Qf3", "Nf6", "Bc4", "Bc5", "Nc3", "d6"]
    d = digest(make_rows(sans))
    assert d.early_queen_moves == 2
    assert d.minors_developed == 2  # Bc4, Nc3


@pytest.mark.parametrize(
    ("fen", "kind"),
    [
        ("8/5k2/8/4p3/4P3/8/5K2/8 w - - 0 1", "pawn"),
        ("8/5k2/4r3/4p3/4P3/4R3/5K2/8 w - - 0 1", "rook"),
        ("8/5k2/4n3/4p3/4P3/4B3/5K2/8 w - - 0 1", "minor"),
        ("8/5k2/4q3/8/8/4Q3/5K2/8 w - - 0 1", "queen"),
        ("8/5k2/4r3/4p3/4P3/4B3/5K2/8 w - - 0 1", "mixed"),
        ("8/5k2/8/8/8/8/5K2/8 w - - 0 1", None),
    ],
)
def test_endgame_type_from_the_material_signature(fen: str, kind: str | None) -> None:
    assert endgame_type(chess.Board(fen)) == kind


def test_a_rook_endgame_game_records_its_type_and_errors() -> None:
    fen = "8/5k2/4r3/4p3/4P3/4R3/5K2/8 w - - 0 40"
    # White blunders on the second move: +0 → −3 after Rf3+ … (synthetic evals)
    rows = make_rows(["Kg3", "Kg7", "Rd3", "Rf6"], [0, 0, 0, -300, -300], fen=fen)
    assert all(r.phase == "endgame" for r in rows)
    d = digest(rows, result="0-1")
    assert d.endgame == "rook" and d.endgame_errors == 1 and d.errors_by_phase["endgame"] == 1


def test_conversion_from_plus_two_needs_a_full_move() -> None:
    sans = ITALIAN
    held_evals = [0, 0, 0, 0, 0, 250, 250, 260, 0, 0, 0]  # after move 5 (W) and 6 (B) both ≥ +2
    blip = [0, 0, 0, 0, 0, 250, 0, 0, 0, 0, 0]  # only after White's move
    assert digest(make_rows(sans, held_evals), result="1/2-1/2").held_plus2 is True
    assert digest(make_rows(sans, blip)).held_plus2 is False
    assert held(make_rows(sans, held_evals), "white", 200)


def test_save_from_minus_two() -> None:
    evals = [0, 0, 0, 0, 0, -250, -250, -260, 0, 0, 0]
    d = digest(make_rows(ITALIAN, evals), result="1/2-1/2")
    assert d.held_minus2 is True and d.result == "draw"
    assert digest(make_rows(ITALIAN, evals), color="black", result="1/2-1/2").held_plus2 is True


def test_low_clock_blunders_and_clock_percentages() -> None:
    evals = [0, 0, 0, 0, 0, -300, -300, -300, -300, -300, -300]
    clocks = [600, 600, 590, 580, 30, 570, 20, 560, 10, 550]  # White's 3rd move under 10% of 600 s
    d = digest(make_rows(ITALIAN, evals, clocks=clocks, base=600), base_seconds=600)
    assert d.time.clock_known
    assert d.time.low_moves == 3 and d.time.low_blunders == 1 and d.time.low_errors == 1
    assert d.time.other_moves == 2 and d.time.other_errors == 0
    (m,) = d.moments
    assert m.ply == 5 and m.move == "3. Bc4" and m.classification == "blunder" and m.clock_pct == 5


def test_no_clock_data() -> None:
    d = digest(make_rows(ITALIAN))
    assert d.time.clock_known is False


def test_key_moments_are_numbered_and_carry_reasons() -> None:
    evals = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 300]  # Black's 5th move (… O-O, ply 10) loses 3
    d = digest(make_rows(ITALIAN, evals), color="black", result="1-0", reasons={9: "didntLook"})
    (m,) = d.moments
    assert (m.ply, m.move, m.played, m.reason, d.result) == (10, "5... O-O", "O-O", "didntLook", "loss")


def test_opening_end_eval_and_opening_errors() -> None:
    evals = [0, 0, 0, -150, -150, -150, -150, -150, -150, -150, -150]
    d = digest(make_rows(ITALIAN, evals))
    assert d.eval_opening_end == -150  # shorter than 30 plies: the last position
    assert d.opening_errors == 1


@pytest.mark.parametrize(
    ("fen", "white"),
    [
        ("4k3/8/8/8/3P4/8/8/4K3 w - - 0 1", (1, 0, 1, True)),  # an isolated, passed d-pawn
        ("4k3/8/8/8/8/2P5/2P5/4K3 w - - 0 1", (2, 1, 2, False)),  # doubled c-pawns: isolated and passed
        ("4k3/2p5/8/8/3PP3/8/8/4K3 w - - 0 1", (0, 0, 1, False)),  # e-pawn passed; c7 guards d-pawn
    ],
)
def test_pawn_structure(fen: str, white: tuple[int, int, int, bool]) -> None:
    s = pawn_structure(chess.Board(fen), chess.WHITE)
    assert (s.isolated, s.doubled, s.passed, s.iqp) == white


def test_trades_while_ahead_or_behind() -> None:
    sans = ["e4", "d5", "exd5", "Qxd5", "Nc3", "Qa5"]
    ahead = digest(make_rows(sans, [0, 0, 200, 200, 0, 0, 0]))
    behind = digest(make_rows(sans, [0, 0, -200, -200, 0, 0, 0]))
    even = digest(make_rows(sans))
    assert (ahead.trades_ahead, ahead.trades_behind) == (1, 0)
    assert (behind.trades_ahead, behind.trades_behind) == (0, 1)
    assert (even.trades_ahead, even.trades_behind) == (0, 0)


@pytest.mark.parametrize(
    ("opening", "eco", "family"),
    [
        ("Sicilian Defense: Najdorf Variation", "B90", "Sicilian Defense"),
        ("Queen's Gambit Declined", "D30", "Queen's Gambit Declined"),
        (None, "C00", "C00"),
        (None, None, "Unknown"),
        ("?", "?", "Unknown"),
    ],
)
def test_opening_family(opening: str | None, eco: str | None, family: str) -> None:
    assert opening_family(opening, eco) == family


def test_round_trips_through_json() -> None:
    evals = [0, 0, 0, 0, -300, -300, -300, -300, -300, -300, -300]
    d = digest(make_rows(ITALIAN, evals, clocks=[600] * 10, base=600), base_seconds=600)
    assert Digest.from_json(d.to_json()) == d


def test_needs_a_color() -> None:
    with pytest.raises(ValueError):
        digest(make_rows(ITALIAN), color="both")
