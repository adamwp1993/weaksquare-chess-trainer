"""Where the opening trainer's outside text and popularity come from (v0.13, FR-12.2, 12.15). Pure.

**Wikibooks** (FR-12.15): pages of *Chess Opening Theory* are named by the line's SAN path, so a transposed
position may have no page under this move order, and that's simply "no page". The text is publicly editable,
so it's **untrusted**: it's stripped of URLs and reference sections and cut to size before it's kept, sent or
shown. Every link is built here, from the page title, and never from anything in the text.

**The explorer** (FR-12.2): a response is checked field by field, and a move that isn't legal is dropped.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import chess

from weaksquare.core.explain import CONTROL

WIKI_ROOT = "Chess Opening Theory"
WIKI_BASE = "https://en.wikibooks.org/wiki/"
LICENCE_NAME = "CC BY-SA 4.0"
LICENCE_URL = "https://creativecommons.org/licenses/by-sa/4.0/"
MAX_PAGE_CHARS = 8000  # what's kept and shown for one page
MAX_PROMPT_PAGE_CHARS = 3000  # what one page may add to a prompt
MAX_PROMPT_CHARS = 8000  # what all pages together may add to a prompt

# Any scheme, a bare //, www., a domain with a path, or a domain on a common ending. A bare "word.word" isn't a link:
# chess text has plenty, such as "1.e4" and "Nf3.Then".
URL = re.compile(
    r"(?:\b[a-z][a-z0-9+.-]*://|(?<![:\w/])//|\bwww\.)\S+"
    r"|\b[\w-]+(?:\.[\w-]+)*\.[a-z]{2,}/\S*"
    r"|\b[\w-]+(?:\.[\w-]+)*\.(?:com|org|net|edu|gov|info|io|co|uk)\b",
    re.IGNORECASE,
)
WORD = re.compile(r"\S+")
MAX_WORD_CHARS = (
    100  # a longer run with no space isn't prose: dropping it whole keeps URL's time bounded on hostile text
)
DROP_SECTIONS = ("theory table", "statistics", "references", "see also", "external links", "further reading", "notes")


def page_title(sans: Sequence[str]) -> str:
    """'Chess Opening Theory/1. e4/1...e5/2. Nf3', the book's own naming, which leaves out + and #."""
    parts = [WIKI_ROOT]
    for i, raw in enumerate(sans):
        number = i // 2 + 1
        san = raw.rstrip("+#")
        parts.append(f"{number}. {san}" if i % 2 == 0 else f"{number}...{san}")
    return "/".join(parts)


def page_url(title: str) -> str:
    return WIKI_BASE + quote(title.replace(" ", "_"), safe="/_.")


def short_title(title: str) -> str:
    """The moves part of a title, for an attribution line."""
    return title.removeprefix(WIKI_ROOT).lstrip("/").replace("/", " ") or WIKI_ROOT


def _no_links(line: str) -> str:
    """URL can't cross a space, so it runs word by word, and anyone can edit a page: it must stay quick on any text."""
    return WORD.sub(lambda m: "" if len(m[0]) > MAX_WORD_CHARS else URL.sub("", m[0]), line)


def _heading(line: str) -> tuple[int, str] | None:
    """'== Name ==' as its level and name. Plain string work, because a pattern backtracks badly on a long run of '='."""
    s = line.strip()
    if not (s.startswith("=") and s.endswith("=")):
        return None
    name = s.strip("=").strip()
    return (len(s) - len(s.lstrip("=")), name) if name else None


def clean_page(text: str) -> str:
    """Plain text ready to keep: no URLs, no control characters, no reference sections, capped."""
    kept: list[str] = []
    dropping_level = 0
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = CONTROL.sub("", raw)
        heading = _heading(line)
        if heading:
            level, name = heading
            if any(name.lower().startswith(d) for d in DROP_SECTIONS):
                dropping_level = level
                continue
            if dropping_level and level > dropping_level:
                continue
            dropping_level = 0
            kept.append(_no_links(name).strip())
            continue
        if dropping_level:
            continue
        kept.append(_no_links(line).rstrip())
    out = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()
    return out[:MAX_PAGE_CHARS].rstrip()


