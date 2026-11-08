"""Game Review grading (v0.8, REQUIREMENTS §11.2–11.3). Pure: the analysis service asks the engine for the
top lines of every position, and this module turns them into per-move rows, symbols, key moments and
the per-side summary.

**Scores** are `Score(cp, mate)` from one side's view, positive = good for that side. In an `eval_after`,
`mate == 0` means the mover has just delivered checkmate (the mover can't be mated by their own move).
For cp loss, scores are clamped to ±1000 and a mate counts as ±1000 (plan v0.8).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal

import chess

from weaksquare.core.engine import EngineLine, score_for

Classification = Literal["best", "good", "inaccuracy", "mistake", "blunder"]
Kind = Literal["missed", "allowed", "other"]
Phase = Literal["opening", "middlegame", "endgame"]
CLASSIFICATIONS: tuple[str, ...] = ("best", "good", "inaccuracy", "mistake", "blunder")
ERRORS: tuple[str, ...] = ("inaccuracy", "mistake", "blunder")
SYMBOLS = {"inaccuracy": "?!", "mistake": "?", "blunder": "??"}
CLAMP = 1000
EDGE = 150  # Missed / Allowed: "a winning edge" (plan v0.8, refined in v0.10)
MAX_SAVED_PLAYER_MOVES = 3  # plan v0.8: a saved line is cut to at most 3 of your moves


@dataclass(frozen=True)
class Score:
    cp: int | None = None
    mate: int | None = None

    def value(self) -> int:
        """Centipawns clamped to ±CLAMP; a mate (or a delivered mate, `mate == 0`) is ±CLAMP."""
        if self.mate is not None:
            return -CLAMP if self.mate < 0 else CLAMP
        return max(-CLAMP, min(CLAMP, self.cp or 0))

    def negate(self) -> Score:
        if self.mate is not None:
            return Score(None, -self.mate)
        return Score(-(self.cp or 0), None)

    def to_json(self) -> dict[str, int]:
        return {"mate": self.mate} if self.mate is not None else {"cp": self.cp or 0}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Score:
        if isinstance(data.get("mate"), int):
            return cls(None, int(data["mate"]))
        return cls(int(data.get("cp") or 0), None)


@dataclass(frozen=True)
class Thresholds:
    """FR-11.9, shared with the Coach: configurable."""

    inaccuracy: int = 50
    mistake: int = 100
    blunder: int = 200
    decided: int = 500

    def validate(self) -> None:
        if not (0 < self.inaccuracy < self.mistake < self.blunder <= 2000) or not (100 <= self.decided <= CLAMP):
            raise ValueError("thresholds must rise: inaccuracy < mistake < blunder, and 'decided' within 100–1000")


DEFAULT_THRESHOLDS = Thresholds()


@dataclass(frozen=True)
class MoveRow:
    """One graded move: a `game_analysis` row. `lines` are the top lines from `fen_before`."""

    ply: int  # 0-based index into the game's moves
    fen_before: str
    move_uci: str
    move_san: str
    mover: str
    eval_before: Score
    eval_after: Score
    best_move: str | None
    lines: tuple[EngineLine, ...]
    refutation: tuple[str, ...]  # FR-11.14: the best line after the move
    cp_loss: int
    classification: str
    kind: str | None
    phase: str
    low_clock: bool | None
    clock_s: float | None
    themes: tuple[str, ...] = ()  # v0.10: lichess-puzzler themes of a Missed / Allowed line (FR-10.12)
    habits: tuple[str, ...] = ()  # v0.10: habit tags (FR-10.27)


def _is_decided(before: int, after: int, th: Thresholds) -> bool:
    """FR-11.9: positions already decided aren't penalized: still winning after the move, or lost
    before it."""
    return (before >= th.decided and after >= th.decided) or (before <= -th.decided and after <= -th.decided)


def _mate_swing(before: Score, after: Score, th: Thresholds) -> bool:
    """Walking into a forced mate from a position that wasn't lost, or giving up your own forced mate
    for a position that isn't winning."""
    allowed_mate = after.mate is not None and after.mate < 0 and not (before.mate is not None and before.mate < 0)
    lost_mate = before.mate is not None and before.mate > 0 and after.value() < th.decided
    return (allowed_mate and before.value() > -th.decided) or lost_mate


