"""Game Review AI (v0.9, REQUIREMENTS §11.4): the grounded context for Explain this move and Explain my
game, the narrative's schema, and its validation.

Pure. Built from the **stored analysis** only (`MoveRow`s), so no engine call is needed.

**Anonymized** (FR-8.16, FR-11.19): the prompt holds your color, the result from your side, the SAN move
list rebuilt from the UCI moves (never the PGN text, so no headers, names, ratings, dates, URLs, clocks or
comments), and the engine's facts. Players are "you" and "your opponent". No game id is sent.

The answer is **untrusted** (CLAUDE.md): every move, line and square is checked before it's drawn.
- **Explain this move** reuses Explain's schema and `validate()` (FR-11.17: "exactly like FR-8.3 to 8.5"),
  with Stockfish's best line from the position before the move as the "solution".
- **Explain my game** (FR-11.18): a moment must be one of the key moments sent and name the move played
  there; its better line must start with the engine's best move and be legal; annotations need valid
  squares. The recommended preset goes through `preset_suggestion.validate_preset`.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import chess

from weaksquare.core.engine import format_score
from weaksquare.core.explain import (
    COLORS,
    MAX_ANNOTATIONS,
    MAX_IDEA,
    MAX_TEXT,
    Annotation,
    EngineLineFact,
    ExplainInput,
    GameMoveFact,
    Ply,
    RefutationFact,
    clean_text,
    parse_annotation,
    ply_facts,
    same_move,
    san_line,
)
from weaksquare.core.game_review import MoveRow, Score, saved_line
from weaksquare.core.preset_suggestion import MAX_PRESET_THEMES, SuggestedPreset, preset_themes, validate_preset
from weaksquare.core.puzzle import NO_PREMOVE, Color

MAX_MOMENTS = 10  # FR-11.18: default 5, max 10
MAX_SUMMARY, MAX_TAKEAWAY, MAX_TAKEAWAYS, MAX_THEMES = 800, 300, 3, 4
MAX_BETTER_LINE = 6
ENGINE_LINES = 3  # top lines per key moment in the prompt


def score_words(s: Score) -> str:
    """A stored eval from the mover's side, worded like Explain's (FR-7.2)."""
    if s.mate is not None:
        if s.mate == 0:
            return "checkmate delivered"
        return f"You mate in {s.mate}" if s.mate > 0 else f"You're mated in {-s.mate}"
    v = (s.cp or 0) / 100
    if round(v, 1) == 0:
        return "0.0 (level)"
    return f"{'+' if v > 0 else '−'}{abs(v):.1f} for you"


def legal_prefix(fen: str, pv: Sequence[str]) -> tuple[str, ...]:
    """The legal start of an engine line (stored lines are trusted, but a bad one must never crash a prompt)."""
    b = chess.Board(fen)
    out: list[str] = []
    for uci in pv:
        try:
            m = chess.Move.from_uci(uci)
        except ValueError:
            break
        if m not in b.legal_moves:
            break
        out.append(uci)
        b.push(m)
    return tuple(out)


def _after(fen: str, uci: str) -> chess.Board:
    b = chess.Board(fen)
    b.push(chess.Move.from_uci(uci))
    return b


# ---- Explain this move (FR-11.17) -------------------------------------------------------------------


def move_input(row: MoveRow) -> ExplainInput | None:
    """Explain's input for one analyzed game move, or None when the analysis has no best line there."""
    best = legal_prefix(row.fen_before, row.lines[0].pv) if row.lines else ()
    if not best:
        return None
    mover: Color = "white" if row.mover == "white" else "black"
    board = chess.Board(row.fen_before)
    engine_lines = tuple(
        EngineLineFact(format_score(line, mover), legal_prefix(row.fen_before, line.pv))
        for line in row.lines[:ENGINE_LINES]
    )
    refutation = None
    if row.move_uci != best[0]:
        reply = legal_prefix(_after(row.fen_before, row.move_uci).fen(), row.refutation)
        refutation = RefutationFact(row.fen_before, row.move_uci, reply, score_words(row.eval_after))
    fact = GameMoveFact(
        move_number=board.fullmove_number,
        played_san=row.move_san,
        classification=row.classification,
        eval_before=score_words(row.eval_before),
        eval_after=score_words(row.eval_after),
        cp_loss=row.cp_loss,
        phase=row.phase,
    )
    return ExplainInput(
        fen=row.fen_before,
        moves=(NO_PREMOVE, *saved_line(best)),
        themes=(),  # theme tags arrive with the v0.10 tagger
        engine_lines=engine_lines,
        refutation=refutation,
        solved=row.move_uci == best[0],
        game_move=fact,
    )


