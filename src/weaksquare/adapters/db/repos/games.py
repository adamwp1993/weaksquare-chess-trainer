"""user.db repositories for the game library (v0.8, §11.5): `games` and `account_sync`."""

from __future__ import annotations

import builtins
import json
import sqlite3
from typing import Any

from weaksquare.adapters.db.connection import Database
from weaksquare.core.games import GameRecord, GameRow, LibraryFilter, SyncState

_COLS = (
    "id, source, source_game_id, url, pgn, moves_hash, played_at, time_control, time_class, rated, white, black,"
    " white_rating, black_rating, user_color, result, eco, opening, platform_accuracy_white,"
    " platform_accuracy_black, lichess_analyzed, analysis_status, analysis_think_s, analysis_engine, extra_json"
)


def _row(r: sqlite3.Row | tuple[Any, ...]) -> GameRow:
    return GameRow(
        id=r[0], source=r[1], source_game_id=r[2], url=r[3], pgn=r[4], moves_hash=r[5], played_at=r[6],
        time_control=r[7], time_class=r[8], rated=None if r[9] is None else bool(r[9]), white=r[10], black=r[11],
        white_rating=r[12], black_rating=r[13], user_color=r[14], result=r[15] or "*", eco=r[16], opening=r[17],
        accuracy_white=r[18], accuracy_black=r[19], lichess_analyzed=bool(r[20]), analysis_status=r[21],
        analysis_think_s=r[22], analysis_engine=r[23], extra=json.loads(r[24]) if r[24] else {},
    )  # fmt: skip


_OPP = "CASE user_color WHEN 'white' THEN black WHEN 'black' THEN white ELSE NULL END"
_RES = (
    "CASE WHEN result = '1/2-1/2' THEN 'draw' WHEN user_color NOT IN ('white','black') OR user_color IS NULL"
    " OR result NOT IN ('1-0','0-1') THEN NULL WHEN (result = '1-0') = (user_color = 'white') THEN 'win'"
    " ELSE 'loss' END"
)


def _where(f: LibraryFilter) -> tuple[str, list[Any]]:
    parts: list[str] = []
    params: list[Any] = []

    def any_of(col: str, values: tuple[str, ...]) -> None:
        if values:
            parts.append(f"{col} IN ({','.join('?' * len(values))})")
            params.extend(values)

    any_of("source", f.platforms)
    any_of("time_class", f.time_classes)
    any_of(f"({_RES})", f.results)
    any_of("user_color", f.colors)
    any_of("analysis_status", f.statuses)
    parts.append("EXISTS (SELECT 1 FROM game_subjects s WHERE s.game_id = games.id AND s.subject = ?)")
    params.append(f.player)
    if f.rated is not None:
        parts.append("rated = ?")
        params.append(int(f.rated))
    if f.opponent.strip():
        parts.append(f"LOWER(COALESCE({_OPP}, white || ' ' || black, '')) LIKE ? ESCAPE '\\'")
        params.append("%" + _like(f.opponent.strip().lower()) + "%")
    if f.opening.strip():
        parts.append("(LOWER(COALESCE(opening, '')) LIKE ? ESCAPE '\\' OR LOWER(COALESCE(eco, '')) = ?)")
        params.extend(["%" + _like(f.opening.strip().lower()) + "%", f.opening.strip().lower()])
    if f.date_from:
        parts.append("played_at >= ?")
        params.append(f.date_from)
    if f.date_to:
        parts.append("played_at < date(?, '+1 day')")
        params.append(f.date_to)
    return (" WHERE " + " AND ".join(parts)) if parts else "", params


ME = "me"


def _has_subject(conn: sqlite3.Connection, game_id: int, subject: str) -> bool:
    found = conn.execute("SELECT 1 FROM game_subjects WHERE game_id = ? AND subject = ?", (game_id, subject))
    return found.fetchone() is not None


def _add_subject(conn: sqlite3.Connection, game_id: int, subject: str, color: str | None) -> None:
    conn.execute(
        "INSERT INTO game_subjects (game_id, subject, color) VALUES (?,?,?)"
        " ON CONFLICT(game_id, subject) DO UPDATE SET color = COALESCE(game_subjects.color, excluded.color)",
        (game_id, subject, color),
    )


