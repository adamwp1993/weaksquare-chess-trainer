"""The opening book (v0.13, REQUIREMENTS §18.1). Pure: parsing, position keys, ranking and line selection.

**Position keys** (FR-12.1): the FEN without move counters, with an en passant square only if the capture
is legal, so two move orders reaching one position share a key.

**Ranking** (FR-12.2): the book has no main-line marker. A move's weight is its explorer popularity when
given, otherwise the number of book lines that pass through it; ties go to the shorter line, then the name,
then the move, so the order never depends on input order.

**Lines** (FR-12.7a, 12.13): the main line follows the top-ranked move at each step, and each sub-line
leaves it at the next-ranked unused branch. Moves past the book come from a caller's `next_move`, because
the explorer and the engine are I/O. A line never holds a move from an LLM: there's no way to give it one.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field

import chess

from weaksquare.core.errors import ValidationError

STARTING_KEY = chess.Board().epd(en_passant="legal")

SOURCE_BOOK, SOURCE_ENGINE, SOURCE_EXPLORER, SOURCE_YOU = "book", "engine", "explorer", "you"
MOVE_NUMBER = re.compile(r"^\d+\.+$")
MAX_LINE_PLIES = 40  # 20 moves, the highest Custom scope (FR-12.7a)


# FR-12.7a: sub-lines besides the main line, and moves per line (an upper limit, FR-12.13).
PRESETS: dict[str, tuple[int, int]] = {"light": (1, 8), "standard": (3, 12), "deep": (6, 16)}
CUSTOM_SUB_LINES = (0, 10)
CUSTOM_MOVES = (4, 20)


@dataclass(frozen=True)
class OpeningScope:
    preset: str
    sub_lines: int
    max_moves: int


def validate_scope(preset: object, sub_lines: object = None, max_moves: object = None) -> OpeningScope:
    """A preset gives its numbers; Custom's are clamped to their limits (FR-12.7a)."""
    if preset in PRESETS:
        subs, moves = PRESETS[str(preset)]
        return OpeningScope(str(preset), subs, moves)
    if preset != "custom":
        raise ValidationError("Choose Light, Standard, Deep or Custom.")
    for value in (sub_lines, max_moves):
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValidationError("Custom needs whole numbers for sub-lines and moves per line.")
    assert isinstance(sub_lines, int) and isinstance(max_moves, int)
    return OpeningScope(
        "custom",
        min(CUSTOM_SUB_LINES[1], max(CUSTOM_SUB_LINES[0], sub_lines)),
        min(CUSTOM_MOVES[1], max(CUSTOM_MOVES[0], max_moves)),
    )


class OpeningDataError(ValueError):
    """A book line that isn't legal chess."""


def position_key(board: chess.Board) -> str:
    return board.epd(en_passant="legal")


def board_of(key: str) -> chess.Board:
    """The position a key stands for. Move counters aren't part of a key, so they start afresh."""
    return chess.Board(f"{key} 0 1")


def family_of(name: str) -> str:
    """'Italian Game: Giuoco Piano' -> 'Italian Game'."""
    return name.split(":", 1)[0].strip()


@dataclass(frozen=True)
class BookLine:
    eco: str
    name: str
    pgn: str
    moves: tuple[str, ...]  # UCI
    sans: tuple[str, ...]
    keys: tuple[str, ...]  # one per position: len(moves) + 1, starting with the initial position
    id: int = 0

    @property
    def family(self) -> str:
        return family_of(self.name)

    @property
    def final_key(self) -> str:
        return self.keys[-1]


def parse_line(eco: str, name: str, pgn: str, line_id: int = 0) -> BookLine:
    """One book row, checked with python-chess (FR-12.1). Any problem raises OpeningDataError."""
    eco, name, pgn = eco.strip(), name.strip(), pgn.strip()
    if not eco or not name or not pgn:
        raise OpeningDataError("a book line needs an ECO code, a name and moves")
    board = chess.Board()
    moves: list[str] = []
    sans: list[str] = []
    keys = [position_key(board)]
    for token in pgn.split():
        if MOVE_NUMBER.match(token):
            continue
        try:
            move = board.parse_san(token)
        except ValueError as e:
            raise OpeningDataError(f"{name}: {token} isn't legal in {board.fen()}") from e
        sans.append(board.san(move))
        moves.append(move.uci())
        board.push(move)
        keys.append(position_key(board))
    if not moves:
        raise OpeningDataError(f"{name}: no moves")
    return BookLine(eco, name, pgn, tuple(moves), tuple(sans), tuple(keys), line_id)


