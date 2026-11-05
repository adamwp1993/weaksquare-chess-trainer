"""Game digests (v0.11, FR-10.52). Pure: one short, deterministic record per game and side, built from the
stored v0.8 analysis (`MoveRow`s) with python-chess and no engine.

A digest holds the facts the whole-game measures (FR-10.53) and the LLM diagnosis (FR-10.54) need: the
opening, the key moments, castling and development, the pawn structure when the opening ends, trades while
ahead or behind, the endgame type, conversion from +2 and saves from −2, and summarised time use.

**Views.** Every eval here is from the digest's side ("you"), clamped to ±1000 like the grading. Plies in
a digest are **1-based** half-move numbers (FR-10.54, v0.11 planning); `MoveRow.ply` is 0-based.
**No raw clocks**: time is kept as a percentage of the starting time, and only at the key moments.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from itertools import pairwise
from typing import Any

import chess

from weaksquare.core.game_review import MoveRow, key_moments

DIGEST_VERSION = 1  # part of the stored analysis key: a new version rebuilds every digest
OPENING_END_PLY = 30  # "when the opening ends (around move 15)", FR-10.53
OPENING_ERROR_MOVES = 15  # errors in the first 15 moves, FR-10.53
HOLD_CP = 200  # +2 / −2 (FR-10.53)
TRADE_CP = 150  # "ahead" / "behind" for trades (the Missed / Allowed edge)
LATE_CASTLE_MOVE = 12  # habit:castledLate (v0.11 planning)
DEVELOPMENT_MOVE = 10  # minors developed by move 10, early queen moves (FR-10.52)
MAX_MOMENTS = 5  # stored; the prompt sends 3 at Summary and 5 at Detailed
SERIOUS = ("mistake", "blunder")
ENDGAME_TYPES = ("pawn", "rook", "minor", "queen", "mixed")


@dataclass(frozen=True)
class Moment:
    ply: int  # 1-based
    move: str  # numbered SAN, e.g. "23... Nf6"
    fen: str  # the position before your move
    played: str  # SAN
    best: str | None  # SAN, or None when the engine gave no move
    eval_before: int  # your view, clamped
    swing: int  # cp lost
    classification: str
    kind: str | None  # missed / allowed / other
    phase: str
    themes: tuple[str, ...] = ()
    clock_pct: int | None = None  # % of your starting time left after the move
    reason: str | None = None  # your mistake reason (§7.3)


@dataclass(frozen=True)
class PawnStructure:
    isolated: int = 0
    doubled: int = 0  # extra pawns on a file
    passed: int = 0
    iqp: bool = False  # an isolated d-pawn


@dataclass(frozen=True)
class TimeUse:
    clock_known: bool = False
    low_moves: int = 0  # your moves under 10% of your time
    low_errors: int = 0  # mistakes and blunders among them
    low_blunders: int = 0
    other_moves: int = 0
    other_errors: int = 0
    other_blunders: int = 0


@dataclass(frozen=True)
class Digest:
    color: str
    result: str | None  # win / loss / draw from your side
    eco: str | None
    opening: str | None
    family: str  # FR-10.53: the name before its first ':', else the ECO code, else "Unknown"
    plies: int
    moments: tuple[Moment, ...]
    # king safety and development
    castled_ply: int | None  # 1-based ply of your castling move
    opp_castled_ply: int | None
    moves_before_castling: int | None  # your moves before castling (None when you never castled)
    minors_developed: int  # your minor pieces off their start squares after your move 10 (or the end)
    early_queen_moves: int  # your queen moves among your first 10 moves
    castled_late: bool | None  # after move 12 or never, with the opponent's queen on; None if over by then
    # structure and trades
    structure: PawnStructure
    opp_structure: PawnStructure
    trades_ahead: int
    trades_behind: int
    # phases
    eval_opening_end: int | None  # your view after ply 30 (or the last ply if shorter)
    opening_errors: int  # your mistakes and blunders in the first 15 moves
    errors_by_phase: dict[str, int] = field(default_factory=dict)  # mistakes and blunders
    endgame: str | None = None  # one of ENDGAME_TYPES
    endgame_errors: int = 0
    held_plus2: bool = False
    held_minus2: bool = False
    time: TimeUse = TimeUse()

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, d: Mapping[str, Any]) -> Digest:
        data = dict(d)
        data["moments"] = tuple(
            Moment(**{**m, "themes": tuple(m.get("themes") or ())}) for m in data.get("moments") or ()
        )
        data["structure"] = PawnStructure(**(data.get("structure") or {}))
        data["opp_structure"] = PawnStructure(**(data.get("opp_structure") or {}))
        data["time"] = TimeUse(**(data.get("time") or {}))
        data["errors_by_phase"] = dict(data.get("errors_by_phase") or {})
        return cls(**data)


def opening_family(opening: str | None, eco: str | None) -> str:
    name = (opening or "").split(":", 1)[0].strip()
    if name and name != "?":
        return name
    code = (eco or "").strip()
    return code if code and code != "?" else "Unknown"


def result_for(result: str, color: str) -> str | None:
    if result == "1/2-1/2":
        return "draw"
    if result not in ("1-0", "0-1") or color not in ("white", "black"):
        return None
    return "win" if (result == "1-0") == (color == "white") else "loss"


def my_eval_after(row: MoveRow, color: str) -> int:
    v = row.eval_after.value()
    return v if row.mover == color else -v


def my_eval_before(row: MoveRow, color: str) -> int:
    v = row.eval_before.value()
    return v if row.mover == color else -v


def endgame_type(board: chess.Board) -> str | None:
    """The material signature, kings excluded (FR-10.52): pawns only, rooks, minor pieces or queens (each
    with pawns or not), or a mix. None for a bare-kings board."""
    kinds = {
        t for t in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN) for c in chess.COLORS if board.pieces(t, c)
    }
    if not kinds:
        pawns = any(board.pieces(chess.PAWN, c) for c in chess.COLORS)
        return "pawn" if pawns else None
    if kinds == {chess.ROOK}:
        return "rook"
    if kinds <= {chess.KNIGHT, chess.BISHOP}:
        return "minor"
    if kinds == {chess.QUEEN}:
        return "queen"
    return "mixed"


def pawn_structure(board: chess.Board, color: chess.Color) -> PawnStructure:
    mine = board.pieces(chess.PAWN, color)
    theirs = board.pieces(chess.PAWN, not color)
    files = [chess.square_file(s) for s in mine]
    count = {f: files.count(f) for f in set(files)}
    isolated = [s for s in mine if not ({chess.square_file(s) - 1, chess.square_file(s) + 1} & set(count))]
    passed = 0
    for s in mine:
        f, r = chess.square_file(s), chess.square_rank(s)
        step = 1 if color == chess.WHITE else -1
        blocked = any(abs(chess.square_file(t) - f) <= 1 and (chess.square_rank(t) - r) * step > 0 for t in theirs)
        passed += not blocked
    return PawnStructure(
        isolated=len(isolated),
        doubled=sum(n - 1 for n in count.values()),
        passed=passed,
        iqp=any(chess.square_file(s) == 3 for s in isolated),
    )


def _board_after(rows: Sequence[MoveRow], upto: int) -> chess.Board:
    """The board after the first `upto` moves (rows[upto - 1])."""
    if upto <= 0:
        return chess.Board(rows[0].fen_before)
    last = rows[min(upto, len(rows)) - 1]
    board = chess.Board(last.fen_before)
    board.push(chess.Move.from_uci(last.move_uci))
    return board


def numbered_san(row: MoveRow) -> str:
    """ "23. Nf3" or "23... Nf6": the move with its number, from its own position."""
    board = chess.Board(row.fen_before)
    n = board.fullmove_number
    return f"{n}. {row.move_san}" if row.mover == "white" else f"{n}... {row.move_san}"


def _san(fen: str, uci: str | None) -> str | None:
    if not uci:
        return None
    try:
        board = chess.Board(fen)
        move = chess.Move.from_uci(uci)
        return board.san(move) if move in board.legal_moves else None
    except ValueError:
        return None


def held(rows: Sequence[MoveRow], color: str, cp: int) -> bool:
    """FR-10.53, v0.11 planning: you held `cp` or better (−`cp` or worse when `cp` < 0) for a full move,
    after your move **and** after the reply, so a one-ply blip doesn't count."""
    for a, b in pairwise(rows):
        if a.mover != color:
            continue
        va, vb = my_eval_after(a, color), my_eval_after(b, color)
        if (cp > 0 and va >= cp and vb >= cp) or (cp < 0 and va <= cp and vb <= cp):
            return True
    return False


