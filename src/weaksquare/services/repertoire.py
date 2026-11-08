"""Your repertoire (v0.13, FR-12.4): add an opening's lines, list the tree, remove by reachability, and choose
main moves. Moves come from the book, the engine, the explorer or you, and each is checked with python-chess
before it's stored. There's no path here for a move from an LLM."""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import chess

from weaksquare.core.clock import Clock
from weaksquare.core.engine import EngineNotInstalled
from weaksquare.core.errors import NotFoundError, ValidationError
from weaksquare.core.opening_practice import (
    BuildLimits,
    Popular,
    ProposedMove,
    Sources,
    parse_their_move,
    path_sources,
    path_to,
    propose,
)
from weaksquare.core.openings import Line, board_of, position_key
from weaksquare.core.repertoire import (
    Edge,
    NewMove,
    TreeRow,
    check_color,
    is_your_turn,
    line_to_moves,
    removal,
    tree_rows,
)
from weaksquare.jobs.runner import CancelToken, JobRunner, ProgressFn
from weaksquare.services.opening_sources import OpeningSources
from weaksquare.services.openings import OpeningsService


class Repo(Protocol):
    def edges(self, color: str) -> list[Edge]: ...

    def add_moves(self, color: str, moves: Sequence[NewMove], created_at: str) -> int: ...

    def delete(self, color: str, edges: Sequence[Edge]) -> None: ...

    def set_main(self, color: str, position_key: str, move_uci: str) -> bool: ...

    def set_order(self, color: str, position_key: str, order: Sequence[str]) -> None: ...

    def openings(self, color: str | None = None) -> list[Any]: ...

    def add_opening(
        self, color: str, name: str, eco: str, root_key: str, root_moves: Sequence[str], created_at: str
    ) -> None: ...

    def delete_opening(self, opening_id: int) -> None: ...


@dataclass(frozen=True)
class RepertoireView:
    color: str
    rows: tuple[TreeRow, ...]
    openings: tuple[Any, ...]


@dataclass(frozen=True)
class AddResult:
    added: int  # new moves stored
    kept: int  # moves you already had, left exactly as they were


@dataclass(frozen=True)
class DeviationReply:
    uci: str
    san: str
    score: str


@dataclass(frozen=True)
class Deviation:
    """FR-12.8: their move, checked, and Stockfish's best replies to it."""

    their_uci: str
    their_san: str
    fen_after: str
    replies: tuple[DeviationReply, ...]
    game_over: str | None


@dataclass(frozen=True)
class Proposal:
    id: str
    color: str
    family: str
    moves: tuple[ProposedMove, ...]


LIMIT_RANGES = {"max_moves": (2, 20), "max_replies": (1, 6), "max_positions": (5, 200)}
BUILD_JOB = "repertoire_build"


def _check_limits(raw: object) -> BuildLimits:
    if not isinstance(raw, dict) or set(raw) - {"max_moves", "min_share", "max_replies", "max_positions"}:
        raise ValidationError("Unknown repertoire limits.")
    base = BuildLimits()
    values: dict[str, int] = {}
    for name, (low, high) in LIMIT_RANGES.items():
        v = raw.get(name, getattr(base, name))
        if isinstance(v, bool) or not isinstance(v, int) or not low <= v <= high:
            raise ValidationError(f"{name.replace('_', ' ').capitalize()} must be from {low} to {high}.")
        values[name] = v
    share = raw.get("min_share", base.min_share)
    if isinstance(share, bool) or not isinstance(share, int | float) or not 0 <= share <= 0.5:
        raise ValidationError("The share of games must be from 0 to 50%.")
    return BuildLimits(values["max_moves"], float(share), values["max_replies"], values["max_positions"])


def _moves_board(moves: object) -> chess.Board:
    """A line of UCI moves from the start of the game, checked before anything else sees it."""
    if not isinstance(moves, list):
        raise ValidationError("That isn't a line of moves.")
    board = chess.Board()
    for uci in moves:
        try:
            move = chess.Move.from_uci(uci) if isinstance(uci, str) else None
        except ValueError:
            move = None
        if move is None or move not in board.legal_moves:
            raise ValidationError("That isn't a line of legal moves.")
        board.push(move)
    return board


