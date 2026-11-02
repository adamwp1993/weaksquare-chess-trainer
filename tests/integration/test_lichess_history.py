"""FR-6.17 history import and the FR-3.9 "exclude played on Lichess" filter."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

import pytest

from tests.fakes.lichess import FAKE_TOKEN, FakeLichess
from weaksquare.adapters.db.repos.lichess import LichessHistoryRepo
from weaksquare.adapters.db.repos.puzzles import LichessDbSource
from weaksquare.adapters.db.repos.user_data import SettingsRepo
from weaksquare.adapters.lichess import is_network_error, is_unauthorized
from weaksquare.core.filters import FilterSpec, upgrade_saved
from weaksquare.core.lichess import ActivityEntry
from weaksquare.jobs.runner import JobRunner
from weaksquare.services.lichess_history import ACCOUNT_KEY, SINCE_KEY, HistoryService


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


def _svc(services, lichess: FakeLichess, acct: Acct | None = None) -> tuple[HistoryService, JobRunner]:  # type: ignore[no-untyped-def]
    runner = JobRunner()
    svc = HistoryService(
        acct or Acct(), lichess, LichessHistoryRepo(services.db), SettingsRepo(services.db), runner,
        is_network_error, is_unauthorized,
    )  # fmt: skip
    return svc, runner


def _ids(services, n: int) -> list[str]:  # type: ignore[no-untyped-def]
    with services.db.session() as c:
        return [r[0] for r in c.execute("SELECT id FROM pz.puzzles ORDER BY n LIMIT ?", (n,))]


def test_import_is_incremental(services) -> None:  # type: ignore[no-untyped-def]
    ids = _ids(services, 3)
    lichess = FakeLichess(activity_entries=[ActivityEntry(ids[1], 2000, True), ActivityEntry(ids[0], 1000, False)])
    svc, runner = _svc(services, lichess)
    st = runner.wait(svc.start_import(), 5)
    assert st.state == "done" and "2" in st.message
    assert svc.count() == 2
    settings = SettingsRepo(services.db)
    assert settings.get(SINCE_KEY) == 2001 and settings.get(ACCOUNT_KEY) == "player_a"
    lichess.activity_entries.insert(0, ActivityEntry(ids[2], 3000, True))
    runner.wait(svc.start_import(), 5)
    assert lichess.activity_since == [None, 2001]  # only what's new
    assert svc.count() == 3


def test_a_broken_stream_keeps_the_old_since(services) -> None:  # type: ignore[no-untyped-def]
    ids = _ids(services, 2)
    lichess = FakeLichess(activity_entries=[ActivityEntry(ids[1], 2000, True), ActivityEntry(ids[0], 1000, True)],
                          activity_error_after=1)  # fmt: skip
    svc, runner = _svc(services, lichess)
    st = runner.wait(svc.start_import(), 5)
    assert (st.state, st.error_code) == ("failed", "offline")
    assert SettingsRepo(services.db).get(SINCE_KEY) is None


def test_another_account_clears_the_history(services) -> None:  # type: ignore[no-untyped-def]
    ids = _ids(services, 2)
    svc, runner = _svc(services, FakeLichess(activity_entries=[ActivityEntry(ids[0], 1000, True)]))
    runner.wait(svc.start_import(), 5)
    acct_b = Acct(id="player_b")
    svc_b, runner_b = _svc(services, FakeLichess(activity_entries=[ActivityEntry(ids[1], 5, True)]), acct_b)
    runner_b.wait(svc_b.start_import(), 5)
    with services.db.session() as c:
        assert [r[0] for r in c.execute("SELECT puzzle_id FROM lichess_history")] == [ids[1]]


def test_expired_token(services) -> None:  # type: ignore[no-untyped-def]
    acct = Acct(secret="lip_FAKEwrong")
    svc, runner = _svc(services, FakeLichess(), acct)
    st = runner.wait(svc.start_import(), 5)
    assert st.error_code == "expired" and acct.expired


def test_signed_out_does_nothing(services) -> None:  # type: ignore[no-untyped-def]
    svc, _ = _svc(services, FakeLichess(), Acct(id=None))
    assert svc.start_import() is None


# ---- the filter -------------------------------------------------------------------------------
BASE = FilterSpec(min_popularity=None, min_plays=None, exclude_solved_here=False, exclude_played_on_lichess=False)


@pytest.mark.parametrize("ratios", [False, True])
def test_exclude_played_on_lichess_count_and_sampling(services, rng, ratios: bool) -> None:  # type: ignore[no-untyped-def]
    src = LichessDbSource(services.db)
    spec = BASE
    if ratios:
        from weaksquare.core.filters import RatioBucket

        spec = dataclasses.replace(BASE, ratios=(RatioBucket(("fork",), 50), RatioBucket(("mate",), 50)))
    total = src.count(spec)
    with services.db.session() as c:
        rows = c.execute(
            f"SELECT p.id, p.n FROM pz.puzzles p WHERE {src.where(spec).sql} LIMIT 5", src.where(spec).params
        ).fetchall()
    played = {r[0]: r[1] for r in rows}
    LichessHistoryRepo(services.db).add([(pid, None, True) for pid in played])
    on = dataclasses.replace(spec, exclude_played_on_lichess=True)
    assert src.count(on) == total - len(played)
    assert src.count(spec) == total  # off: nothing hidden
    keys = src.sample_keys(on, 1000, rng, set(), src.count(on))
    assert not set(keys) & set(played.values())
    # Only my misses overrides it (a miss is a replay you've usually synced).
    assert dataclasses.replace(on, only_my_misses=True).excludes_played is False


def test_both_history_filters_together_count_each_puzzle_once(services) -> None:  # type: ignore[no-untyped-def]
    src = LichessDbSource(services.db)
    ids = _ids(services, 3)
    from weaksquare.adapters.db.repos.user_data import AttemptsRepo
    from weaksquare.core.modes.base import AttemptResult
    from weaksquare.core.puzzle import PuzzleRef

    with services.db.session() as c:
        c.execute("INSERT INTO sessions (started_at, mode, filters_json) VALUES ('t','standard','{}')")
    win = AttemptResult(win=True, first_move_correct=True, line_correct=True, help_used="none", time_ms=1)
    AttemptsRepo(services.db).append(PuzzleRef("lichess", ids[0]), 1, "standard", "t", "t", win)
    LichessHistoryRepo(services.db).add([(ids[0], None, True), (ids[1], None, True)])  # ids[0] in both
    total = src.count(BASE)
    both = dataclasses.replace(BASE, exclude_solved_here=True, exclude_played_on_lichess=True)
    assert src.count(both) == total - 2


def test_defaults_and_saved_filters_upgrade() -> None:
    assert FilterSpec().exclude_played_on_lichess is True  # Adam, v0.3 planning
    FilterSpec.from_json({"exclude_played_on_lichess": True})  # no longer "unsupported in this version"
    v2 = FilterSpec().to_json() | {"exclude_played_on_lichess": False}
    assert upgrade_saved(v2, 2)["exclude_played_on_lichess"] is True
    assert upgrade_saved(v2, 3)["exclude_played_on_lichess"] is False  # after that, your choice is kept
