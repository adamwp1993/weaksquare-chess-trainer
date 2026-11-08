"""A downloaded Lichess study, parsed and checked (FR-13.7, 13.8). Pure: text in, data out, no I/O.

Every move is validated with python-chess. A chapter with an illegal move, another variant, or moves from an
invalid position is **rejected** with a reason, and the others are kept. A chapter with no moves whose position is
invalid (a decorative board: empty, or pawn art with no kings) is kept as a **text chapter** (Adam, v0.14 planning).

Comments and titles are untrusted text: `[%…]` commands are removed, control characters stripped and lengths capped,
and they're only ever shown as plain text. Arrows and highlights are parsed item by item, so one invalid square drops
that item only (python-chess drops the whole group).

The tree is stored as JSON in `study_chapters.tree` (see `node_to_json`), so a saved study opens offline exactly as it
was checked. It's stored **flat** (a list of moves, each naming its parent) and every walk here is a loop, never a
recursion per move: a 130-move game nested one level per move would pass Python's recursion limit, and `json` refuses
deep nesting too (QA v0.14-B1).
"""

from __future__ import annotations

import hashlib
import io
import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

import chess
import chess.pgn

from weaksquare.core.study_links import is_study_id

ChapterMode = Literal["normal", "gamebook"]

MAX_CHAPTERS = 64  # Lichess's own limit per study
MAX_NODES = 5000  # moves per chapter, side lines included
MAX_COMMENT = 4000  # characters per comment
MAX_TITLE = 200
TREE_FORMAT = 2  # `node_to_json`'s flat layout

COLORS = {"G": "green", "R": "red", "Y": "yellow", "B": "blue"}
_COMMAND = re.compile(r"\[%(\w+)\s*([^\]]*)\]")
_SQUARE = re.compile(r"^([GRYB])([a-h][1-8])$")
_ARROW = re.compile(r"^([GRYB])([a-h][1-8])([a-h][1-8])$")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-‏‪-‮⁦-⁩]")
_AUTHOR = re.compile(r"^https://lichess\.org/@/([A-Za-z0-9_-]{2,30})$")
_NAME = re.compile(r"^[A-Za-z0-9_-]{2,30}$")
_CHAPTER_URL = re.compile(r"^https://lichess\.org/study/([A-Za-z0-9]{8})/([A-Za-z0-9]{8})$")


@dataclass(frozen=True)
class Shape:
    """An arrow (`orig != dest`) or a highlighted square (`dest` is None)."""

    orig: str
    dest: str | None
    color: str


@dataclass
class Node:
    """One move (the root has no move). `children[0]` is the main line; the rest are side lines."""

    san: str | None = None
    uci: str | None = None
    comment: str = ""
    shapes: list[Shape] = field(default_factory=list)
    nags: list[int] = field(default_factory=list)
    children: list[Node] = field(default_factory=list)


@dataclass
class Chapter:
    index: int  # 0-based order in the study
    chapter_id: str | None  # from ChapterURL; None if Lichess didn't send one
    title: str
    mode: ChapterMode
    orientation: Literal["white", "black"]
    start_fen: str  # always set; the standard start position for most chapters
    text_only: bool = False
    rejected: str | None = None  # why it was rejected; then `root` is empty
    root: Node = field(default_factory=Node)

    @property
    def move_count(self) -> int:
        """Moves in the chapter, side lines included."""
        return _count(self.root) - 1


@dataclass
class Study:
    study_id: str
    title: str
    author: str | None
    chapters: list[Chapter]
    pgn_hash: str  # SHA-256 of the downloaded PGN, to tell whether Check for updates found anything

    @property
    def usable(self) -> list[Chapter]:
        return [c for c in self.chapters if c.rejected is None]


def clean_text(text: object, limit: int = MAX_COMMENT) -> str:
    """Plain text from a comment or title: `[%…]` commands removed, control and bidi characters stripped, whitespace
    tidied, capped. Never interpreted as markup or links; the UI renders it escaped."""
    if not isinstance(text, str):
        return ""
    s = _COMMAND.sub(" ", text)
    s = _CONTROL.sub("", s)
    s = "\n".join(" ".join(line.split()) for line in s.replace("\r\n", "\n").split("\n"))
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s[:limit].rstrip() + ("…" if len(s) > limit else "")