def grade(before: Score, after: Score, played_best: bool, th: Thresholds) -> tuple[int, str]:
    """(cp loss, classification) for one move, both scores from the mover's view (FR-11.9)."""
    b, a = before.value(), after.value()
    if played_best:
        return 0, "best"
    if _mate_swing(before, after, th):
        return max(0, b - a), "blunder"
    if _is_decided(b, a, th):
        return 0, "good"
    loss = max(0, b - a)
    if loss >= th.blunder:
        return loss, "blunder"
    if loss >= th.mistake:
        return loss, "mistake"
    if loss >= th.inaccuracy:
        return loss, "inaccuracy"
    return loss, "good"


def missed_or_allowed(before: Score, after: Score, classification: str) -> str | None:
    """FR-10.11 for mistakes and blunders: **Missed** when your best move kept a winning edge; otherwise
    **Allowed** when the opponent's best reply is winning for them; else Other. One exception (v0.10-B2):
    a move that walks into a forced mate is **Allowed** even from a winning position, since that mate is
    what decided the game."""
    if classification not in ("mistake", "blunder"):
        return None
    if after.mate is not None and after.mate < 0:
        return "allowed"
    if before.value() >= EDGE:
        return "missed"
    if after.value() <= -EDGE:
        return "allowed"
    return "other"


def _pieces(board: chess.Board) -> int:
    """Non-pawn, non-king pieces on the board (both sides; 14 at the start)."""
    return sum(
        len(board.pieces(t, c)) for t in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN) for c in chess.COLORS
    )


def phase_of(board: chess.Board, ply: int, division: dict[str, int] | None) -> str:
    """Lichess's `division` (the plies where the middlegame and endgame start) when the export has it;
    otherwise a rule (plan v0.8): the opening is moves 1–10 while at least 13 pieces remain; the endgame
    has 6 or fewer pieces; everything else is the middlegame."""
    if division:
        end, middle = division.get("end"), division.get("middle")
        if end is not None and ply + 1 >= end:
            return "endgame"
        if middle is not None and ply + 1 < middle:
            return "opening"
        if middle is not None or end is not None:
            return "middlegame"
    n = _pieces(board)
    if n <= 6:
        return "endgame"
    if ply // 2 + 1 <= 10 and n >= 13:
        return "opening"
    return "middlegame"


def _position_score(lines: Sequence[EngineLine] | None, board: chess.Board, view: str) -> Score:
    """The score of `board` from `view`'s side. With no lines, the game is over: a checkmate is a mate
    delivered by the side that just moved; anything else (stalemate, draw) is 0."""
    if lines:
        cp, mate = score_for(lines[0], "white" if view == "white" else "black")
        return Score(cp, mate)
    if board.is_checkmate():
        mated = "white" if board.turn == chess.WHITE else "black"
        return Score(None, 0) if mated != view else Score(None, -1)
    return Score(0, None)


def grade_game(
    start_fen: str,
    moves: Sequence[str],
    analyses: Sequence[Sequence[EngineLine] | None],
    *,
    clocks: Sequence[float | None] = (),
    low_clock_of: Any = None,
    division: dict[str, int] | None = None,
    th: Thresholds = DEFAULT_THRESHOLDS,
) -> list[MoveRow]:
    """Every move graded. `analyses[i]` holds the top lines of the position before move i, and
    `analyses[len(moves)]` those of the final position (None when the game is over there).
    `low_clock_of(seconds)` decides whether a clock reading is low (None without clock data)."""
    if len(analyses) != len(moves) + 1:
        raise ValueError("need one analysis per position, the final one included")
    board = chess.Board(start_fen)
    rows: list[MoveRow] = []
    for i, uci in enumerate(moves):
        move = chess.Move.from_uci(uci)
        mover = "white" if board.turn == chess.WHITE else "black"
        lines = tuple(analyses[i] or ())
        fen = board.fen()
        san = board.san(move)
        phase = phase_of(board, i, division)
        before = _position_score(lines, board, mover)
        best = lines[0].pv[0] if lines and lines[0].pv else None
        board.push(move)
        after = _position_score(analyses[i + 1], board, mover)
        nxt = analyses[i + 1]
        refutation = tuple(nxt[0].pv) if nxt and nxt[0].pv else ()
        loss, cls = grade(before, after, best == uci, th)
        clock = clocks[i] if i < len(clocks) else None
        rows.append(
            MoveRow(
                ply=i,
                fen_before=fen,
                move_uci=uci,
                move_san=san,
                mover=mover,
                eval_before=before,
                eval_after=after,
                best_move=best,
                lines=lines,
                refutation=refutation,
                cp_loss=loss,
                classification=cls,
                kind=missed_or_allowed(before, after, cls),
                phase=phase,
                low_clock=low_clock_of(clock) if low_clock_of is not None else None,
                clock_s=clock,
            )
        )
    return rows


