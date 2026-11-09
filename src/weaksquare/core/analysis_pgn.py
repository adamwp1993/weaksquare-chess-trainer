"""A PGN pasted into the Analysis tab (v0.15, FR-14.3). Pure: text in, move trees out, no I/O.

Each game becomes a move tree with its side lines, through the same converter and size caps as Lichess studies
(`core.study_pgn`), so every move is checked by python-chess. What's kept is only the moves, their glyphs, the
comments as plain text (`[%clk]`, `[%eval]` and the other commands removed) and their arrows. Headers are used only for
the "pick a game" label and are never sent anywhere. Nothing here is added to your game library.

A PGN that can't be used raises `GameError` with a message, before anything changes on the board.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import chess
import chess.pgn

from weaksquare.core.games import MAX_PGN_BYTES, GameError
from weaksquare.core.study_pgn import LimitedBuilder, Node, TooBig, clean_text, convert_game, has_null_move, mainline

MAX_GAMES = 200  # listed to pick from; a bigger file says so


@dataclass(frozen=True)
class AnalysisGame:
    index: int
    label: str
    start_fen: str
    root: Node

    @property
    def move_count(self) -> int:
        """Half-moves on the main line, for the pick list (side lines aren't counted: QA v0.15-B5)."""
        return len(mainline(self.root))


def parse_analysis_pgn(text: object) -> tuple[list[AnalysisGame], list[str]]:
    """The usable games in `text`, and one sentence for each game that was skipped. Raises `GameError` when nothing in
    it is usable."""
    if not isinstance(text, str) or not text.strip():
        raise GameError("Paste a PGN first.")
    if len(text.encode("utf-8", errors="replace")) > MAX_PGN_BYTES:
        raise GameError(f"The PGN is larger than {MAX_PGN_BYTES // (1024 * 1024)} MB.")
    stream = io.StringIO(text.lstrip("﻿"))
    games: list[AnalysisGame] = []
    skipped: list[str] = []
    n = 0
    while True:
        try:
            game = chess.pgn.read_game(stream, Visitor=LimitedBuilder)
        except TooBig as e:
            skipped.append(f"Game {n + 1} is too large ({e}). Nothing after it was read.")
            break
        except Exception:  # python-chess raises on some malformed headers
            skipped.append(f"Game {n + 1} can't be read. Nothing after it was read.")
            break
        if game is None:
            break
        if not game.variations and not game.errors and _blank(game.headers):
            continue  # text that isn't PGN at all reads as an empty game
        if len(games) + len(skipped) >= MAX_GAMES:
            skipped.append(f"The PGN has more than {MAX_GAMES} games: only the first {MAX_GAMES} are listed.")
            break
        reason = _problem(n, game)
        if reason:
            skipped.append(reason)
        else:
            games.append(AnalysisGame(n, _label(n, game.headers), game.board().fen(), convert_game(game)))
        n += 1
    if not games:
        if skipped:
            raise GameError(skipped[0])
        raise GameError('That isn\'t a PGN. Paste one that starts with tags like [White "…"] or with 1. e4.')
    return games, skipped


def _problem(n: int, game: chess.pgn.Game) -> str | None:
    variant = game.headers.get("Variant", "").strip().lower()
    if variant and variant not in ("standard", "chess", "from position", "fromposition"):
        return f"Game {n + 1} is {clean_text(game.headers.get('Variant'), 40)}: only standard chess is supported."
    try:
        board = game.board()
    except ValueError:
        return f"Game {n + 1} has a starting position that isn't a valid FEN."
    if board.chess960 and board.has_chess960_castling_rights():
        return f"Game {n + 1} is Chess960: only standard chess is supported."
    if not board.is_valid():
        return f"Game {n + 1} starts from an impossible position."
    if game.errors:
        msg = clean_text(str(game.errors[0]).split(" in ", 1)[0], 80) or "unknown error"
        return f"Game {n + 1} has an illegal or unreadable move ({msg})."
    if has_null_move(game):
        return f"Game {n + 1} has a null move (--), which isn't a real move."
    return None


def _label(n: int, headers: chess.pgn.Headers) -> str:
    """For the pick list, shown only on your screen: `White – Black, 2026.10.01 (1-0)`, else `Game 3`."""

    def tag(name: str) -> str:
        v = clean_text(headers.get(name, ""), 40)
        return "" if v in ("?", "????.??.??", "*") else v

    white, black, date, result = tag("White"), tag("Black"), tag("Date").replace(".??", ""), tag("Result")
    if not (white or black):
        event = tag("Event")
        return f"Game {n + 1}" + (f": {event}" if event else "")
    label = f"{white or '?'} – {black or '?'}"
    return label + (f", {date}" if date else "") + (f" ({result})" if result else "")


def _blank(headers: chess.pgn.Headers) -> bool:
    return all(v in ("?", "????.??.??", "*", "") for v in headers.values())