def parse_shapes(comment: object) -> list[Shape]:
    """`[%csl Gd4,Re5]` and `[%cal Ge2e4]`, item by item: an invalid square drops that item only (FR-13.7)."""
    if not isinstance(comment, str):
        return []
    out: list[Shape] = []
    seen: set[tuple[str, str | None]] = set()
    for name, body in _COMMAND.findall(comment):
        if name not in ("csl", "cal"):
            continue
        for item in body.replace(" ", "").split(","):
            m = (_SQUARE if name == "csl" else _ARROW).match(item)
            if not m:
                continue
            color, orig = COLORS[m.group(1)], m.group(2)
            dest = m.group(3) if name == "cal" else None
            if dest == orig:
                dest = None
            if (orig, dest) in seen:
                continue
            seen.add((orig, dest))
            out.append(Shape(orig, dest, color))
    return out


def author_of(headers: chess.pgn.Headers) -> str | None:
    m = _AUTHOR.match(headers.get("Annotator", "").strip())
    return m.group(1) if m else None


def parse_study(study_id: str, pgn: str) -> Study:
    """All chapters of one study's PGN export (`GET /api/study/{id}.pgn`). Raises ValueError if it holds none."""
    if not is_study_id(study_id):
        raise ValueError("not a study ID")
    chapters: list[Chapter] = []
    title, author = "", None
    handle = io.StringIO(pgn)
    for offset, headers in _chapter_offsets(handle):
        handle.seek(offset)
        try:
            game = chess.pgn.read_game(handle, Visitor=LimitedBuilder)
        except TooBig as e:
            chapters.append(_rejected(len(chapters), _chapter_id(headers.get("ChapterURL", "")), f"is too large ({e})"))
            continue
        except Exception:  # python-chess raises on badly broken input
            chapters.append(_rejected(len(chapters), _chapter_id(headers.get("ChapterURL", "")), "couldn't be read"))
            continue
        if game is None:
            break
        if not title:
            title = clean_text(game.headers.get("StudyName", ""), MAX_TITLE)
            author = author_of(game.headers)
        chapters.append(parse_chapter(len(chapters), game))
    if not chapters:
        raise ValueError("the study has no chapters")
    return Study(
        study_id=study_id,
        title=title or "Untitled study",
        author=author,
        chapters=chapters,
        pgn_hash=hashlib.sha256(pgn.encode("utf-8")).hexdigest(),
    )


def parse_chapter(index: int, game: chess.pgn.Game) -> Chapter:
    h = game.headers
    chapter_id = _chapter_id(h.get("ChapterURL", ""))
    name = h.get("ChapterName") or h.get("Event", "").split(": ", 1)[-1]
    title = clean_text(name, MAX_TITLE) or f"Chapter {index + 1}"
    mode: ChapterMode = "gamebook" if h.get("ChapterMode", "").lower() == "gamebook" else "normal"
    orientation: Literal["white", "black"] = "black" if h.get("Orientation", "").lower() == "black" else "white"
    variant = h.get("Variant", "Standard").strip().lower()
    board = game.board()
    fen = board.fen()
    base = Chapter(index, chapter_id, title, mode, orientation, fen)

    if variant not in ("standard", "from position", ""):
        return _with_reason(base, f"is a {h.get('Variant')} chapter; only standard chess is supported")
    if game.errors:
        return _with_reason(base, f"has an illegal or unreadable move ({_first_error(game.errors)})")
    has_moves = bool(game.variations)
    if not board.is_valid():
        if has_moves:
            return _with_reason(base, "starts from an impossible position")
        base.text_only = True
        base.root = Node(comment=clean_text(game.comment))
        return base
    base.root = convert_game(game)
    return base


def convert_game(game: chess.pgn.Game) -> Node:
    """python-chess's tree as ours, every move kept, in a loop (a long main line must not recurse, B1)."""
    root = Node(comment=clean_text(game.comment), shapes=parse_shapes(game.comment))
    stack: list[tuple[chess.pgn.GameNode, Node, chess.Board]] = [(game, root, game.board())]
    while stack:
        pnode, out, board = stack.pop()
        for child in pnode.variations:
            node = Node(
                san=board.san(child.move),
                uci=child.move.uci(),
                comment=clean_text(child.comment),
                shapes=parse_shapes(child.comment),
                nags=sorted(n for n in child.nags if 0 < n < 256),
            )
            out.children.append(node)
            nxt = board.copy(stack=False)
            nxt.push(child.move)
            stack.append((child, node, nxt))
    return root


