"""Game Review (v0.8, REQUIREMENTS §11.3): the review of an analyzed game, Retry mode, Save as puzzle and
mistake reasons on your game moves.

- **The review** is built from the stored analysis only (the refutation of every move is stored), so
  opening it needs no engine call (FR-11.12–11.14).
- **Retry mode** (FR-11.15): from the position before each of your mistakes, you play a move; any move
  within the tolerance of the best (30 cp by default) counts as found. Moves the analysis didn't cover
  are checked with the **interactive** engine (never the background one). The answer is returned only
  with the result. Results are stored locally, never synced (FR-11.22).
- **Save as puzzle** (FR-11.16): the position before a mistake becomes a `custom_puzzles` row, solved
  with the engine tolerance (Adam, v0.8 planning). One puzzle per game and ply.
- **Reasons** (FR-5.7): on each of your inaccuracies, mistakes and blunders, and after a Retry miss.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC
from typing import Any, Protocol

import chess

from weaksquare.core.clock import Clock
from weaksquare.core.engine import EngineLine, EngineNotInstalled, score_for, validate_fen
from weaksquare.core.errors import ConflictError, NotFoundError, ValidationError
from weaksquare.core.game_review import (
    ERRORS,
    SYMBOLS,
    MoveRow,
    Score,
    SideSummary,
    key_moments,
    saved_line,
    side_summary,
    white_eval,
)
from weaksquare.core.games import GameRow, parse_single_pgn
from weaksquare.core.puzzle import Color, NewCustomPuzzle
from weaksquare.core.reasons import ReasonContext, is_forcing_reply, reason_info, suggest, validate_note
from weaksquare.core.tagging import best_line_themes
from weaksquare.core.tolerance import within_tolerance
from weaksquare.services.analysis import ReviewSettings

RETRY_CLASSES = ("mistake", "blunder")


class Games(Protocol):
    def get(self, game_id: int) -> GameRow | None: ...


class Analysis(Protocol):
    def rows(self, game_id: int) -> list[MoveRow]: ...


class ReviewPrefs(Protocol):
    def settings(self) -> ReviewSettings: ...


class AskPrefs(Protocol):
    def reasons_ask(self) -> str: ...


class InteractiveEngine(Protocol):
    def analyse(
        self, board: chess.Board, player: Any, *, multipv: int = ..., key: Any = ..., gen: Any = ...
    ) -> Any: ...

    def status(self) -> Any: ...

    def ticket(self, key: Any) -> int: ...


class CustomPuzzles(Protocol):
    def add(self, p: Any, created_at: str) -> tuple[int, bool]: ...

    def saved_plies(self, game_id: int) -> set[int]: ...


class Retries(Protocol):
    def add(
        self, game_id: int, ply: int, played_uci: str, found: bool, cp_loss: int | None, created_at: str
    ) -> int: ...

    def get(self, retry_id: int) -> tuple[int, int, bool] | None: ...


class Reasons(Protocol):
    def add(
        self, source: str, ref_id: str, reason: str, suggested: str | None, note: str | None, created_at: str
    ) -> None: ...

    def latest(self, source: str, ref_id: str) -> Any: ...


@dataclass(frozen=True)
class LineView:
    score: str  # from the mover's side: "+1.2", "−0.4", "Mate in 3", "Mated in 2"
    pv: tuple[str, ...]  # UCI from the position
    sans: tuple[str, ...]


@dataclass(frozen=True)
class MoveView:
    ply: int
    san: str
    uci: str
    mover: str
    fen_before: str
    classification: str | None  # None until analyzed
    symbol: str | None  # ?! ? ??
    cp_loss: int | None
    eval_white: int | None  # the eval after the move from White's side, clamped (the graph)
    eval_text: str | None  # the same as text: "+1.2", "#3", "#-2"
    best_move: str | None
    best_san: str | None
    lines: tuple[LineView, ...]
    refutation: tuple[str, ...]  # the best line after this move (FR-11.14)
    kind: str | None
    phase: str | None
    low_clock: bool | None
    reason: str | None
    suggested_reason: str | None
    saved: bool  # already saved as a puzzle


@dataclass(frozen=True)
class ReviewView:
    game: GameRow
    start_fen: str
    moves: tuple[MoveView, ...]
    analyzed: bool
    current: bool  # analyzed at today's settings
    summaries: tuple[SideSummary, ...]  # White, then Black (FR-11.11)
    key_moments: tuple[int, ...]  # plies (FR-11.13)
    retry_plies: tuple[int, ...]  # your mistakes and blunders (FR-11.15)
    ask_reasons: bool  # the FR-5.8 setting allows asking in Game Review


@dataclass(frozen=True)
class RetryResult:
    retry_id: int
    found: bool
    played_san: str
    played_score: str
    best_san: str | None
    best_line: tuple[str, ...]  # UCI from the position: the answer, shown only now
    reply_line: tuple[str, ...]  # the engine's answer to your move, when it wasn't found
    suggested_reason: str | None
    engine_checked: bool  # False: Stockfish isn't installed, so only the analysis's lines could be used


def _score_text(s: Score) -> str:
    if s.mate is not None:
        if s.mate == 0:
            return "Checkmate"
        return f"Mate in {s.mate}" if s.mate > 0 else f"Mated in {-s.mate}"
    v = (s.cp or 0) / 100
    return "0.0" if round(v, 1) == 0 else f"{'+' if v > 0 else '−'}{abs(v):.1f}"


def _white_text(row: MoveRow) -> str:
    s = row.eval_after if row.mover == "white" else row.eval_after.negate()
    if s.mate is not None:
        if s.mate == 0:
            return "#"  # mate delivered by White
        return f"#{s.mate}" if s.mate > 0 else f"#-{-s.mate}"
    v = (s.cp or 0) / 100
    return f"{v:+.1f}"


def _sans(fen: str, pv: Sequence[str]) -> tuple[str, ...]:
    b = chess.Board(fen)
    out: list[str] = []
    for uci in pv:
        try:
            m = chess.Move.from_uci(uci)
        except ValueError:
            break
        if m not in b.legal_moves:
            break
        out.append(b.san(m))
        b.push(m)
    return tuple(out)


def _line_view(fen: str, line: EngineLine, mover: str) -> LineView:
    cp, mate = score_for(line, "white" if mover == "white" else "black")
    sans = _sans(fen, line.pv)
    return LineView(_score_text(Score(cp, mate)), tuple(line.pv[: len(sans)]), sans)


class ReviewService:
    def __init__(
        self,
        games: Games,
        analysis: Analysis,
        prefs: ReviewPrefs,
        is_current: Any,
        engine: InteractiveEngine,
        puzzles: CustomPuzzles,
        retries: Retries,
        reasons: Reasons,
        ask: AskPrefs,
        clock: Clock,
    ) -> None:
        self._games = games
        self._analysis = analysis
        self._prefs = prefs
        self._is_current = is_current
        self._engine = engine
        self._puzzles = puzzles
        self._retries = retries
        self._reasons = reasons
        self._ask = ask
        self._clock = clock

    def _game(self, game_id: int) -> GameRow:
        if not isinstance(game_id, int) or isinstance(game_id, bool):
            raise ValidationError("game_id must be a whole number")
        g = self._games.get(game_id)
        if g is None:
            raise NotFoundError("That game isn't in your library.")
        return g

    def _now(self) -> str:
        return self._clock.now().astimezone(UTC).isoformat(timespec="seconds")

    def _yours(self, game: GameRow, mover: str) -> bool:
        return game.user_color == "both" or game.user_color == mover

    def _suggestion(self, row: MoveRow) -> str | None:
        reply = row.refutation[0] if row.refutation else None
        fen_after = None
        if reply:
            b = chess.Board(row.fen_before)
            b.push(chess.Move.from_uci(row.move_uci))
            fen_after = b.fen()
        ctx = ReasonContext(
            decisive_ms=None,
            rushed_ms=0,
            low_clock=bool(row.low_clock),
            reply_forcing=bool(reply and fen_after and is_forcing_reply(fen_after, reply)),
            reply_mates=row.eval_after.mate is not None and row.eval_after.mate < 0,
        )
        return suggest(ctx)

    # ------------------------------------------------------------ the review

    def review(self, game_id: int) -> ReviewView:
        game = self._game(game_id)
        parsed = parse_single_pgn(game.pgn)
        rows = self._analysis.rows(game_id) if game.analysis_status != "none" else []
        analyzed = len(rows) == len(parsed.moves) and bool(rows)
        st = self._prefs.settings()
        saved = self._puzzles.saved_plies(game_id) if analyzed else set()
        moves: list[MoveView] = []
        board = chess.Board(parsed.start_fen)
        for i, (uci, san) in enumerate(zip(parsed.moves, parsed.sans, strict=True)):
            mover = "white" if board.turn == chess.WHITE else "black"
            r = rows[i] if analyzed else None
            reason = suggested = None
            if r is not None and r.classification in ERRORS and self._yours(game, mover):
                latest = self._reasons.latest("game", f"{game_id}:{i}")
                reason = latest.reason if latest else None
                suggested = self._suggestion(r)
            moves.append(
                MoveView(
                    ply=i, san=san, uci=uci, mover=mover, fen_before=board.fen(),
                    classification=r.classification if r else None,
                    symbol=SYMBOLS.get(r.classification) if r else None,
                    cp_loss=r.cp_loss if r else None,
                    eval_white=white_eval(r) if r else None,
                    eval_text=_white_text(r) if r else None,
                    best_move=r.best_move if r else None,
                    best_san=_sans(r.fen_before, [r.best_move])[0] if r and r.best_move else None,
                    lines=tuple(_line_view(r.fen_before, ln, mover) for ln in r.lines) if r else (),
                    refutation=r.refutation if r else (),
                    kind=r.kind if r else None, phase=r.phase if r else None, low_clock=r.low_clock if r else None,
                    reason=reason, suggested_reason=suggested, saved=i in saved,
                )
            )  # fmt: skip
            board.push(chess.Move.from_uci(uci))
        colors = ("white", "black") if game.user_color == "both" else (game.user_color,) if game.user_color else ()
        moments: list[int] = []
        retry: list[int] = []
        if analyzed:
            for c in colors:
                moments += [r.ply for r in key_moments(rows, c, st.key_moments)]
                retry += [r.ply for r in rows if r.mover == c and r.classification in RETRY_CLASSES]
        summaries = (
            (side_summary(rows, "white", game.accuracy_white), side_summary(rows, "black", game.accuracy_black))
            if analyzed
            else ()
        )
        return ReviewView(
            game=game,
            start_fen=parsed.start_fen,
            moves=tuple(moves),
            analyzed=analyzed,
            current=analyzed and bool(self._is_current(game)),
            summaries=summaries,
            key_moments=tuple(sorted(moments)),
            retry_plies=tuple(sorted(retry)),
            ask_reasons=self._ask.reasons_ask() in ("always", "game_review"),
        )

    def _row(self, game: GameRow, ply: int) -> MoveRow:
        if not isinstance(ply, int) or isinstance(ply, bool):
            raise ValidationError("ply must be a whole number")
        rows = self._analysis.rows(game.id) if game.analysis_status != "none" else []
        if not rows:
            raise ConflictError("Analyze this game first.", retryable=False)
        if not 0 <= ply < len(rows):
            raise ValidationError("That move isn't in this game.")
        return rows[ply]

    # ------------------------------------------------------------ Retry mode

    def retry_move(
        self, game_id: int, ply: int, uci: str, think_ms: int | None = None, rushed_ms: int = 3000
    ) -> RetryResult:
        game = self._game(game_id)
        row = self._row(game, ply)
        if not self._yours(game, row.mover) or row.classification not in RETRY_CLASSES:
            raise ValidationError("Retry works on your mistakes and blunders.")
        board = chess.Board(row.fen_before)
        try:
            move = chess.Move.from_uci(uci) if isinstance(uci, str) else None
        except ValueError:
            move = None
        if move is None or move not in board.legal_moves:
            raise ValidationError("That move isn't legal here.")
        mover: Color = "white" if row.mover == "white" else "black"
        best = Score(*score_for(row.lines[0], mover)) if row.lines else row.eval_before
        played: Score | None = None
        reply: tuple[str, ...] = ()
        checked = True
        for ln in row.lines:  # a move the analysis already scored needs no engine call
            if ln.pv and ln.pv[0] == move.uci():
                played = Score(*score_for(ln, mover))
                reply = tuple(ln.pv[1:])
        after = board.copy()
        after.push(move)
        if after.is_checkmate():
            played = Score(None, 0)
        if played is None:
            if self._engine.status().state == "ready":
                analysis = self._engine.analyse(after, mover)
                if analysis.lines:
                    first = analysis.lines[0]
                    played = Score(first.cp, first.mate)
                    reply = tuple(first.pv)
                else:  # stalemate or a draw by rule after your move
                    played = Score(0, None)
            else:
                checked = False
        found = played is not None and within_tolerance(best, played, self._prefs.settings().tolerance_cp)
        loss = max(0, best.value() - played.value()) if played is not None else None
        # v0.8-B3: without Stockfish a move off the stored lines can't be graded: not a miss, not recorded.
        rid = self._retries.add(game_id, ply, move.uci(), found, loss, self._now()) if checked else 0
        suggested = None
        if not found and checked:
            ctx = ReasonContext(
                decisive_ms=think_ms,
                rushed_ms=rushed_ms,
                reply_forcing=bool(reply) and is_forcing_reply(after.fen(), reply[0]),
                reply_mates=played is not None and played.mate is not None and played.mate < 0,
            )
            suggested = suggest(ctx)
        best_line = row.lines[0].pv if row.lines else ((row.best_move,) if row.best_move else ())
        return RetryResult(
            retry_id=rid,
            found=found,
            played_san=board.san(move),
            played_score=_score_text(played) if played is not None else "not checked",
            best_san=_sans(row.fen_before, best_line[:1])[0] if best_line else None,
            best_line=tuple(best_line),
            reply_line=() if found else reply,
            suggested_reason=suggested,
            engine_checked=checked,
        )

    # ------------------------------------------------------------ Save as puzzle

    def save_as_puzzle(self, game_id: int, ply: int) -> tuple[int, bool]:
        """(puzzle id, created). The position before the move, solved as the side that moved, with the
        engine's best line (FR-11.16)."""
        game = self._game(game_id)
        row = self._row(game, ply)
        if not row.lines or not row.lines[0].pv:
            raise ConflictError("There's no engine line to save for this move.", retryable=False)
        line = saved_line(row.lines[0].pv)
        themes = best_line_themes(self._analysis.rows(game_id), ply)  # rows[ply] is this move (_row)
        return self._puzzles.add(
            NewCustomPuzzle(
                fen=row.fen_before, solution=line, player_color=row.mover, origin="manual", strict=False,
                game_id=game_id, ply=ply, kind=row.kind,
                severity=row.classification if row.classification in ERRORS else None,
                cp_loss=row.cp_loss, phase=row.phase, time_class=game.time_class,
                game_date=(game.played_at or "")[:10] or None, themes=themes,
            ),
            self._now(),
        )  # fmt: skip

    # ------------------------------------------------------------ Analyze from here (v0.10, FR-11.34)

    def analyze_position(self, game_id: int, fen: Any, purpose: Any = "board") -> Any:
        """Eval and top lines for any position on the free analysis board opened from a game, on the
        **interactive** engine (never the background one, ARCHITECTURE §3 decision 12). The position is
        validated first (FR-7.6). Nothing here touches the game, its analysis or any stats."""
        if purpose not in ("panel", "board"):
            raise ValidationError("Unknown analysis purpose.")
        game = self._game(game_id)
        board = validate_fen(fen)
        if self._engine.status().state != "ready":
            raise EngineNotInstalled("Install Stockfish to analyze positions.")
        color = game.user_color if game.user_color in ("white", "black") else ("white" if board.turn else "black")
        key = ("review", game.id, purpose)
        return self._engine.analyse(board, color, key=key, gen=self._engine.ticket(key))

    # ------------------------------------------------------------ reasons

    def set_game_reason(self, game_id: int, ply: int, reason: str, note: str | None = None) -> None:
        """FR-5.7: why you made this mistake. The latest choice counts."""
        reason_info(reason)
        text = validate_note(note)
        game = self._game(game_id)
        row = self._row(game, ply)
        if not self._yours(game, row.mover) or row.classification not in ERRORS:
            raise ValidationError("Reasons are for your inaccuracies, mistakes and blunders.")
        self._reasons.add("game", f"{game_id}:{ply}", reason, self._suggestion(row), text, self._now())

    def set_retry_reason(
        self, retry_id: int, reason: str, note: str | None = None, suggested: str | None = None
    ) -> None:
        reason_info(reason)
        text = validate_note(note)
        if not isinstance(retry_id, int) or isinstance(retry_id, bool):
            raise ValidationError("retry_id must be a whole number")
        found = self._retries.get(retry_id)
        if found is None:
            raise NotFoundError("That retry isn't recorded.")
        if found[2]:
            raise ValidationError("Reasons are for misses.")
        self._reasons.add("retry", str(retry_id), reason, suggested, text, self._now())
