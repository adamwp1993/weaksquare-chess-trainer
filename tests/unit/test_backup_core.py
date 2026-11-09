"""core/backup.py (FR-15, v0.16): manifest, refusals, names, the automatic schedule and retention."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from weaksquare.core import backup as b
from weaksquare.core.errors import ValidationError

AT = datetime(2026, 11, 9, 15, 30, 5, tzinfo=UTC)
SHA = "a" * 64


def manifest(**over: object) -> b.Manifest:
    base = {"app_version": "0.16.0", "schema_version": 14, "created_at": AT.isoformat(),
            "counts": b.Counts(3, 120, 2), "db_sha256": SHA, "db_size": 4096}  # fmt: skip
    base.update(over)
    return b.Manifest(**base)  # type: ignore[arg-type]


def raw(**over: object) -> bytes:
    data = json.loads(b.manifest_json(manifest()))
    data.update(over)
    return json.dumps(data).encode()


def test_manifest_round_trip() -> None:
    m = manifest()
    assert b.parse_manifest(b.manifest_json(m).encode()) == m


@pytest.mark.parametrize(
    "payload",
    [b"", b"not json", b"\xff\xfe", json.dumps([1, 2]).encode(), json.dumps({"format": "zip"}).encode(),
     b"x" * (b.MANIFEST_MAX_BYTES + 1)],
)  # fmt: skip
def test_a_file_that_isnt_ours_is_not_a_backup(payload: bytes) -> None:
    with pytest.raises(b.BackupError) as e:
        b.parse_manifest(payload)
    assert e.value.code == "not_backup"


@pytest.mark.parametrize(
    "over",
    [{"schema_version": -1}, {"schema_version": "14"}, {"schema_version": True}, {"db_sha256": "abc"},
     {"created_at": "yesterday"}, {"counts": None}, {"counts": {"games": 1}}, {"app_version": 5},
     {"format_version": "1"}, {"db_size": -5}],
)  # fmt: skip
def test_our_manifest_with_bad_fields_is_damaged(over: dict) -> None:
    with pytest.raises(b.BackupError) as e:
        b.parse_manifest(raw(**over))
    assert e.value.code == "damaged"


def test_a_newer_format_or_schema_is_refused_with_the_nfr3_message() -> None:
    with pytest.raises(b.BackupError) as e:
        b.parse_manifest(raw(format_version=b.FORMAT_VERSION + 1))
    assert e.value.code == "newer_backup"
    with pytest.raises(b.BackupError) as e:
        b.check_restorable(manifest(schema_version=15), known_schema=14)
    assert e.value.code == "newer_backup"
    assert e.value.message == "This backup was made by a newer version of WeakSquare. Update the app first."


def test_an_older_or_equal_schema_is_restorable() -> None:
    b.check_restorable(manifest(schema_version=10), known_schema=14)
    b.check_restorable(manifest(schema_version=14), known_schema=14)


def test_names() -> None:
    assert b.manual_file_name(AT) == "weaksquare-backup-2026-11-09.zip"
    assert b.auto_file_name(AT) == "weaksquare-backup-2026-11-09-153005.zip"
    assert b.before_restore_name(AT) == "before-restore-2026-11-09-153005.zip"
    assert b.is_auto_name(b.auto_file_name(AT)) and b.is_auto_name(b.manual_file_name(AT))
    assert b.is_before_restore_name(b.before_restore_name(AT))
    for other in ("weaksquare-backup-notes.zip", "holiday.zip", "weaksquare-backup-2026-11-09.zip.txt",
                  "before-restore-2026-11-09-153005.zip"):  # fmt: skip
        assert not b.is_auto_name(other)


def test_auto_settings_are_checked() -> None:
    assert b.checked_auto_settings(False, None, 7, 5) == b.AutoSettings()
    assert b.checked_auto_settings(True, "  E:\\Backups ", 7, 5).folder == "E:\\Backups"
    for args in ((True, None, 7, 5), (True, "  ", 7, 5), (False, None, 0, 5), (False, None, 91, 5),
                 (False, None, 7, 0), (False, None, 7, 51)):  # fmt: skip
        with pytest.raises(ValidationError):
            b.checked_auto_settings(*args)  # type: ignore[arg-type]


def test_due_rules() -> None:
    assert b.next_due(None, 7, None, AT) is None
    assert b.next_due(None, 7, AT, AT) == AT  # none made yet: due as soon as they're on
    assert b.next_due(AT, 7, AT - timedelta(days=30), AT) == AT + timedelta(days=7)


def test_a_time_in_the_future_means_the_clock_was_wrong_so_a_backup_is_due_now() -> None:
    """v0.16-B6: a last backup (or switch-on) recorded while the clock ran ahead doesn't stop backups until then."""
    assert b.next_due(AT + timedelta(days=200), 7, None, AT) == AT
    assert b.next_due(None, 7, AT + timedelta(days=200), AT) == AT
    assert b.next_due(AT - timedelta(days=1), 7, AT + timedelta(days=200), AT) == AT + timedelta(days=6)
    assert b.is_due(AT, AT) and not b.is_due(AT - timedelta(seconds=1), AT) and not b.is_due(AT, None)


