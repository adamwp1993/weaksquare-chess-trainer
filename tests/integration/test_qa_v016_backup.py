"""QA v0.16: backup and restore beyond the happy path (FR-15). Hostile zips, interrupted swaps, retention, clocks."""

from __future__ import annotations

import sqlite3
import struct
import threading
import tracemalloc
import zipfile
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from tests.fakes.desktop import FakeScheduler
from weaksquare import config
from weaksquare.adapters.backup_files import BackupFiles, check_db, extract_db, make_backup, read_manifest
from weaksquare.adapters.db.migrate import load_migrations, migrate
from weaksquare.adapters.db.repos.user_data import SettingsRepo
from weaksquare.app import apply_staged_restore
from weaksquare.core import backup as core
from weaksquare.core.clock import FixedClock
from weaksquare.core.errors import AppError
from weaksquare.jobs.runner import JobRunner
from weaksquare.services.backup import LAST_AUTO_KEY, SAVE_FAILED, BackupService

KNOWN = load_migrations(config.MIGRATIONS_DIR / "user")[-1].version


# ---- helpers ----------------------------------------------------------------------------------------
def files_for(p: config.Paths) -> BackupFiles:
    return BackupFiles(p.user_db, p.downloads_dir, p.user_restore_db, p.user_restore_manifest, "0.16.0")


def mark(db: Path, value: str) -> None:
    conn = sqlite3.connect(db)
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('mixer.filters', ?)", (f'"{value}"',))
    conn.commit()
    conn.close()


def marker(db: Path) -> str | None:
    conn = sqlite3.connect(db)
    try:
        row = conn.execute("SELECT value FROM settings WHERE key = 'mixer.filters'").fetchone()
    finally:
        conn.close()
    return None if row is None else str(row[0]).strip('"')


def fresh(tmp_path: Path, clock: FixedClock, name: str = "d", value: str = "original") -> config.Paths:
    p = config.Paths(tmp_path / name)
    p.ensure()
    migrate(p.user_db, config.MIGRATIONS_DIR / "user", clock)
    mark(p.user_db, value)
    return p


def good_backup(tmp_path: Path, clock: FixedClock, value: str = "from-backup") -> Path:
    src = fresh(tmp_path, clock, "src", value)
    z = tmp_path / "good.zip"
    make_backup(src.user_db, z, src.downloads_dir, "0.16.0", clock.now().isoformat())
    return z