def _chapter_id(url: str) -> str | None:
    m = _CHAPTER_URL.match(url.strip())
    return m.group(2) if m else None


def _first_error(errors: list[Exception]) -> str:
    msg = str(errors[0]).split(" in ", 1)[0]
    return clean_text(msg, 80) or "unknown error"


def _with_reason(chapter: Chapter, reason: str) -> Chapter:
    chapter.rejected = reason
    chapter.root = Node()
    return chapter


def _rejected(index: int, chapter_id: str | None, reason: str) -> Chapter:
    return Chapter(index, chapter_id, f"Chapter {index + 1}", "normal", "white", chess.STARTING_FEN, rejected=reason)


def _count(node: Node) -> int:
    return sum(1 for _ in walk(node))


def walk(root: Node) -> list[Node]:
    """Every node, root first, in pre-order (a main line before its side lines), without recursion."""
    out: list[Node] = []
    stack = [root]
    while stack:
        n = stack.pop()
        out.append(n)
        stack.extend(reversed(n.children))
    return out


class TooBig(Exception):
    pass


class LimitedBuilder(chess.pgn.GameBuilder):
    """python-chess's builder with a cap on moves and comment size, so a huge chapter can't exhaust memory."""

    def begin_game(self) -> None:
        super().begin_game()
        self._nodes = 0

    def visit_move(self, board: chess.Board, move: chess.Move) -> None:
        self._nodes += 1
        if self._nodes > MAX_NODES:
            raise TooBig(f"more than {MAX_NODES} moves")
        super().visit_move(board, move)

    def visit_comment(self, comment: str | list[str]) -> None:
        text = comment if isinstance(comment, str) else " ".join(comment)
        if len(text) > MAX_COMMENT * 4:
            text = text[: MAX_COMMENT * 4]
        super().visit_comment(text)


def _chapter_offsets(handle: io.StringIO) -> list[tuple[int, chess.pgn.Headers]]:
    """Where each chapter starts, found by reading headers only (python-chess's way to index a multi-game file).
    Each chapter is then parsed from its own offset, so a chapter that's rejected half-way can't swallow the next."""
    found: list[tuple[int, chess.pgn.Headers]] = []
    while len(found) < MAX_CHAPTERS:
        offset = handle.tell()
        try:
            headers = chess.pgn.read_headers(handle)
        except Exception:
            break
        if headers is None:
            break
        found.append((offset, headers))
    return found


# ---- JSON for storage and the bridge --------------------------------------------------------------------------------
def node_to_json(root: Node) -> dict[str, Any]:
    """`{"v": 2, "nodes": [...]}`: the nodes in pre-order, root first; every other node has `p`, its parent's index,
    which is always earlier. Children keep their order (the first is the main line)."""
    nodes: list[dict[str, Any]] = []
    stack: list[tuple[Node, int | None]] = [(root, None)]
    while stack:
        node, parent = stack.pop()
        d: dict[str, Any] = {}
        if parent is not None:
            d["p"] = parent
        if node.san is not None:
            d["san"], d["uci"] = node.san, node.uci
        if node.comment:
            d["comment"] = node.comment
        if node.shapes:
            d["shapes"] = [[s.orig, s.dest, s.color] for s in node.shapes]
        if node.nags:
            d["nags"] = node.nags
        me = len(nodes)
        nodes.append(d)
        stack.extend((c, me) for c in reversed(node.children))
    return {"v": TREE_FORMAT, "nodes": nodes}