def regrade(row: MoveRow, th: Thresholds) -> MoveRow:
    """The same move graded with other thresholds (v0.8-B1): only the stored evals are needed."""
    loss, cls = grade(row.eval_before, row.eval_after, row.best_move == row.move_uci, th)
    return replace(row, cp_loss=loss, classification=cls, kind=missed_or_allowed(row.eval_before, row.eval_after, cls))


def saved_line(pv: Sequence[str], max_player_moves: int = MAX_SAVED_PLAYER_MOVES) -> tuple[str, ...]:
    """The solution of a saved puzzle: the engine's best line from your position, cut to whole moves of
    yours (it ends on your move) and at most `max_player_moves` of them."""
    line = tuple(pv[: 2 * max_player_moves - 1])
    if len(line) % 2 == 0:
        line = line[:-1]
    return line


def white_eval(row: MoveRow) -> int:
    """The eval after the move from White's side, clamped: one point of the eval graph (FR-11.12)."""
    v = row.eval_after.value()
    return v if row.mover == "white" else -v


def key_moments(rows: Sequence[MoveRow], color: str, n: int = 5) -> list[MoveRow]:
    """FR-11.13: the side's `n` largest cp losses that are at least inaccuracies, in game order."""
    errs = [r for r in rows if r.mover == color and r.classification in ERRORS]
    top = sorted(errs, key=lambda r: (-r.cp_loss, r.ply))[: max(0, n)]
    return sorted(top, key=lambda r: r.ply)


@dataclass(frozen=True)
class PhaseSummary:
    moves: int
    inaccuracies: int
    mistakes: int
    blunders: int
    avg_cp_loss: float | None


@dataclass(frozen=True)
class SideSummary:
    """FR-11.11 for one side."""

    color: str
    moves: int
    inaccuracies: int
    mistakes: int
    blunders: int
    avg_cp_loss: float | None
    platform_accuracy: float | None
    by_phase: dict[str, PhaseSummary]
    low_clock_errors: int | None  # mistakes and blunders on a low clock; None without clock data


def _phase_summary(rows: list[MoveRow]) -> PhaseSummary:
    return PhaseSummary(
        moves=len(rows),
        inaccuracies=sum(r.classification == "inaccuracy" for r in rows),
        mistakes=sum(r.classification == "mistake" for r in rows),
        blunders=sum(r.classification == "blunder" for r in rows),
        avg_cp_loss=round(sum(r.cp_loss for r in rows) / len(rows), 1) if rows else None,
    )


def side_summary(rows: Sequence[MoveRow], color: str, platform_accuracy: float | None = None) -> SideSummary:
    mine = [r for r in rows if r.mover == color]
    total = _phase_summary(mine)
    clocked = [r for r in mine if r.low_clock is not None]
    return SideSummary(
        color=color,
        moves=total.moves,
        inaccuracies=total.inaccuracies,
        mistakes=total.mistakes,
        blunders=total.blunders,
        avg_cp_loss=total.avg_cp_loss,
        platform_accuracy=platform_accuracy,
        by_phase={p: _phase_summary([r for r in mine if r.phase == p]) for p in ("opening", "middlegame", "endgame")},
        low_clock_errors=(
            sum(1 for r in clocked if r.low_clock and r.classification in ("mistake", "blunder")) if clocked else None
        ),
    )