def members(z: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(z) as zf:
        return {n: zf.read(n) for n in zf.namelist()}


def write_zip(path: Path, items: list[tuple[str, bytes]], compression: int = zipfile.ZIP_DEFLATED) -> Path:
    with zipfile.ZipFile(path, "w", compression=compression) as zf:
        for name, data in items:
            zf.writestr(zipfile.ZipInfo(name, (2026, 11, 9, 12, 0, 0)), data, compress_type=compression)
    return path


def corrupt_deflate(z: Path, member: str, out: Path) -> Path:
    """Make `member`'s deflate stream start with a reserved block type: zlib refuses it ("invalid block type")."""
    data = bytearray(z.read_bytes())
    with zipfile.ZipFile(z) as zf:
        info = zf.getinfo(member)
    assert info.compress_type == zipfile.ZIP_DEFLATED
    name_len, extra_len = struct.unpack("<HH", data[info.header_offset + 26 : info.header_offset + 30])
    start = info.header_offset + 30 + name_len + extra_len
    data[start] = 0x07  # BFINAL=1, BTYPE=11 (reserved)
    out.write_bytes(bytes(data))
    return out


def set_encrypted_flag(z: Path, member: str, out: Path) -> Path:
    """Flag `member` as encrypted (general purpose bit 0) in both its local and central headers."""
    data = bytearray(z.read_bytes())
    with zipfile.ZipFile(z) as zf:
        info = zf.getinfo(member)
    data[info.header_offset + 6] |= 0x01
    cd = data.find(b"PK\x01\x02" + bytes(data[info.header_offset + 4 : info.header_offset + 6]), 0)
    while cd != -1:
        name_len = struct.unpack("<H", data[cd + 28 : cd + 30])[0]
        if data[cd + 46 : cd + 46 + name_len] == member.encode():
            data[cd + 8] |= 0x01
            break
        cd = data.find(b"PK\x01\x02", cd + 4)
    out.write_bytes(bytes(data))
    return out


def refused_cleanly(svc_files: BackupFiles, bad: Path) -> str:
    """Inspect, then stage. Returns the BackupError code; anything else (a crash) fails the test."""
    try:
        read_manifest(bad)
        svc_files.stage_restore(bad)
    except core.BackupError as e:
        return e.code
    return "accepted"


# ---- hostile zips: refused as not a backup / damaged, never a crash, nothing written outside ----------
@pytest.mark.parametrize(
    "names",
    [
        ["manifest.json", "user.db", "user.db"],  # a duplicate member
        ["manifest.json", "sub/user.db"],
        ["manifest.json", "../user.db"],
        ["manifest.json", "..\\user.db"],
        ["manifest.json", "/user.db"],
        ["manifest.json", "C:/user.db"],
        ["MANIFEST.JSON", "USER.DB"],
        ["manifest.json", "user.db", "manifest.json"],
        ["manifest.json", "user.db", "user.db/"],
    ],
)
def test_qa_zips_with_odd_member_names_are_not_backups(names: list[str], tmp_path: Path, clock: FixedClock) -> None:
    good = members(good_backup(tmp_path, clock))
    p = fresh(tmp_path, clock)
    before = p.user_db.read_bytes()
    bad = tmp_path / "odd.zip"
    with pytest.warns(UserWarning) if len(set(names)) < len(names) else _nothing():
        write_zip(bad, [(n, good.get(n.lower().split("/")[-1].split("\\")[-1], b"x")) for n in names])
    assert refused_cleanly(files_for(p), bad) == "not_backup"
    assert p.user_db.read_bytes() == before
    assert not p.user_restore_db.exists()
    assert not (tmp_path / "user.db").exists() and not (p.data_dir.parent / "user.db").exists()


class _nothing:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *a: object) -> None:
        return None


def test_qa_a_manifest_that_lies_about_the_size_is_damaged(tmp_path: Path, clock: FixedClock) -> None:
    z = good_backup(tmp_path, clock)
    m = read_manifest(z)
    db = members(z)["user.db"]
    p = fresh(tmp_path, clock)
    for size in (m.db_size - 1, m.db_size + 1, 10**15):
        lie = core.manifest_json(core.Manifest(m.app_version, m.schema_version, m.created_at, m.counts, m.db_sha256,
                                               size))  # fmt: skip
        bad = write_zip(tmp_path / f"size{size}.zip", [("manifest.json", lie.encode()), ("user.db", db)])
        assert refused_cleanly(files_for(p), bad) == "damaged"
    assert not p.user_restore_db.exists()


def test_qa_a_huge_declared_size_is_refused_for_space_before_anything_is_written(tmp_path: Path,
                                                                                 clock: FixedClock) -> None:  # fmt: skip
    z = good_backup(tmp_path, clock)
    p = fresh(tmp_path, clock)
    files = BackupFiles(
        p.user_db,
        p.downloads_dir,
        p.user_restore_db,
        p.user_restore_manifest,
        "0.16.0",
        free_bytes=lambda _p: read_manifest(z).db_size,
    )  # exactly the size: no 10 % margin
    from weaksquare.adapters.backup_files import NoSpaceError

    with pytest.raises(NoSpaceError) as e:
        files.stage_restore(z)
    assert "Nothing was changed" in e.value.message
    assert not p.user_restore_db.exists()


