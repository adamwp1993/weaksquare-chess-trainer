"""v0.8 game library service: incremental sync on both platforms, the first-sync window, ETag months,
dedupe that reuses analysis on re-import (FR-11.7), Verify, color detection and one-off imports."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tests.fakes.games import CC_BASE, FakeChesscom, FakeLichessGames
from tests.fakes.lichess import FAKE_TOKEN
from weaksquare.adapters.chesscom import classify_game_error
from weaksquare.adapters.db.connection import Database
from weaksquare.adapters.db.migrate import migrate
from weaksquare.adapters.db.repos.games import AccountSyncRepo, GamesRepo
from weaksquare.adapters.db.repos.user_data import SettingsRepo
from weaksquare.adapters.http import HttpError
from weaksquare.config import MIGRATIONS_DIR, Paths
from weaksquare.core.clock import FixedClock
from weaksquare.core.errors import NotFoundError, ValidationError
from weaksquare.core.games import LibraryFilter
from weaksquare.jobs.runner import JobRunner
from weaksquare.services.games import GameLibraryService

MATE = '[White "player_a"]\n[Black "opponent_b"]\n[Result "1-0"]\n\n1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7# 1-0\n'
SECOND = '[White "opponent_c"]\n[Black "someone_else"]\n[Result "0-1"]\n\n1. f3 e5 2. g4 Qh4# 0-1\n'


@dataclass
class Acct:
    id: str | None = "player_a"
    secret: str | None = FAKE_TOKEN
    expired: bool = False

    def account_id(self) -> str | None:
        return self.id

    def token(self) -> str | None:
        return self.secret

    def mark_expired(self) -> None:
        self.expired = True


@dataclass
class Rig:
    svc: GameLibraryService
    runner: JobRunner
    repo: GamesRepo
    lichess: FakeLichessGames
    chesscom: FakeChesscom
    clock: FixedClock
    acct: Acct
    settings: SettingsRepo


@pytest.fixture
def rig(paths: Paths) -> Rig:
    clock = FixedClock(datetime(2026, 10, 1, 12, 0, tzinfo=UTC))
    migrate(paths.user_db, MIGRATIONS_DIR / "user", clock)
    db = Database(paths.user_db, paths.puzzles_db)
    repo = GamesRepo(db)
    runner = JobRunner()
    lichess, chesscom, acct, settings = FakeLichessGames(), FakeChesscom(), Acct(), SettingsRepo(db)
    svc = GameLibraryService(
        repo, AccountSyncRepo(db), settings, runner, clock, acct, lichess, chesscom, classify_game_error
    )
    return Rig(svc, runner, repo, lichess, chesscom, clock, acct, settings)


def _sync(rig: Rig) -> str:
    job = rig.svc.start_sync()
    assert job is not None
    st = rig.runner.wait(job, 5)
    assert st is not None and st.state == "done", st
    return st.message


def test_first_sync_pulls_both_platforms_metadata_and_pgns_only(rig: Rig) -> None:
    rig.svc.set_chesscom_username("player_a")
    msg = _sync(rig)
    assert msg.startswith("4 new games")  # 2 Lichess (the atomic game skipped) + 2 chess.com (Chess960 skipped)
    rows, total = rig.svc.list_games(LibraryFilter())
    assert total == 4 and all(r.analysis_status == "none" for r in rows)  # no analysis on sync (FR-11.27)
    by_id = {r.source_game_id: r for r in rows}
    assert by_id["GAMEID11"].user_color == "white" and by_id["GAMEID12"].user_color == "black"
    assert by_id["100000001"].user_color == "black" and by_id["100000001"].accuracy_black == 88.0
    assert by_id["GAMEID11"].lichess_analyzed and by_id["GAMEID11"].extra["division"] == {"middle": 8}
    # The first Lichess request starts 90 days back and asks for at most 200 games
    first = rig.lichess.calls[0]
    assert first["max"] == 200 and first["since_ms"] == int(datetime(2026, 7, 3, 12, tzinfo=UTC).timestamp() * 1000)


def test_sync_is_incremental_and_a_second_run_adds_nothing(rig: Rig) -> None:
    rig.svc.set_chesscom_username("player_a")
    _sync(rig)
    assert _sync(rig).startswith("0 new games")
    second = rig.lichess.calls[-1]
    assert second["since_ms"] == 1790000000001  # after the newest game seen
    # chess.com: months on or after the last synced one, each with its ETag: unchanged → 304, no games read
    month_calls = [c for c in rig.chesscom.calls if c[0].startswith(CC_BASE)]
    later = month_calls[-1]
    assert later[0] == CC_BASE + "2026/09" and later[1] is not None
    assert (CC_BASE + "2026/08", None) not in month_calls[2:]  # an older month isn't fetched again


def test_a_new_game_in_the_current_month_arrives_on_the_next_sync(rig: Rig) -> None:
    rig.svc.set_chesscom_username("player_a")
    _sync(rig)
    extra = copy.deepcopy(rig.chesscom.months[CC_BASE + "2026/09"][0])
    extra["url"] = "https://www.chess.com/game/live/100000009"
    extra["pgn"] = extra["pgn"].replace("100000001", "100000009").replace("1. e4 e5", "1. d4 d5", 1)
    extra["pgn"] = '[White "opponent_e"]\n[Black "player_a"]\n[Result "*"]\n\n1. d4 d5 *\n'
    rig.chesscom.months[CC_BASE + "2026/09"].append(extra)
    assert _sync(rig).startswith("1 new game")


def test_first_sync_respects_the_game_count_limit(rig: Rig) -> None:
    rig.svc.set_settings(first_sync_max=1)
    rig.svc.set_chesscom_username("player_a")
    _sync(rig)
    _, total = rig.svc.list_games(LibraryFilter(platforms=("chesscom",)))
    assert total == 1
    assert rig.lichess.calls[0]["max"] == 1


def test_first_sync_window_skips_older_chesscom_games(rig: Rig) -> None:
    rig.svc.set_settings(first_sync_days=7)  # the fixture's games are from mid-September
    rig.svc.set_chesscom_username("player_a")
    _sync(rig)
    rows, _ = rig.svc.list_games(LibraryFilter(platforms=("chesscom",)))
    assert [r.source_game_id for r in rows] == ["100000002"]  # the dated game is older; the undated one is kept


def test_no_linked_account_means_no_sync(rig: Rig) -> None:
    rig.acct.id = None
    assert rig.svc.start_sync() is None


def test_lichess_offline_still_syncs_chesscom_and_says_so(rig: Rig) -> None:
    rig.svc.set_chesscom_username("player_a")
    rig.lichess.error = HttpError("network", status=None, retryable=True)
    msg = _sync(rig)
    assert "2 new games" in msg and "Couldn't reach Lichess" in msg


def test_an_expired_lichess_token_is_reported(rig: Rig) -> None:
    from weaksquare.adapters.http import Unauthorized

    rig.lichess.error = Unauthorized("401", status=401, retryable=False)
    job = rig.svc.start_sync()
    assert job is not None
    st = rig.runner.wait(job, 5)
    assert st is not None and st.state == "failed" and rig.acct.expired


def test_reimport_reuses_the_stored_game_and_its_analysis(rig: Rig) -> None:
    out = rig.svc.import_pgn(MATE)
    assert out.game_id and out.created and out.needs_color is False  # player_a is your Lichess account
    rig.repo.set_analysis(out.game_id, "analyzed", 0.3, "Stockfish 19")
    again = rig.svc.import_pgn('[Event "Other tags, same moves"]\n' + MATE)
    assert again.game_id == out.game_id and not again.created and again.analyzed  # FR-11.7


def test_a_synced_game_reimported_by_url_or_paste_is_the_same_game(rig: Rig) -> None:
    _sync(rig)
    rows, _ = rig.svc.list_games(LibraryFilter(platforms=("lichess",)))
    synced = next(r for r in rows if r.source_game_id == "GAMEID11")
    rig.repo.set_analysis(synced.id, "analyzed", 0.3, "Stockfish 19")
    job = rig.svc.start_url_import("https://lichess.org/GAMEID11/white")
    st = rig.runner.wait(job, 5)
    assert st is not None and st.state == "done"
    res = rig.svc.url_result(job)
    assert res is not None and res.game_id == synced.id and res.analyzed
    pasted = rig.svc.import_pgn(synced.pgn)
    assert pasted.game_id == synced.id


def test_an_unknown_color_asks_and_can_be_set(rig: Rig) -> None:
    out = rig.svc.import_pgn(SECOND)
    assert out.needs_color and out.game_id
    rig.svc.set_user_color(out.game_id, "both")
    assert rig.svc.get(out.game_id).user_color == "both"
    with pytest.raises(ValidationError):
        rig.svc.set_user_color(out.game_id, "purple")


def test_a_multi_game_file_lists_its_games_with_reasons_and_picks_one(rig: Rig, tmp_path: Path) -> None:
    bad = '[White "x"]\n[Black "y"]\n\n1. e4 e5 2. Ke3 *\n'
    f = tmp_path / "games.pgn"
    f.write_text(MATE + "\n" + bad + "\n" + SECOND, encoding="utf-8")
    out = rig.svc.import_file(f)
    assert out.game_id is None and out.token and len(out.choices) == 3
    assert out.choices[1].error and "illegal" in out.choices[1].error
    with pytest.raises(ValidationError):
        rig.svc.pick(out.token, 1)
    picked = rig.svc.pick(out.token, 2)
    assert picked.game_id and rig.svc.get(picked.game_id).source == "file"


@pytest.mark.parametrize(
    "text, words",
    [("", "Paste a PGN"), ("hello", "No game found"), ('[Variant "Atomic"]\n\n1. e4 *', "only standard chess")],
)
def test_bad_pastes_give_clear_errors(rig: Rig, text: str, words: str) -> None:
    with pytest.raises(ValidationError, match=words):
        rig.svc.import_pgn(text)


def test_chesscom_url_import_searches_the_archives_one_request_at_a_time(rig: Rig) -> None:
    rig.chesscom.delay_s = 0.01
    with pytest.raises(ValidationError) as e:
        rig.svc.start_url_import("https://www.chess.com/game/live/100000002")
    assert e.value.code == "chesscom_username_needed"
    job = rig.svc.start_url_import("https://www.chess.com/game/live/100000002", chesscom_username="player_a")
    st = rig.runner.wait(job, 5)
    assert st is not None and st.state == "done", st
    res = rig.svc.url_result(job)
    assert res is not None and res.game_id and rig.svc.get(res.game_id).source_game_id == "100000002"


def test_a_chesscom_game_that_isnt_found_asks_for_the_pgn(rig: Rig) -> None:
    rig.svc.set_chesscom_username("player_a")
    job = rig.svc.start_url_import("https://www.chess.com/game/live/100000077")
    st = rig.runner.wait(job, 5)
    assert st is not None and st.state == "failed" and "Paste its PGN" in st.message


def test_verify_shows_the_profile_or_says_no_such_player(rig: Rig) -> None:
    assert rig.svc.verify_chesscom("https://www.chess.com/member/player_a")["username"] == "player_a"
    with pytest.raises(NotFoundError, match=r"no chess.com player called nobody_here"):
        rig.svc.verify_chesscom("nobody_here")
    with pytest.raises(ValidationError):
        rig.svc.verify_chesscom("not a name!")


def test_changing_the_chesscom_username_forgets_the_old_sync_position(rig: Rig) -> None:
    rig.svc.set_chesscom_username("player_a")
    _sync(rig)
    rig.svc.set_chesscom_username("player_b")
    assert AccountSyncRepo(rig.repo._db).get("chesscom") is None  # type: ignore[attr-defined]


def test_library_filters(rig: Rig) -> None:
    rig.svc.set_chesscom_username("player_a")
    _sync(rig)
    _, total = rig.svc.list_games(LibraryFilter(results=("win",)))
    assert total == 2  # the two chess.com games player_a won
    _, total = rig.svc.list_games(LibraryFilter(time_classes=("rapid",), colors=("white",)))
    assert total == 1
    _, total = rig.svc.list_games(LibraryFilter(opponent="opponent_e"))
    assert total == 1
    _, total = rig.svc.list_games(LibraryFilter(opening="italian"))
    assert total == 2
    _, total = rig.svc.list_games(LibraryFilter(rated=False))
    assert total == 1
    _, total = rig.svc.list_games(LibraryFilter(date_from="2026-09-20", date_to="2026-09-20"))
    assert total == 1
    _, total = rig.svc.list_games(LibraryFilter(statuses=("analyzed",)))
    assert total == 0
    rows, total = rig.svc.list_games(LibraryFilter(limit=2))
    assert total == 4 and len(rows) == 2 and rows[0].played_at >= rows[1].played_at  # type: ignore[operator]