# ---- v0.14: the review in three parts (FR-11.36) --------------------------------------------------------------------
# Summary and What you did well, from the stored analysis only (no engine run, no AI), so they work with no AI key.
# Every strength names a move you played and a fact the engine measured; nothing is praised that the numbers don't show.
ONLY_MOVE_GAP = 150  # the engine's second choice is at least this much worse (cp, from your side)
HARD_DEFENCE = -150  # an eval this bad or worse before your move
CONVERT_FROM = 200  # reached this...
CONVERT_KEEP = 100  # ...and never fell below this afterwards
CLEAN_PHASE_MOVES = 8
MAX_PER_KIND = 3
MAX_STRENGTHS = 8

StrengthKind = Literal["only_move", "punished", "defence", "conversion", "clean_phase"]


@dataclass(frozen=True)
class Strength:
    kind: StrengthKind
    ply: int | None  # the move it's about (None for a whole phase)
    text: str


@dataclass(frozen=True)
class GameStory:
    color: str
    result: str  # won / lost / drawn / unfinished, from your side
    summary: tuple[str, ...]  # plain sentences
    strengths: tuple[Strength, ...]


def move_label(ply: int, san: str, start_fullmove: int = 1, black_first: bool = False) -> str:
    """'12. Nf3' or '12... Nf3' for 0-based `ply` in a game starting at `start_fullmove`."""
    offset = ply + (1 if black_first else 0)
    number = start_fullmove + offset // 2
    return f"{number}. {san}" if offset % 2 == 0 else f"{number}... {san}"


def _result_for(result: str, color: str) -> str:
    if result == "1/2-1/2":
        return "drawn"
    if result in ("1-0", "0-1"):
        return "won" if (result == "1-0") == (color == "white") else "lost"
    return "unfinished"


def _line_value(line: EngineLine, mover: str) -> int:
    v = (CLAMP if line.mate > 0 else -CLAMP) if line.mate is not None else max(-CLAMP, min(CLAMP, line.cp or 0))
    return v if mover == "white" else -v


def _yours_after(r: MoveRow, color: str) -> int:
    """The eval after this move from `color`'s side."""
    v = r.eval_after.value()
    return v if r.mover == color else -v


def _pawns(cp: int) -> str:
    return f"{cp / 100:.1f}"