def test_qa_a_valid_sqlite_file_that_isnt_a_weaksquare_db_is_damaged(tmp_path: Path, clock: FixedClock) -> None:
    import hashlib

    other = tmp_path / "other.db"
    conn = sqlite3.connect(other)
    conn.execute("CREATE TABLE notes (x)")
    conn.commit()
    conn.close()
    raw = other.read_bytes()
    m = read_manifest(good_backup(tmp_path, clock))
    fake = core.manifest_json(core.Manifest(m.app_version, m.schema_version, m.created_at, m.counts,
                                            hashlib.sha256(raw).hexdigest(), len(raw)))  # fmt: skip
    bad = write_zip(tmp_path / "other.zip", [("manifest.json", fake.encode()), ("user.db", raw)])
    p = fresh(tmp_path, clock)
    assert refused_cleanly(files_for(p), bad) == "damaged"


def test_qa_an_uncompressed_backup_is_accepted(tmp_path: Path, clock: FixedClock) -> None:
    """A backup re-zipped by another tool (stored, not deflated) is still a backup."""
    good = members(good_backup(tmp_path, clock))
    z = write_zip(tmp_path / "stored.zip", list(good.items()), zipfile.ZIP_STORED)
    p = fresh(tmp_path, clock)
    files_for(p).stage_restore(z)
    assert marker(p.user_restore_db) == "from-backup"


@pytest.mark.parametrize("member", ["user.db", "manifest.json"])
def test_qa_b1_a_broken_deflate_stream_is_damaged_not_a_crash(member: str, tmp_path: Path, clock: FixedClock) -> None:
    bad = corrupt_deflate(good_backup(tmp_path, clock), member, tmp_path / "flip.zip")
    p = fresh(tmp_path, clock)
    before = p.user_db.read_bytes()
    try:
        assert refused_cleanly(files_for(p), bad) == "damaged"
    finally:
        assert p.user_db.read_bytes() == before
        assert not p.user_restore_db.exists()


@pytest.mark.parametrize("member", ["user.db", "manifest.json"])
def test_qa_b1_an_encrypted_member_is_refused_not_a_crash(member: str, tmp_path: Path, clock: FixedClock) -> None:
    bad = set_encrypted_flag(good_backup(tmp_path, clock), member, tmp_path / "enc.zip")
    p = fresh(tmp_path, clock)
    assert refused_cleanly(files_for(p), bad) in {"not_backup", "damaged"}
    assert not p.user_restore_db.exists()


def test_qa_b1_the_bridge_names_the_reason_for_a_broken_backup(tmp_path: Path, clock: FixedClock) -> None:
    from tests.helpers import build_api

    bad = corrupt_deflate(good_backup(tmp_path, clock), "manifest.json", tmp_path / "flip.zip")
    p = fresh(tmp_path, clock)
    api = build_api(p, clock)
    api._desktop.next_file = str(bad)  # type: ignore[attr-defined]
    out = api.choose_backup_to_restore()
    assert out["ok"] is False
    assert out["error"]["code"] in {"damaged", "not_backup"}, out["error"]


def test_qa_b4_a_huge_manifest_is_refused_without_reading_it_all(tmp_path: Path, clock: FixedClock) -> None:
    db = members(good_backup(tmp_path, clock))["user.db"]
    bomb = b'{"format": "weaksquare-backup"' + b" " * (80 * 1024 * 1024) + b"}"
    bad = write_zip(tmp_path / "bomb.zip", [("manifest.json", bomb), ("user.db", db)])
    del bomb
    assert bad.stat().st_size < 1024 * 1024  # under a megabyte on disk
    tracemalloc.start()
    try:
        with pytest.raises(core.BackupError):
            read_manifest(bad)
        _cur, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 8 * 1024 * 1024, f"peak {peak / 1e6:.0f} MB to refuse a 64 KB-limited manifest"


# ---- the startup swap, interrupted ----------------------------------------------------------------------
def test_qa_a_leftover_manifest_without_a_staged_db_is_removed_and_nothing_changes(tmp_path: Path,
                                                                                   clock: FixedClock) -> None:  # fmt: skip
    p = fresh(tmp_path, clock)
    p.user_restore_manifest.write_text("{}", encoding="utf-8")
    before = p.user_db.read_bytes()
    assert apply_staged_restore(p, clock) is None
    assert not p.user_restore_manifest.exists() and p.user_db.read_bytes() == before


