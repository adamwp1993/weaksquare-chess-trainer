"""QA v0.16 round 2: trying to break the B1-B7 fixes (lying headers, fuzzed zips, clocks both ways, interrupted swaps)."""

from __future__ import annotations

import os
import random
import struct
import tracemalloc
import zipfile
from datetime import timedelta
from pathlib import Path

import pytest

from tests.fakes.desktop import FakeScheduler
from tests.integration.test_qa_v016_backup import files_for, fresh, good_backup, marker, members, write_zip
from weaksquare import config
from weaksquare.adapters.backup_files import (
    INCOMPLETE_MESSAGE,
    NoSpaceError,
    extract_db,
    list_backups,
    make_backup,
    read_manifest,
)
from weaksquare.adapters.db.connection import Database
from weaksquare.adapters.db.migrate import load_migrations
from weaksquare.adapters.db.repos.user_data import SettingsRepo
from weaksquare.app import apply_staged_restore
from weaksquare.core import backup as core
from weaksquare.core.clock import FixedClock
from weaksquare.jobs.runner import JobRunner
from weaksquare.services.backup import BackupService

KNOWN = load_migrations(config.MIGRATIONS_DIR / "user")[-1].version


def lie_about_size(z: Path, member: str, size: int, out: Path) -> Path:
    """Rewrite `member`'s uncompressed size in both its local and central headers."""
    data = bytearray(z.read_bytes())
    with zipfile.ZipFile(z) as zf:
        info = zf.getinfo(member)
    struct.pack_into("<I", data, info.header_offset + 22, size)
    cd = data.find(b"PK\x01\x02")
    while cd != -1:
        name_len = struct.unpack_from("<H", data, cd + 28)[0]
        if data[cd + 46 : cd + 46 + name_len] == member.encode():
            struct.pack_into("<I", data, cd + 24, size)
        cd = data.find(b"PK\x01\x02", cd + 4)
    out.write_bytes(bytes(data))
    return out


@pytest.mark.parametrize("claimed", [100, core.MANIFEST_MAX_BYTES, core.MANIFEST_MAX_BYTES - 1])
def test_qa_r2_a_lying_small_header_over_a_huge_manifest_reads_little_and_is_refused(claimed: int, tmp_path: Path,
                                                                                    clock: FixedClock) -> None:  # fmt: skip
    db = members(good_backup(tmp_path, clock))["user.db"]
    bomb = b'{"format": "weaksquare-backup"' + b" " * (80 * 1024 * 1024) + b"}"
    honest = write_zip(tmp_path / "bomb.zip", [("manifest.json", bomb), ("user.db", db)])
    del bomb
    bad = lie_about_size(honest, "manifest.json", claimed, tmp_path / "liar.zip")
    tracemalloc.start()
    try:
        with pytest.raises(core.BackupError):
            read_manifest(bad)
        _cur, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 8 * 1024 * 1024, f"peak {peak / 1e6:.0f} MB"


def test_qa_r2_a_lying_big_header_on_a_small_manifest_is_refused(tmp_path: Path, clock: FixedClock) -> None:
    bad = lie_about_size(good_backup(tmp_path, clock), "manifest.json", 10**9, tmp_path / "liar.zip")
    with pytest.raises(core.BackupError):
        read_manifest(bad)


@pytest.mark.parametrize("delta", [-1, +1, 10**6])
def test_qa_r2_a_user_db_header_that_lies_with_a_matching_manifest_is_damaged(delta: int, tmp_path: Path,
                                                                             clock: FixedClock) -> None:  # fmt: skip
    z = good_backup(tmp_path, clock)
    m = read_manifest(z)
    size = m.db_size + delta
    lie = core.manifest_json(core.Manifest(m.app_version, m.schema_version, m.created_at, m.counts, m.db_sha256, size))
    rezipped = write_zip(tmp_path / "re.zip", [("manifest.json", lie.encode()), ("user.db", members(z)["user.db"])])
    bad = lie_about_size(rezipped, "user.db", size, tmp_path / "liar.zip")
    p = fresh(tmp_path, clock)
    before = p.user_db.read_bytes()
    with pytest.raises(core.BackupError) as e:
        files_for(p).stage_restore(bad)
    assert e.value.code == "damaged"
    assert p.user_db.read_bytes() == before and not p.user_restore_db.exists()


