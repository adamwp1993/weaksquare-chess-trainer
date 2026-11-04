"""Games (v0.8, REQUIREMENTS §11): PGN parsing and validation, color detection, URL parsing, time
classes, and the parser for Lichess's game JSON. Pure: the HTTP clients are `adapters/lichess_games.py`
and `adapters/chesscom.py`; chess.com's archive format is parsed in `core/chesscom.py`.

Only standard chess is supported (FR-11.6). A game may start from a set-up position (Lichess's
"From Position"), as long as the position is legal standard chess.
"""

from __future__ import annotations

import hashlib
import io
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

import chess
import chess.pgn

Side = Literal["white", "black"]
UserColor = Literal["white", "black", "both"]
TimeClass = Literal["bullet", "blitz", "rapid", "classical", "daily"]
TIME_CLASSES: tuple[str, ...] = ("bullet", "blitz", "rapid", "classical", "daily")
GAME_SOURCES: tuple[str, ...] = ("lichess", "chesscom", "paste", "file")

MAX_PGN_BYTES = 10 * 1024 * 1024  # a game file (plan v0.8)
MAX_GAMES_LISTED = 500
MAX_PLIES = 400
RESULTS = ("1-0", "0-1", "1/2-1/2", "*")


class GameError(Exception):
    """A game that can't be imported, with a reason the user can act on (FR-11.6)."""

    def __init__(self, reason: str, index: int = 0) -> None:
        super().__init__(reason)
        self.reason = reason
        self.index = index


@dataclass(frozen=True)
class ParsedGame:
    """One validated game from a PGN. `moves` are UCI from `start_fen`; `clocks[i]` is the mover's
    remaining time in seconds after ply i (from `%clk`), or None."""

    index: int
    headers: dict[str, str]
    start_fen: str
    moves: tuple[str, ...]
    sans: tuple[str, ...]
    clocks: tuple[float | None, ...]
    pgn: str

    @property
    def white(self) -> str:
        return self.headers.get("White", "?")

    @property
    def black(self) -> str:
        return self.headers.get("Black", "?")

    @property
    def result(self) -> str:
        r = self.headers.get("Result", "*")
        return r if r in RESULTS else "*"

    @property
    def label(self) -> str:
        """For the "pick a game" list: `White – Black, 2026.10.01 (1-0)`."""
        date = self.headers.get("Date", "").replace("????.??.??", "").strip()
        return f"{self.white} – {self.black}" + (f", {date}" if date else "") + f" ({self.result})"


@dataclass(frozen=True)
class GameRecord:
    """A game ready for the `games` table. Player fields are per color, because your color can be
    unknown at import time. `played_at` is ISO-8601 UTC, or None."""

    source: str
    source_game_id: str | None
    url: str | None
    pgn: str
    played_at: str | None = None
    time_control: str | None = None
    time_class: str | None = None
    rated: bool | None = None
    white: str | None = None
    black: str | None = None
    white_rating: int | None = None
    black_rating: int | None = None
    result: str = "*"
    eco: str | None = None
    opening: str | None = None
    accuracy_white: float | None = None
    accuracy_black: float | None = None
    lichess_analyzed: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


class Skip(Exception):
    """A platform game that is valid data but not importable (a variant, an aborted game)."""


# ---------------------------------------------------------------- PGN


def _is_variant(headers: chess.pgn.Headers) -> str | None:
    variant = headers.get("Variant", "").strip().lower()
    if variant and variant not in ("standard", "chess", "from position", "fromposition"):
        return headers.get("Variant", variant)
    return None