def test_qa_a_half_written_staged_db_from_an_interrupted_restore_is_not_kept(tmp_path: Path,
                                                                                      clock: FixedClock) -> None:  # fmt: skip
    """The restore job writes user.restore.db first and the manifest last. Closing the app mid-job kills that daemon
    thread after `cancel_all`'s 10 s, leaving a partial file and no manifest. The next start must not use it."""
    z = good_backup(tmp_path, clock)
    p = fresh(tmp_path, clock)
    full = tmp_path / "full.db"
    extract_db(z, full)
    raw = full.read_bytes()
    p.user_restore_db.write_bytes(raw[: len(raw) // 2])  # killed halfway; no manifest yet
    notice = apply_staged_restore(p, clock)
    assert marker(p.user_db) == "original", "the original data must stay"
    assert notice is None or notice.error is not None
    assert not p.user_restore_db.exists()


def test_qa_b2_a_staged_db_without_a_manifest_never_brings_another_pcs_settings(tmp_path: Path,
                                                                                clock: FixedClock) -> None:  # fmt: skip
    """Killed after extract_db, before carry_pc_settings and the manifest: the staged file still has the old PC's
    `backup.auto` folder and `lichess.account`."""
    src = fresh(tmp_path, clock, "src", "from-backup")
    set_raw(src.user_db, "backup.auto", '{"enabled": true, "folder": "Z:\\\\old-pc", "interval_days": 7, "keep": 5}')
    z = tmp_path / "b.zip"
    make_backup(src.user_db, z, src.downloads_dir, "0.16.0", clock.now().isoformat())
    p = fresh(tmp_path, clock)
    extract_db(z, p.user_restore_db)  # the step that finished; the manifest was never written
    apply_staged_restore(p, clock)
    conn = sqlite3.connect(p.user_db)
    keys = {k for (k,) in conn.execute("SELECT key FROM settings")}
    conn.close()
    assert "backup.auto" not in keys


def set_raw(db: Path, key: str, value: str) -> None:
    conn = sqlite3.connect(db)
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()


def test_qa_a_restore_interrupted_during_migration_leaves_a_working_db(tmp_path: Path, clock: FixedClock) -> None:
    """Killed after the swap, during migrate: user.db is the restored copy (migrations are transactional), the old one
    is in user.db.replaced, and the manifest is left. The next start must open without error."""
    z = good_backup(tmp_path, clock)
    p = fresh(tmp_path, clock)
    files_for(p).stage_restore(z)
    import os

    os.replace(p.user_db, p.user_db.with_name("user.db.replaced"))
    os.replace(p.user_restore_db, p.user_db)
    assert apply_staged_restore(p, clock) is None
    migrate(p.user_db, config.MIGRATIONS_DIR / "user", clock)
    assert marker(p.user_db) == "from-backup"
    assert not p.user_restore_manifest.exists()


def test_qa_b5_a_leftover_replaced_file_is_cleaned_up_at_the_next_start(tmp_path: Path, clock: FixedClock) -> None:
    z = good_backup(tmp_path, clock)
    p = fresh(tmp_path, clock)
    files_for(p).stage_restore(z)
    import os

    replaced = p.user_db.with_name("user.db.replaced")
    os.replace(p.user_db, replaced)
    os.replace(p.user_restore_db, p.user_db)
    apply_staged_restore(p, clock)
    assert not replaced.exists()


def test_qa_a_staged_restore_into_a_folder_with_no_user_db_saves_nothing_aside(tmp_path: Path,
                                                                               clock: FixedClock) -> None:  # fmt: skip
    z = good_backup(tmp_path, clock)
    p = config.Paths(tmp_path / "empty")
    p.ensure()
    files_for(p).stage_restore(z)
    notice = apply_staged_restore(p, clock)
    assert notice is not None and notice.error is None
    assert marker(p.user_db) == "from-backup"
    assert not list(p.backups_dir.glob("before-restore-*.zip"))


def test_qa_a_wal_left_by_a_crash_is_saved_aside_and_not_applied_to_the_restored_db(tmp_path: Path,
                                                                                     clock: FixedClock) -> None:  # fmt: skip
    """The old app crashed with unflushed writes in user.db-wal. The before-restore copy includes them, and the
    restored data never gets the stale WAL applied on top."""
    z = good_backup(tmp_path, clock)
    p = fresh(tmp_path, clock)
    files_for(p).stage_restore(z)
    conn = sqlite3.connect(p.user_db, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.execute("UPDATE settings SET value = '\"in-the-wal\"' WHERE key = 'mixer.filters'")
    # leave the WAL un-checkpointed: copy files while the connection is open, as after a crash
    wal = p.user_db.with_name("user.db-wal").read_bytes()
    main = p.user_db.read_bytes()
    conn.close()
    p.user_db.write_bytes(main)
    p.user_db.with_name("user.db-wal").write_bytes(wal)
    notice = apply_staged_restore(p, clock)
    assert notice is not None and notice.error is None
    assert marker(p.user_db) == "from-backup"
    saved = next(p.backups_dir.glob("before-restore-*.zip"))
    out = tmp_path / "saved.db"
    extract_db(saved, out)
    assert marker(out) == "in-the-wal"


# ---- retention and the automatic timer ---------------------------------------------------------------------
def auto(p: config.Paths, clock: FixedClock) -> tuple[BackupService, FakeScheduler, JobRunner, SettingsRepo]:
    from weaksquare.adapters.db.connection import Database

    db = Database(p.user_db, p.puzzles_db)
    settings = SettingsRepo(db)
    sched, runner = FakeScheduler(), JobRunner()
    return (
        BackupService(files_for(p), settings, runner, clock, sched, KNOWN, restart=lambda: None),
        sched,
        runner,
        settings,
    )


def drain(runner: JobRunner) -> None:
    for s in runner.active():
        runner.wait(s.id, 30)


def test_qa_retention_never_touches_files_that_arent_ours(tmp_path: Path, clock: FixedClock) -> None:
    p = fresh(tmp_path, clock)
    folder = tmp_path / "auto"
    folder.mkdir()
    real_other = good_backup(tmp_path, clock)  # a real backup, but a name you chose
    keep = {
        "holiday.zip": b"x",
        "weaksquare-backup-notes.txt": b"x",
        "Weaksquare-Backup-2020-01-01.zip": real_other.read_bytes(),  # different case
        "weaksquare-backup-2020-01-01.zip.bak": real_other.read_bytes(),
        "weaksquare-backup-2020-01-01 (1).zip": real_other.read_bytes(),  # Windows' copy name
        "my-weaksquare-backup-2020-01-01.zip": real_other.read_bytes(),
        "before-restore-2020-01-01-000000.zip": real_other.read_bytes(),
    }
    for name, data in keep.items():
        (folder / name).write_bytes(data)
    (folder / "weaksquare-backup-2019-01-01.zip").mkdir()  # a folder named like ours
    svc, sched, runner, _ = auto(p, clock)
    svc.set_auto_settings(True, str(folder), 1, 1)
    for _ in range(3):
        sched.run_next()
        drain(runner)
        clock.advance(days=1, seconds=1)
    for name in keep:
        assert (folder / name).exists(), name
    assert (folder / "weaksquare-backup-2019-01-01.zip").is_dir()
    assert len([f for f in folder.iterdir() if core.is_auto_name(f.name) and f.is_file()]) == 1


def test_qa_b3_a_damaged_old_backup_in_the_folder_doesnt_make_a_backup_every_minute(tmp_path: Path,
                                                                                    clock: FixedClock) -> None:  # fmt: skip
    p = fresh(tmp_path, clock)
    folder = tmp_path / "auto"
    folder.mkdir()
    old = good_backup(tmp_path, clock)
    corrupt_deflate(old, "manifest.json", folder / "weaksquare-backup-2020-01-01-000000.zip")  # bit rot on the stick
    svc, sched, runner, _ = auto(p, clock)
    svc.set_auto_settings(True, str(folder), 7, 5)
    for _ in range(5):  # five timer ticks, each a minute or so apart
        delay = sched.run_next()
        drain(runner)
        clock.advance(seconds=max(delay, 60) + 1)
    made = [f for f in folder.iterdir() if f.name != "weaksquare-backup-2020-01-01-000000.zip"]
    assert len(made) == 1, f"{len(made)} backups in 5 minutes; status: {svc.status().last_error}"


def test_qa_the_clock_jumping_forward_makes_one_backup_not_many(tmp_path: Path, clock: FixedClock) -> None:
    p = fresh(tmp_path, clock)
    folder = tmp_path / "auto"
    folder.mkdir()
    svc, sched, runner, _ = auto(p, clock)
    svc.set_auto_settings(True, str(folder), 7, 50)
    sched.run_next()
    drain(runner)
    clock.advance(days=365)  # hibernated for a year, or the clock was fixed
    for _ in range(5):
        delay = sched.run_next()
        drain(runner)
        clock.advance(seconds=delay)
    assert len(list(folder.iterdir())) == 2
    due = svc.status().next_due
    assert due is not None


def test_qa_b6_the_clock_set_back_doesnt_stop_automatic_backups(tmp_path: Path, clock: FixedClock) -> None:
    p = fresh(tmp_path, clock)
    folder = tmp_path / "auto"
    folder.mkdir()
    svc, _sched, runner, settings = auto(p, clock)
    svc.set_auto_settings(True, str(folder), 7, 5)
    settings.set(LAST_AUTO_KEY, (clock.now() + timedelta(days=200)).isoformat())  # made while the clock was wrong
    clock.advance(days=8)
    svc.start()
    drain(runner)
    assert len(list(folder.iterdir())) == 1, f"next due {svc.status().next_due}"


def test_qa_b6_retention_keeps_the_newest_real_backups_after_a_clock_mistake(tmp_path: Path, clock: FixedClock) -> None:
    p = fresh(tmp_path, clock)
    folder = tmp_path / "auto"
    folder.mkdir()
    future = clock.now() + timedelta(days=400)
    make_backup(p.user_db, folder / core.auto_file_name(future), p.downloads_dir, "0.16.0", future.isoformat())
    svc, sched, runner, _ = auto(p, clock)
    svc.set_auto_settings(True, str(folder), 1, 2)
    for _ in range(3):
        sched.run_next()
        drain(runner)
        clock.advance(days=1, seconds=1)
    names = sorted(f.name for f in folder.iterdir())
    real = [n for n in names if n != core.auto_file_name(future)]
    assert len(real) == 2, names


# ---- Back up now: targets and paths -------------------------------------------------------------------------
def test_qa_back_up_over_an_existing_file_replaces_it_atomically(tmp_path: Path, clock: FixedClock) -> None:
    p = fresh(tmp_path, clock)
    svc, _s, runner, _ = auto(p, clock)
    target = tmp_path / "out.zip"
    target.write_bytes(b"an older file the Save dialog asked to replace")
    status = runner.wait(svc.backup_now(str(target)), 30)
    assert status is not None and status.state == "done"
    assert read_manifest(target).schema_version == KNOWN
    assert [f.name for f in tmp_path.iterdir() if f.name.startswith(".out.zip")] == []  # no temp file left


def test_qa_back_up_onto_a_folder_named_like_the_file_fails_with_a_message(tmp_path: Path, clock: FixedClock) -> None:
    p = fresh(tmp_path, clock)
    svc, _s, runner, _ = auto(p, clock)
    target = tmp_path / "taken.zip"
    target.mkdir()
    status = runner.wait(svc.backup_now(str(target)), 30)
    assert status is not None and status.state == "failed" and status.message == SAVE_FAILED
    assert target.is_dir() and not list(target.iterdir())
    assert [f.name for f in tmp_path.iterdir() if f.name.endswith(".tmp")] == []


def test_qa_back_up_onto_a_read_only_file_fails_with_a_message(tmp_path: Path, clock: FixedClock) -> None:
    import os
    import stat

    p = fresh(tmp_path, clock)
    svc, _s, runner, _ = auto(p, clock)
    target = tmp_path / "ro.zip"
    target.write_bytes(b"read only")
    os.chmod(target, stat.S_IREAD)
    try:
        status = runner.wait(svc.backup_now(str(target)), 30)
        assert status is not None and status.state == "failed" and status.message == SAVE_FAILED
        assert target.read_bytes() == b"read only"
    finally:
        os.chmod(target, stat.S_IWRITE | stat.S_IREAD)


def test_qa_a_name_without_zip_gets_zip_and_never_overwrites_user_db(tmp_path: Path, clock: FixedClock) -> None:
    p = fresh(tmp_path, clock)
    svc, _s, runner, _ = auto(p, clock)
    status = runner.wait(svc.backup_now(str(p.user_db)), 30)  # someone types the live file's own name
    assert status is not None and status.state == "done"
    assert check_db(p.user_db).schema_version == KNOWN and marker(p.user_db) == "original"
    assert read_manifest(p.user_db.with_name("user.db.zip")).schema_version == KNOWN


@pytest.mark.parametrize("folder", [
    "Ünïcødé 日本語 – backups", "spaces and (brackets) & ampersand", "a" * 40 + "/" + "b" * 40,
    "with#hash", "with%41percent",  # v0.16-B7
])  # fmt: skip
def test_qa_unicode_and_odd_folder_names_back_up_and_restore(folder: str, tmp_path: Path, clock: FixedClock) -> None:
    src = config.Paths(tmp_path / folder / "data")
    src.ensure()
    migrate(src.user_db, config.MIGRATIONS_DIR / "user", clock)
    mark(src.user_db, "odd-path")
    target = tmp_path / folder / "out" / "weaksquare-backup-2026-11-09.zip"
    make_backup(src.user_db, target, src.downloads_dir, "0.16.0", clock.now().isoformat())
    dst = config.Paths(tmp_path / folder / "new data")
    dst.ensure()
    files_for(dst).stage_restore(target)
    assert apply_staged_restore(dst, clock).error is None  # type: ignore[union-attr]
    assert marker(dst.user_db) == "odd-path"


def test_qa_b7_check_db_works_in_a_folder_with_uri_characters(tmp_path: Path, clock: FixedClock) -> None:
    """readonly_uri doesn't percent-encode; a data folder with '#' or '?' must still be checkable."""
    d = tmp_path / "C#dev"
    d.mkdir()
    db = d / "user.db"
    migrate(db, config.MIGRATIONS_DIR / "user", clock)
    assert check_db(db).schema_version == KNOWN


def test_qa_a_long_path_backup_either_works_or_fails_with_a_message(tmp_path: Path, clock: FixedClock) -> None:
    p = fresh(tmp_path, clock)
    deep = tmp_path
    while len(str(deep)) < 235:  # a folder Windows still allows; the backup's full name goes past 260
        deep = deep / ("d" * min(50, 240 - len(str(deep))))
    try:
        deep.mkdir(parents=True)
    except OSError:
        pytest.skip("this PC can't make a path that long at all")
    svc, _s, runner, _ = auto(p, clock)
    target = deep / "weaksquare-backup-2026-11-09.zip"
    status = runner.wait(svc.backup_now(str(target)), 30)
    assert status is not None
    assert (status.state == "done" and read_manifest(target).schema_version == KNOWN) or (
        status.state == "failed" and status.message == SAVE_FAILED
    ), status


# ---- restore and jobs -------------------------------------------------------------------------------------------
@pytest.mark.parametrize("kind", ["backup", "games_sync", "explain", "an_unknown_kind"])
def test_qa_restore_is_refused_while_any_job_runs_and_nothing_is_staged(kind: str, tmp_path: Path,
                                                                        clock: FixedClock) -> None:  # fmt: skip
    from weaksquare.core.errors import ConflictError

    z = good_backup(tmp_path, clock)
    p = fresh(tmp_path, clock)
    svc, _s, runner, _ = auto(p, clock)
    release = threading.Event()
    job = runner.submit(kind, lambda progress, token: release.wait(10))
    try:
        with pytest.raises(ConflictError) as e:
            svc.restore(str(z))
        assert e.value.message.startswith("Wait for ") and "cancel it" in e.value.message
    finally:
        release.set()
        runner.wait(job, 10)
    assert not p.user_restore_db.exists()


def test_qa_a_second_restore_and_backup_during_a_restore_are_refused(tmp_path: Path, clock: FixedClock) -> None:
    from weaksquare.core.errors import ConflictError

    z = good_backup(tmp_path, clock)
    p = fresh(tmp_path, clock)
    gate = threading.Event()
    restarted = threading.Event()

    class SlowFiles(BackupFiles):
        def stage_restore(self, path: Path) -> core.Manifest:
            gate.wait(10)
            return super().stage_restore(path)

    from weaksquare.adapters.db.connection import Database

    runner = JobRunner()
    svc = BackupService(SlowFiles(p.user_db, p.downloads_dir, p.user_restore_db, p.user_restore_manifest, "0.16.0"),
                        SettingsRepo(Database(p.user_db, p.puzzles_db)), runner, clock, FakeScheduler(), KNOWN,
                        restart=restarted.set)  # fmt: skip
    job = svc.restore(str(z))
    try:
        with pytest.raises(ConflictError):
            svc.restore(str(z))
        with pytest.raises(ConflictError):
            svc.backup_now(str(tmp_path / "x.zip"))
    finally:
        gate.set()
    assert runner.wait(job, 30).state == "done"  # type: ignore[union-attr]
    assert restarted.is_set()


def test_qa_a_newer_backup_is_refused_by_inspect_with_the_nfr3_message(tmp_path: Path, clock: FixedClock) -> None:
    z = good_backup(tmp_path, clock)
    m = read_manifest(z)
    db = members(z)["user.db"]
    newer = core.manifest_json(core.Manifest("9.9.9", KNOWN + 5, m.created_at, m.counts, m.db_sha256, m.db_size))
    bad = write_zip(tmp_path / "newer.zip", [("manifest.json", newer.encode()), ("user.db", db)])
    p = fresh(tmp_path, clock)
    svc, _s, _r, _ = auto(p, clock)
    with pytest.raises(AppError) as e:
        svc.inspect(str(bad))
    assert e.value.message == core.NEWER_MESSAGE


# ---- privacy: nothing secret-shaped in a backup ----------------------------------------------------------------
def test_qa_no_setting_in_a_backup_looks_like_a_secret(services: Any, tmp_path: Path) -> None:
    """Sign in and set AI keys through the fake secret store, then check the backup's settings table by key and value."""
    import re

    services.games.import_pgn('[White "player_a"]\n[Black "opponent_b"]\n[Result "*"]\n\n1. e4 e5 *\n')
    target = tmp_path / "s.zip"
    status = services.backup._runner.wait(services.backup.backup_now(str(target)), 30)
    assert status.state == "done"
    out = tmp_path / "s.db"
    extract_db(target, out)
    conn = sqlite3.connect(out)
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    conn.close()
    pattern = re.compile(r"(lip_|sk-ant-|sk-proj-|sk-[A-Za-z0-9]{20}|bearer|password|secret|verifier)", re.I)
    for k, v in rows:
        assert not pattern.search(f"{k}={v}"), k
    assert not [t for t in tables if re.search(r"token|secret|credential|key", t, re.I) and t != "api_keys_unused"]