# ---- Explain my game (FR-11.18, 11.19) ------------------------------------------------------------------

NARRATIVE_SCHEMA_NAME = "game_review"
_ANNOTATION = {
    "type": "object",
    "additionalProperties": False,
    "required": ["type", "from", "to", "color"],
    "properties": {
        "type": {"type": "string", "enum": ["arrow", "circle"]},
        "from": {"type": "string"},
        "to": {"type": ["string", "null"]},
        "color": {"type": "string", "enum": list(COLORS)},
    },
}
NARRATIVE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["opening_summary", "turning_point_ply", "recurring_themes", "takeaways", "moments", "preset"],
    "properties": {
        "opening_summary": {"type": "string"},
        "turning_point_ply": {"type": ["integer", "null"]},
        "recurring_themes": {"type": "array", "items": {"type": "string"}},
        "takeaways": {"type": "array", "items": {"type": "string"}},
        "moments": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["ply", "played", "text", "annotations", "better_line"],
                "properties": {
                    "ply": {"type": "integer"},
                    "played": {"type": "string"},
                    "text": {"type": "string"},
                    "annotations": {"type": "array", "items": _ANNOTATION},
                    "better_line": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "preset": {
            "type": "object",
            "additionalProperties": False,
            "required": ["themes", "rating_min", "rating_max"],
            "properties": {
                "themes": {"type": "array", "items": {"type": "string"}},
                "rating_min": {"type": ["integer", "null"]},
                "rating_max": {"type": ["integer", "null"]},
            },
        },
    },
}

NARRATIVE_SYSTEM_PROMPT = f"""You are a chess coach going through one of the player's own games with them, using Stockfish's analysis.

Rules:
- Use ONLY the moves, evaluations and facts given. Never invent a move, a piece or a square. If the facts
  don't settle something, say less rather than guess.
- Speak to the player as "you" and to the other side as "your opponent". Plain text only: no markdown, no HTML.
- "opening_summary": 1–3 sentences on how the opening went.
- "turning_point_ply": the ply number of the key moment where the game turned, or null.
- "recurring_themes": 1–{MAX_THEMES} short phrases for patterns across the key moments (for example "missed forks", "king safety").
- "takeaways": 2–{MAX_TAKEAWAYS} concrete lessons, one sentence each.
- "moments": one entry per key moment, in order. "ply" and "played" exactly as given. "text": 2–4
  sentences on what went wrong and why the better move is better. "annotations": up to 4 arrows or circles
  in the position before the move (an arrow has "from" and "to"; a circle has its square in "from" and
  "to": null). Colors: green for the better move, red for the mistake or the threat, blue for lines and
  attacks, yellow for key squares. "better_line": Stockfish's best move from that position, then up to
  {MAX_BETTER_LINE - 1} more SAN moves of its line as given; [] if unsure.
- "preset": up to {MAX_PRESET_THEMES} puzzle theme keys to practise, chosen ONLY from the allowed theme keys, with an
  optional puzzle rating range ("rating_min"/"rating_max", or null). "themes": [] if nothing fits."""


@dataclass(frozen=True)
class NarrativeInput:
    start_fen: str
    moves: tuple[str, ...]  # the game's UCI moves
    rows: tuple[MoveRow, ...]  # the stored analysis, one per move
    user_color: str  # white / black / both
    result: str | None  # win / loss / draw from your side; None when unknown
    moments: tuple[int, ...]  # the plies of the top-N key moments (FR-11.13), in game order


def san_moves(start_fen: str, moves: Sequence[str]) -> str:
    """The numbered SAN move list, rebuilt from the UCI moves: nothing of the PGN text survives."""
    b = chess.Board(start_fen)
    parts: list[str] = []
    for i, uci in enumerate(moves):
        m = chess.Move.from_uci(uci)
        if b.turn == chess.WHITE:
            parts.append(f"{b.fullmove_number}. {b.san(m)}")
        elif i == 0:
            parts.append(f"{b.fullmove_number}... {b.san(m)}")
        else:
            parts.append(b.san(m))
        b.push(m)
    return " ".join(parts)


def _move_label(row: MoveRow) -> str:
    n = chess.Board(row.fen_before).fullmove_number
    return f"{n}. {row.move_san}" if row.mover == "white" else f"{n}... {row.move_san}"


