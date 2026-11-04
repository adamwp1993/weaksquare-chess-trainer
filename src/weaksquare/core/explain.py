"""Explain (§9.2, FR-8.2–8.4, 8.7): the grounded context, the answer's schema, and validation.

Pure. The LLM explains; it doesn't calculate. It gets an **allowlist** of facts (SR-11): the position, the
solution (SAN and UCI), the themes, your moves, Stockfish's lines and refutation, and attack/defense facts
from python-chess. It never gets the puzzle ID, its rating, any username, setting or error text.

Its answer is **untrusted** (CLAUDE.md): `validate` replays everything against the real position.
- A step must name the solution move at its ply, or the whole step is dropped.
- A variation must be legal move by move from the position after that step's move, or it's dropped.
- Annotations need valid squares and a known color.
- Text is capped and stripped of control characters.

Every dropped item is counted, so the UI can say "some annotations were discarded" (FR-8.4).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

import chess

from weaksquare.core.chess_rules import start_position

SQUARE = re.compile(r"[a-h][1-8]")
COLORS = ("green", "red", "blue", "yellow")
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MAX_SUMMARY, MAX_TEXT, MAX_IDEA, MAX_IDEAS = 1200, 700, 60, 6
MAX_ANNOTATIONS, MAX_VARIATION = 6, 8
ENGINE_PLIES = 8  # how much of each engine line goes into the prompt

PIECE_NAMES = {chess.PAWN: "pawn", chess.KNIGHT: "knight", chess.BISHOP: "bishop", chess.ROOK: "rook",
               chess.QUEEN: "queen", chess.KING: "king"}  # fmt: skip

SCHEMA_NAME = "puzzle_explanation"
# Strict-mode compatible for both providers: every property required, no extra properties, `to` nullable.
SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "steps", "key_ideas"],
    "properties": {
        "summary": {"type": "string"},
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["ply", "move", "text", "annotations", "variation"],
                "properties": {
                    "ply": {"type": "integer"},
                    "move": {"type": "string"},
                    "text": {"type": "string"},
                    "annotations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["type", "from", "to", "color"],
                            "properties": {
                                "type": {"type": "string", "enum": ["arrow", "circle"]},
                                "from": {"type": "string"},
                                "to": {"type": ["string", "null"]},
                                "color": {"type": "string", "enum": list(COLORS)},
                            },
                        },
                    },
                    "variation": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "key_ideas": {"type": "array", "items": {"type": "string"}},
    },
}

SYSTEM_PROMPT = """You are a chess coach explaining a tactics puzzle to the player who just tried it.

Rules:
- Use ONLY the moves, pieces and evaluations given in the facts. Never invent a move, a piece or a square.
  If the facts don't settle something, say less rather than guess.
- Write one step per solution ply, in order. "ply" is the number given in the solution list, and "move" is
  that ply's SAN exactly as given.
- "text": 1–3 plain sentences on why the move works (or, for the opponent's moves, why it's forced or best).
  Speak to the player as "you". Plain text only: no markdown, no HTML.
- "annotations": up to 4 arrows or circles that show the idea on the board in the position before that
  ply's move. An arrow has "from" and "to" squares; a circle has its square in "from" and "to": null.
  Colors: green for the good move, red for threats or what goes wrong, blue for lines and attacks, yellow for key squares.
- "variation": optional, up to 6 SAN moves starting right after this ply's move, only when a short line
  (for example, a defence that fails) makes the idea clearer. Use only legal moves. Otherwise [].