def _one_game(index: int, game: chess.pgn.Game) -> ParsedGame:
    variant = _is_variant(game.headers)
    if variant:
        raise GameError(f"Game {index + 1} is {variant}: only standard chess is supported.", index)
    try:
        board = game.board()
    except ValueError as e:
        raise GameError(f"Game {index + 1} has an invalid starting position ({e}).", index) from e
    if board.chess960 and board.has_chess960_castling_rights():
        raise GameError(f"Game {index + 1} is Chess960: only standard chess is supported.", index)
    if board.status() != chess.STATUS_VALID:
        raise GameError(f"Game {index + 1} has an invalid starting position.", index)
    if game.errors:
        raise GameError(f"Game {index + 1} has an illegal or unreadable move ({game.errors[0]}).", index)
    start_fen = board.fen()
    moves: list[str] = []
    sans: list[str] = []
    clocks: list[float | None] = []
    for node in game.mainline():
        move = node.move
        if move is None or move not in board.legal_moves:  # null moves (`--`) are not real moves
            raise GameError(f"Game {index + 1} has an illegal move at ply {len(moves) + 1}.", index)
        sans.append(board.san(move))
        moves.append(move.uci())
        board.push(move)
        clocks.append(node.clock())
        if len(moves) > MAX_PLIES:
            raise GameError(f"Game {index + 1} is longer than {MAX_PLIES} plies.", index)
    if not moves:
        raise GameError(f"Game {index + 1} has no moves.", index)
    exporter = chess.pgn.StringExporter(headers=True, variations=False, comments=True)
    return ParsedGame(
        index=index,
        headers=dict(game.headers),
        start_fen=start_fen,
        moves=tuple(moves),
        sans=tuple(sans),
        clocks=tuple(clocks),
        pgn=game.accept(exporter),
    )


def parse_pgn(text: str, *, max_games: int = MAX_GAMES_LISTED) -> list[ParsedGame | GameError]:
    """Every game in `text`, each either parsed or a `GameError` saying why not. A file with no
    recognizable game raises `GameError`."""
    if len(text.encode("utf-8", errors="replace")) > MAX_PGN_BYTES:
        raise GameError(f"The PGN is larger than {MAX_PGN_BYTES // (1024 * 1024)} MB.")
    stream = io.StringIO(text.lstrip("﻿"))
    out: list[ParsedGame | GameError] = []
    while len(out) < max_games:
        try:
            game = chess.pgn.read_game(stream)
        except Exception as e:  # python-chess raises on some malformed headers
            out.append(GameError(f"Game {len(out) + 1} can't be read ({e}).", len(out)))
            break
        if game is None:
            break
        # read_game returns an empty game for text that isn't PGN at all ("hello world"): not a game
        if not game.variations and not game.errors and _blank(game.headers):
            continue
        try:
            out.append(_one_game(len(out), game))
        except GameError as e:
            out.append(e)
    if not out:
        raise GameError('No game found. Paste a PGN that starts with tags like [White "…"] or with 1. e4.')
    return out


def _blank(headers: chess.pgn.Headers) -> bool:
    return all(v in ("?", "????.??.??", "*", "") for v in headers.values())


def parse_single_pgn(text: str) -> ParsedGame:
    """Exactly the first game in `text` (the platform exports hold one game)."""
    first = parse_pgn(text, max_games=1)[0]
    if isinstance(first, GameError):
        raise first
    return first


def moves_hash(start_fen: str, moves: tuple[str, ...] | list[str]) -> str:
    """Identity of a game by its moves (FR-11.7): the same moves from the same start are the same game."""
    return hashlib.sha256((start_fen + "|" + " ".join(moves)).encode("ascii")).hexdigest()


def detect_color(white: str | None, black: str | None, usernames: list[str]) -> Side | None:
    """Your color from the player names and your linked usernames (FR-11.5), or None if unknown."""
    names = {u.strip().lower() for u in usernames if u and u.strip()}
    w = (white or "").strip().lower()
    b = (black or "").strip().lower()
    if w in names and b not in names:
        return "white"
    if b in names and w not in names:
        return "black"
    return None


# ---------------------------------------------------------------- time controls

_TC = re.compile(r"^(\d+)(?:\+(\d+))?$")


def time_class(time_control: str | None) -> str | None:
    """Lichess's speed rule (estimated duration = base + 40 × increment): under 3 min bullet, under 8
    blitz, under 25 rapid, else classical. `1/86400`-style or `-` is daily (correspondence)."""
    if not time_control:
        return None
    tc = time_control.strip()
    if tc == "-" or "/" in tc:
        return "daily"
    m = _TC.match(tc)
    if not m:
        return None
    est = int(m.group(1)) + 40 * int(m.group(2) or 0)
    if est < 180:
        return "bullet"
    if est < 480:
        return "blitz"
    if est < 1500:
        return "rapid"
    return "classical"


def base_seconds(time_control: str | None) -> int | None:
    m = _TC.match((time_control or "").strip())
    return int(m.group(1)) if m else None


