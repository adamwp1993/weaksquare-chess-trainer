"""Practice and opening stats (v0.13, FR-12.9–12.11).

A session walks from the start to each position that's due, then a few you haven't seen. The app plays the opponent's
stored replies and you play your side. Every attempt goes in its own table, so nothing here can touch puzzle stats,
ratings, sync or the Coach. All time comes from the injected clock and all choices from the injected rng.

What's recorded: a position that's due or new when you answer it, once per session, and any wrong move or help anywhere,
because a miss on the way there still means you don't know it. A correct answer on the way to something else isn't
recorded, so walking through a position doesn't move it up a box before it's due.
"""

from __future__ import annotations

import random
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

import chess

from weaksquare.core.clock import Clock
from weaksquare.core.errors import ConflictError, NotFoundError, ValidationError
from weaksquare.core.opening_practice import (
    CORRECT,
    DEFAULT_NEW,
    HELPED,
    WRONG,
    Review,
    Target,
    due_and_new,
    path_to,
    pick_reply,
    schedule_position,
    side_cp,
    subtree_positions,
)
from weaksquare.core.openings import board_of, position_key
from weaksquare.core.reasons import reason_info, validate_note
from weaksquare.core.repertoire import Edge, after, by_position, check_color, is_your_turn, reachable, your_positions
from weaksquare.core.srs import DEFAULT_INTERVALS, Card, is_due, validate_intervals
from weaksquare.core.tolerance import DEFAULT_TOLERANCE_CP
from weaksquare.services.opening_sources import OpeningSources
from weaksquare.services.openings import OpeningsService
from weaksquare.services.repertoire import RepertoireService
from weaksquare.services.ui_settings import SRS_INTERVALS_KEY

TOLERANCE_KEY = "openings.practice_tolerance"  # FR-12.9, default off
MODES = ("due", "new", "all")
MAX_DECISIONS = (1, 100)
DEFAULT_DECISIONS = 15
MAX_LINES_LISTED = 40


class Attempts(Protocol):
    def add(
        self, session_id: str, color: str, opening_id: int | None, position_key: str, played_uci: str | None,
        played_san: str | None, outcome: str, time_ms: int | None, finished_at: str,
    ) -> int: ...  # fmt: skip

    def for_color(self, color: str) -> list[Any]: ...

    def get(self, attempt_id: int) -> Any | None: ...


class ReasonStore(Protocol):
    def add(
        self, source: str, ref_id: str, reason: str, suggested: str | None, note: str | None, created_at: str
    ) -> None: ...


class Settings(Protocol):
    def get(self, key: str) -> Any | None: ...

    def set(self, key: str, value: Any) -> None: ...


@dataclass
class _Session:
    id: str
    color: str
    opening_id: int | None
    within: set[str] | None
    mode: str
    limit: int
    targets: list[Target]
    board: chess.Board = field(default_factory=chess.Board)
    path: list[Edge] = field(default_factory=list)
    target: str | None = None
    state: str = "your_move"  # your_move / wrong / helped / line_end / finished
    recorded: set[str] = field(default_factory=set)
    decisions: int = 0
    correct: int = 0
    wrong: int = 0
    lines_clean: int = 0
    lines_lost: int = 0
    line_lost: bool = False
    asked_at: datetime | None = None
    last_attempt: int | None = None
    last_moves: tuple[tuple[str, str], ...] = ()  # the opponent's reply just played: (uci, san)
    message: str | None = None
    wrong_uci: str | None = None


@dataclass(frozen=True)
class PracticeState:
    session_id: str
    state: str
    fen: str
    color: str
    decisions: int
    correct: int
    wrong: int
    lines_clean: int
    lines_lost: int
    remaining: int
    target_reason: str | None
    replies: tuple[tuple[str, str], ...]  # the opponent's moves just played, for the sounds and the arrow
    correct_moves: tuple[tuple[str, str], ...]  # (uci, san), only after a miss or help
    attempt_id: int | None
    message: str | None
    wrong_fen: str | None
    position_key: str


@dataclass(frozen=True)
class PositionStat:
    position_key: str
    label: str
    attempts: int
    correct: int
    due: bool