def _castling(rows: Sequence[MoveRow], side: str) -> int | None:
    for r in rows:
        if r.mover == side and r.move_san.startswith("O-O"):
            return r.ply + 1
    return None


def _development(rows: Sequence[MoveRow], color: str) -> tuple[int, int]:
    """(minor pieces off their start squares after your 10th move, queen moves in your first 10)."""
    mine = [r for r in rows if r.mover == color][:DEVELOPMENT_MOVE]
    queen = 0
    for r in mine:
        board = chess.Board(r.fen_before)
        piece = board.piece_at(chess.Move.from_uci(r.move_uci).from_square)
        queen += bool(piece and piece.piece_type == chess.QUEEN)
    if not mine:
        return 0, 0
    board = _board_after(rows, mine[-1].ply + 1)
    c = chess.WHITE if color == "white" else chess.BLACK
    starts = [chess.B1, chess.G1, chess.C1, chess.F1] if c == chess.WHITE else [chess.B8, chess.G8, chess.C8, chess.F8]
    minors = board.pieces(chess.KNIGHT, c) | board.pieces(chess.BISHOP, c)
    home = sum(1 for s in starts if s in minors)
    total = len(minors)
    return max(0, total - home), queen


def _castled_late(rows: Sequence[MoveRow], color: str, castled_ply: int | None) -> bool | None:
    """Not castled by your move 12 while the opponent still has a queen then; None if the game ended
    before your move 12."""
    mine = [r for r in rows if r.mover == color]
    if len(mine) < LATE_CASTLE_MOVE:
        return None
    twelfth = mine[LATE_CASTLE_MOVE - 1]
    if castled_ply is not None and castled_ply <= twelfth.ply + 1:
        return False
    board = _board_after(rows, twelfth.ply + 1)
    opp = chess.BLACK if color == "white" else chess.WHITE
    return bool(board.pieces(chess.QUEEN, opp))