def _like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class GamesRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add(
        self, rec: GameRecord, moves_hash: str, user_color: str | None, fetched_at: str, subject: str = ME
    ) -> tuple[int, bool]:
        """(id, created). `subject` is whose game this is (v0.10, FR-10.3): 'me', or another player's
        subject, and `user_color` is then that player's color. A game that becomes yours takes your color. An existing game is reused with its analysis (FR-11.7), and missing details (URL,
        platform id, color) are filled in from the new copy. A platform game matches its own platform id,
        or a paste/file copy with the same moves. A paste or file matches any game with the same moves.
        Two platform games with different ids are different games, even with identical moves (a short
        trap can be played many times)."""
        with self._db.transaction() as conn:
            if rec.source_game_id:
                existing = conn.execute(
                    "SELECT id FROM games WHERE source = ? AND source_game_id = ?", (rec.source, rec.source_game_id)
                ).fetchone()
                if existing is None:
                    existing = conn.execute(
                        "SELECT id FROM games WHERE moves_hash = ? AND source_game_id IS NULL ORDER BY id LIMIT 1",
                        (moves_hash,),
                    ).fetchone()
            else:
                existing = conn.execute(
                    "SELECT id FROM games WHERE moves_hash = ? ORDER BY source_game_id IS NULL, id LIMIT 1",
                    (moves_hash,),
                ).fetchone()
            if existing is not None:
                gid = int(existing[0])
                if subject == ME and not _has_subject(conn, gid, ME) and user_color is not None:
                    conn.execute("UPDATE games SET user_color = ? WHERE id = ?", (user_color, gid))
                _add_subject(conn, gid, subject, user_color)
                conn.execute(
                    "UPDATE games SET url = COALESCE(url, ?), user_color = COALESCE(user_color, ?),"
                    " platform_accuracy_white = COALESCE(platform_accuracy_white, ?),"
                    " platform_accuracy_black = COALESCE(platform_accuracy_black, ?),"
                    " lichess_analyzed = MAX(lichess_analyzed, ?) WHERE id = ?",
                    (rec.url, user_color, rec.accuracy_white, rec.accuracy_black, int(rec.lichess_analyzed), gid),
                )
                if rec.source_game_id and rec.source in ("lichess", "chesscom"):
                    conn.execute(
                        "UPDATE games SET source = ?, source_game_id = ? WHERE id = ? AND source_game_id IS NULL"
                        " AND NOT EXISTS (SELECT 1 FROM games WHERE source = ? AND source_game_id = ?)",
                        (rec.source, rec.source_game_id, gid, rec.source, rec.source_game_id),
                    )
                return gid, False
            cur = conn.execute(
                "INSERT INTO games (source, source_game_id, url, pgn, moves_hash, played_at, time_control, time_class,"
                " rated, white, black, white_rating, black_rating, user_color, result, eco, opening,"
                " platform_accuracy_white, platform_accuracy_black, lichess_analyzed, extra_json, fetched_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    rec.source, rec.source_game_id, rec.url, rec.pgn, moves_hash, rec.played_at, rec.time_control,
                    rec.time_class, None if rec.rated is None else int(rec.rated), rec.white, rec.black,
                    rec.white_rating, rec.black_rating, user_color, rec.result, rec.eco, rec.opening,
                    rec.accuracy_white, rec.accuracy_black, int(rec.lichess_analyzed),
                    json.dumps(rec.extra) if rec.extra else None, fetched_at,
                ),
            )  # fmt: skip
            gid = int(cur.lastrowid or 0)
            _add_subject(conn, gid, subject, user_color)
            return gid, True

    def get(self, game_id: int) -> GameRow | None:
        with self._db.session() as conn:
            r = conn.execute(f"SELECT {_COLS} FROM games WHERE id = ?", (game_id,)).fetchone()
        return _row(r) if r else None

    def list(self, f: LibraryFilter) -> tuple[list[GameRow], int]:
        where, params = _where(f)
        with self._db.session() as conn:
            total = int(conn.execute(f"SELECT COUNT(*) FROM games{where}", params).fetchone()[0])
            rows = conn.execute(
                f"SELECT {_COLS} FROM games{where} ORDER BY played_at IS NULL, played_at DESC, id DESC LIMIT ? OFFSET ?",
                [*params, max(1, min(f.limit, 500)), max(0, f.offset)],
            ).fetchall()
        return [_row(r) for r in rows], total

    def set_user_color(self, game_id: int, color: str) -> None:
        with self._db.transaction() as conn:
            conn.execute("UPDATE games SET user_color = ? WHERE id = ?", (color, game_id))
            conn.execute("UPDATE game_subjects SET color = ? WHERE game_id = ? AND subject = 'me'", (color, game_id))

    def subjects(self, game_id: int) -> dict[str, str | None]:
        """Whose games this game counts for, with their color (v0.10)."""
        with self._db.session() as conn:
            rows = conn.execute("SELECT subject, color FROM game_subjects WHERE game_id = ?", (game_id,)).fetchall()
        return {str(r[0]): r[1] for r in rows}

    def players(self) -> builtins.list[tuple[str, int]]:
        """The other players you ran the Coach on, with their game counts (the Player filter)."""
        with self._db.session() as conn:
            rows = conn.execute(
                "SELECT subject, COUNT(*) FROM game_subjects WHERE subject <> 'me' GROUP BY subject ORDER BY subject"
            ).fetchall()
        return [(str(r[0]), int(r[1])) for r in rows]

    def set_analysis(self, game_id: int, status: str, think_s: float | None, engine: str | None) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE games SET analysis_status = ?, analysis_think_s = ?, analysis_engine = ? WHERE id = ?",
                (status, think_s, engine, game_id),
            )

    def mark_ai_reviewed(self, game_id: int) -> None:
        """FR-11.25 (v0.9): Explain my game ran on the current analysis. Re-analysis sets it back to analyzed."""
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE games SET analysis_status = 'ai_reviewed' WHERE id = ? AND analysis_status = 'analyzed'",
                (game_id,),
            )

    def count(self) -> int:
        with self._db.session() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM games").fetchone()[0])


class AccountSyncRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, platform: str) -> SyncState | None:
        with self._db.session() as conn:
            r = conn.execute(
                "SELECT platform, username, last_sync_at, last_archive, etag_json FROM account_sync WHERE platform = ?",
                (platform,),
            ).fetchone()
        if r is None:
            return None
        return SyncState(r[0], r[1], r[2], r[3], json.loads(r[4]) if r[4] else {})

    def put(self, s: SyncState) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO account_sync (platform, username, last_sync_at, last_archive, etag_json) VALUES (?,?,?,?,?)"
                " ON CONFLICT(platform) DO UPDATE SET username = excluded.username, last_sync_at = excluded.last_sync_at,"
                " last_archive = excluded.last_archive, etag_json = excluded.etag_json",
                (s.platform, s.username, s.last_sync_at, s.last_archive, json.dumps(s.etags) if s.etags else None),
            )

    def clear(self, platform: str) -> None:
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM account_sync WHERE platform = ?", (platform,))
