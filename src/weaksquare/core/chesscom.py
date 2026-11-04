"""chess.com Published-Data API shapes (v0.8, FR-11.28). Pure: the HTTP client is `adapters/chesscom.py`.

Monthly archive games document `white`/`black` (`username`, `rating`, `result`), `url`, `pgn`, `fen`,
`end_time`, `time_control`, `rules`, `eco` and, only when chess.com already computed them,
`accuracies`. Every field is read defensively: only `url` and `pgn` are needed to import a game; the
rest becomes None when missing or malformed (CLAUDE.md: treat every non-core field as optional).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from weaksquare.core.games import RESULTS, TIME_CLASSES, GameRecord, Skip, time_class

API_BASE = "https://api.chess.com/pub"
_GAME_URL = re.compile(r"chess\.com/game/(live|daily)/(\d{1,15})")
_ARCHIVE_URL = re.compile(r"/games/(\d{4})/(\d{2})/?$")
_DRAWS = {"agreed", "repetition", "stalemate", "insufficient", "50move", "timevsinsufficient"}


def _side(data: dict[str, Any], color: str) -> dict[str, Any]:
    p = data.get(color)
    return p if isinstance(p, dict) else {}


def _dict(v: Any) -> dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _int(v: Any) -> int | None:
    return int(v) if isinstance(v, int) and not isinstance(v, bool) else None


def _float(v: Any) -> float | None:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def _str(v: Any) -> str | None:
    return v if isinstance(v, str) and v else None


def _pgn_tag(pgn: str, tag: str) -> str | None:
    m = re.search(rf'\[{tag} "([^"]*)"\]', pgn)
    return m.group(1) if m and m.group(1) not in ("", "?") else None


def _opening_from_url(url: str | None) -> str | None:
    """`https://www.chess.com/openings/Italian-Game-Two-Knights` → `Italian Game Two Knights`."""
    if not url or "/openings/" not in url:
        return None
    slug = url.rsplit("/openings/", 1)[1].split("?")[0].strip("/")
    return slug.replace("-", " ") or None


def game_id_from_url(url: str | None) -> str | None:
    m = _GAME_URL.search(url or "")
    return m.group(2) if m else None


def _result(white: dict[str, Any], black: dict[str, Any], pgn: str) -> str:
    wr, br = white.get("result"), black.get("result")
    if wr == "win":
        return "1-0"
    if br == "win":
        return "0-1"
    if wr in _DRAWS or br in _DRAWS:
        return "1/2-1/2"
    tag = _pgn_tag(pgn, "Result")
    return tag if tag in RESULTS else "*"


def parse_archive_game(data: dict[str, Any]) -> GameRecord:
    """One game from a monthly archive. Raises `Skip` for variants (`rules` other than `chess`,
    FR-11.28) and for entries without a URL or PGN."""
    url, pgn = _str(data.get("url")), _str(data.get("pgn"))
    if not url or not pgn:
        raise Skip("no url or PGN")
    rules = data.get("rules")
    if rules is not None and rules != "chess":
        raise Skip(f"variant {rules}")
    gid = game_id_from_url(url)
    if gid is None:
        raise Skip("not a game URL")
    white, black = _side(data, "white"), _side(data, "black")
    tc = _str(data.get("time_control")) or _pgn_tag(pgn, "TimeControl")
    tclass = _str(data.get("time_class"))
    if tclass not in TIME_CLASSES:
        tclass = time_class(tc)  # derived when missing (FR-11.28)
    end = _int(data.get("end_time"))
    acc = _dict(data.get("accuracies"))
    eco_url = _str(data.get("eco")) or _pgn_tag(pgn, "ECOUrl")
    return GameRecord(
        source="chesscom",
        source_game_id=gid,
        url=url,
        pgn=pgn,
        played_at=datetime.fromtimestamp(end, UTC).isoformat(timespec="seconds") if end and end > 0 else None,
        time_control=tc,
        time_class=tclass,
        rated=data.get("rated") if isinstance(data.get("rated"), bool) else None,
        white=_str(white.get("username")) or _pgn_tag(pgn, "White"),
        black=_str(black.get("username")) or _pgn_tag(pgn, "Black"),
        white_rating=_int(white.get("rating")),
        black_rating=_int(black.get("rating")),
        result=_result(white, black, pgn),
        eco=_pgn_tag(pgn, "ECO"),
        opening=_opening_from_url(eco_url),
        accuracy_white=_float(acc.get("white")),
        accuracy_black=_float(acc.get("black")),
    )


def archive_month(url: str) -> str | None:
    """`…/games/2026/10` → `2026/10`."""
    m = _ARCHIVE_URL.search(url)
    return f"{m.group(1)}/{m.group(2)}" if m else None


def months_to_fetch(archives: list[str], last_archive: str | None, since_month: str | None) -> list[str]:
    """Archive URLs to fetch, newest first (FR-11.27): months newer than or equal to the last synced one,
    or, on the first sync, months on or after `since_month` (YYYY/MM). Unknown URLs are ignored."""
    floor = last_archive or since_month
    keep = [(m, u) for u in archives if (m := archive_month(u)) is not None and (floor is None or m >= floor)]
    return [u for _, u in sorted(keep, reverse=True)]