@dataclass(frozen=True)
class LineStat:
    name: str
    positions: int
    attempts: int
    correct: int
    due: int


@dataclass(frozen=True)
class OpeningStat:
    id: int
    color: str
    name: str
    eco: str
    positions: int
    attempts: int
    correct: int
    due: int
    weakest: tuple[PositionStat, ...]
    lines: tuple[LineStat, ...]


def _tally(rows: Sequence[Any]) -> tuple[int, int]:
    return len(rows), sum(1 for r in rows if r.outcome == CORRECT)


def _reason_for(card: Card | None, today: Any) -> str:
    if card is None:
        return "new"
    return "due" if is_due(card, today) else "review"


def _session_key(rng: random.Random) -> str:
    return f"p{rng.getrandbits(48):012x}"


class OpeningPracticeService:
    def __init__(
        self, attempts: Attempts, reasons: ReasonStore, repertoire: RepertoireService, openings: OpeningsService,
        sources: OpeningSources, settings: Settings, clock: Clock, rng: random.Random,
    ) -> None:  # fmt: skip
        self._attempts = attempts
        self._reasons = reasons
        self._repertoire = repertoire
        self._openings = openings
        self._sources = sources
        self._settings = settings
        self._clock = clock
        self._rng = rng
        self._lock = threading.Lock()
        self._sessions: dict[str, _Session] = {}

    # ---- settings -----------------------------------------------------------------------------------------------

    def tolerance_on(self) -> bool:
        return self._settings.get(TOLERANCE_KEY) is True

    def set_tolerance(self, on: object) -> bool:
        if not isinstance(on, bool):
            raise ValidationError("Choose whether close moves count.")
        self._settings.set(TOLERANCE_KEY, on)
        return on

    def _intervals(self) -> tuple[int, ...]:
        saved = self._settings.get(SRS_INTERVALS_KEY)
        try:
            return validate_intervals(saved) if saved is not None else DEFAULT_INTERVALS
        except ValidationError:
            return DEFAULT_INTERVALS

    # ---- the schedule ------------------------------------------------------------------------------------------------

    def _cards(self, color: str, edges: Sequence[Edge]) -> dict[str, Card | None]:
        by_key: dict[str, list[Review]] = {}
        for row in self._attempts.for_color(color):
            by_key.setdefault(row.position_key, []).append(Review(datetime.fromisoformat(row.finished_at), row.outcome))
        return {
            key: schedule_position(by_key.get(key, []), self._intervals(), self._clock.local_date)
            for key in your_positions(edges, color)
        }

    def _today(self) -> Any:
        return self._clock.local_date(self._clock.now())

    def summary(self, color: object) -> dict[str, int]:
        c = check_color(color)
        edges = self._repertoire.edges(c)
        cards = self._cards(c, edges)
        today = self._today()
        return {
            "due": sum(1 for card in cards.values() if card is not None and is_due(card, today)),
            "new": sum(1 for card in cards.values() if card is None),
            "positions": len(cards),
        }

    # ---- a session -----------------------------------------------------------------------------------------------------

    def start(
        self, color: object, opening_id: object = None, branch: object = None, mode: object = "due",
        limit: object = DEFAULT_DECISIONS, new_limit: object = DEFAULT_NEW,
    ) -> PracticeState:  # fmt: skip
        c = check_color(color)
        if mode not in MODES:
            raise ValidationError("Choose due, new or all.")
        for value, low, high, label in ((limit, *MAX_DECISIONS, "positions"), (new_limit, 0, 50, "new positions")):
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise ValidationError(f"Choose {low} to {high} {label}.")
        edges = self._repertoire.edges(c)
        if not edges:
            raise ConflictError("Add some lines to your repertoire first.")
        within = self._limit(c, edges, opening_id, branch)
        cards = self._cards(c, edges)
        today = self._today()
        if mode == "all":
            mine = your_positions(edges, c)
            keys = sorted(
                (k for k in mine if within is None or k in within), key=lambda k: (len(path_to(edges, k) or []), k)
            )
            # Everything comes up, but only what was due or new is recorded when you get it right, so going
            # through it all doesn't move anything through the schedule early.
            targets = [Target(k, _reason_for(cards.get(k), today)) for k in keys]
        else:
            targets = due_and_new(edges, c, cards, today, within, new_limit if mode == "due" else limit)  # type: ignore[arg-type]
            if mode == "new":
                targets = [t for t in targets if t.reason == "new"]
        session = _Session(
            _session_key(self._rng), c, opening_id if isinstance(opening_id, int) else None, within, str(mode),
            int(limit), targets,  # type: ignore[call-overload]
        )  # fmt: skip
        with self._lock:
            self._sessions[session.id] = session
        self._next_line(session, edges)
        return self._state(session)

    def _limit(self, color: str, edges: Sequence[Edge], opening_id: object, branch: object) -> set[str] | None:
        """FR-12.10: one opening or one branch. A color alone is the whole repertoire for that side."""
        if branch is not None:
            if not isinstance(branch, str) or path_to(edges, branch) is None:
                raise NotFoundError("That branch isn't in your repertoire.")
            return subtree_positions(edges, branch)
        if opening_id is None:
            return None
        for o in self._repertoire.openings(color):
            if o.id == opening_id:
                return subtree_positions(edges, o.root_key)
        raise NotFoundError("That opening isn't in your repertoire.")

    def _get(self, session_id: object) -> _Session:
        with self._lock:
            s = self._sessions.get(session_id) if isinstance(session_id, str) else None
        if s is None:
            raise NotFoundError("That practice session has ended.")
        return s

    def _state(self, s: _Session, correct: Sequence[tuple[str, str]] = ()) -> PracticeState:
        reason = next((t.reason for t in s.targets if t.position_key == s.target), None)
        wrong_fen = None
        if s.state == "wrong" and s.wrong_uci:
            b = s.board.copy()
            b.push(chess.Move.from_uci(s.wrong_uci))
            wrong_fen = b.fen()
        return PracticeState(
            s.id, s.state, s.board.fen(), s.color, s.decisions, s.correct, s.wrong, s.lines_clean, s.lines_lost,
            len(s.targets), reason, s.last_moves, tuple(correct), s.last_attempt, s.message, wrong_fen,
            position_key(s.board),
        )  # fmt: skip

    def _next_line(self, s: _Session, edges: Sequence[Edge]) -> None:
        """Start the next due or new position from the beginning of the game, or finish."""
        s.board = chess.Board()
        s.line_lost = False
        s.message = None
        s.last_moves = ()
        s.wrong_uci = None
        while s.targets and s.decisions < s.limit:
            target = s.targets[0]
            path = path_to(edges, target.position_key)
            if path is None:
                s.targets.pop(0)
                continue
            s.target, s.path = target.position_key, path
            s.state = "your_move"
            s.asked_at = self._clock.now()
            self._advance(s, edges)
            return
        s.state = "finished"
        s.target, s.path = None, []

    def _advance(self, s: _Session, edges: Sequence[Edge]) -> None:
        """Play the opponent's moves until it's your turn or the line runs out."""
        graph = by_position(edges)
        replies: list[tuple[str, str]] = []
        while True:
            key = position_key(s.board)
            if is_your_turn(key, s.color):
                if graph.get(key):
                    s.state = "your_move"
                    s.asked_at = self._clock.now()
                else:
                    self._line_over(s)
                break
            moves = graph.get(key, [])
            if not moves:
                self._line_over(s)
                break
            edge = self._reply(s, moves, key)
            move = chess.Move.from_uci(edge.move_uci)
            replies.append((edge.move_uci, s.board.san(move)))
            s.board.push(move)
        s.last_moves = tuple(replies)

    def _reply(self, s: _Session, moves: Sequence[Edge], key: str) -> Edge:
        while s.path and s.path[0].position_key != key:
            s.path.pop(0)
        if s.path and any(m.move_uci == s.path[0].move_uci for m in moves):
            return s.path.pop(0)
        popular = self._sources.stored_explorer(board_of(key))
        return pick_reply(moves, self._rng, popular.popularity() if popular else None)

    def _line_over(self, s: _Session) -> None:
        s.state = "line_end"
        if s.line_lost:
            s.lines_lost += 1
        else:
            s.lines_clean += 1

    def _record(self, s: _Session, played: chess.Move | None, san: str | None, outcome: str) -> int:
        key = position_key(s.board)
        now = self._clock.now()
        spent = round((now - s.asked_at).total_seconds() * 1000) if s.asked_at else None
        attempt = self._attempts.add(
            s.id, s.color, s.opening_id, key, played.uci() if played else None, san, outcome, spent, now.isoformat()
        )
        s.recorded.add(key)
        s.targets = [t for t in s.targets if t.position_key != key]
        return attempt

    def _close_enough(self, s: _Session, move: chess.Move, answers: Sequence[Edge]) -> bool:
        """FR-12.9: off by default. With it on, a move within the engine tolerance also counts."""
        if not self.tolerance_on():
            return False
        best = self._openings.engine_lines(position_key(s.board), True)
        if not best:
            return False
        after_board = s.board.copy()
        after_board.push(move)
        reply = self._openings.engine_lines(position_key(after_board), True)
        if not reply:
            return False
        return side_cp(best[0], s.color) - side_cp(reply[0], s.color) <= DEFAULT_TOLERANCE_CP

    def play(self, session_id: object, uci: object) -> PracticeState:
        s = self._get(session_id)
        if s.state != "your_move":
            raise ConflictError("It isn't your move.")
        try:
            move = chess.Move.from_uci(uci) if isinstance(uci, str) else None
        except ValueError:
            move = None
        if move is None or move not in s.board.legal_moves:
            raise ValidationError("That move isn't legal here.")
        edges = self._repertoire.edges(s.color)
        key = position_key(s.board)
        answers = by_position(edges).get(key, [])
        san = s.board.san(move)
        s.decisions += 1
        s.message = None
        is_answer = any(a.move_uci == move.uci() for a in answers)
        close = not is_answer and self._close_enough(s, move, answers)
        if not is_answer and not close:
            s.wrong += 1
            s.line_lost = True
            s.last_attempt = self._record(s, move, san, WRONG)
            s.state, s.wrong_uci = "wrong", move.uci()
            s.last_moves = ()
            return self._state(s, tuple((a.move_uci, a.san) for a in answers))
        s.correct += 1
        wanted = key not in s.recorded and any(t.position_key == key and t.reason != "review" for t in s.targets)
        s.last_attempt = self._record(s, move, san, CORRECT) if wanted else None
        s.targets = [t for t in s.targets if t.position_key != key]
        if close:
            answer = answers[0]
            s.message = f"Close enough: {san} is within the engine's tolerance, but your line plays {answer.san}."
            s.board.push(chess.Move.from_uci(answer.move_uci))
        else:
            s.board.push(move)
        note = s.message
        self._advance(s, edges)
        s.message = note
        return self._state(s)

    def show_answer(self, session_id: object) -> PracticeState:
        """Any help before the line ends is a loss (§7.1)."""
        s = self._get(session_id)
        if s.state != "your_move":
            raise ConflictError("It isn't your move.")
        answers = by_position(self._repertoire.edges(s.color)).get(position_key(s.board), [])
        s.decisions += 1
        s.wrong += 1
        s.line_lost = True
        s.last_attempt = self._record(s, None, None, HELPED)
        s.state, s.last_moves = "helped", ()
        return self._state(s, tuple((a.move_uci, a.san) for a in answers))

    def proceed(self, session_id: object) -> PracticeState:
        """After a miss or help: your stored move is played and the line goes on. At a line's end: the next one."""
        s = self._get(session_id)
        edges = self._repertoire.edges(s.color)
        if s.state in ("wrong", "helped"):
            answers = by_position(edges).get(position_key(s.board), [])
            s.state, s.wrong_uci = "your_move", None
            if answers:
                s.board.push(chess.Move.from_uci(answers[0].move_uci))
            self._advance(s, edges)
        elif s.state == "line_end":
            self._next_line(s, edges)
        elif s.state != "your_move":
            raise ConflictError("This session has finished.")
        return self._state(s)

    def end(self, session_id: object) -> None:
        with self._lock:
            if isinstance(session_id, str):
                self._sessions.pop(session_id, None)

    def set_reason(self, attempt_id: object, reason: object, note: object = None) -> None:
        """§7.3 for a missed position. It's stored under its own source, so puzzle reason stats never see it."""
        if isinstance(attempt_id, bool) or not isinstance(attempt_id, int) or attempt_id <= 0:
            raise ValidationError("attempt_id must be a positive whole number.")
        if not isinstance(reason, str):
            raise ValidationError("Unknown mistake reason.")
        key = reason_info(reason).key
        text = validate_note(note)
        row = self._attempts.get(attempt_id)
        if row is None:
            raise NotFoundError("That attempt doesn't exist.")
        if row.outcome == CORRECT:
            raise ConflictError("You got that one right: there's no miss to explain.")
        self._reasons.add("opening", str(attempt_id), key, None, text, self._clock.now().isoformat(timespec="seconds"))

    # ---- stats (FR-12.11) -------------------------------------------------------------------------------------------------

    def _label(self, edges: Sequence[Edge], key: str) -> str:
        path = path_to(edges, key) or []
        out: list[str] = []
        for i, e in enumerate(path):
            out.append(f"{i // 2 + 1}. {e.san}" if i % 2 == 0 else e.san)
        return " ".join(out) or "Start of the game"

    def _leaves(self, edges: Sequence[Edge], root: str) -> list[list[str]]:
        """Each way from `root` to the end of a branch, as its positions. A position seen again ends the branch."""
        graph = by_position(edges)
        out: list[list[str]] = []

        def walk(key: str, seen: list[str]) -> None:
            if len(out) >= MAX_LINES_LISTED:
                return
            moves = graph.get(key, [])
            next_keys = [after(e.position_key, e.move_uci) for e in moves]
            fresh = [k for k in next_keys if k not in seen]
            if not fresh:
                out.append([*seen, key])
                return
            for k in fresh:
                walk(k, [*seen, key])

        walk(root, [])
        return out

    def stats(self, color: object) -> list[OpeningStat]:
        c = check_color(color)
        edges = self._repertoire.edges(c)
        rows = self._attempts.for_color(c)
        by_key: dict[str, list[Any]] = {}
        for row in rows:
            by_key.setdefault(row.position_key, []).append(row)
        cards = self._cards(c, edges)
        today = self._today()
        live = reachable(edges)
        out: list[OpeningStat] = []
        for o in self._repertoire.openings(c):
            if not any(k == o.root_key for k, _ in live) and path_to(edges, o.root_key) is None:
                continue
            within = subtree_positions(edges, o.root_key)
            mine = [k for k in cards if k in within]
            attempts, correct = _tally([r for k in mine for r in by_key.get(k, [])])
            due_keys = [k for k in mine if (card := cards[k]) is not None and is_due(card, today)]
            stats = []
            for k in mine:
                n, good = _tally(by_key.get(k, []))
                if n:
                    stats.append(PositionStat(k, self._label(edges, k), n, good, k in due_keys))
            weakest = sorted((p for p in stats if p.correct < p.attempts), key=lambda p: (p.correct / p.attempts, -p.attempts, p.position_key))[:5]  # fmt: skip
            lines = []
            for leaf in self._leaves(edges, o.root_key):
                decision = [k for k in leaf if is_your_turn(k, c) and k in cards]
                n, good = _tally([r for k in decision for r in by_key.get(k, [])])
                named = next((b for k in reversed(leaf) if (b := self._openings.name_of(k)) is not None), None)
                lines.append(
                    LineStat(
                        named.name if named else o.name,
                        len(decision),
                        n,
                        good,
                        sum(1 for k in decision if k in due_keys),
                    )
                )
            out.append(OpeningStat(o.id, c, o.name, o.eco, len(mine), attempts, correct, len(due_keys), tuple(weakest), tuple(lines)))  # fmt: skip
        return out