def node_from_json(d: Any, board: chess.Board | None = None) -> Node:
    """Read a stored tree back, re-checking every move against `board` (the chapter's start position). A stored tree
    that no longer validates raises ValueError, so a damaged row can't put an illegal move on the board."""
    raw = _stored_nodes(d)
    root = _bare(raw[0])
    if "p" in raw[0]:
        raise ValueError("bad root")
    built: list[tuple[Node, chess.Board]] = [(root, board or chess.Board())]
    for r in raw[1:]:
        p = r.get("p")
        if not isinstance(p, int) or isinstance(p, bool) or not 0 <= p < len(built):
            raise ValueError("bad parent")
        parent, parent_board = built[p]
        try:
            move = chess.Move.from_uci(str(r.get("uci", "")))
        except ValueError:
            raise ValueError("bad move") from None
        if move not in parent_board.legal_moves:
            raise ValueError("illegal stored move")
        child = _bare(r)
        child.san, child.uci = parent_board.san(move), move.uci()
        child_board = parent_board.copy(stack=False)
        child_board.push(move)
        parent.children.append(child)
        built.append((child, child_board))
    return root


def stored_comment(d: Any) -> str:
    """A text chapter's comment from its stored tree (its board can't be replayed); "" if the row is damaged."""
    try:
        return _bare(_stored_nodes(d)[0]).comment
    except ValueError:
        return ""


def _stored_nodes(d: Any) -> list[dict[str, Any]]:
    if not isinstance(d, dict) or d.get("v") != TREE_FORMAT:
        raise ValueError("bad tree")
    raw = d.get("nodes")
    if not isinstance(raw, list) or not raw or len(raw) > MAX_NODES + 1 or not all(isinstance(r, dict) for r in raw):
        raise ValueError("bad tree")
    return raw


def _bare(r: dict[str, Any]) -> Node:
    """A stored node's text, shapes and glyphs, re-cleaned; the move is set by the caller."""
    nags = r.get("nags", [])
    node = Node(comment=clean_text(r.get("comment", "")),
                nags=[n for n in nags if isinstance(n, int) and 0 < n < 256] if isinstance(nags, list) else [])  # fmt: skip
    for s in r.get("shapes", []) if isinstance(r.get("shapes"), list) else []:
        if isinstance(s, list) and len(s) == 3:
            node.shapes.extend(parse_shapes(f"[%{'cal' if s[1] else 'csl'} {_color_letter(s[2])}{s[0]}{s[1] or ''}]"))
    return node


def _color_letter(color: object) -> str:
    for k, v in COLORS.items():
        if v == color:
            return k
    return "X"  # unknown colours fail parse_shapes and are dropped


MAX_PATH = 600
_UCI = re.compile(r"^[a-h][1-8][a-h][1-8][qrbn]?$")


def parse_path(path: object) -> list[str] | None:
    """Your place in a chapter: UCI moves from its start, space-separated. None if malformed."""
    if not isinstance(path, str):
        return None
    moves = path.split()
    if len(moves) > MAX_PATH or not all(_UCI.match(m) for m in moves):
        return None
    return moves


def follow(root: Node, moves: list[str]) -> Node | None:
    """The node reached by playing `moves` through the tree (main line or side lines); None if it leaves the tree."""
    node = root
    for uci in moves:
        nxt = next((c for c in node.children if c.uci == uci), None)
        if nxt is None:
            return None
        node = nxt
    return node


@dataclass(frozen=True)
class ChapterDiff:
    """What Check for updates found (FR-13.7): chapter titles, by chapter."""

    added: list[str]
    removed: list[str]
    changed: list[str]
    unchanged: int

    @property
    def any(self) -> bool:
        return bool(self.added or self.removed or self.changed)


def diff_chapters(old: list[tuple[str, str, str]], new: list[tuple[str, str, str]]) -> ChapterDiff:
    """Compare chapters as (key, title, fingerprint) lists, matched by key (Lichess's chapter ID)."""
    old_by = {k: (t, f) for k, t, f in old}
    new_by = {k: (t, f) for k, t, f in new}
    added = [t for k, t, _ in new if k not in old_by]
    removed = [t for k, t, _ in old if k not in new_by]
    changed = [t for k, t, f in new if k in old_by and old_by[k] != (t, f)]
    unchanged = sum(1 for k, t, f in new if old_by.get(k) == (t, f))
    return ChapterDiff(added, removed, changed, unchanged)


def fingerprint(chapter_json: Any, *extra: object) -> str:
    """A stable hash of a chapter's stored tree and attributes, for `diff_chapters`."""
    blob = json.dumps([chapter_json, *extra], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def mainline(root: Node) -> list[Node]:
    """The main line's moves, in order."""
    out: list[Node] = []
    n = root
    while n.children:
        n = n.children[0]
        out.append(n)
    return out