def test_qa_r2_fuzzed_backups_are_always_refused_cleanly_and_never_break_retention(tmp_path: Path,
                                                                                 clock: FixedClock) -> None:  # fmt: skip
    """600 single-byte changes anywhere in a real backup (headers, central directory, data): every one is accepted
    (a byte that doesn't matter) or refused with BackupError, and retention's listing never raises."""
    z = good_backup(tmp_path, clock)
    data = z.read_bytes()
    p = fresh(tmp_path, clock)
    files = files_for(p)
    rnd = random.Random(16)
    folder = tmp_path / "fuzz"
    folder.mkdir()
    outcomes: dict[str, int] = {}
    for i in range(600):
        b = bytearray(data)
        pos = rnd.randrange(len(b))
        b[pos] = rnd.randrange(256) if i % 2 else b[pos] ^ (1 << rnd.randrange(8))
        bad = folder / f"weaksquare-backup-2020-01-01-{i:06d}.zip"
        bad.write_bytes(bytes(b))
        try:
            read_manifest(bad)
            files.stage_restore(bad)
            files.discard_staged()
            key = "accepted"
        except core.BackupError as e:
            key = e.code
        except NoSpaceError:  # a mutated db_size can claim terabytes
            key = "no_space"
        outcomes[key] = outcomes.get(key, 0) + 1
        assert not p.user_restore_db.exists()
    assert set(outcomes) <= {"accepted", "damaged", "not_backup", "newer_backup", "no_space"}, outcomes
    found = list_backups(folder, core.is_auto_name)  # must not raise
    assert len(found) <= 600


def test_qa_r2_a_staged_db_without_a_manifest_says_so_and_keeps_your_data(tmp_path: Path, clock: FixedClock) -> None:
    z = good_backup(tmp_path, clock)
    p = fresh(tmp_path, clock)
    extract_db(z, p.user_restore_db)
    notice = apply_staged_restore(p, clock)
    assert notice is not None and notice.error == INCOMPLETE_MESSAGE
    assert marker(p.user_db) == "original" and not p.user_restore_db.exists()
    assert not list(p.backups_dir.glob("before-restore-*.zip"))  # nothing to undo


