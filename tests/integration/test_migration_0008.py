"""user.db 0008 (v0.10): existing games become yours, the error view, other players' games kept apart."""

from __future__ import annotations

import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from weaksquare.adapters.db.connection import Database
from weaksquare.adapters.db.migrate import migrate
from weaksquare.adapters.db.repos.games import GamesRepo
from weaksquare.config import MIGRATIONS_DIR
from weaksquare.core.clock import FixedClock
from weaksquare.core.games import GameRecord, LibraryFilter

CLOCK = FixedClock(datetime(2026, 11, 4, 12, tzinfo=UTC))


def _rec(gid: str, white: str = "player_a", black: str = "opponent_b") -> GameRecord:
    return GameRecord(
        source="lichess", source_game_id=gid, url=f"https://lichess.org/{gid}", pgn="1. e4 e5 *",
        played_at="2026-10-01T10:00:00Z", time_control="600+0", time_class="rapid", rated=True,
        white=white, black=black, white_rating=1500, black_rating=1500, result="1-0", eco="C20",
        opening="King's Pawn", accuracy_white=None, accuracy_black=None, lichess_analyzed=False, extra={},
    )  # fmt: skip


def test_existing_games_become_yours(tmp_path: Path) -> None:
    old = tmp_path / "v7"
    old.mkdir()
    for f in sorted((MIGRATIONS_DIR / "user").glob("000[1-7]_*.sql")):
        shutil.copy(f, old / f.name)
    db_path = tmp_path / "user.db"
    migrate(db_path, old, CLOCK)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO games (source, pgn, moves_hash, user_color, fetched_at) VALUES ('paste', '1. e4 *', 'h', 'white', 'x')"
    )
    conn.commit()
    conn.close()

    migrate(db_path, MIGRATIONS_DIR / "user", CLOCK)
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT game_id, subject, color FROM game_subjects").fetchall() == [(1, "me", "white")]
    cols = {r[1] for r in conn.execute("PRAGMA table_info(game_analysis)")}
    assert {"themes", "habits"} <= cols
    assert conn.execute("SELECT COUNT(*) FROM game_errors").fetchone() == (0,)
    conn.close()


def _repo(tmp_path: Path) -> GamesRepo:
    migrate(tmp_path / "user.db", MIGRATIONS_DIR / "user", CLOCK)
    return GamesRepo(Database(tmp_path / "user.db", tmp_path / "puzzles.db"))


def test_another_players_games_stay_out_of_my_games(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    mine, _ = repo.add(_rec("aaaa0001"), "h1", "white", "t")
    theirs, _ = repo.add(_rec("aaaa0002", "someone", "other"), "h2", "white", "t", subject="lichess:someone")
    assert [g.id for g in repo.list(LibraryFilter())[0]] == [mine]
    assert [g.id for g in repo.list(LibraryFilter(player="lichess:someone"))[0]] == [theirs]
    assert repo.players() == [("lichess:someone", 1)]


def test_a_shared_game_is_stored_once_with_both_colors(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    gid, created = repo.add(_rec("aaaa0003", "someone", "player_a"), "h3", "white", "t", subject="lichess:someone")
    assert created
    same, created = repo.add(_rec("aaaa0003", "someone", "player_a"), "h3", "black", "t")
    assert same == gid and not created
    assert repo.subjects(gid) == {"lichess:someone": "white", "me": "black"}
    game = repo.get(gid)
    assert game is not None and game.user_color == "black"  # the game is yours now: your color


def test_my_color_is_not_overwritten_by_another_player(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    gid, _ = repo.add(_rec("aaaa0004", "player_a", "someone"), "h4", "white", "t")
    repo.add(_rec("aaaa0004", "player_a", "someone"), "h4", "black", "t", subject="lichess:someone")
    game = repo.get(gid)
    assert game is not None and game.user_color == "white"
    repo.set_user_color(gid, "both")
    assert repo.subjects(gid)["me"] == "both"
