"""Optional AI coaching on a Coach report (v0.10, REQUIREMENTS §10.6): the prompt, the schema and the
validation. Pure.

**What's sent (FR-10.21, FR-8.16):** the aggregated report (rates, severities, mistake-reason counts,
the gap table) and a few example positions (FEN, the move played, Stockfish's best line, themes, the
eval swing): 12 at Summary, 20 at Detailed with the two moves before each. **Never** a player name, a
username, a game id or URL, a date, a clock or a PGN. Examples are labelled E1, E2, … and moves are
rebuilt as SAN from UCI.

**What comes back (FR-10.22, 10.23):** a short summary, 3–5 weaknesses (each must be one of the keys
sent), and 1–3 presets in the §5 filter schema. Everything is untrusted: unknown keys and invalid preset
fields are dropped, and when no preset survives, the report's deterministic preset is the fallback.
Text is plain and rendered escaped by the UI.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import chess

from weaksquare.core.preset_suggestion import COACH_MODES, CoachPreset, preset_themes, validate_coach_preset
from weaksquare.core.urls import strip_urls

SCHEMA_NAME = "coach"
SUMMARY_EXAMPLES = 12
DETAILED_EXAMPLES = 20
MIN_WEAKNESSES, MAX_WEAKNESSES = 3, 5
MAX_PRESETS = 3
MAX_TEXT = 1200
MAX_SUMMARY = 1500

SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "weaknesses", "presets"],
    "properties": {
        "summary": {"type": "string"},
        "weaknesses": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["key", "explanation", "drill"],
                "properties": {
                    "key": {"type": "string"},
                    "explanation": {"type": "string"},
                    "drill": {"type": "string"},
                },
            },
        },
        "presets": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "themes", "rating_min", "rating_max", "lengths", "mode", "queue_size"],
                "properties": {
                    "name": {"type": "string"},
                    "themes": {"type": "array", "items": {"type": "string"}},
                    "rating_min": {"type": ["integer", "null"]},
                    "rating_max": {"type": ["integer", "null"]},
                    "lengths": {"type": "array", "items": {"type": "integer"}},
                    "mode": {"type": "string", "enum": list(COACH_MODES)},
                    "queue_size": {"type": ["integer", "null"]},
                },
            },
        },
    },
}

SYSTEM_PROMPT = f"""You are a chess coach. You get a statistical report of a player's mistakes, worked out by Stockfish
and a tactics tagger on their PC, and a few example positions. Coach them.

Rules:
- Use ONLY the numbers and positions given. Never invent a statistic, a move, a piece or a square.
- Speak to the player as "you". Plain text only: no markdown, no HTML, no links.
- "summary": 3–5 sentences on what costs this player most and what to do first.
- "weaknesses": the {MIN_WEAKNESSES}–{MAX_WEAKNESSES} most important ones, each with "key" copied exactly from the report's
  weakness keys, an "explanation" (what goes wrong, citing the numbers and examples like E3), and "drill" (how
  to train it). Use the mistake-reason counts: "didntLook" means they didn't look, "miscalculated" that they
  saw it but calculated wrong, "unknownPattern" that they didn't know the idea, "rushed" that they moved too fast.
- "presets": 1–{MAX_PRESETS} puzzle presets. "themes" uses only the theme keys listed at the end; "lengths" are
  move counts from 1 to 4 (4 means 4 or more); "mode" is one of {", ".join(COACH_MODES)};
  "queue_size" is 5–100; ratings are puzzle ratings or null.