def low_clock(remaining_s: float | None, time_control: str | None) -> bool | None:
    """Under 10% of the starting time (FR-10.13), or None without clock data."""
    base = base_seconds(time_control)
    if remaining_s is None or not base:
        return None
    return remaining_s < 0.1 * base


# ---------------------------------------------------------------- URLs

_LICHESS_URL = re.compile(
    r"^(?:https?://)?(?:www\.)?lichess\.org/(?:game/export/)?([A-Za-z0-9]{8})(?:[A-Za-z0-9]{4})?"
    r"(?:/(?:white|black))?/?(?:[#?].*)?$"
)
_CHESSCOM_URL = re.compile(
    r"^(?:https?://)?(?:www\.)?chess\.com/(?:analysis/)?game/(live|daily)/(\d{1,15})/?(?:[#?].*)?$"
)
_CHESSCOM_LEGACY = re.compile(r"^(?:https?://)?(?:www\.)?chess\.com/(live|daily)/game/(\d{1,15})/?(?:[#?].*)?$")
_USERNAME = re.compile(r"^[A-Za-z0-9_-]{2,30}$")


def parse_lichess_url(text: str) -> str | None:
    """The 8-character game id from a Lichess game URL (FR-11.3), or None."""
    m = _LICHESS_URL.match(text.strip())
    return m.group(1) if m else None


def parse_chesscom_url(text: str) -> tuple[str, str] | None:
    """(`live` or `daily`, numeric id) from a chess.com game URL (FR-11.4), or None."""
    t = text.strip()
    m = _CHESSCOM_URL.match(t) or _CHESSCOM_LEGACY.match(t)
    return (m.group(1), m.group(2)) if m else None


def valid_username(name: str) -> bool:
    return bool(_USERNAME.match(name))


def username_from(text: str) -> str:
    """A plain username or a profile URL (`chess.com/member/<u>`, `lichess.org/@/<u>`, FR-10.3)."""
    t = text.strip().rstrip("/")
    for marker in ("chess.com/member/", "chess.com/players/", "lichess.org/@/"):
        i = t.lower().find(marker)
        if i >= 0:
            t = t[i + len(marker) :].split("/")[0].split("?")[0]
            break
    return t


# ---------------------------------------------------------------- Lichess game JSON


def _iso_ms(ms: Any) -> str | None:
    if not isinstance(ms, int | float) or isinstance(ms, bool) or ms <= 0:
        return None
    return datetime.fromtimestamp(ms / 1000, UTC).isoformat(timespec="seconds")


def _player(players: dict[str, Any], color: str) -> dict[str, Any]:
    p = players.get(color)
    return p if isinstance(p, dict) else {}


def _name(p: dict[str, Any]) -> str | None:
    user = p.get("user")
    if isinstance(user, dict) and isinstance(user.get("name"), str):
        return str(user["name"])
    if p.get("aiLevel") is not None:
        return f"Stockfish level {p.get('aiLevel')}"
    return None


def _dict(v: Any) -> dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _int(v: Any) -> int | None:
    return int(v) if isinstance(v, int) and not isinstance(v, bool) else None