def _check_key(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("That position isn't in your repertoire.")
    return value


class RepertoireService:
    def __init__(
        self, repo: Repo, openings: OpeningsService, sources: OpeningSources, runner: JobRunner, clock: Clock
    ) -> None:
        self._sources = sources
        self._runner = runner
        self._lock = threading.Lock()
        self._proposals: dict[str, Proposal] = {}
        self._next_proposal = 0
        self._repo = repo
        self._openings = openings
        self._clock = clock

    def _now(self) -> str:
        return self._clock.now().isoformat()

    def view(self, color: object) -> RepertoireView:
        c = check_color(color)
        return RepertoireView(c, tuple(tree_rows(self._repo.edges(c), c)), tuple(self._repo.openings(c)))

    def edges(self, color: object) -> list[Edge]:
        return self._repo.edges(check_color(color))

    def openings(self, color: object) -> list[Any]:
        return self._repo.openings(check_color(color))

    # ---- "What if they play…?" (FR-12.8) --------------------------------------------------------------------

    def what_if(self, color: object, moves: object, their_move: object) -> Deviation:
        """Check their move, then ask Stockfish for your best replies. An illegal move never reaches the engine."""
        c = check_color(color)
        board = _moves_board(moves)
        if is_your_turn(position_key(board), c):
            raise ValidationError("It's your move here. A deviation is a move for the other side.")
        move = parse_their_move(board, their_move)
        if move is None:
            raise ValidationError("That move isn't legal here.")
        san = board.san(move)
        board.push(move)
        if self._openings.engine_status_state() != "ready":
            raise EngineNotInstalled("Install Stockfish to get replies to this move.")
        analysis = self._openings.analyze(board.fen(), "board", c)
        replies = []
        for line in analysis.lines:
            if line.pv:
                reply = chess.Move.from_uci(line.pv[0])
                replies.append(DeviationReply(line.pv[0], board.san(reply), line.score))
        return Deviation(move.uci(), san, board.fen(), tuple(replies), analysis.game_over)

    def add_deviation(self, color: object, moves: object, their_move: object, reply_uci: object) -> AddResult:
        """Store the branch, and what it hangs from, so it's connected and gets drilled (FR-12.8)."""
        c = check_color(color)
        board = _moves_board(moves)
        if is_your_turn(position_key(board), c):
            raise ValidationError("It's your move here. A deviation is a move for the other side.")
        their = parse_their_move(board, their_move)
        if their is None:
            raise ValidationError("That move isn't legal here.")
        after_their = board.copy()
        after_their.push(their)
        try:
            reply = chess.Move.from_uci(reply_uci) if isinstance(reply_uci, str) else None
        except ValueError:
            reply = None
        if reply is None or reply not in after_their.legal_moves:
            raise ValidationError("That reply isn't legal here.")
        ucis = [str(m) for m in moves]  # type: ignore[attr-defined]
        pairs = path_sources(ucis, self._openings.is_book_move, self._openings.stored_source)
        stored = self._openings.engine_lines(position_key(after_their), False) or []
        best = {ln.pv[0] for ln in stored if ln.pv}
        reply_source = "engine" if reply.uci() in best else "you"
        pairs.extend([(their.uci(), "you"), (reply.uci(), reply_source)])
        new = line_to_moves(pairs)
        added = self._repo.add_moves(c, new, self._now())
        self._list_opening_of(c, [uci for uci, _ in pairs])
        return AddResult(added, len(new) - added)

    def _list_opening_of(self, color: str, ucis: Sequence[str]) -> None:
        """A branch belongs to the deepest opening the book names along it, so Stats and the Practice menu can show it."""
        board = chess.Board()
        on_path = {position_key(board)}
        named = []
        for uci in ucis:
            board.push(chess.Move.from_uci(uci))
            key = position_key(board)
            on_path.add(key)
            line = self._openings.name_of(key)
            if line is not None:
                named.append(line)
        for line in reversed(named):
            root = self._openings.root(line.family)
            if root.final_key in on_path:
                self._repo.add_opening(color, root.family, root.eco, root.final_key, root.moves, self._now())
                return

    # ---- Build my repertoire (FR-12.14) ---------------------------------------------------------------------

    def _build_sources(self, color: str) -> Sources:
        def popular(board: chess.Board) -> tuple[int, list[Popular]] | None:
            found = self._sources.fetch_explorer(board)
            if found is None or not found.moves:
                return None
            return found.total, [Popular(m.uci, m.games) for m in found.moves]

        def engine(board: chess.Board) -> list[Any]:
            return self._openings.engine_lines(position_key(board), True) or []

        stored: dict[str, list[Edge]] = {}
        for e in self._repo.edges(color):
            stored.setdefault(e.position_key, []).append(e)
        return Sources(popular, self._openings.book_moves, engine, stored)

    def build_now(
        self, color: object, family: object, limits: object, cancel: Callable[[], None] = lambda: None
    ) -> Proposal:
        """Work out a proposal. **Nothing is saved**: it waits for `save_proposal`, after you've reviewed it."""
        c = check_color(color)
        lim = _check_limits(limits)
        root = self._openings.root(family)
        src = self._build_sources(c)

        def checked(fn: Callable[[chess.Board], Any]) -> Callable[[chess.Board], Any]:
            def run(board: chess.Board) -> Any:
                cancel()
                return fn(board)

            return run

        guarded = Sources(checked(src.popular), checked(src.book), checked(src.engine), src.stored)
        moves = propose(root.moves, c, lim, guarded)
        with self._lock:
            self._next_proposal += 1
            proposal = Proposal(f"b{self._next_proposal}", c, root.family, tuple(moves))
            self._proposals[proposal.id] = proposal
        return proposal

    def start_build(self, color: object, family: object, limits: object) -> str:
        c = check_color(color)
        _check_limits(limits)
        root = self._openings.root(family)
        if self._openings.engine_status_state() != "ready" and not self._sources.signed_in():
            raise EngineNotInstalled("Install Stockfish or sign in to Lichess to build a repertoire.")

        def job(progress: ProgressFn, token: CancelToken) -> str:
            progress(None, "Looking at replies and answers…")
            proposal = self.build_now(c, root.family, limits, token.raise_if_cancelled)
            return proposal.id

        return self._runner.submit(BUILD_JOB, job)

    def proposal(self, proposal_id: object) -> Proposal:
        with self._lock:
            found = self._proposals.get(proposal_id) if isinstance(proposal_id, str) else None
        if found is None:
            raise NotFoundError("That proposal has gone. Build it again.")
        return found

    def latest_proposal(self) -> Proposal | None:
        with self._lock:
            return self._proposals.get(f"b{self._next_proposal}")

    def save_proposal(self, proposal_id: object) -> AddResult:
        """Store a reviewed proposal. A move you already have stays exactly as it was."""
        p = self.proposal(proposal_id)
        new = [NewMove(m.position_key, m.move_uci, m.san, m.source) for m in p.moves]
        added = self._repo.add_moves(p.color, new, self._now())
        root = self._openings.root(p.family)
        self._repo.add_opening(p.color, root.family, root.eco, root.final_key, root.moves, self._now())
        with self._lock:
            self._proposals.pop(p.id, None)
        return AddResult(added, len(new) - added)

    def discard_proposal(self, proposal_id: object) -> None:
        with self._lock:
            if isinstance(proposal_id, str):
                self._proposals.pop(proposal_id, None)

    def _store(self, color: str, lines: Sequence[Line]) -> AddResult:
        moves: dict[tuple[str, str], NewMove] = {}
        for line in lines:
            for m in line_to_moves([(x.uci, x.source) for x in line.moves]):
                moves.setdefault((m.position_key, m.move_uci), m)
        added = self._repo.add_moves(color, list(moves.values()), self._now())
        return AddResult(added, len(moves) - added)

    def add_study_moves(self, color: object, moves: Sequence[NewMove], mains: Sequence[tuple[str, str]]) -> AddResult:
        """v0.14 (FR-13.11): moves from a study, already planned by `core.study_repertoire` (checked, reachable, with
        your conflict choices applied). Each is checked again here. `mains` are the study moves you chose over yours:
        they become the main move at their position, and yours stay as sidelines."""
        c = check_color(color)
        for m in moves:
            board = board_of(m.position_key)
            move = chess.Move.from_uci(m.move_uci)
            if move not in board.legal_moves or m.source != "study":
                raise ValidationError("That move can't be added.")
        added = self._repo.add_moves(c, list(moves), self._now())
        for key, uci in mains:
            self._repo.set_main(c, key, uci)
        return AddResult(added, len(moves) - added)

    def add_lines(self, color: object, family: object, indices: object) -> AddResult:
        """Add lines the service works out for itself, so a move's source can't be claimed by the caller."""
        c = check_color(color)
        if not isinstance(indices, list) or not indices:
            raise ValidationError("Choose at least one line to add.")
        lines = self._openings.lines(family).lines
        chosen: list[Line] = []
        for i in indices:
            if not isinstance(i, int) or isinstance(i, bool) or not 0 <= i < len(lines):
                raise ValidationError("That line isn't in this opening.")
            chosen.append(lines[i])
        root = self._openings.root(family)
        result = self._store(c, chosen)
        self._repo.add_opening(c, root.family, root.eco, root.final_key, root.moves, self._now())
        return result

    def removal_preview(self, color: object, key: object, move_uci: object) -> list[Edge]:
        c = check_color(color)
        edges = self._repo.edges(c)
        k = _check_key(key)
        if not any(e.position_key == k and e.move_uci == move_uci for e in edges):
            raise NotFoundError("That move isn't in your repertoire.")
        return removal(edges, k, str(move_uci))

    def remove(self, color: object, key: object, move_uci: object) -> int:
        """Remove a move and whatever only it could reach (FR-12.4). Returns how many moves went."""
        gone = self.removal_preview(color, key, move_uci)
        c = check_color(color)
        self._repo.delete(c, gone)
        left = self._repo.edges(c)
        for opening in self._repo.openings(c):
            if path_to(left, opening.root_key) is None:  # its moves have gone, so it's no longer in your repertoire
                self._repo.delete_opening(opening.id)
        return len(gone)

    def set_main(self, color: object, key: object, move_uci: object) -> None:
        if not isinstance(move_uci, str) or not self._repo.set_main(check_color(color), _check_key(key), move_uci):
            raise NotFoundError("That move isn't in your repertoire.")

    def move(self, color: object, key: object, move_uci: object, direction: object) -> None:
        """Reorder a move among its position's moves (FR-12.4)."""
        c = check_color(color)
        k = _check_key(key)
        if direction not in ("up", "down"):
            raise ValidationError("Move it up or down.")
        here = [e.move_uci for e in self._repo.edges(c) if e.position_key == k]
        if move_uci not in here:
            raise NotFoundError("That move isn't in your repertoire.")
        i = here.index(str(move_uci))
        j = i - 1 if direction == "up" else i + 1
        if 0 <= j < len(here):
            here[i], here[j] = here[j], here[i]
            self._repo.set_order(c, k, here)