def _count(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def game_story(
    rows: Sequence[MoveRow],
    color: str,
    result: str,
    platform_accuracy: float | None = None,
    th: Thresholds = DEFAULT_THRESHOLDS,
    label: Callable[[int, str], str] | None = None,
) -> GameStory:
    """FR-11.36: Summary and What you did well for `color`. `label(ply, san)` writes a move ('12... Nf3')."""
    lab = label or move_label
    outcome = _result_for(result, color)
    summary = side_summary(rows, color, platform_accuracy)
    lines: list[str] = []
    verb = {"won": "You won", "lost": "You lost", "drawn": "You drew", "unfinished": "The game wasn't finished"}[
        outcome
    ]
    detail = []
    if platform_accuracy is not None:
        detail.append(f"accuracy {platform_accuracy:.0f}%")
    if summary.avg_cp_loss is not None:
        detail.append(f"an average loss of {summary.avg_cp_loss:.0f} centipawns a move")
    lines.append(verb + (f", with {' and '.join(detail)}." if detail else "."))
    lines.append(
        f"Stockfish found {_count(summary.inaccuracies, 'inaccuracy', 'inaccuracies')}, "
        f"{_count(summary.mistakes, 'mistake', 'mistakes')} and {_count(summary.blunders, 'blunder', 'blunders')} "
        "in your moves."
    )
    swings = [r for r in rows if r.classification in ("mistake", "blunder")]
    if swings:
        t = max(swings, key=lambda r: (r.cp_loss, -r.ply))
        who = "your" if t.mover == color else "your opponent's"
        lines.append(
            f"The turning point: {lab(t.ply, t.move_san)}, {who} {t.classification}, which cost {_pawns(t.cp_loss)}."
        )
    else:
        lines.append("No big swings: neither side made a mistake or a blunder.")
    verdicts = []
    for phase in ("opening", "middlegame", "endgame"):
        ps = summary.by_phase.get(phase)
        if not ps or not ps.moves:
            continue
        if ps.blunders:
            verdicts.append(f"the {phase} had {_count(ps.blunders, 'blunder', 'blunders')}")
        elif ps.mistakes:
            verdicts.append(f"the {phase} had {_count(ps.mistakes, 'mistake', 'mistakes')}")
        else:
            verdicts.append(f"the {phase} was clean")
    if verdicts:
        text = ", ".join(verdicts)
        lines.append(text[0].upper() + text[1:] + ".")
    return GameStory(color, outcome, tuple(lines), tuple(_strengths(rows, color, outcome, th, lab)))


def _strengths(
    rows: Sequence[MoveRow], color: str, outcome: str, th: Thresholds, lab: Callable[[int, str], str]
) -> list[Strength]:
    by_ply = {r.ply: r for r in rows}
    only: list[tuple[int, Strength]] = []
    punished: list[tuple[int, Strength]] = []
    defence: list[tuple[int, Strength]] = []
    for r in rows:
        if r.mover != color:
            continue
        before = r.eval_before.value()
        live = -th.decided < before < th.decided
        # Only move found: you played the engine's best, and its second choice was much worse.
        if live and r.best_move == r.move_uci and len(r.lines) >= 2:
            gap = _line_value(r.lines[0], color) - _line_value(r.lines[1], color)
            if gap >= ONLY_MOVE_GAP:
                text = (
                    f"{lab(r.ply, r.move_san)}: you found the only good move. "
                    f"Anything else was at least {_pawns(gap)} worse."
                )
                only.append((gap, Strength("only_move", r.ply, text)))
        # Mistake punished: right after your opponent's mistake or blunder, you kept what it gave you.
        prev = by_ply.get(r.ply - 1)
        if (
            prev is not None
            and prev.mover != color
            and prev.classification in ("mistake", "blunder")
            and -th.decided < prev.eval_before.value() < th.decided
            and r.cp_loss < th.inaccuracy
        ):
            text = (
                f"{lab(r.ply, r.move_san)}: you punished your opponent's {prev.classification} "
                f"{lab(prev.ply, prev.move_san)} straight away."
            )
            punished.append((prev.cp_loss, Strength("punished", r.ply, text)))
        # Hard defence: a bad position, and you still found a best or good move.
        if -th.decided < before <= HARD_DEFENCE and r.classification in ("best", "good"):
            text = f"{lab(r.ply, r.move_san)}: a good defensive move in a difficult position ({_pawns(before)})."
            defence.append((-before, Strength("defence", r.ply, text)))
    out: list[Strength] = []
    for found in (only, punished, defence):
        out += [s for _, s in sorted(found, key=lambda x: -x[0])[:MAX_PER_KIND]]
    # Conversion: you reached a clear advantage and won without letting it slip.
    if outcome == "won":
        values = [_yours_after(r, color) for r in rows]
        for i, r in enumerate(rows):
            if r.mover == color and values[i] >= CONVERT_FROM and min(values[i:]) >= CONVERT_KEEP:
                text = (
                    f"From {lab(r.ply, r.move_san)} you were clearly better, and you converted it "
                    "without letting the advantage slip."
                )
                out.append(Strength("conversion", r.ply, text))
                break
    # Clean phase: enough moves with no mistake or blunder.
    phases: dict[str, list[MoveRow]] = {}
    for r in rows:
        if r.mover == color:
            phases.setdefault(r.phase, []).append(r)
    for phase in ("opening", "middlegame", "endgame"):
        mine = phases.get(phase, [])
        if len(mine) >= CLEAN_PHASE_MOVES and not any(r.classification in ("mistake", "blunder") for r in mine):
            out.append(
                Strength("clean_phase", None, f"A clean {phase}: {len(mine)} moves without a mistake or blunder.")
            )
    out.sort(key=lambda s: s.ply if s.ply is not None else 10_000)
    return out[:MAX_STRENGTHS]