def test_qa_r2_a_truncated_manifest_from_a_crash_mid_write_discards_the_staging(tmp_path: Path,
                                                                                clock: FixedClock) -> None:  # fmt: skip
    z = good_backup(tmp_path, clock)
    p = fresh(tmp_path, clock)
    files_for(p).stage_restore(z)
    raw = p.user_restore_manifest.read_bytes()
    p.user_restore_manifest.write_bytes(raw[: len(raw) // 2])
    notice = apply_staged_restore(p, clock)
    assert notice is not None and notice.error == INCOMPLETE_MESSAGE
    assert marker(p.user_db) == "original"


def test_qa_r2_a_crash_between_the_renames_puts_your_data_back_then_finishes_the_restore(tmp_path: Path,
                                                                                         clock: FixedClock) -> None:  # fmt: skip
    """Stopped after user.db went to user.db.replaced, before the staged file moved in. The next start recovers your
    data, then the staged restore (still complete, with its manifest) runs as normal."""
    z = good_backup(tmp_path, clock)
    p = fresh(tmp_path, clock)
    files_for(p).stage_restore(z)
    os.replace(p.user_db, p.user_db.with_name("user.db.replaced"))
    notice = apply_staged_restore(p, clock)
    assert notice is not None and notice.error is None
    assert marker(p.user_db) == "from-backup"
    saved = next(p.backups_dir.glob("before-restore-*.zip"))
    out = tmp_path / "saved.db"
    extract_db(saved, out)
    assert marker(out) == "original"  # the undo copy holds your data, not nothing
    assert not p.user_db.with_name("user.db.replaced").exists()


def test_qa_r2_a_crash_between_the_renames_without_staging_left_just_puts_your_data_back(tmp_path: Path,
                                                                                         clock: FixedClock) -> None:  # fmt: skip
    p = fresh(tmp_path, clock)
    os.replace(p.user_db, p.user_db.with_name("user.db.replaced"))
    assert apply_staged_restore(p, clock) is None
    assert marker(p.user_db) == "original"


# ---- clocks both ways ---------------------------------------------------------------------------------------------
def auto(p: config.Paths, clock: FixedClock) -> tuple[BackupService, FakeScheduler, JobRunner]:
    sched, runner = FakeScheduler(), JobRunner()
    svc = BackupService(files_for(p), SettingsRepo(Database(p.user_db, p.puzzles_db)), runner, clock, sched, KNOWN,
                        restart=lambda: None)  # fmt: skip
    return svc, sched, runner


def drain(runner: JobRunner) -> None:
    for s in runner.active():
        runner.wait(s.id, 30)


def tick(svc: BackupService, runner: JobRunner) -> None:
    svc.start()
    drain(runner)


def test_qa_r2_clock_ahead_then_behind_then_right_again(tmp_path: Path, clock: FixedClock) -> None:
    p = fresh(tmp_path, clock)
    folder = tmp_path / "auto"
    folder.mkdir()
    svc, _sched, runner = auto(p, clock)
    svc.set_auto_settings(True, str(folder), 7, 3)
    tick(svc, runner)  # 1: today
    clock.advance(days=300)  # the clock runs a year-ish ahead
    tick(svc, runner)  # 2: future-dated
    clock.advance(days=-300 + 1)  # fixed: back to day 1
    tick(svc, runner)  # 3: due now, since the last one is "in the future"
    tick(svc, runner)  # nothing more: the new last backup is now
    assert len(list(folder.iterdir())) == 3
    for _ in range(4):  # a month of normal weeks
        clock.advance(days=7, seconds=1)
        tick(svc, runner)
    names = sorted(f.name for f in folder.iterdir())
    future = [n for n in names if n > core.auto_file_name((clock.now() + timedelta(days=1)).astimezone())]
    real = [n for n in names if n not in future]
    assert len(future) == 1, names  # the future-dated one is left alone
    assert len(real) == 3, names  # keep 3 real ones
    due = svc.status().next_due
    assert due is not None and due > clock.now().isoformat()[:10]


def test_qa_r2_clock_behind_then_right_makes_no_burst(tmp_path: Path, clock: FixedClock) -> None:
    p = fresh(tmp_path, clock)
    folder = tmp_path / "auto"
    folder.mkdir()
    svc, _sched, runner = auto(p, clock)
    svc.set_auto_settings(True, str(folder), 7, 50)
    tick(svc, runner)
    clock.advance(days=-200)  # the clock is set back by mistake
    for _ in range(3):
        tick(svc, runner)
    clock.advance(days=200 + 8)  # corrected, and a week passes
    for _ in range(3):
        tick(svc, runner)
    assert len(list(folder.iterdir())) == 3, sorted(f.name for f in folder.iterdir())


def test_qa_r2_retention_with_the_clock_set_back_never_deletes_your_newest_real_backups(tmp_path: Path,
                                                                                         clock: FixedClock) -> None:  # fmt: skip
    p = fresh(tmp_path, clock)
    folder = tmp_path / "auto"
    folder.mkdir()
    for d in range(3):  # three correct backups
        at = clock.now() - timedelta(days=7 * (3 - d))
        make_backup(p.user_db, folder / core.auto_file_name(at.astimezone()), p.downloads_dir, "0.16.0", at.isoformat())
    keep_names = {f.name for f in folder.iterdir()}
    clock.advance(days=-365)  # now the clock is a year behind: all three look "future"
    svc, _sched, runner = auto(p, clock)
    svc.set_auto_settings(True, str(folder), 1, 1)
    for _ in range(3):
        tick(svc, runner)
        clock.advance(days=1, seconds=1)
    assert keep_names <= {f.name for f in folder.iterdir()}


def set_extract_version(z: Path, member: str, version: int, out: Path) -> Path:
    """Set `member`'s "version needed to extract" in the central directory (a value zipfile doesn't support)."""
    data = bytearray(z.read_bytes())
    cd = data.find(b"PK\x01\x02")
    while cd != -1:
        name_len = struct.unpack_from("<H", data, cd + 28)[0]
        if data[cd + 46 : cd + 46 + name_len] == member.encode():
            data[cd + 6] = version
        cd = data.find(b"PK\x01\x02", cd + 4)
    out.write_bytes(bytes(data))
    return out


@pytest.mark.parametrize("member", ["manifest.json", "user.db"])
def test_qa_r2_b11_an_unsupported_zip_version_is_refused_not_a_crash(member: str, tmp_path: Path,
                                                                     clock: FixedClock) -> None:  # fmt: skip
    bad = set_extract_version(good_backup(tmp_path, clock), member, 88, tmp_path / "v88.zip")  # 8.8 > 6.3
    p = fresh(tmp_path, clock)
    with pytest.raises(core.BackupError):
        read_manifest(bad)
        files_for(p).stage_restore(bad)
    assert not p.user_restore_db.exists()


def test_qa_r2_b11_the_bridge_names_the_reason(tmp_path: Path, clock: FixedClock) -> None:
    from tests.helpers import build_api

    bad = set_extract_version(good_backup(tmp_path, clock), "user.db", 88, tmp_path / "v88.zip")
    p = fresh(tmp_path, clock)
    api = build_api(p, clock)
    api._desktop.next_file = str(bad)  # type: ignore[attr-defined]
    out = api.choose_backup_to_restore()
    assert out["ok"] is False and out["error"]["code"] in {"damaged", "not_backup"}, out["error"]


def test_qa_r2_b11_retention_survives_it(tmp_path: Path, clock: FixedClock) -> None:
    folder = tmp_path / "auto"
    folder.mkdir()
    set_extract_version(good_backup(tmp_path, clock), "user.db", 88, folder / "weaksquare-backup-2020-01-01.zip")
    assert list_backups(folder, core.is_auto_name) == []
    assert (folder / "weaksquare-backup-2020-01-01.zip").exists()