def _moment_lines(row: MoveRow) -> list[str]:
    board = chess.Board(row.fen_before)
    played = chess.Move.from_uci(row.move_uci)
    best = legal_prefix(row.fen_before, row.lines[0].pv) if row.lines else ()
    best_san = board.san(chess.Move.from_uci(best[0])) if best else "(unknown)"
    kind = f", {row.kind}" if row.kind in ("missed", "allowed") else ""
    out = [
        f"- ply {row.ply} ({_move_label(row)}, {row.phase}): played {row.move_san} ({row.classification}{kind}); "
        f"best was {best_san}. Eval with the best move: {score_words(row.eval_before)}; after the move played: "
        f"{score_words(row.eval_after)} (a loss of {row.cp_loss} centipawns)."
    ]
    after = board.copy()
    after.push(played)
    reply = legal_prefix(after.fen(), row.refutation)
    if reply:
        out.append(f"  Stockfish's reply to {row.move_san}: {san_line(after, reply)}")
    mover: Color = "white" if row.mover == "white" else "black"
    for line in row.lines[:ENGINE_LINES]:
        pv = legal_prefix(row.fen_before, line.pv)
        if pv:
            out.append(f"  Line ({format_score(line, mover)}): {san_line(board, pv)}")
    out.append("  Facts, move played: " + ply_facts(Ply(row.ply, "you", board.copy(), played, row.move_san)))
    if best and best[0] != row.move_uci:
        bm = chess.Move.from_uci(best[0])
        out.append("  Facts, best move: " + ply_facts(Ply(row.ply, "you", board.copy(), bm, best_san)))
    return out


RESULT_WORDS = {"win": "you won", "loss": "you lost", "draw": "a draw", None: "unknown"}


def build_narrative_prompt(inp: NarrativeInput) -> str:
    """The user message (SR-11): only what FR-11.19 allows."""
    if inp.user_color in ("white", "black"):
        you = f"You played {inp.user_color.capitalize()}."
    else:
        you = "The player is reviewing both sides: every move is theirs."
    lines = [you, f"Result: {RESULT_WORDS.get(inp.result, 'unknown')}."]
    if inp.start_fen != chess.STARTING_FEN:
        lines.append(f"Start position (FEN): {inp.start_fen}")
    lines += ["", "Moves (SAN):", san_moves(inp.start_fen, inp.moves), ""]
    yours = [r for r in inp.rows if inp.user_color not in ("white", "black") or r.mover == inp.user_color]
    counts = {c: sum(r.classification == c for r in yours) for c in ("inaccuracy", "mistake", "blunder")}
    lines.append(
        f"Your errors (Stockfish): {counts['inaccuracy']} inaccuracies, {counts['mistake']} mistakes, "
        f"{counts['blunder']} blunders."
    )
    lines += ["", "Key moments (evals from the mover's side):"]
    by_ply = {r.ply: r for r in inp.rows}
    for ply in inp.moments:
        lines += _moment_lines(by_ply[ply])
    lines += ["", "Allowed theme keys for the preset: " + ", ".join(preset_themes())]
    return "\n".join(lines)


@dataclass(frozen=True)
class MomentNote:
    ply: int
    played_san: str
    text: str
    annotations: tuple[Annotation, ...]
    better_line: tuple[str, ...]  # SAN, legal from the position before the move
    better_uci: tuple[str, ...]


@dataclass(frozen=True)
class GameNarrative:
    opening_summary: str
    turning_point: int | None
    themes: tuple[str, ...]
    takeaways: tuple[str, ...]
    moments: tuple[MomentNote, ...]
    preset: SuggestedPreset | None
    discarded: int = 0  # dropped by validation (FR-8.4's note)

    def to_json(self) -> str:
        return json.dumps(
            {
                "opening_summary": self.opening_summary,
                "turning_point": self.turning_point,
                "themes": list(self.themes),
                "takeaways": list(self.takeaways),
                "moments": [
                    {"ply": m.ply, "played_san": m.played_san, "text": m.text,
                     "annotations": [{"kind": a.kind, "orig": a.orig, "dest": a.dest, "color": a.color}
                                     for a in m.annotations],
                     "better_line": list(m.better_line), "better_uci": list(m.better_uci)}
                    for m in self.moments
                ],
                "preset": self.preset.to_json() if self.preset else None,
                "discarded": self.discarded,
            },
            separators=(",", ":"),
        )  # fmt: skip

    @classmethod
    def from_json(cls, text: str) -> GameNarrative:
        d = json.loads(text)
        moments = tuple(
            MomentNote(m["ply"], m["played_san"], m["text"],
                       tuple(Annotation(a["kind"], a["orig"], a["dest"], a["color"]) for a in m["annotations"]),
                       tuple(m["better_line"]), tuple(m["better_uci"]))
            for m in d["moments"]
        )  # fmt: skip
        preset = SuggestedPreset.from_json(d["preset"]) if d.get("preset") else None
        return cls(d["opening_summary"], d["turning_point"], tuple(d["themes"]), tuple(d["takeaways"]), moments,
                   preset, int(d["discarded"]))  # fmt: skip


