"""Puzzles from your own files (v0.8, REQUIREMENTS §10.10, FR-10.46–10.49). Pure: the service reads the
file and stores the puzzles.

Three formats:
- **PGN:** each game is a puzzle. Its `FEN` tag is the position, and its main line is the solution.
  Comments and variations are ignored.
- **EPD:** one position per line, with `pv` (the full line) or `bm` (the best move) as the solution, and
  `id` as an optional name.
- **CSV:** read by header name (`fen`, `solution` or `moves`, and an optional `name`). The solution is
  space-separated, in UCI or SAN.

Every position and every move is checked with python-chess. A bad entry is reported (entry number and
reason) and skipped. The side to move is the solver. A line is cut to end on the solver's move, and if
the file gives only the first move, the puzzle is that one move (FR-10.49).
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from typing import Literal

import chess
import chess.pgn

Format = Literal["pgn", "epd", "csv"]
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_ENTRIES = 20_000
MAX_LINE = 30  # plies: far longer than any real puzzle
MAX_NAME = 120
MAX_LABEL = 60


@dataclass(frozen=True)
class ImportedPuzzle:
    n: int  # entry number in the file, from 1
    fen: str
    solution: tuple[str, ...]  # UCI, ending on the solver's move
    name: str | None

    @property
    def player_color(self) -> str:
        return "white" if chess.Board(self.fen).turn == chess.WHITE else "black"


@dataclass(frozen=True)
class EntryError:
    n: int
    reason: str


Entry = ImportedPuzzle | EntryError


class FileError(Exception):
    """The file as a whole can't be imported."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _too_many(n: int, max_entries: int) -> EntryError:
    """v0.8-B2: the file holds more entries than the app reads; the rest aren't imported."""
    return EntryError(n, f"the file has more than {max_entries:,} entries: this one and the rest weren't read")


def validate_label(label: object) -> str:
    if not isinstance(label, str) or not label.strip():
        raise ValueError("Give the set a label, e.g. the book's title.")
    text = " ".join(label.split())
    if len(text) > MAX_LABEL:
        raise ValueError(f"Keep the label under {MAX_LABEL} characters.")
    return text


def detect_format(filename: str, text: str) -> Format:
    lower = filename.lower()
    for ext in ("pgn", "epd", "csv"):
        if lower.endswith("." + ext):
            return ext  # type: ignore[return-value]
    head = text.lstrip("﻿").lstrip()[:2000]
    if head.startswith("[") or re.match(r"^\d+\.", head):
        return "pgn"
    first = head.splitlines()[0].lower() if head else ""
    if "fen" in first and "," in first:
        return "csv"
    return "epd"


def _clean_name(name: object) -> str | None:
    if not isinstance(name, str):
        return None
    text = " ".join(name.split())[:MAX_NAME]
    return text or None


def _board(fen: str) -> chess.Board:
    try:
        board = chess.Board(fen.strip())
    except ValueError:
        raise ValueError("the position isn't a valid FEN") from None
    if board.status() != chess.STATUS_VALID:
        raise ValueError("the position isn't legal")
    if board.is_game_over():
        raise ValueError("the game is already over in this position")
    return board


def _finish(n: int, board: chess.Board, moves: list[chess.Move], name: str | None) -> Entry:
    if not moves:
        return EntryError(n, "it has no solution moves")
    if len(moves) > MAX_LINE:
        moves = moves[:MAX_LINE]
    if len(moves) % 2 == 0:
        moves = moves[:-1]  # end on the solver's move
    return ImportedPuzzle(n, board.fen(), tuple(m.uci() for m in moves), name)


def _replay(board: chess.Board, tokens: list[str]) -> list[chess.Move]:
    """Each token as UCI, else SAN, from the position; illegal moves raise ValueError."""
    b = board.copy()
    out: list[chess.Move] = []
    for i, tok in enumerate(tokens, 1):
        tok = tok.strip()
        if not tok or re.fullmatch(r"\d+\.+", tok) or tok in ("*", "1-0", "0-1", "1/2-1/2"):
            continue
        tok = re.sub(r"^\d+\.+", "", tok)
        move: chess.Move | None = None
        try:
            cand = chess.Move.from_uci(tok.lower())
            if cand in b.legal_moves:
                move = cand
        except ValueError:
            pass
        if move is None:
            try:
                move = b.parse_san(tok)
            except ValueError:
                raise ValueError(f"move {i} ({tok[:12]}) isn't legal") from None
        if move not in b.legal_moves:  # parse_san accepts a null move
            raise ValueError(f"move {i} ({tok[:12]}) isn't legal")
        out.append(move)
        b.push(move)
    return out