def test_the_timer_waits_until_due_but_at_least_a_minute_and_at_most_an_hour() -> None:
    assert b.seconds_until_check(AT, None) == b.RECHECK_S
    assert b.seconds_until_check(AT, AT + timedelta(days=3)) == b.RECHECK_S
    assert b.seconds_until_check(AT, AT + timedelta(minutes=10)) == 600
    assert b.seconds_until_check(AT, AT - timedelta(days=1)) == b.MIN_WAIT_S


def test_retention_keeps_the_newest() -> None:
    found = [(f"n{i}", (AT + timedelta(days=i)).isoformat()) for i in (3, 0, 4, 1, 2)]
    now = AT + timedelta(days=10)
    assert b.stale(found, 3, now) == ["n0", "n1"]
    assert b.stale(found, 10, now) == []
    # a hand-edited manifest with no offset sorts as UTC instead of crashing
    assert b.stale([("x", "2026-01-01T00:00:00"), ("y", AT.isoformat())], 1, now) == ["x"]


def test_retention_ignores_a_backup_dated_in_the_future() -> None:
    """v0.16-B6: a file made while the clock ran ahead isn't "newest"; the real ones are kept and it isn't deleted."""
    found = [("future", (AT + timedelta(days=400)).isoformat()), ("a", (AT - timedelta(days=2)).isoformat()),
             ("b", (AT - timedelta(days=1)).isoformat()), ("c", AT.isoformat())]  # fmt: skip
    assert b.stale(found, 2, AT) == ["a"]
    assert b.stale(found, 2, AT + timedelta(days=500)) == ["a", "b"]  # once its date has passed, it counts


def test_pc_local_keys() -> None:
    for k in ("backup.auto", "backup.last_error", "puzzle_db.last_check", "lichess.account", "debug.time_offset_days",
              "engine.custom_path", "engine.threads", "engine.hash_mb"):  # fmt: skip
        assert b.is_pc_local(k)
    for k in (
        "mixer.filters",
        "plan.params",
        "lichess.history_account",
        "llm.provider",
        "ui.color_scheme",
        "engine.think_s",
    ):
        assert not b.is_pc_local(k)


def test_busy_message_names_the_jobs() -> None:
    assert b.busy_message(["game_analysis"]) == "Wait for the game analysis to finish, or cancel it, then restore."
    msg = b.busy_message(["coach_run", "game_analysis", "game_puzzles", "something_new"])
    assert msg == ("Wait for a background task, the Coach report and the game analysis to finish, or cancel it, "
                   "then restore.")  # fmt: skip