def _better_line(row: MoveRow, raw: Any) -> tuple[tuple[str, ...], tuple[str, ...], bool]:
    """(SAN, UCI, dropped). The line must start with the engine's best move and be legal throughout."""
    if not isinstance(raw, list) or not raw:
        return (), (), False
    if len(raw) > MAX_BETTER_LINE or not row.lines or not row.lines[0].pv:
        return (), (), True
    b = chess.Board(row.fen_before)
    sans: list[str] = []
    ucis: list[str] = []
    for said in raw:
        if not isinstance(said, str):
            return (), (), True
        try:
            m = b.parse_san(said.strip())
        except ValueError:
            return (), (), True
        if not m or m not in b.legal_moves:
            return (), (), True
        sans.append(b.san(m))
        ucis.append(m.uci())
        b.push(m)
    if ucis[0] != row.lines[0].pv[0]:
        return (), (), True  # it's not Stockfish's move: the LLM explains, it doesn't calculate
    return tuple(sans), tuple(ucis), False


def _texts(raw: Any, limit: int, most: int) -> tuple[list[str], int]:
    items = raw if isinstance(raw, list) else []
    kept = [t for t in (clean_text(x, limit) for x in items) if t]
    return kept[:most], len(items) - min(len(kept), most)


def validate_narrative(inp: NarrativeInput, text: str) -> GameNarrative | None:
    """The model's answer, checked against the game. None if it isn't the JSON asked for."""
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    summary = clean_text(data.get("opening_summary"), MAX_SUMMARY)
    if summary is None:
        return None
    discarded = 0
    tp = data.get("turning_point_ply")
    turning: int | None = None
    if isinstance(tp, int) and not isinstance(tp, bool) and 0 <= tp < len(inp.moves):
        turning = tp
    elif tp is not None:
        discarded += 1
    themes, d1 = _texts(data.get("recurring_themes"), MAX_IDEA, MAX_THEMES)
    takeaways, d2 = _texts(data.get("takeaways"), MAX_TAKEAWAY, MAX_TAKEAWAYS)
    discarded += d1 + d2
    by_ply = {r.ply: r for r in inp.rows}
    wanted = set(inp.moments)
    notes: dict[int, MomentNote] = {}
    raw_moments = data.get("moments")
    for raw in raw_moments if isinstance(raw_moments, list) else []:
        ply = raw.get("ply") if isinstance(raw, dict) else None
        if isinstance(ply, bool) or not isinstance(ply, int) or ply not in wanted or ply in notes:
            discarded += 1  # a ply that isn't a key moment we sent, or a repeat
            continue
        row = by_ply[ply]
        board = chess.Board(row.fen_before)
        if not same_move(board, raw.get("played"), chess.Move.from_uci(row.move_uci)):
            discarded += 1  # it's talking about some other move
            continue
        annotations: list[Annotation] = []
        raw_ann = raw.get("annotations")
        for a in raw_ann if isinstance(raw_ann, list) else []:
            ann = parse_annotation(a)
            if ann is None or len(annotations) >= MAX_ANNOTATIONS:
                discarded += 1
            else:
                annotations.append(ann)
        sans, ucis, dropped = _better_line(row, raw.get("better_line"))
        discarded += dropped
        notes[ply] = MomentNote(ply, row.move_san, clean_text(raw.get("text"), MAX_TEXT) or "", tuple(annotations),
                                sans, ucis)  # fmt: skip
    preset, d3 = validate_preset(data.get("preset"))
    discarded += d3
    return GameNarrative(summary, turning, tuple(themes), tuple(takeaways), tuple(notes[k] for k in sorted(notes)),
                         preset, discarded)  # fmt: skip