def parse_pgn_puzzles(text: str, max_entries: int = MAX_ENTRIES) -> list[Entry]:
    stream = io.StringIO(text.lstrip("﻿"))
    out: list[Entry] = []
    while True:
        n = len(out) + 1
        if len(out) >= max_entries:
            try:
                more = chess.pgn.read_game(stream)
            except Exception:
                more = None
            if more is not None:
                out.append(_too_many(n, max_entries))
            break
        try:
            game = chess.pgn.read_game(stream)
        except Exception:
            out.append(EntryError(n, "it can't be read as PGN"))
            break
        if game is None:
            break
        fen = game.headers.get("FEN")
        if not fen:
            if not game.variations and not game.errors:
                continue  # stray text between games
            out.append(EntryError(n, "it has no FEN tag, so there's no puzzle position"))
            continue
        variant = game.headers.get("Variant", "").lower()
        if variant and variant not in ("standard", "chess", "from position"):
            out.append(EntryError(n, "only standard chess is supported"))
            continue
        try:
            board = _board(fen)
        except ValueError as e:
            out.append(EntryError(n, str(e)))
            continue
        if game.errors:
            out.append(EntryError(n, "a move in its solution isn't legal"))
            continue
        moves: list[chess.Move] = []
        b = board.copy()
        bad = False
        for node in game.mainline():
            if node.move is None or node.move not in b.legal_moves:
                bad = True
                break
            moves.append(node.move)
            b.push(node.move)
        if bad:
            out.append(EntryError(n, "a move in its solution isn't legal"))
            continue
        event = game.headers.get("Event", "")
        out.append(_finish(n, board, moves, _clean_name(event if event not in ("?", "") else None)))
    return out


def parse_epd(text: str, max_entries: int = MAX_ENTRIES) -> list[Entry]:
    out: list[Entry] = []
    n = 0
    for raw in text.lstrip("﻿").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "%")):
            continue
        n += 1
        if n > max_entries:
            out.append(_too_many(n, max_entries))
            break
        try:
            board = chess.Board()
            ops = board.set_epd(line)
        except ValueError:
            out.append(EntryError(n, "the line isn't valid EPD"))
            continue
        try:
            board = _board(board.fen())
        except ValueError as e:
            out.append(EntryError(n, str(e)))
            continue
        pv, bm = ops.get("pv"), ops.get("bm")
        moves: list[chess.Move] = []
        if isinstance(pv, list) and pv:
            moves = [m for m in pv if isinstance(m, chess.Move)]
        elif isinstance(bm, list) and bm:
            moves = [bm[0]] if isinstance(bm[0], chess.Move) else []
        if not moves:
            out.append(EntryError(n, "it has no bm or pv solution"))
            continue
        b = board.copy()
        legal = True
        for m in moves:
            if m not in b.legal_moves:
                legal = False
                break
            b.push(m)
        if not legal:
            out.append(EntryError(n, "a move in its solution isn't legal"))
            continue
        name = ops.get("id")
        out.append(_finish(n, board, moves, _clean_name(name)))
    return out


def parse_csv(text: str, max_entries: int = MAX_ENTRIES) -> list[Entry]:
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    try:
        header = [h.strip().lower() for h in next(reader)]
    except StopIteration:
        raise FileError("The CSV file is empty.") from None
    col = {h: i for i, h in enumerate(header)}
    fen_i = col.get("fen")
    sol_i = col.get("solution", col.get("moves"))
    name_i = col.get("name")
    if fen_i is None or sol_i is None:
        raise FileError("The CSV needs a header row with 'fen' and 'solution' (or 'moves') columns.")
    out: list[Entry] = []
    for n, row in enumerate(reader, 1):
        if n > max_entries:
            out.append(_too_many(n, max_entries))
            break
        if not any(c.strip() for c in row):
            continue
        if len(row) <= max(fen_i, sol_i):
            out.append(EntryError(n, "the row is missing its FEN or solution"))
            continue
        try:
            board = _board(row[fen_i])
            moves = _replay(board, row[sol_i].split())
        except ValueError as e:
            out.append(EntryError(n, str(e)))
            continue
        name = row[name_i] if name_i is not None and name_i < len(row) else None
        out.append(_finish(n, board, moves, _clean_name(name)))
    return out


def parse_puzzle_file(filename: str, text: str) -> tuple[Format, list[Entry]]:
    if len(text.encode("utf-8", errors="replace")) > MAX_FILE_BYTES:
        raise FileError(f"The file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB.")
    fmt = detect_format(filename, text)
    entries = {"pgn": parse_pgn_puzzles, "epd": parse_epd, "csv": parse_csv}[fmt](text)
    if not entries:
        raise FileError("No puzzles found in the file.")
    return fmt, entries