"""


@dataclass(frozen=True)
class ExamplePosition:
    """One moment for the prompt, already anonymized: a label, never a game id."""

    label: str
    weakness: str  # the weakness key it illustrates
    fen: str  # the position before the move
    played: str  # UCI
    best_line: tuple[str, ...]  # UCI from the same position
    themes: tuple[str, ...]
    cp_loss: int
    before: tuple[str, ...] = ()  # Detailed: the two moves that led here (UCI, from two plies earlier)
    before_fen: str | None = None


def _san_line(fen: str, line: Sequence[str]) -> list[str]:
    try:
        board = chess.Board(fen)
    except ValueError:
        return []
    out: list[str] = []
    for uci in line:
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            break
        if move not in board.legal_moves:
            break
        out.append(board.san(move))
        board.push(move)
    return out


def _weakness_json(w: dict[str, Any]) -> dict[str, Any]:
    keep = ("key", "label", "count", "per10", "severity", "reasons", "puzzle_accuracy", "multi_move")
    return {k: w[k] for k in keep if k in w}


def build_prompt(report: dict[str, Any], examples: Sequence[ExamplePosition], detail: str) -> str:
    """The user message: the report's numbers and the examples. Only allow-listed fields are copied, so
    nothing else in a stored report (game ids, dates, labels with names) can reach the prompt."""
    data: dict[str, Any] = {
        "source": report.get("source"),
        "games": report.get("games"),
        "errors_per_10_games": report.get("per10"),
        "results": report.get("results"),
        "reason_mix": report.get("reasons"),
        "low_clock_errors": report.get("low_clock_errors"),
        "weaknesses": {
            group: [_weakness_json(w) for w in report.get(group) or [] if isinstance(w, dict)][:8]
            for group in ("missed", "allowed", "habits", "puzzles")
        },
        "puzzles_vs_games": [
            {k: g.get(k) for k in ("theme", "puzzle_accuracy", "puzzle_attempts", "missed_per10", "allowed_per10")}
            for g in report.get("gap") or []
            if isinstance(g, dict)
        ][:10],
    }
    lines = ["Report (rates are per 10 games; severity is the average eval lost in centipawns):",
             json.dumps(data, separators=(",", ":"))]  # fmt: skip
    if examples:
        lines.append("")
        lines.append("Example positions (FEN before the move; SAN):")
        for e in examples:
            item: dict[str, Any] = {
                "id": e.label,
                "weakness": e.weakness,
                "fen": e.fen,
                "played": (_san_line(e.fen, [e.played]) or ["?"])[0],
                "best_line": _san_line(e.fen, e.best_line),
                "themes": list(e.themes),
                "eval_lost_cp": e.cp_loss,
            }
            if detail == "detailed" and e.before and e.before_fen:
                item["moves_before"] = _san_line(e.before_fen, e.before)
            lines.append(json.dumps(item, separators=(",", ":")))
    lines.append("")
    lines.append("Allowed theme keys for presets: " + ", ".join(preset_themes()))
    return "\n".join(lines)


@dataclass(frozen=True)
class CoachWeaknessNote:
    key: str
    explanation: str
    drill: str


@dataclass(frozen=True)
class Coaching:
    summary: str
    weaknesses: tuple[CoachWeaknessNote, ...]
    presets: tuple[CoachPreset, ...]
    fallback_preset: bool  # no AI preset survived validation: the report's own is offered instead
    discarded: int

    def to_json(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "weaknesses": [{"key": w.key, "explanation": w.explanation, "drill": w.drill} for w in self.weaknesses],
            "presets": [p.to_json() for p in self.presets],
            "fallback_preset": self.fallback_preset,
            "discarded": self.discarded,
        }

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> Coaching:
        presets = []
        for p in d.get("presets") or []:
            v, _ = validate_coach_preset(p)
            if v is not None:
                presets.append(v)
        return cls(
            str(d.get("summary") or ""),
            tuple(
                CoachWeaknessNote(str(w["key"]), str(w["explanation"]), str(w["drill"]))
                for w in d.get("weaknesses") or []
            ),
            tuple(presets),
            bool(d.get("fallback_preset")),
            int(d.get("discarded") or 0),
        )


def _text(v: Any, limit: int) -> str | None:
    if not isinstance(v, str):
        return None
    t = " ".join(strip_urls(v).split())  # QA v0.11-B1: never a URL the LLM wrote
    return t[:limit] if t else None


def validate(text: str, sent_keys: Sequence[str], fallback: dict[str, Any] | None) -> Coaching | None:
    """FR-10.23. None when the answer isn't the expected object at all."""
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    summary = _text(data.get("summary"), MAX_SUMMARY)
    if summary is None:
        return None
    discarded = 0
    keys = set(sent_keys)
    notes: list[CoachWeaknessNote] = []
    raw_w = data.get("weaknesses")
    for w in raw_w if isinstance(raw_w, list) else []:
        if not isinstance(w, dict) or w.get("key") not in keys or any(n.key == w.get("key") for n in notes):
            discarded += 1
            continue
        exp, drill = _text(w.get("explanation"), MAX_TEXT), _text(w.get("drill"), MAX_TEXT)
        if exp is None or drill is None or len(notes) >= MAX_WEAKNESSES:
            discarded += 1
            continue
        notes.append(CoachWeaknessNote(str(w["key"]), exp, drill))
    presets: list[CoachPreset] = []
    raw_p = data.get("presets")
    for p in raw_p if isinstance(raw_p, list) else []:
        v, dropped = validate_coach_preset(p)
        discarded += dropped
        if v is None or len(presets) >= MAX_PRESETS:
            discarded += v is not None
            continue
        presets.append(v)
    fallback_used = False
    if not presets and fallback:
        fb, _ = validate_coach_preset(fallback)
        if fb is not None:
            presets.append(fb)
            fallback_used = True
    return Coaching(summary, tuple(notes), tuple(presets), fallback_used, discarded)


def fallback_preset(report: dict[str, Any]) -> dict[str, Any] | None:
    """The report's deterministic preset (FR-10.19) in the AI preset's shape, for FR-10.23's fallback."""
    preset = report.get("preset")
    spec = preset.get("spec") if isinstance(preset, dict) else None
    if not isinstance(spec, dict):
        return None
    themes: list[str] = []
    for b in spec.get("ratios") or []:
        for t in b.get("themes") or []:
            if t not in themes and t not in ("long", "veryLong"):
                themes.append(t)
    return {
        "name": "The report's mix",
        "themes": themes or list(spec.get("themes") or []),
        "rating_min": spec.get("rating_min"),
        "rating_max": spec.get("rating_max"),
        "lengths": [],
        "mode": preset.get("mode") or "standard" if isinstance(preset, dict) else "standard",
        "queue_size": spec.get("queue_size"),
    }