def rows_of_tsv(text: str) -> Iterable[tuple[str, str, str]]:
    """The rows of one book file, read by header name, as every data file is (CLAUDE.md)."""
    lines = [ln for ln in text.replace("\r\n", "\n").split("\n") if ln.strip()]
    if not lines:
        return
    header = lines[0].split("\t")
    try:
        eco, name, pgn = header.index("eco"), header.index("name"), header.index("pgn")
    except ValueError as e:
        raise OpeningDataError("a book file needs eco, name and pgn columns") from e
    for line in lines[1:]:
        cells = line.split("\t")
        if len(cells) <= max(eco, name, pgn):
            raise OpeningDataError(f"a book row is too short: {line[:60]}")
        yield cells[eco], cells[name], cells[pgn]


@dataclass(frozen=True)
class Family:
    """One entry in the browse list: 'Italian Game', and the line that names its starting position."""

    name: str
    eco: str
    root: BookLine
    lines: int


def root_of(lines: Sequence[BookLine], family: str) -> BookLine | None:
    """The line naming a family's own position: its exact name if there is one, otherwise its shortest."""
    members = [ln for ln in lines if ln.family == family]
    if not members:
        return None
    exact = [ln for ln in members if ln.name == family]
    return min(exact or members, key=lambda ln: (len(ln.moves), ln.name, ln.moves))


def families(lines: Sequence[BookLine]) -> list[Family]:
    counts: dict[str, int] = {}
    for ln in lines:
        counts[ln.family] = counts.get(ln.family, 0) + 1
    out: list[Family] = []
    for name in sorted(counts):
        root = root_of(lines, name)
        assert root is not None
        out.append(Family(name, root.eco, root, counts[name]))
    return out


@dataclass
class BookIndex:
    """Book moves by position, merging move orders. `through[(key, uci)]` is how many lines use the move."""

    through: dict[tuple[str, str], int] = field(default_factory=dict)
    moves: dict[str, list[str]] = field(default_factory=dict)
    sans: dict[tuple[str, str], str] = field(default_factory=dict)
    shortest: dict[tuple[str, str], int] = field(default_factory=dict)
    name: dict[tuple[str, str], str] = field(default_factory=dict)
    named: dict[str, BookLine] = field(default_factory=dict)  # the line ending at a position


def build_index(lines: Iterable[BookLine]) -> BookIndex:
    ix = BookIndex()
    for ln in lines:
        current = ix.named.get(ln.final_key)
        if current is None or (len(ln.moves), ln.name) < (len(current.moves), current.name):
            ix.named[ln.final_key] = ln
        for i, uci in enumerate(ln.moves):
            edge = (ln.keys[i], uci)
            if edge not in ix.through:
                ix.moves.setdefault(ln.keys[i], []).append(uci)
                ix.sans[edge] = ln.sans[i]
                ix.through[edge] = 0
                ix.shortest[edge] = len(ln.moves)
                ix.name[edge] = ln.name
            ix.through[edge] += 1
            if (len(ln.moves), ln.name) < (ix.shortest[edge], ix.name[edge]):
                ix.shortest[edge], ix.name[edge] = len(ln.moves), ln.name
    return ix


def ranked_moves(ix: BookIndex, key: str, popularity: Mapping[str, int] | None = None) -> list[str]:
    """The book's moves at a position, best first. `popularity` is explorer games per UCI move."""
    moves = ix.moves.get(key, [])
    pop = popularity or {}

    def order(uci: str) -> tuple[int, int, int, str, str]:
        edge = (key, uci)
        return (-pop.get(uci, 0), -ix.through[edge], ix.shortest[edge], ix.name[edge], uci)

    return sorted(moves, key=order)


@dataclass(frozen=True)
class LineMove:
    uci: str
    san: str
    source: str  # book / explorer / engine
    key_before: str


@dataclass(frozen=True)
class Line:
    name: str
    eco: str
    moves: tuple[LineMove, ...]

    @property
    def keys(self) -> tuple[str, ...]:
        if not self.moves:
            return ()
        return (*(m.key_before for m in self.moves), final_key_of(self.moves))


