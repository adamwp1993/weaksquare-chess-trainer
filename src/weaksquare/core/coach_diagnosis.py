"""The whole-game AI diagnosis (v0.11, FR-10.54–10.56, 10.60): the prompt, the schema and the evidence
rule. Pure. It replaces v0.10's keyed coaching (`core/coach_llm.py`) for reports that include games; a
puzzle-history-only report keeps the v0.10 prompt.

**What's sent (FR-8.16):**
- the report's allow-listed aggregates (as in v0.10), the whole-game measures and weaknesses;
- one digest per game, labelled G1, G2, … (never a game id, URL, date or name): the opening, castling and
  development, the pawn structure, trades, phases, the endgame type, conversion, time use as percentages
  of the starting clock (never raw clocks) and the key moments (3 at Summary, 5 at Detailed) with plies,
  1-based, next to the numbered SAN;
- the v0.10 example positions, now carrying the same game label and ply;
- only with **Advanced analysis**: each capped game's SAN move list, rebuilt from UCI (no PGN text);
- only with **Include my notes**: your notes, with web addresses removed.

**What comes back:** a summary, 3–8 weaknesses and 1–3 presets. Each weakness cites evidence as
``{"game": "G3", "ply": 23}``. A citation must be a ply sent for that game (a key moment, an example, or
any ply of a game whose move list was sent); others are dropped, and a weakness left without one is
dropped. Fewer than 3 cited games makes it **tentative**. A ``key`` must be one of the measured weaknesses
sent (then it's tracked; otherwise it's an observation, FR-10.57). A ``topic`` must be in the lesson
catalog sent (FR-10.59). Text is plain, URLs are cut out, and the UI renders it escaped.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from weaksquare.core.coach_llm import (
    MAX_PRESETS,
    ExamplePosition,
    _san_line,
    _weakness_json,
)
from weaksquare.core.coach_llm import SCHEMA as KEYED_SCHEMA
from weaksquare.core.digest import Digest
from weaksquare.core.lessons import Topic
from weaksquare.core.preset_suggestion import COACH_MODES, CoachPreset, preset_themes, validate_coach_preset
from weaksquare.core.urls import strip_urls

SCHEMA_NAME = "coach_diagnosis"
MIN_WEAKNESSES, MAX_WEAKNESSES = 3, 8
MAX_EVIDENCE = 8
TENTATIVE_GAMES = 3  # FR-10.55
MOMENTS = {"summary": 3, "detailed": 5}
MAX_TEXT = 1200
MAX_TITLE = 120
MAX_SUMMARY = 1500
MAX_NOTE = 300
CATEGORIES = ("tactical", "strategic", "opening", "endgame", "time", "other")
GAME_GROUPS = ("missed", "allowed", "habits", "puzzles", "whole_game")

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
                "required": ["key", "category", "title", "explanation", "advice", "topic", "evidence"],
                "properties": {
                    "key": {"type": ["string", "null"]},
                    "category": {"type": "string", "enum": list(CATEGORIES)},
                    "title": {"type": "string"},
                    "explanation": {"type": "string"},
                    "advice": {"type": "string"},
                    "topic": {"type": ["string", "null"]},
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["game", "ply"],
                            "properties": {"game": {"type": "string"}, "ply": {"type": "integer"}},
                        },
                    },
                },
            },
        },
        "presets": KEYED_SCHEMA["properties"]["presets"],
    },
}

SYSTEM_PROMPT = f"""You are a chess coach reading a player's games the way a tutor does. Stockfish and python-chess
measured the facts on their PC; you get the measures, one digest per game (labelled G1, G2, ...) and a few
example positions. Diagnose this player.

Rules:
- Find their tactical, strategic and practical weaknesses, including but not limited to openings, phases
  (and converting winning positions), endgame types, king safety and development, pawn structure, trades
  and time use. The listed areas are examples, not a closed list: name anything the evidence shows.
- Use ONLY the facts given. Never invent a game, a move, a statistic, a piece or a square.
- Every weakness needs "evidence": the games and plies that show it, as {{"game": "G3", "ply": 23}}, using
  only plies given for that game. A weakness seen in fewer than 3 games is weak evidence: say so.
