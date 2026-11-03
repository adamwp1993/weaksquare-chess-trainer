"""v0.6 Stats (FR-9.3, 9.7, FR-5.10): misclicks left out, Danger spotting only by mode, mode details and the
reason breakdown."""

from __future__ import annotations

from datetime import UTC, date, datetime

from weaksquare.core.stats import AttemptRow, build_report, reason_report


def row(win: bool, **kw: object) -> AttemptRow:
    base: dict[str, object] = {
        "win": win,
        "first_move_correct": win,
        "line_correct": win,
        "puzzle_rating": 1500,
        "themes": ("fork",),
        "length": 2,
    }
    base.update(kw)
    return AttemptRow(**base)  # type: ignore[arg-type]


def at(d: str) -> datetime:
    return datetime.fromisoformat(d).replace(tzinfo=UTC)


def test_misclicks_are_left_out_and_counted_apart() -> None:
    rows = [row(True), row(False), row(False, reason="misclick"), row(False, reason="rushed")]
    r = build_report(rows, str)
    assert (r.overall.attempts, r.overall.solved) == (3, 1)
    assert r.by_theme[0].attempts == 3 and r.by_mode[0].attempts == 3
    assert r.misclicks == 1
    # A win can't be a misclick, whatever was stored.
    assert build_report([row(True, reason="misclick")], str).misclicks == 0


def test_misclick_warning() -> None:
    tagged = [row(False, reason="didntLook")] * 6 + [row(False, reason="misclick")] * 2
    assert build_report(tagged, str).misclick_warning
    assert not build_report(tagged[:7], str).misclick_warning  # 1 of 7 tagged: too few


def test_danger_spotting_counts_only_by_mode_and_in_the_details() -> None:
    rows = [
        row(True),
        row(True, mode="danger_spotting", danger_safe=True),
        row(False, mode="danger_spotting", danger_safe=True),
        row(True, mode="danger_spotting", danger_safe=False),
    ]
    r = build_report(rows, str)
    assert r.overall.attempts == 1 and r.by_theme[0].attempts == 1 and r.by_length[0].attempts == 1
    danger = next(t for t in r.by_mode if t.key == "danger_spotting")
    assert (danger.attempts, danger.solved, danger.label) == (3, 2, "Danger spotting")
    d = r.details
    assert (d.danger_safe, d.danger_safe_right, d.danger_blunder, d.danger_blunder_right) == (2, 1, 1, 1)


def test_commit_and_name_the_idea_details() -> None:
    rows = [
        row(False, mode="commit_line", replies_correct=1, replies_total=2),
        row(True, mode="commit_line", replies_correct=2, replies_total=2),
        row(True, mode="commit_line", replies_correct=0, replies_total=0),  # no replies: not counted
        row(True, mode="name_idea", idea_found=1, idea_total=2, idea_extra=1),
        row(True, mode="name_idea", idea_found=None, idea_total=0, idea_extra=None),  # no motifs
    ]
    d = build_report(rows, str).details
    assert (d.replies_correct, d.replies_total) == (3, 4)
    assert (d.ideas_found, d.ideas_total, d.tags_named) == (1, 2, 2)
    names = [t.label for t in build_report(rows, str).by_mode]
    assert names == ["Commit the line", "Name the idea first"]


def test_reason_breakdown_filters_and_shares() -> None:
    rows = [
        row(False, reason="didntLook", themes=("fork",)),
        row(False, reason="didntLook", themes=("pin",), mode="commit_line"),
        row(False, reason="rushed", themes=("fork",)),
        row(False, reason="misclick"),
        row(False),  # untagged
        row(True, reason="rushed"),  # wins never count
    ]
    r = reason_report(rows, lambda t: t.date())
    counts = {c.key: c.count for c in r.reasons}
    assert counts == {"didntLook": 2, "missedResource": 0, "miscalculated": 0, "unknownPattern": 0, "rushed": 1}
    assert r.reasons[0].key == "didntLook" and "misclick" not in counts
    assert (r.tagged, r.untagged, r.misclicks) == (3, 1, 1)
    assert abs(next(c.share for c in r.reasons if c.key == "didntLook") - 2 / 3) < 1e-9  # type: ignore[operator]
    fork = reason_report(rows, lambda t: t.date(), theme="fork")
    assert fork.tagged == 2 and fork.misclicks == 1
    commit = reason_report(rows, lambda t: t.date(), mode="commit_line")
    assert commit.tagged == 1 and commit.untagged == 0


def test_reason_trend_by_local_week() -> None:
    rows = [
        row(False, reason="rushed", finished_at=at("2026-11-02T10:00:00")),  # Monday
        row(False, reason="rushed", finished_at=at("2026-11-08T23:30:00")),  # Sunday, same week
        row(False, reason="didntLook", finished_at=at("2026-11-09T09:00:00")),  # next Monday
    ]
    r = reason_report(rows, lambda t: t.date())
    assert [(w.week, w.counts) for w in r.trend] == [
        (date(2026, 11, 2), (0, 0, 0, 0, 2)),
        (date(2026, 11, 9), (1, 0, 0, 0, 0)),
    ]
    # Your calendar decides: 23:30 UTC on Sunday is already Monday an hour east.
    shifted = reason_report(rows[1:2], lambda t: date(2026, 11, 9))
    assert shifted.trend[0].week == date(2026, 11, 9)