@dataclass(frozen=True)
class WikiPage:
    title: str
    status: str  # 'ok' or 'missing'
    revision_id: int | None
    text: str


def parse_extract(title: str, data: Any) -> WikiPage:
    """The MediaWiki `query` answer for one title. Anything unexpected counts as no page."""
    missing = WikiPage(title, "missing", None, "")
    try:
        page = data["query"]["pages"][0]
    except (KeyError, IndexError, TypeError):
        return missing
    if not isinstance(page, dict) or page.get("missing") or not isinstance(page.get("extract"), str):
        return missing
    text = clean_page(page["extract"])
    if not text:
        return missing
    revisions = page.get("revisions")
    rev = (
        revisions[0].get("revid")
        if isinstance(revisions, list) and revisions and isinstance(revisions[0], dict)
        else None
    )
    return WikiPage(title, "ok", rev if isinstance(rev, int) and not isinstance(rev, bool) else None, text)


def prompt_text(pages: Sequence[WikiPage]) -> tuple[str, tuple[WikiPage, ...]]:
    """Reference text for a prompt, within the limits, and the pages it actually drew on (FR-12.15)."""
    parts: list[str] = []
    used: list[WikiPage] = []
    left = MAX_PROMPT_CHARS
    for page in pages:
        if page.status != "ok" or not page.text or left <= 0:
            continue
        cut = page.text[: min(MAX_PROMPT_PAGE_CHARS, left)]
        parts.append(f"[{short_title(page.title)}]\n{cut}")
        used.append(page)
        left -= len(cut)
    return "\n\n".join(parts), tuple(used)


def unfetched_chars(pages: int) -> int:
    """FR-12.15: no page is fetched before you Confirm, so an estimate counts them at the limit."""
    return min(MAX_PROMPT_CHARS, max(0, pages) * MAX_PROMPT_PAGE_CHARS)


# ---- the explorer ----------------------------------------------------------------------------------------

EXPLORER_SOURCES = ("lichess", "masters")
EXPLORER_RATINGS = (0, 1000, 1200, 1400, 1600, 1800, 2000, 2200, 2500)
EXPLORER_SPEEDS = "blitz,rapid,classical,correspondence"
DEFAULT_RATINGS = (1600, 1800, 2000)
MAX_MOVES = 12


@dataclass(frozen=True)
class ExplorerMove:
    uci: str
    san: str
    games: int


@dataclass(frozen=True)
class ExplorerResult:
    total: int
    moves: tuple[ExplorerMove, ...]

    def popularity(self) -> dict[str, int]:
        return {m.uci: m.games for m in self.moves}


def _count(row: Any, key: str) -> int:
    value = row.get(key) if isinstance(row, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def parse_explorer(board: chess.Board, data: Any) -> ExplorerResult:
    """Keep the legal moves with their game counts, most played first. SAN is rebuilt, never trusted."""
    rows = data.get("moves") if isinstance(data, dict) else None
    moves: list[ExplorerMove] = []
    for row in rows if isinstance(rows, list) else []:
        uci = row.get("uci") if isinstance(row, dict) else None
        if not isinstance(uci, str):
            continue
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            continue
        if move not in board.legal_moves:
            continue
        games = _count(row, "white") + _count(row, "draws") + _count(row, "black")
        moves.append(ExplorerMove(uci, board.san(move), games))
    moves.sort(key=lambda m: (-m.games, m.uci))
    total = _count(data, "white") + _count(data, "draws") + _count(data, "black")
    return ExplorerResult(total or sum(m.games for m in moves), tuple(moves))


def validate_explorer_settings(source: Any, ratings: Any) -> tuple[str, tuple[int, ...]]:
    from weaksquare.core.errors import ValidationError

    if source not in EXPLORER_SOURCES:
        raise ValidationError("Popular moves come from Lichess games or masters' games.")
    if not isinstance(ratings, list | tuple) or not ratings:
        raise ValidationError("Choose at least one rating band.")
    picked: list[int] = []
    for r in ratings:
        if isinstance(r, bool) or r not in EXPLORER_RATINGS:
            raise ValidationError("That isn't one of the explorer's rating bands.")
        picked.append(int(r))
    return str(source), tuple(sorted(set(picked)))