- "key": copy a weakness key from the report exactly when your weakness is that one; otherwise null.
- "category": one of {", ".join(CATEGORIES)}.
- "topic": one topic id from the list at the end, for a lesson; or null.
- Speak to the player as "you". Plain text only: no markdown, no HTML, no links or web addresses.
- "summary": 3–5 sentences on what costs them most and what to do first.
- "weaknesses": the {MIN_WEAKNESSES}–{MAX_WEAKNESSES} most important, worst first, each with a short "title", an
  "explanation" citing the facts, and practical "advice".
- Mistake reasons: "didntLook" means they didn't look, "miscalculated" that they saw it but calculated
  wrong, "unknownPattern" that they didn't know the idea, "rushed" that they moved too fast.
- "presets": 1–{MAX_PRESETS} puzzle presets. "themes" uses only the theme keys listed at the end; "lengths" are
  move counts from 1 to 4 (4 means 4 or more); "mode" is one of {", ".join(COACH_MODES)};
  "queue_size" is 5–100; ratings are puzzle ratings or null.
"""


@dataclass(frozen=True)
class NoteItem:
    """One note for Include my notes (FR-10.60), already anonymized."""

    text: str  # URLs already removed
    reason: str | None = None
    game: str | None = None  # a G label
    ply: int | None = None  # 1-based
    source: str = "game"  # game / retry / puzzle / danger


@dataclass
class Sent:
    """What the prompt carried, for the evidence rule."""

    plies: dict[str, set[int]] = field(default_factory=dict)  # label → citable 1-based plies
    keys: set[str] = field(default_factory=set)
    topics: set[str] = field(default_factory=set)


def _moment_json(m: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "ply": m.ply,
        "move": m.move,
        "fen": m.fen,
        "best": m.best,
        "eval_before_cp": m.eval_before,
        "lost_cp": m.swing,
        "class": m.classification,
        "kind": m.kind,
        "phase": m.phase,
    }
    if m.themes:
        out["themes"] = list(m.themes)
    if m.clock_pct is not None:
        out["clock_left_pct"] = m.clock_pct
    if m.reason:
        out["reason"] = m.reason
    return out


def digest_json(label: str, d: Digest, detail: str) -> dict[str, Any]:
    n = MOMENTS.get(detail, 3)
    moments = sorted(sorted(d.moments, key=lambda m: -m.swing)[:n], key=lambda m: m.ply)
    s, o = d.structure, d.opp_structure
    out: dict[str, Any] = {
        "game": label,
        "you": d.color,
        "result": d.result,
        "opening": d.opening or d.family,
        "eco": d.eco,
        "plies": d.plies,
        "castled_ply": d.castled_ply,
        "opponent_castled_ply": d.opp_castled_ply,
        "moves_before_castling": d.moves_before_castling,
        "minor_pieces_developed_by_move_10": d.minors_developed,
        "early_queen_moves": d.early_queen_moves,
        "castled_late": d.castled_late,
        "pawns_at_move_15": {"isolated": s.isolated, "doubled": s.doubled, "passed": s.passed, "iqp": s.iqp},
        "opponent_pawns_at_move_15": {"isolated": o.isolated, "doubled": o.doubled, "passed": o.passed, "iqp": o.iqp},
        "trades_while_ahead": d.trades_ahead,
        "trades_while_behind": d.trades_behind,
        "eval_at_move_15_cp": d.eval_opening_end,
        "errors_first_15_moves": d.opening_errors,
        "errors_by_phase": d.errors_by_phase,
        "endgame": d.endgame,
        "held_plus2": d.held_plus2,
        "held_minus2": d.held_minus2,
        "key_moments": [_moment_json(m) for m in moments],
    }
    if d.time.clock_known:
        t = d.time
        out["time"] = {
            "moves_under_10pct_clock": t.low_moves,
            "errors_under_10pct_clock": t.low_errors,
            "errors_rest_of_game": t.other_errors,
        }
    return out


def build_prompt(
    report: Mapping[str, Any],
    games: Sequence[tuple[str, Digest]],
    examples: Sequence[tuple[ExamplePosition, str | None, int]],
    detail: str,
    topics: Sequence[Topic],
    *,
    moves: Mapping[str, str] | None = None,
    notes: Sequence[NoteItem] | None = None,
) -> tuple[str, Sent]:
    """The user message and what it carried. ``examples`` are (position, game label, 1-based ply);
    ``moves`` (Advanced only) maps a label to its SAN move list; ``notes`` only with Include my notes."""
    sent = Sent()
    data: dict[str, Any] = {
        "source": report.get("source"),
        "games": report.get("games"),
        "errors_per_10_games": report.get("per10"),
        "results": report.get("results"),
        "reason_mix": report.get("reasons"),
        "low_clock_errors": report.get("low_clock_errors"),
        "weaknesses": {
            group: [_weakness_json(w) for w in report.get(group) or [] if isinstance(w, dict)][:8]
            for group in GAME_GROUPS
        },
        "measures": _measures_json(report.get("measures")),
        # QA v0.11-B6: v0.10's puzzles-vs-games table still goes (FR-10.21)
        "puzzles_vs_games": [
            {k: g.get(k) for k in ("theme", "puzzle_accuracy", "puzzle_attempts", "missed_per10", "allowed_per10")}
            for g in report.get("gap") or []
            if isinstance(g, dict)
        ][:10],
    }
    for group in data["weaknesses"].values():
        sent.keys.update(str(w["key"]) for w in group if "key" in w)
    lines = [
        "Report (rates are per 10 games; severity is the average eval lost in centipawns; groups marked"
        ' "enough": false have fewer than 5 games and are not reliable):',
        json.dumps(data, separators=(",", ":")),
        "",
        "Game digests (plies are 1-based half-moves; evals are from your side, in centipawns):",
    ]
    for label, d in games:
        dj = digest_json(label, d, detail)
        sent.plies.setdefault(label, set()).update(int(m["ply"]) for m in dj["key_moments"])
        lines.append(json.dumps(dj, separators=(",", ":")))
    if examples:
        lines += ["", "Example positions (FEN before the move; SAN):"]
        for n, (e, glabel, ply) in enumerate(examples, start=1):
            item: dict[str, Any] = {"id": f"E{n}", "weakness": e.weakness}
            if glabel is not None:
                item["game"], item["ply"] = glabel, ply
                sent.plies.setdefault(glabel, set()).add(ply)
            item.update(
                {
                    "fen": e.fen,
                    "played": (_san_line(e.fen, [e.played]) or ["?"])[0],
                    "best_line": _san_line(e.fen, e.best_line),
                    "themes": list(e.themes),
                    "eval_lost_cp": e.cp_loss,
                }
            )
            if detail == "detailed" and e.before and e.before_fen:
                item["moves_before"] = _san_line(e.before_fen, e.before)
            lines.append(json.dumps(item, separators=(",", ":")))
    if moves:
        lines += ["", "Move lists (Advanced analysis; SAN only):"]
        by_label = dict(games)
        for label, san in moves.items():
            if label in by_label:
                lines.append(f"{label}: {san}")
                sent.plies.setdefault(label, set()).update(range(1, by_label[label].plies + 1))
    if notes:
        lines += ["", "Your own notes on your mistakes (written by the player):"]
        for note in notes:
            item = {"note": note.text}
            if note.reason:
                item["reason"] = note.reason
            if note.game is not None:
                item["game"], item["ply"] = note.game, note.ply  # type: ignore[assignment]
            else:
                item["source"] = "puzzle"
            lines.append(json.dumps(item, separators=(",", ":")))
    sent.topics = {t.id for t in topics}
    lines += ["", "Lesson topic ids: " + ", ".join(f"{t.id} ({t.label})" for t in topics)]
    lines += ["", "Allowed theme keys for presets: " + ", ".join(preset_themes())]
    return "\n".join(lines), sent


def _measures_json(ms: Any) -> Any:
    """The measures as stored, minus anything that isn't a plain number, flag or label."""
    if not isinstance(ms, dict):
        return None
    return json.loads(json.dumps(ms))