- "summary": 2–3 sentences: the main idea and, if the player went wrong, why their move failed.
- "key_ideas": 1–4 short tactic names (for example "deflection", "overloaded defender")."""


# ---- inputs (plain data from the session; no IDs, ratings or names) -------------------------------------


@dataclass(frozen=True)
class EngineLineFact:
    score: str  # from your side: "+3.2 for you"
    pv: tuple[str, ...]  # UCI from the start position


@dataclass(frozen=True)
class RefutationFact:
    fen_before: str
    wrong_move: str  # UCI
    line: tuple[str, ...]  # the reply line after it
    score: str | None


@dataclass(frozen=True)
class DangerFact:
    candidate: str  # UCI, played from the puzzle's raw FEN (the blunderer's position)
    is_safe: bool
    call: Literal["safe", "unsafe"] | None


@dataclass(frozen=True)
class ExplainInput:
    fen: str  # the puzzle's FEN: before the opponent's move (§4.2)
    moves: tuple[str, ...]  # UCI; moves[0] is the opponent's
    themes: tuple[str, ...]  # display names
    engine_lines: tuple[EngineLineFact, ...] = ()
    refutation: RefutationFact | None = None
    entered_line: tuple[str, ...] | None = None  # Commit the line: what you submitted (UCI)
    solved: bool = False
    danger: DangerFact | None = None


# ---- the result -----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Annotation:
    kind: Literal["arrow", "circle"]
    orig: str
    dest: str | None
    color: str


@dataclass(frozen=True)
class Step:
    ply: int  # 0 = your first move (puzzle.moves[1])
    side: Literal["you", "opponent"]
    san: str
    uci: str
    text: str
    annotations: tuple[Annotation, ...]
    variation: tuple[str, ...]  # SAN, legal from the position after this ply


@dataclass(frozen=True)
class Explanation:
    summary: str
    steps: tuple[Step, ...]
    key_ideas: tuple[str, ...]
    discarded: int = 0  # annotations, variations and steps dropped by validation (FR-8.4)

    def to_json(self) -> str:
        return json.dumps(
            {
                "summary": self.summary,
                "steps": [
                    {"ply": s.ply, "side": s.side, "san": s.san, "uci": s.uci, "text": s.text,
                     "annotations": [{"kind": a.kind, "orig": a.orig, "dest": a.dest, "color": a.color}
                                     for a in s.annotations],
                     "variation": list(s.variation)}
                    for s in self.steps
                ],
                "key_ideas": list(self.key_ideas),
                "discarded": self.discarded,
            },
            separators=(",", ":"),
        )  # fmt: skip

    @classmethod
    def from_json(cls, text: str) -> Explanation:
        """A cached, already-validated result (llm_cache)."""
        d = json.loads(text)
        steps = tuple(
            Step(s["ply"], s["side"], s["san"], s["uci"], s["text"],
                 tuple(Annotation(a["kind"], a["orig"], a["dest"], a["color"]) for a in s["annotations"]),
                 tuple(s["variation"]))
            for s in d["steps"]
        )  # fmt: skip
        return cls(d["summary"], steps, tuple(d["key_ideas"]), int(d["discarded"]))


# ---- the context (FR-8.2) ------------------------------------------------------------------------------


@dataclass
class _Ply:
    index: int
    side: Literal["you", "opponent"]
    board_before: chess.Board
    move: chess.Move
    san: str


def _solution(inp: ExplainInput) -> tuple[chess.Board, list[_Ply]]:
    board, _ = start_position(inp.fen, inp.moves)  # raises PuzzleDataError on a bad line
    start = board.copy()
    plies = []
    for i, uci in enumerate(inp.moves[1:]):
        move = chess.Move.from_uci(uci)
        plies.append(_Ply(i, "you" if i % 2 == 0 else "opponent", board.copy(), move, board.san(move)))
        board.push(move)
    return start, plies


def _side(color: chess.Color) -> str:
    return "White" if color == chess.WHITE else "Black"


def _piece(board: chess.Board, sq: chess.Square) -> str:
    p = board.piece_at(sq)
    return f"{PIECE_NAMES[p.piece_type]} {chess.square_name(sq)}" if p else chess.square_name(sq)


def _list(board: chess.Board, squares: Any) -> str:
    names = [_piece(board, s) for s in sorted(squares)]
    return ", ".join(names) if names else "nothing"


def ply_facts(p: _Ply) -> str:
    """Attack/defense facts for one solution move, from python-chess (FR-8.2)."""
    b = p.board_before
    mover = b.piece_at(p.move.from_square)
    assert mover is not None
    who = "You" if p.side == "you" else "Opponent"
    parts = [f"{p.index}. {who}: {p.san} ({PIECE_NAMES[mover.piece_type]} "
             f"{chess.square_name(p.move.from_square)}→{chess.square_name(p.move.to_square)})"]  # fmt: skip
    captured = b.piece_at(p.move.to_square)
    if captured:
        parts.append(f"captures the {PIECE_NAMES[captured.piece_type]}")
    elif b.is_en_passant(p.move):
        parts.append("captures a pawn en passant")
    before_attackers = b.attackers(not mover.color, p.move.to_square)
    before_defenders = b.attackers(mover.color, p.move.to_square) - chess.SquareSet([p.move.from_square])
    after = b.copy()
    after.push(p.move)
    if after.is_checkmate():
        parts.append("checkmate")
    elif after.is_check():
        parts.append("gives check")
    targets = [s for s in after.attacks(p.move.to_square) if (q := after.piece_at(s)) and q.color != mover.color]
    parts.append(f"from {chess.square_name(p.move.to_square)} it attacks {_list(after, targets)}")
    parts.append(
        f"that square was attacked by {_list(b, before_attackers)} and defended by {_list(b, before_defenders)}"
    )
    return "; ".join(parts)


def _san_line(board: chess.Board, ucis: tuple[str, ...], limit: int = ENGINE_PLIES) -> str:
    b = board.copy()
    out = []
    for uci in ucis[:limit]:
        move = chess.Move.from_uci(uci)
        if move not in b.legal_moves:
            break
        out.append(b.san(move))
        b.push(move)
    return " ".join(out) if out else "(none)"


def build_prompt(inp: ExplainInput) -> str:
    """The user message: the facts only (SR-11). The system prompt is SYSTEM_PROMPT."""
    start, plies = _solution(inp)
    raw = chess.Board(inp.fen)
    opp = chess.Move.from_uci(inp.moves[0])
    you = _side(start.turn)
    lines = [
        f"You play {you}. Position before your first move (FEN): {start.fen()}",
        f"The opponent has just played {raw.san(opp)}.",
        f"Themes: {', '.join(inp.themes) if inp.themes else '(none given)'}",
        "",
        "Solution (ply: side SAN [UCI]):",
        *[f"{p.index}: {'you' if p.side == 'you' else 'opponent'} {p.san} [{p.move.uci()}]" for p in plies],
        "",
        "Facts for each solution ply (python-chess):",
        *[ply_facts(p) for p in plies],
    ]
    lines.append("")
    if inp.danger:
        d = inp.danger
        cand = chess.Move.from_uci(d.candidate)
        lines += [
            "Mode: Danger spotting. The player was shown the position BEFORE the opponent's move above, "
            f"with {_side(raw.turn)}'s candidate move {raw.san(cand)} highlighted, and asked whether it was safe.",
            f"The truth: {raw.san(cand)} was {'a safe move (Stockfish checked it)' if d.is_safe else 'the real blunder, which the solution punishes'}.",
            f"The player's call: {d.call or 'none (moved on)'}.",
            "Explain why the candidate was safe or why it loses, then the solution.",
        ]  # fmt: skip
    elif inp.entered_line is not None:
        lines.append(f"Mode: Commit the line. The player entered: {_san_line(start, inp.entered_line, 20)}")
    if inp.refutation:
        r = inp.refutation
        b = chess.Board(r.fen_before)
        wrong = chess.Move.from_uci(r.wrong_move)
        after = b.copy()
        after.push(wrong)
        lines.append(f"The player went wrong with {b.san(wrong)} (in FEN {r.fen_before}). Stockfish's refutation: "
                     f"{_san_line(after, r.line)} ({r.score or 'game over'}).")  # fmt: skip
    elif inp.danger is None:
        lines.append("The player solved it." if inp.solved else "The player didn't play a wrong move but used help.")
    if inp.engine_lines:
        lines += ["", "Stockfish's top lines from the position before your first move (evals from your side):"]
        lines += [f"- {e.score}: {_san_line(start, e.pv)}" for e in inp.engine_lines]
    return "\n".join(lines)


# ---- validation (FR-8.4) ------------------------------------------------------------------------------


def _clean(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = CONTROL.sub("", value).strip()
    return text[:limit] if text else None


def _annotation(raw: Any) -> Annotation | None:
    if not isinstance(raw, dict):
        return None
    kind, orig, dest, color = raw.get("type"), raw.get("from"), raw.get("to"), raw.get("color")
    if color not in COLORS or not isinstance(orig, str) or not SQUARE.fullmatch(orig):
        return None
    if kind == "circle":
        return Annotation("circle", orig, None, color) if dest in (None, orig) else None
    if kind == "arrow" and isinstance(dest, str) and SQUARE.fullmatch(dest) and dest != orig:
        return Annotation("arrow", orig, dest, color)
    return None


def _variation(board: chess.Board, raw: Any) -> tuple[tuple[str, ...], bool]:
    """(the legal SAN line, whether something was dropped). The whole variation goes if any move is illegal."""
    if not isinstance(raw, list) or not raw:
        return (), False
    if len(raw) > MAX_VARIATION:
        return (), True
    b = board.copy()
    out = []
    for san in raw:
        if not isinstance(san, str):
            return (), True
        try:
            move = b.parse_san(san.strip())
        except ValueError:
            return (), True
        out.append(b.san(move))
        b.push(move)
    return tuple(out), False


def _same_move(board: chess.Board, said: Any, move: chess.Move) -> bool:
    if not isinstance(said, str):
        return False
    s = said.strip()
    if s == move.uci():
        return True
    try:
        return board.parse_san(s) == move
    except ValueError:
        return False


def validate(inp: ExplainInput, text: str) -> Explanation | None:
    """The model's answer, checked against the real position. None if it isn't the JSON asked for."""
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    summary = _clean(data.get("summary"), MAX_SUMMARY)
    if summary is None:
        return None
    _, plies = _solution(inp)
    discarded = 0
    steps: dict[int, Step] = {}
    raw_steps = data.get("steps")
    for raw in raw_steps if isinstance(raw_steps, list) else []:
        if not isinstance(raw, dict):
            discarded += 1
            continue
        ply = raw.get("ply")
        if isinstance(ply, bool) or not isinstance(ply, int) or not 0 <= ply < len(plies) or ply in steps:
            discarded += 1  # a ply the solution doesn't have, or a repeat
            continue
        p = plies[ply]
        if not _same_move(p.board_before, raw.get("move"), p.move):
            discarded += 1  # it's talking about some other move
            continue
        step_text = _clean(raw.get("text"), MAX_TEXT) or ""
        annotations: list[Annotation] = []
        raw_ann = raw.get("annotations")
        for a in raw_ann if isinstance(raw_ann, list) else []:
            ann = _annotation(a)
            if ann is None or len(annotations) >= MAX_ANNOTATIONS:
                discarded += 1
            else:
                annotations.append(ann)
        after = p.board_before.copy()
        after.push(p.move)
        variation, dropped = _variation(after, raw.get("variation"))
        discarded += dropped
        steps[ply] = Step(ply, p.side, p.san, p.move.uci(), step_text, tuple(annotations), variation)
    ideas_raw = data.get("key_ideas")
    ideas = [i for i in (_clean(x, MAX_IDEA) for x in (ideas_raw if isinstance(ideas_raw, list) else [])) if i]
    ideas = ideas[:MAX_IDEAS]
    return Explanation(summary, tuple(steps[k] for k in sorted(steps)), tuple(ideas), discarded)


@dataclass(frozen=True)
class CacheKeyParts:
    puzzle: str  # PuzzleRef as text: the cache key only, never sent to the LLM
    path: tuple[str, ...] = field(default_factory=tuple)  # your moves, the call, the entered line
    provider: str = ""
    model: str = ""

    def canonical(self) -> str:
        return json.dumps([self.puzzle, list(self.path), self.provider, self.model], separators=(",", ":"))
