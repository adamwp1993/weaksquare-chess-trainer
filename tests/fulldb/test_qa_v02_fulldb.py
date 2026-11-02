"""QA v0.2 extra checks on the full DB (`uv run pytest -m fulldb -s`).

Written by the independent QA pass (qa/QA-v0.2.md).
- The Done-when ratio test, on real draws: an endless 50/30/20 session over the full DB serves 1,000
  puzzles, each from its own group, with every group's share within ±5 points and no repeats.
- The live ratio count (`count_with_buckets`) matches the raw-text oracle per group and in total.
- Timing of the ratio count over the full rating range (known limit: ~550 ms against the 500 ms
  target). The strict-500 ms check is an xfail that documents the limit.
"""

from __future__ import annotations

import dataclasses
import random
import sqlite3
import time

import pytest

from tests.integration.test_filter_count import oracle_count
from weaksquare.core.filters import FilterSpec, RatioBucket
from weaksquare.services.session import SessionService

pytestmark = pytest.mark.fulldb
LIMIT_S = 0.5

THREE_GROUPS = (RatioBucket(("fork",), 50), RatioBucket(("pin", "skewer"), 30), RatioBucket(("oneMove",), 20))
# Disjoint groups, so every served puzzle belongs to exactly one group.
DISJOINT = (RatioBucket(("middlegame",), 50), RatioBucket(("endgame",), 30), RatioBucket(("opening",), 20))


@pytest.fixture(scope="module")
def raw(fulldb_path) -> sqlite3.Connection:  # type: ignore[no-untyped-def]
    conn = sqlite3.connect(f"file:{fulldb_path.as_posix()}?mode=ro", uri=True)
    yield conn
    conn.close()


class _Attempts:
    def append(self, *a, **k) -> int:  # type: ignore[no-untyped-def]
        return 0

    def session_tally(self, sid: int) -> object:
        return None

    def all_time_tally(self) -> object:
        return None


class _Sessions:
    n = 0

    def create(self, *a: object) -> int:
        self.n += 1
        return self.n


def _themes(raw: sqlite3.Connection, ids: list[str]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for i in range(0, len(ids), 500):
        chunk = ids[i : i + 500]
        q = f"SELECT id, themes FROM puzzles WHERE id IN ({', '.join('?' * len(chunk))})"
        out.update((r[0], set(r[1].split())) for r in raw.execute(q, chunk))
    return out


def test_ratio_50_30_20_over_1000_real_draws(full_source, raw) -> None:  # type: ignore[no-untyped-def]
    """Done-when: ratio sampling within ±5% over 1,000 draws, through SessionService on the full DB."""
    spec = FilterSpec(ratios=DISJOINT, queue_size=None)
    service = SessionService(full_source, _Attempts(), _Sessions(), _clock(), random.Random(11))  # type: ignore[arg-type]
    sid = service.start(spec).session_id
    served: list[str] = []
    for _ in range(1000):
        view = service.next_puzzle(sid)
        assert view is not None
        served.append(view.puzzle_id)
    assert len(set(served)) == 1000
    themes = _themes(raw, served)
    tally = {"middlegame": 0, "endgame": 0, "opening": 0}
    for pid in served:
        (group,) = tally.keys() & themes[pid]
        tally[group] += 1
    for group, weight in (("middlegame", 50), ("endgame", 30), ("opening", 20)):
        assert abs(tally[group] / 10 - weight) <= 5, tally


def _clock():  # type: ignore[no-untyped-def]
    from weaksquare.core.clock import FixedClock

    return FixedClock()


@pytest.mark.parametrize(
    "spec",
    [
        FilterSpec(ratios=THREE_GROUPS),
        FilterSpec(ratios=THREE_GROUPS, min_popularity=None, min_plays=None, exclude_solved_here=False),
        FilterSpec(ratios=THREE_GROUPS, rating_min=1500, rating_max=1900, side="black", exclude_themes=("mate",)),
    ],
    ids=["defaults", "no quality", "narrow"],
)
def test_ratio_count_matches_the_oracle(full_source, raw, spec: FilterSpec) -> None:  # type: ignore[no-untyped-def]
    total, groups = full_source.count_with_buckets(spec)
    plain = dataclasses.replace(spec, ratios=())
    expected_groups = [oracle_count(raw, dataclasses.replace(plain, themes=b.themes, match="any")) for b in spec.ratios]
    union = tuple(t for b in spec.ratios for t in b.themes)
    assert groups == expected_groups
    assert total == oracle_count(raw, dataclasses.replace(plain, themes=union, match="any"))


def _time_ratio_count(full_source) -> float:  # type: ignore[no-untyped-def]
    spec = FilterSpec(ratios=THREE_GROUPS)
    full_source.count_with_buckets(spec)  # warm-up
    times = []
    for _ in range(5):
        started = time.perf_counter()
        full_source.count_with_buckets(spec)
        times.append(time.perf_counter() - started)
    times.sort()
    median = times[2]
    print(f"\n  3-group ratio count, full range, defaults: median {median * 1000:.0f} ms "
          f"(min {times[0] * 1000:.0f}, max {times[-1] * 1000:.0f})")  # fmt: skip
    return median


def test_ratio_count_full_range_within_known_limit(full_source) -> None:  # type: ignore[no-untyped-def]
    """Known limit (ARCHITECTURE §7, v0.2): about 550 ms. Fails if it regresses past 700 ms."""
    assert _time_ratio_count(full_source) < 0.7


@pytest.mark.xfail(reason="Known v0.2 limit (v0.2-B2): 3-group ratio count ~550 ms > 500 ms", strict=False)
def test_ratio_count_full_range_under_500ms(full_source) -> None:  # type: ignore[no-untyped-def]
    assert _time_ratio_count(full_source) < LIMIT_S