@dataclass(frozen=True)
class Evidence:
    game: str  # G label
    ply: int  # 1-based


@dataclass(frozen=True)
class Finding:
    key: str | None  # a measured weakness (tracked) or None (an observation)
    category: str
    title: str
    explanation: str
    advice: str
    topic: str | None
    evidence: tuple[Evidence, ...]
    tentative: bool  # fewer than 3 games cited (FR-10.55)

    def to_json(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "category": self.category,
            "title": self.title,
            "explanation": self.explanation,
            "advice": self.advice,
            "topic": self.topic,
            "evidence": [{"game": e.game, "ply": e.ply} for e in self.evidence],
            "tentative": self.tentative,
        }


@dataclass(frozen=True)
class Diagnosis:
    summary: str
    findings: tuple[Finding, ...]
    presets: tuple[CoachPreset, ...]
    fallback_preset: bool
    discarded: int  # weaknesses or citations dropped by validation

    def to_json(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "findings": [f.to_json() for f in self.findings],
            "presets": [p.to_json() for p in self.presets],
            "fallback_preset": self.fallback_preset,
            "discarded": self.discarded,
        }

    @classmethod
    def from_json(cls, d: Mapping[str, Any]) -> Diagnosis:
        presets = []
        for p in d.get("presets") or []:
            v, _ = validate_coach_preset(p)
            if v is not None:
                presets.append(v)
        findings = tuple(
            Finding(
                f.get("key"),
                str(f.get("category") or "other"),
                str(f.get("title") or ""),
                str(f.get("explanation") or ""),
                str(f.get("advice") or ""),
                f.get("topic"),
                tuple(Evidence(str(e["game"]), int(e["ply"])) for e in f.get("evidence") or []),
                bool(f.get("tentative")),
            )
            for f in d.get("findings") or []
            if isinstance(f, dict)
        )
        return cls(
            str(d.get("summary") or ""), findings, tuple(presets), bool(d.get("fallback_preset")),
            int(d.get("discarded") or 0),
        )  # fmt: skip


