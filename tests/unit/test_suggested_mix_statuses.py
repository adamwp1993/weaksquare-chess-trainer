"""v1.0 (FR-10.29): after a checkpoint, statuses order the Suggested mix's groups (Regressed, then New/Training by
score, then Improving), Fixed weaknesses get only a 10% maintenance share, and the why-lines say so."""

from __future__ import annotations

from weaksquare.core.coach import Report, Weakness
from weaksquare.core.suggested_mix import MAINTENANCE, build_suggestion


def _w(key: str, score: float) -> Weakness:
    kind, _, name = key.partition(":")
    return Weakness(key, kind, name, f"{kind.title()}: {name}", 6, 2.0, 300, score, (name,), None, {})


FORK, PIN, SKEWER, MATE = _w("allowed:fork", 9.0), _w("missed:pin", 6.0), _w("missed:skewer", 3.0), _w("allowed:mateIn2", 1.0)
REPORT = Report("games", 30, None, None, {}, {}, [PIN, SKEWER], [FORK, MATE], [], [], [], {}, 0,
                weaknesses=[FORK, PIN, SKEWER, MATE])  # fmt: skip


def _build(**kw):  # type: ignore[no-untyped-def]
    s = build_suggestion(REPORT, puzzle_rating=1500, recent_accuracy=None, has_game_puzzles=False, **kw)
    assert s is not None
    return s


def test_without_statuses_the_score_decides_as_before() -> None:
    assert _build().weaknesses == ("allowed:fork", "missed:pin", "missed:skewer", "allowed:mateIn2")


def test_regressed_comes_first_then_new_and_training_then_improving() -> None:
    s = _build(statuses={"allowed:fork": "improving", "missed:pin": "training", "missed:skewer": "new",
                         "allowed:mateIn2": "regressed"})  # fmt: skip
    assert s.weaknesses == ("allowed:mateIn2", "missed:pin", "missed:skewer", "allowed:fork")
    assert "top priority again" in s.why[0]


def test_fixed_weaknesses_get_only_the_maintenance_share() -> None:
    s = _build(statuses={"allowed:fork": "fixed", "missed:pin": "training", "missed:skewer": "new",
                         "allowed:mateIn2": "new"},
               maintenance=[("Allowed: Fork", ("fork",))])  # fmt: skip
    assert "allowed:fork" not in s.weaknesses
    buckets = {b.themes: b.weight for b in s.spec.ratios}
    assert buckets[("fork",)] == MAINTENANCE
    assert sum(buckets.values()) == 100
    assert any("maintenance share" in w and "Allowed: Fork" in w for w in s.why)


def test_a_weakness_not_tracked_yet_counts_as_new() -> None:
    s = _build(statuses={"allowed:fork": "improving"})
    assert s.weaknesses[-1] == "allowed:fork"


def test_no_maintenance_group_without_fixed_weaknesses() -> None:
    s = _build(statuses={})
    assert all(b.weight != MAINTENANCE or b.themes == ("long", "veryLong") for b in s.spec.ratios)
    assert not any("maintenance" in w for w in s.why)