def _float(v: Any) -> float | None:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def parse_lichess_game(data: dict[str, Any], base_url: str = "https://lichess.org") -> GameRecord:
    """A game from `/api/games/user` or `/game/export` with `pgnInJson` (FR-11.27). Variants raise
    `Skip`; every field except `id` and `pgn` is optional."""
    gid = data.get("id")
    pgn = data.get("pgn")
    if not isinstance(gid, str) or not isinstance(pgn, str) or not pgn.strip():
        raise Skip("no id or PGN")
    variant = data.get("variant")
    if isinstance(variant, str) and variant not in ("standard", "fromPosition"):
        raise Skip(f"variant {variant}")
    players = _dict(data.get("players"))
    w, b = _player(players, "white"), _player(players, "black")
    clock = _dict(data.get("clock"))
    tc = None
    if _int(clock.get("initial")) is not None:
        tc = f"{clock['initial']}+{_int(clock.get('increment')) or 0}"
    elif data.get("speed") == "correspondence":
        tc = "-"
    winner = data.get("winner")
    status = data.get("status")
    if winner == "white":
        result = "1-0"
    elif winner == "black":
        result = "0-1"
    elif status in ("draw", "stalemate"):
        result = "1/2-1/2"
    else:
        result = _pgn_result(pgn)
    opening = _dict(data.get("opening"))
    speed = data.get("speed")
    tclass = {"ultraBullet": "bullet", "correspondence": "daily"}.get(str(speed), speed)
    extra: dict[str, Any] = {}
    division = data.get("division")
    if isinstance(division, dict):
        extra["division"] = {k: v for k, v in division.items() if k in ("middle", "end") and _int(v)}
    return GameRecord(
        source="lichess",
        source_game_id=gid[:8],
        url=f"{base_url}/{gid[:8]}",
        pgn=pgn,
        played_at=_iso_ms(data.get("createdAt")),
        time_control=tc,
        time_class=tclass if tclass in TIME_CLASSES else time_class(tc),
        rated=data.get("rated") if isinstance(data.get("rated"), bool) else None,
        white=_name(w),
        black=_name(b),
        white_rating=_int(w.get("rating")),
        black_rating=_int(b.get("rating")),
        result=result,
        eco=opening.get("eco") if isinstance(opening.get("eco"), str) else None,
        opening=opening.get("name") if isinstance(opening.get("name"), str) else None,
        accuracy_white=_float(_dict(w.get("analysis")).get("accuracy")),
        accuracy_black=_float(_dict(b.get("analysis")).get("accuracy")),
        lichess_analyzed=isinstance(data.get("analysis"), list) and len(data["analysis"]) > 0,
        extra=extra,
    )


def _pgn_result(pgn: str) -> str:
    m = re.search(r'\[Result "([^"]*)"\]', pgn)
    return m.group(1) if m and m.group(1) in RESULTS else "*"


def record_from_parsed(game: ParsedGame, source: str) -> GameRecord:
    """A pasted or file game: everything comes from its tags (FR-11.2). A Lichess or chess.com `Site`
    tag is kept as the URL, so *Open on …* works, but the game stays a paste/file import."""
    h = game.headers
    site = h.get("Site", "")
    url = site if site.startswith(("https://lichess.org/", "https://www.chess.com/", "https://chess.com/")) else None
    date = h.get("UTCDate") or h.get("Date") or ""
    played_at = None
    m = re.match(r"^(\d{4})\.(\d{2})\.(\d{2})$", date)
    if m:
        t = h.get("UTCTime", "00:00:00")
        played_at = (
            f"{m.group(1)}-{m.group(2)}-{m.group(3)}T{t if re.match(r'^\d{2}:\d{2}:\d{2}$', t) else '00:00:00'}+00:00"
        )
    tc = h.get("TimeControl")
    tc = tc if tc and tc not in ("?", "") else None
    return GameRecord(
        source=source,
        source_game_id=None,
        url=url,
        pgn=game.pgn,
        played_at=played_at,
        time_control=tc,
        time_class=time_class(tc),
        rated=None,
        white=game.white,
        black=game.black,
        white_rating=_int_text(h.get("WhiteElo")),
        black_rating=_int_text(h.get("BlackElo")),
        result=game.result,
        eco=h.get("ECO") if h.get("ECO", "?") != "?" else None,
        opening=h.get("Opening") or None,
    )


def _int_text(v: str | None) -> int | None:
    return int(v) if v and v.isdigit() else None


# ---------------------------------------------------------------- clients (implemented in adapters/)


class LichessGamesClient(Protocol):
    def user_games(
        self, token: str | None, username: str, *, since_ms: int | None, max_games: int
    ) -> Iterator[dict[str, Any]]: ...

    def export_game(self, token: str | None, game_id: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ChesscomProfile:
    username: str
    name: str | None
    url: str | None
    avatar: str | None
    joined: int | None


@dataclass(frozen=True)
class Archive:
    """One monthly archive response: `status` 200 (fresh data) or 304 (unchanged since `etag`)."""

    status: int
    games: list[dict[str, Any]]
    etag: str | None


class ChesscomClient(Protocol):
    def profile(self, username: str) -> ChesscomProfile: ...

    def archives(self, username: str) -> list[str]: ...

    def archive(self, url: str, etag: str | None) -> Archive: ...