def _trades(rows: Sequence[MoveRow], color: str) -> tuple[int, int]:
    """Captures recaptured on the same square on the next ply, while you were ahead (≥ +1.50) or behind
    (≤ −1.50) before the capture."""
    ahead = behind = 0
    for a, b in pairwise(rows):
        board = chess.Board(a.fen_before)
        move = chess.Move.from_uci(a.move_uci)
        if not board.is_capture(move):
            continue
        reply = chess.Move.from_uci(b.move_uci)
        if reply.to_square != move.to_square or not chess.Board(b.fen_before).is_capture(reply):
            continue
        v = my_eval_before(a, color)
        ahead += v >= TRADE_CP
        behind += v <= -TRADE_CP
    return ahead, behind


def _time(rows: Sequence[MoveRow], color: str) -> TimeUse:
    mine = [r for r in rows if r.mover == color and r.low_clock is not None]
    if not mine:
        return TimeUse()
    low = [r for r in mine if r.low_clock]
    other = [r for r in mine if not r.low_clock]
    return TimeUse(
        clock_known=True,
        low_moves=len(low),
        low_errors=sum(r.classification in SERIOUS for r in low),
        low_blunders=sum(r.classification == "blunder" for r in low),
        other_moves=len(other),
        other_errors=sum(r.classification in SERIOUS for r in other),
        other_blunders=sum(r.classification == "blunder" for r in other),
    )


def build_digest(
    *,
    rows: Sequence[MoveRow],
    color: str,
    result: str,
    eco: str | None,
    opening: str | None,
    base_seconds: int | None,
    reasons: Mapping[int, str] | None = None,
) -> Digest:
    """The digest of one analyzed game from `color`'s side. `result` is the PGN result; `reasons` maps a
    0-based ply to your mistake reason."""
    if color not in ("white", "black"):
        raise ValueError("a digest needs your color")
    rows = list(rows)
    reasons = reasons or {}
    c = chess.WHITE if color == "white" else chess.BLACK
    opp = "black" if color == "white" else "white"
    moments: list[Moment] = []
    for r in key_moments(rows, color, MAX_MOMENTS):
        clock_pct = None
        if r.clock_s is not None and base_seconds:
            clock_pct = max(0, min(100, round(100 * r.clock_s / base_seconds)))
        moments.append(
            Moment(
                ply=r.ply + 1,
                move=numbered_san(r),
                fen=r.fen_before,
                played=r.move_san,
                best=_san(r.fen_before, r.best_move),
                eval_before=r.eval_before.value(),
                swing=r.cp_loss,
                classification=r.classification,
                kind=r.kind,
                phase=r.phase,
                themes=tuple(r.themes),
                clock_pct=clock_pct,
                reason=reasons.get(r.ply),
            )
        )
    castled = _castling(rows, color) if rows else None
    opp_castled = _castling(rows, opp) if rows else None
    minors, queen = _development(rows, color) if rows else (0, 0)
    before_castling = None
    if castled is not None:
        before_castling = sum(1 for r in rows if r.mover == color and r.ply + 1 < castled)
    end_at = min(OPENING_END_PLY, len(rows))
    board_end = _board_after(rows, end_at) if rows else chess.Board()
    eval_end = my_eval_after(rows[end_at - 1], color) if rows else None
    mine = [r for r in rows if r.mover == color]
    serious = [r for r in mine if r.classification in SERIOUS]
    first_endgame = next((r for r in rows if r.phase == "endgame"), None)
    eg = endgame_type(chess.Board(first_endgame.fen_before)) if first_endgame else None
    ahead, behind = _trades(rows, color) if rows else (0, 0)
    return Digest(
        color=color,
        result=result_for(result, color),
        eco=eco if eco and eco != "?" else None,
        opening=opening or None,
        family=opening_family(opening, eco),
        plies=len(rows),
        moments=tuple(moments),
        castled_ply=castled,
        opp_castled_ply=opp_castled,
        moves_before_castling=before_castling,
        minors_developed=minors,
        early_queen_moves=queen,
        castled_late=_castled_late(rows, color, castled) if rows else None,
        structure=pawn_structure(board_end, c),
        opp_structure=pawn_structure(board_end, not c),
        trades_ahead=ahead,
        trades_behind=behind,
        eval_opening_end=eval_end,
        opening_errors=sum(1 for r in serious if r.ply < 2 * OPENING_ERROR_MOVES),
        errors_by_phase={p: sum(1 for r in serious if r.phase == p) for p in ("opening", "middlegame", "endgame")},
        endgame=eg,
        endgame_errors=sum(1 for r in serious if r.phase == "endgame") if eg else 0,
        held_plus2=held(rows, color, HOLD_CP),
        held_minus2=held(rows, color, -HOLD_CP),
        time=_time(rows, color),
    )