def final_key_of(moves: Sequence[LineMove]) -> str:
    board = board_of(moves[-1].key_before)
    board.push(chess.Move.from_uci(moves[-1].uci))
    return position_key(board)


NextMove = Callable[[chess.Board], tuple[str, str] | None]  # a board -> (uci, source), or None to stop
PopularityOf = Callable[[str], Mapping[str, int] | None]  # a position key -> explorer games per move


def _walk(
    ix: BookIndex, prefix: tuple[LineMove, ...], max_plies: int, popularity: PopularityOf
) -> tuple[LineMove, ...]:
    """From the end of `prefix`, follow the top-ranked book move until the book or the limit ends."""
    moves = list(prefix)
    board = chess.Board()
    for m in moves:
        board.push(chess.Move.from_uci(m.uci))
    seen = {position_key(board)}
    while len(moves) < max_plies:
        key = position_key(board)
        ranked = ranked_moves(ix, key, popularity(key))
        if not ranked:
            break
        uci = ranked[0]
        move = chess.Move.from_uci(uci)
        moves.append(LineMove(uci, board.san(move), SOURCE_BOOK, key))
        board.push(move)
        after = position_key(board)
        if after in seen:
            break
        seen.add(after)
    return tuple(moves)


def _no_popularity(_key: str) -> None:
    return None


def _label(ix: BookIndex, line: tuple[LineMove, ...], root: BookLine) -> tuple[str, str]:
    """The most specific book name along the line."""
    named = root
    for key in (*(m.key_before for m in line), final_key_of(line)):
        found = ix.named.get(key)
        if found is not None:
            named = found
    return named.name, named.eco


def select_lines(
    ix: BookIndex,
    root: BookLine,
    sub_lines: int,
    max_moves: int,
    popularity: PopularityOf = _no_popularity,
) -> list[Line]:
    """The main line through `root`, then up to `sub_lines` next-ranked branches off lines already chosen
    (FR-12.7a). `max_moves` counts full moves from the start of the game."""
    max_plies = min(MAX_LINE_PLIES, max(1, max_moves) * 2)
    prefix = tuple(
        LineMove(uci, san, SOURCE_BOOK, key)
        for uci, san, key in zip(root.moves, root.sans, root.keys[:-1], strict=True)
    )
    main = _walk(ix, prefix, max_plies, popularity)
    chosen = [main]

    used: set[tuple[str, str]] = {(m.key_before, m.uci) for m in main}
    while len(chosen) - 1 < sub_lines:
        best: tuple[tuple[int, int, int, str, str], tuple[LineMove, ...], str] | None = None
        for line in chosen:
            for i in range(len(root.moves), len(line)):
                key = line[i].key_before
                pop = popularity(key) or {}
                for uci in ix.moves.get(key, []):
                    if (key, uci) in used:
                        continue
                    edge = (key, uci)
                    order = (-pop.get(uci, 0), -ix.through[edge], ix.shortest[edge], ix.name[edge], uci)
                    if best is None or order < best[0]:
                        best = (order, line[:i], uci)
        if best is None:
            break
        _, head, uci = best
        b = chess.Board()
        for m in head:
            b.push(chess.Move.from_uci(m.uci))
        key = position_key(b)
        move = chess.Move.from_uci(uci)
        branch = (*head, LineMove(uci, b.san(move), SOURCE_BOOK, key))
        full = _walk(ix, branch, max_plies, popularity) if len(branch) < max_plies else branch
        used.update((m.key_before, m.uci) for m in full)
        chosen.append(full)
    return [Line(*_label(ix, ln, root), ln) for ln in chosen]


def extend_line(line: Line, max_moves: int, next_move: NextMove) -> Line:
    """Continue a line past the book (FR-12.13). `next_move` is the explorer or the engine, and every move
    is checked here, so a bad one ends the line instead of entering it."""
    max_plies = min(MAX_LINE_PLIES, max(1, max_moves) * 2)
    board = chess.Board()
    moves = list(line.moves)
    for m in moves:
        board.push(chess.Move.from_uci(m.uci))
    while len(moves) < max_plies and not board.is_game_over(claim_draw=False):
        got = next_move(board)
        if got is None:
            break
        uci, source = got
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            break
        if move not in board.legal_moves:
            break
        moves.append(LineMove(uci, board.san(move), source, position_key(board)))
        board.push(move)
    return Line(line.name, line.eco, tuple(moves))