def _text(v: Any, limit: int) -> str | None:
    if not isinstance(v, str):
        return None
    t = " ".join(strip_urls(v).split())
    return t[:limit] if t else None


def _evidence(raw: Any, sent: Sent) -> tuple[list[Evidence], int]:
    out: list[Evidence] = []
    dropped = 0
    for e in raw if isinstance(raw, list) else []:
        game = e.get("game") if isinstance(e, dict) else None
        ply = e.get("ply") if isinstance(e, dict) else None
        ok = (
            isinstance(game, str) and isinstance(ply, int) and not isinstance(ply, bool)
            and ply in sent.plies.get(game, ())
        )  # fmt: skip
        if not ok:
            dropped += 1
            continue
        ev = Evidence(str(game), int(ply))  # type: ignore[arg-type]
        if ev not in out and len(out) < MAX_EVIDENCE:
            out.append(ev)
    return out, dropped


def validate(text: str, sent: Sent, fallback: dict[str, Any] | None) -> Diagnosis | None:
    """FR-10.55 and FR-10.23. None when the answer isn't the expected object at all."""
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
    findings: list[Finding] = []
    raw_w = data.get("weaknesses")
    for w in raw_w if isinstance(raw_w, list) else []:
        if not isinstance(w, dict) or len(findings) >= MAX_WEAKNESSES:
            discarded += 1
            continue
        title, exp, advice = (
            _text(w.get("title"), MAX_TITLE), _text(w.get("explanation"), MAX_TEXT), _text(w.get("advice"), MAX_TEXT)
        )  # fmt: skip
        evidence, dropped = _evidence(w.get("evidence"), sent)
        discarded += dropped
        if title is None or exp is None or advice is None or not evidence:
            discarded += 1
            continue
        key = w.get("key") if isinstance(w.get("key"), str) and w.get("key") in sent.keys else None
        if key is not None and any(f.key == key for f in findings):
            key = None  # a second finding on the same measured weakness is an observation
        category = w.get("category") if w.get("category") in CATEGORIES else "other"
        topic = w.get("topic") if isinstance(w.get("topic"), str) and w.get("topic") in sent.topics else None
        games = {e.game for e in evidence}
        findings.append(
            Finding(key, str(category), title, exp, advice, topic, tuple(evidence), len(games) < TENTATIVE_GAMES)
        )
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
    return Diagnosis(summary, tuple(findings), tuple(presets), fallback_used, discarded)


def title_key(title: str) -> str:
    """A normalized title, for matching an observation across runs when it has no topic (FR-10.57)."""
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", title.lower()).split())[:80]
