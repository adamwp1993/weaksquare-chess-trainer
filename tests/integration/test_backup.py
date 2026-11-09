"""Backup and restore with real files (FR-15, v0.16; ROADMAP v0.16 *Done when*)."""

from __future__ import annotations

import shutil
import sqlite3
import threading
import zipfile
from pathlib import Path
from typing import Any

import pytest

from tests.fakes.desktop import FakeScheduler
from tests.helpers import build_api, fake_service_kwargs
from weaksquare import config
from weaksquare.adapters.backup_files import (
    BackupFiles,
    NoSpaceError,
    check_db,
    make_backup,
    read_manifest,
    swap_in_staged,
)
from weaksquare.adapters.db.migrate import load_migrations, migrate, read_version
from weaksquare.adapters.db.repos.user_data import SettingsRepo
from weaksquare.adapters.secret_store import MemorySecretStore
from weaksquare.app import apply_staged_restore, build_services
from weaksquare.core import backup as core
from weaksquare.core.clock import FixedClock
from weaksquare.core.errors import ConflictError, ValidationError
from weaksquare.core.filters import FilterSpec
from weaksquare.jobs.runner import JobRunner
from weaksquare.services.backup import FOLDER_MISSING, BackupService

MATE = '[White "player_a"]\n[Black "opponent_b"]\n[Result "1-0"]\n\n1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7# 1-0\n'
TRAP = '[White "player_a"]\n[Black "opponent_c"]\n[Result "0-1"]\n\n1. e4 e5 2. Nf3 Nc6 3. Bc4 Nd4 4. Nxe5 Qg5 5. Nxf7 Qxg2 6. Rf1 Qxe4+ 7. Be2 Nf3# 0-1\n'
KNOWN = load_migrations(config.MIGRATIONS_DIR / "user")[-1].version


def seed(services: Any) -> None:
    services.games.import_pgn(MATE)
    services.games.import_pgn(TRAP)
    services.journal.add("First thought.")
    services.presets.save("Combo night", FilterSpec())
    s = SettingsRepo(services.db)
    s.set("mixer.filters", {"seeded": True})
    s.set("puzzle_db.last_check", "from-the-old-pc")
    s.set("backup.auto", {"enabled": True, "folder": "Z:\\old-pc", "interval_days": 7, "keep": 5})


def dump(db: Path, skip_pc_local: bool = False) -> dict[str, list[tuple]]:
    conn = sqlite3.connect(db)
    try:
        tables = [
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        ]
        out = {t: sorted(conn.execute(f"SELECT * FROM {t}").fetchall(), key=repr) for t in tables}
    finally:
        conn.close()
    if skip_pc_local:
        out["settings"] = [r for r in out["settings"] if not core.is_pc_local(r[0])]
    return out


def files_for(paths: config.Paths) -> BackupFiles:
    return BackupFiles(paths.user_db, paths.downloads_dir, paths.user_restore_db, paths.user_restore_manifest, "0.16.0")


def new_install(tmp_path: Path, name: str = "new") -> config.Paths:
    p = config.Paths(tmp_path / name)
    p.ensure()
    return p


def backup_of(services: Any, tmp_path: Path, clock: FixedClock) -> Path:
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    target = out / "b.zip"
    job = services.backup.backup_now(str(target))
    status = services.backup._runner.wait(job, 30)
    assert status.state == "done", status
    return target


# ---- round trip ------------------------------------------------------------------------------------
def test_backup_and_restore_into_an_empty_folder_gives_the_same_data(services: Any, paths: config.Paths,
                                                                      tmp_path: Path, clock: FixedClock) -> None:  # fmt: skip
    seed(services)
    zip_path = backup_of(services, tmp_path, clock)
    m = read_manifest(zip_path)
    assert (m.counts.games, m.schema_version, m.app_version) == (2, KNOWN, config.APP_VERSION)
    assert sorted(zipfile.ZipFile(zip_path).namelist()) == ["manifest.json", "user.db"]

    new = new_install(tmp_path)
    files_for(new).stage_restore(zip_path)
    notice = apply_staged_restore(new, clock)
    assert notice is not None and notice.error is None and notice.created_at == m.created_at
    assert not new.user_restore_db.exists() and not new.user_restore_manifest.exists()
    services.db.close_all()
    assert dump(new.user_db, skip_pc_local=True) == dump(paths.user_db, skip_pc_local=True)
    assert all(not core.is_pc_local(k) for (k, _v) in dump(new.user_db)["settings"])  # none came across


def test_a_backup_never_changes_user_db(services: Any, paths: config.Paths, tmp_path: Path, clock: FixedClock) -> None:
    seed(services)
    before = dump(paths.user_db, skip_pc_local=True)
    backup_of(services, tmp_path, clock)
    assert dump(paths.user_db, skip_pc_local=True) == before  # only this PC's "last backup" time is recorded
    assert SettingsRepo(services.db).get("backup.last_at") == clock.now().isoformat()


def test_a_backup_taken_while_the_app_writes_is_consistent(services: Any, paths: config.Paths, tmp_path: Path) -> None:
    seed(services)
    stop = threading.Event()
    writes = [0]

    def writer() -> None:
        conn = sqlite3.connect(paths.user_db, timeout=5.0, isolation_level=None)
        while not stop.is_set():
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT INTO settings (key, value) VALUES (?, '1')", (f"load.{writes[0]}",))
            conn.execute("COMMIT")
            writes[0] += 1
        conn.close()

    t = threading.Thread(target=writer)
    t.start()
    try:
        for i in range(3):
            target = tmp_path / f"live-{i}.zip"
            make_backup(paths.user_db, target, paths.downloads_dir, "0.16.0", "2026-11-09T12:00:00+00:00")
            new = new_install(tmp_path, f"live-{i}")
            files_for(new).stage_restore(target)  # checks CRC, SHA-256 and integrity
            assert check_db(new.user_restore_db).schema_version == KNOWN
    finally:
        stop.set()
        t.join()
    assert writes[0] > 0


def test_a_backup_holds_no_credential(paths: config.Paths, clock: FixedClock, rng: Any, tmp_path: Path) -> None:
    migrate(paths.user_db, config.MIGRATIONS_DIR / "user", clock)
    secrets = MemorySecretStore()
    placeholders = ["lip_FAKEbackupTokenNeverInAFile0000", "sk-ant-FAKEbackupKeyNeverInAFile0000"]
    secrets.set("lichess", placeholders[0])
    secrets.set("anthropic", placeholders[1])
    kwargs = fake_service_kwargs()
    kwargs["secrets"] = secrets
    services = build_services(paths, clock, JobRunner(), rng, **kwargs)
    try:
        seed(services)
        zip_path = backup_of(services, tmp_path, clock)
    finally:
        services.close()
    blob = zip_path.read_bytes() + zipfile.ZipFile(zip_path).read("user.db")
    for p in placeholders:
        assert p.encode() not in blob
        assert p.encode("utf-16-le") not in blob


# ---- refusals: nothing changes ---------------------------------------------------------------------
def _zip(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return path


def _good(services: Any, tmp_path: Path, clock: FixedClock) -> Path:
    seed(services)
    return backup_of(services, tmp_path, clock)


@pytest.mark.parametrize("kind", ["text", "empty_zip", "no_manifest", "extra_member", "traversal", "truncated",
                                  "sha_mismatch", "newer_schema", "not_sqlite"])  # fmt: skip
def test_bad_files_are_refused_and_nothing_changes(kind: str, services: Any, paths: config.Paths, tmp_path: Path,
                                                    clock: FixedClock) -> None:  # fmt: skip
    good = _good(services, tmp_path, clock)
    zf = zipfile.ZipFile(good)
    manifest, db = zf.read("manifest.json"), zf.read("user.db")
    zf.close()
    bad = tmp_path / f"{kind}.zip"
    if kind == "text":
        bad.write_text("hello", encoding="utf-8")
    elif kind == "empty_zip":
        _zip(bad, {})
    elif kind == "no_manifest":
        _zip(bad, {"user.db": db})
    elif kind == "extra_member":
        _zip(bad, {"manifest.json": manifest, "user.db": db, "notes.txt": b"x"})
    elif kind == "traversal":
        _zip(bad, {"manifest.json": manifest, "user.db": db, "../../evil.db": b"x"})
    elif kind == "truncated":
        bad.write_bytes(good.read_bytes()[: good.stat().st_size // 2])
    elif kind == "sha_mismatch":
        flipped = bytearray(db)
        flipped[-100] ^= 0xFF
        _zip(bad, {"manifest.json": manifest, "user.db": bytes(flipped)})
    elif kind == "newer_schema":
        m = read_manifest(good)
        newer = core.manifest_json(core.Manifest(m.app_version, KNOWN + 1, m.created_at, m.counts, m.db_sha256,
                                                 m.db_size))  # fmt: skip
        _zip(bad, {"manifest.json": newer.encode(), "user.db": db})
    elif kind == "not_sqlite":
        junk = b"j" * len(db)
        m = read_manifest(good)
        import hashlib

        fake = core.manifest_json(core.Manifest(m.app_version, m.schema_version, m.created_at, m.counts,
                                                hashlib.sha256(junk).hexdigest(), len(junk)))  # fmt: skip
        _zip(bad, {"manifest.json": fake.encode(), "user.db": junk})

    services.db.close_all()
    before = paths.user_db.read_bytes()
    runner = JobRunner()
    svc = BackupService(files_for(paths), SettingsRepo(services.db), runner, clock, FakeScheduler(), KNOWN,
                        restart=lambda: pytest.fail("must not restart"))  # fmt: skip
    with pytest.raises(core.BackupError) as e:
        svc.inspect(str(bad))
        job = svc.restore(str(bad))  # inspect passed: the full check in the job must refuse it
        status = runner.wait(job, 30)
        assert status is not None and status.state == "failed"
        assert status.message != "Something went wrong. See the log."  # the reason, not a crash
        raise core.BackupError(status.error_code)  # type: ignore[arg-type]
    expected = {"newer_schema": "newer_backup", "truncated": "not_backup", "text": "not_backup",
                "empty_zip": "not_backup", "no_manifest": "not_backup", "extra_member": "not_backup",
                "traversal": "not_backup"}  # fmt: skip
    assert e.value.code == expected.get(kind, "damaged")
    assert paths.user_db.read_bytes() == before
    assert not paths.user_restore_db.exists() and not paths.user_restore_manifest.exists()
    assert not (tmp_path.parent / "evil.db").exists()


def test_not_enough_disk_space_is_refused(
    services: Any, paths: config.Paths, tmp_path: Path, clock: FixedClock
) -> None:
    good = _good(services, tmp_path, clock)
    files = BackupFiles(paths.user_db, paths.downloads_dir, paths.user_restore_db, paths.user_restore_manifest,
                        "0.16.0", free_bytes=lambda p: 10)  # fmt: skip
    with pytest.raises(NoSpaceError):
        files.stage_restore(good)
    assert not paths.user_restore_db.exists()


# ---- restore ---------------------------------------------------------------------------------------
def test_an_older_schema_backup_is_restored_and_migrated(
    paths: config.Paths, tmp_path: Path, clock: FixedClock
) -> None:
    old_migrations = tmp_path / "m10"
    old_migrations.mkdir()
    for f in sorted((config.MIGRATIONS_DIR / "user").glob("*.sql"))[:10]:
        shutil.copy(f, old_migrations / f.name)
    old_db = tmp_path / "old" / "user.db"
    old_db.parent.mkdir()
    migrate(old_db, old_migrations, clock)
    assert read_version(old_db) == 10
    zip_path = tmp_path / "old.zip"
    make_backup(old_db, zip_path, tmp_path / "work", "0.10.0", clock.now().isoformat())
    assert read_manifest(zip_path).schema_version == 10

    new = new_install(tmp_path)
    files_for(new).stage_restore(zip_path)
    notice = apply_staged_restore(new, clock)
    assert notice is not None and notice.error is None and notice.app_version == "0.10.0"
    assert read_version(new.user_db) == KNOWN


def test_restore_saves_the_current_data_first_and_that_copy_undoes_it(services: Any, paths: config.Paths,
                                                                       tmp_path: Path, clock: FixedClock) -> None:  # fmt: skip
    seed(services)
    zip_path = backup_of(services, tmp_path, clock)
    services.close()
    original = dump(paths.user_db)

    other = new_install(tmp_path, "other")  # a different install with its own, different data
    migrate(other.user_db, config.MIGRATIONS_DIR / "user", clock)
    conn = sqlite3.connect(other.user_db)
    conn.execute("INSERT INTO settings (key, value) VALUES ('mixer.filters', '\"other\"')")
    conn.commit()
    conn.close()
    other_data = dump(other.user_db)

    files_for(other).stage_restore(zip_path)
    notice = apply_staged_restore(other, clock)
    assert notice is not None and notice.error is None
    saved = list(other.backups_dir.glob("before-restore-*.zip"))
    assert len(saved) == 1
    assert dump(other.user_db, True) == {k: v for k, v in original.items()} | {
        "settings": dump(other.user_db, True)["settings"]
    }
    assert dump(other.user_db, True)["settings"] == [r for r in original["settings"] if not core.is_pc_local(r[0])]

    files_for(other).stage_restore(saved[0])  # undo
    clock.advance(seconds=5)
    apply_staged_restore(other, clock)
    assert dump(other.user_db) == other_data


def test_before_restore_copies_keep_only_the_last_five(paths: config.Paths, tmp_path: Path, clock: FixedClock) -> None:
    migrate(paths.user_db, config.MIGRATIONS_DIR / "user", clock)
    zip_path = tmp_path / "b.zip"
    make_backup(paths.user_db, zip_path, paths.downloads_dir, "0.16.0", clock.now().isoformat())
    (paths.backups_dir / "before-restore-notes.txt").write_text("mine", encoding="utf-8")
    for _ in range(7):
        clock.advance(minutes=1)
        files_for(paths).stage_restore(zip_path)
        assert apply_staged_restore(paths, clock).error is None  # type: ignore[union-attr]
    assert len(list(paths.backups_dir.glob("before-restore-*.zip"))) == core.KEEP_BEFORE_RESTORE
    assert (paths.backups_dir / "before-restore-notes.txt").exists()


def test_a_swap_that_fails_partway_puts_the_original_back(
    paths: config.Paths, tmp_path: Path, clock: FixedClock
) -> None:
    migrate(paths.user_db, config.MIGRATIONS_DIR / "user", clock)
    zip_path = tmp_path / "b.zip"
    make_backup(paths.user_db, zip_path, paths.downloads_dir, "0.16.0", clock.now().isoformat())
    conn = sqlite3.connect(paths.user_db)
    conn.execute("INSERT INTO settings (key, value) VALUES ('mixer.filters', '\"original\"')")
    conn.commit()
    conn.close()
    before = dump(paths.user_db)
    files_for(paths).stage_restore(zip_path)

    def boom() -> None:
        raise RuntimeError("migration exploded")

    result = swap_in_staged(paths.user_db, paths.user_restore_db, paths.user_restore_manifest, lambda: None, boom)
    assert result.error is not None and "put back" in result.error and "exploded" not in result.error
    assert dump(paths.user_db) == before
    assert not paths.user_restore_db.exists()


def test_save_aside_failing_means_nothing_is_restored(paths: config.Paths, tmp_path: Path, clock: FixedClock) -> None:
    migrate(paths.user_db, config.MIGRATIONS_DIR / "user", clock)
    zip_path = tmp_path / "b.zip"
    make_backup(paths.user_db, zip_path, paths.downloads_dir, "0.16.0", clock.now().isoformat())
    before = paths.user_db.read_bytes()
    files_for(paths).stage_restore(zip_path)

    def no_room() -> Path:
        raise OSError("disk full")

    result = swap_in_staged(paths.user_db, paths.user_restore_db, paths.user_restore_manifest, no_room, lambda: None)
    assert result.error is not None and result.restored_from is None
    assert paths.user_db.read_bytes() == before


def test_pc_local_settings_keep_this_installs_values(services: Any, tmp_path: Path, clock: FixedClock) -> None:
    seed(services)
    zip_path = backup_of(services, tmp_path, clock)
    new = new_install(tmp_path)
    migrate(new.user_db, config.MIGRATIONS_DIR / "user", clock)
    conn = sqlite3.connect(new.user_db)
    conn.executemany("INSERT INTO settings (key, value) VALUES (?, ?)", [
        ("puzzle_db.last_check", '"this-pc"'), ("backup.auto", '{"enabled": false}'),
        ("lichess.account", '{"id": "player_a", "username": "player_a"}'),
    ])  # fmt: skip
    conn.commit()
    conn.close()
    files_for(new).stage_restore(zip_path)
    apply_staged_restore(new, clock)
    settings = dict(dump(new.user_db)["settings"])
    assert settings["puzzle_db.last_check"] == '"this-pc"'
    assert settings["backup.auto"] == '{"enabled": false}'
    assert "player_a" in settings["lichess.account"]
    assert settings["mixer.filters"] == '{"seeded": true}'  # your data did come across


def test_restore_is_refused_while_a_job_runs(services: Any, tmp_path: Path, clock: FixedClock) -> None:
    good = _good(services, tmp_path, clock)
    runner = services.backup._runner
    release = threading.Event()
    job = runner.submit("game_analysis", lambda progress, token: release.wait(10))
    try:
        with pytest.raises(ConflictError) as e:
            services.backup.restore(str(good))
        assert "game analysis" in e.value.message
    finally:
        release.set()
        runner.wait(job, 10)


def test_restore_stages_then_restarts(paths: config.Paths, tmp_path: Path, clock: FixedClock, services: Any) -> None:
    good = _good(services, tmp_path, clock)
    restarted = threading.Event()
    runner = JobRunner()
    svc = BackupService(files_for(paths), SettingsRepo(services.db), runner, clock, FakeScheduler(), KNOWN,
                        restart=restarted.set)  # fmt: skip
    status = runner.wait(svc.restore(str(good)), 30)
    assert status is not None and status.state == "done"
    assert restarted.is_set()
    assert paths.user_restore_db.exists() and paths.user_restore_manifest.exists()


# ---- the bridge -------------------------------------------------------------------------------------
def test_bridge_restore_needs_the_token_from_the_open_dialog(
    paths: config.Paths, tmp_path: Path, clock: FixedClock
) -> None:
    migrate(paths.user_db, config.MIGRATIONS_DIR / "user", clock)
    api = build_api(paths, clock)
    zip_path = tmp_path / "b.zip"
    make_backup(paths.user_db, zip_path, paths.downloads_dir, "0.16.0", clock.now().isoformat())
    assert api.restore_backup("made-up")["error"]["code"] == "invalid_argument"
    api._desktop.next_file = str(zip_path)  # type: ignore[attr-defined]
    info = api.choose_backup_to_restore()["data"]
    assert info["games"] == 0 and info["schema_version"] == KNOWN
    assert api.restore_backup("wrong-token")["error"]["code"] == "invalid_argument"
    api._desktop.next_file = str(tmp_path)  # type: ignore[attr-defined]
    refused = api.choose_backup_to_restore()
    assert refused["ok"] is False and refused["error"]["code"] == "not_backup"
    assert str(tmp_path) not in refused["error"]["message"]  # NFR-5: no paths in messages


def test_bridge_backup_now_suggests_the_dated_name_and_cancel_does_nothing(
    paths: config.Paths, clock: FixedClock
) -> None:
    migrate(paths.user_db, config.MIGRATIONS_DIR / "user", clock)
    api = build_api(paths, clock)
    assert api.backup_now()["data"] is None
    assert api._desktop.suggested_name.startswith("weaksquare-backup-")  # type: ignore[attr-defined]


def test_bridge_backup_settings_need_an_absolute_folder(paths: config.Paths, clock: FixedClock) -> None:
    migrate(paths.user_db, config.MIGRATIONS_DIR / "user", clock)
    api = build_api(paths, clock)
    assert api.set_backup_settings(True, "relative\\folder", 7, 5)["error"]["code"] == "invalid_argument"
    assert api.get_backup_status()["data"]["settings"]["enabled"] is False


# ---- automatic backups (FR-15.3) --------------------------------------------------------------------
def auto_service(
    paths: config.Paths, clock: FixedClock, services: Any
) -> tuple[BackupService, FakeScheduler, JobRunner]:
    sched = FakeScheduler()
    runner = JobRunner()
    svc = BackupService(files_for(paths), SettingsRepo(services.db), runner, clock, sched, KNOWN, restart=lambda: None)
    return svc, sched, runner


def _drain(runner: JobRunner) -> None:
    for s in runner.active():
        runner.wait(s.id, 30)


def test_automatic_backups_are_off_by_default(services: Any, paths: config.Paths, clock: FixedClock) -> None:
    svc, sched, runner = auto_service(paths, clock, services)
    svc.start()
    assert svc.status().auto == core.AutoSettings() and not runner.active() and not sched.pending


def test_automatic_backup_runs_when_due_and_keeps_only_n(services: Any, paths: config.Paths, tmp_path: Path,
                                                          clock: FixedClock) -> None:  # fmt: skip
    folder = tmp_path / "auto"
    folder.mkdir()
    (folder / "holiday.zip").write_bytes(b"not ours")
    (folder / "weaksquare-backup-2020-01-01.zip").write_bytes(b"named like ours, but not a backup")
    svc, sched, runner = auto_service(paths, clock, services)
    svc.set_auto_settings(True, str(folder), 7, 2)
    for _ in range(4):
        sched.run_next()  # the timer fires
        _drain(runner)
        assert svc.status().last_error is None
        clock.advance(days=7)
    ours = sorted(p.name for p in folder.glob("weaksquare-backup-*.zip") if core.is_auto_name(p.name))
    real = [n for n in ours if n != "weaksquare-backup-2020-01-01.zip"]
    assert len(real) == 2
    assert (folder / "holiday.zip").exists() and (folder / "weaksquare-backup-2020-01-01.zip").exists()


def test_an_automatic_backup_that_came_due_while_closed_runs_at_launch(services: Any, paths: config.Paths,
                                                                        tmp_path: Path, clock: FixedClock) -> None:  # fmt: skip
    folder = tmp_path / "auto"
    folder.mkdir()
    svc, sched, runner = auto_service(paths, clock, services)
    svc.set_auto_settings(True, str(folder), 7, 5)
    sched.run_next()
    _drain(runner)
    assert len(list(folder.iterdir())) == 1

    clock.advance(days=3)  # not due yet: the launch check does nothing, and the timer waits at most an hour
    svc2, sched2, runner2 = auto_service(paths, clock, services)
    svc2.start()
    assert not runner2.active() and sched2.delays == [core.RECHECK_S]

    clock.advance(days=5)  # the app was closed past the due date
    svc3, _sched3, runner3 = auto_service(paths, clock, services)
    svc3.start()
    _drain(runner3)
    assert len(list(folder.iterdir())) == 2


def test_a_missing_folder_is_reported_and_retried(services: Any, paths: config.Paths, tmp_path: Path,
                                                  clock: FixedClock) -> None:  # fmt: skip
    folder = tmp_path / "usb"
    folder.mkdir()
    svc, sched, runner = auto_service(paths, clock, services)
    svc.set_auto_settings(True, str(folder), 7, 5)
    folder.rmdir()  # the drive was unplugged
    sched.run_next()
    _drain(runner)
    assert svc.status().last_error == FOLDER_MISSING
    assert sched.pending  # it tries again
    folder.mkdir()
    clock.advance(hours=1)
    sched.run_next()
    _drain(runner)
    assert svc.status().last_error is None and len(list(folder.iterdir())) == 1


def test_changing_the_settings_replaces_the_timer(services: Any, paths: config.Paths, tmp_path: Path,
                                                  clock: FixedClock) -> None:  # fmt: skip
    folder = tmp_path / "auto"
    folder.mkdir()
    svc, sched, runner = auto_service(paths, clock, services)
    svc.set_auto_settings(True, str(folder), 7, 5)
    svc.set_auto_settings(False, str(folder), 7, 5)
    while sched.pending:
        sched.run_next()  # the first timer is stale; the second sees them off
    _drain(runner)
    assert not list(folder.iterdir())


def test_backup_now_refuses_a_missing_folder_and_a_second_backup(services: Any, tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        services.backup.backup_now(str(tmp_path / "nope" / "b.zip"))
    with pytest.raises(ValidationError):
        services.backup.backup_now("  ")
    job = services.backup.backup_now(str(tmp_path / "b"))  # .zip is added
    services.backup._runner.wait(job, 30)
    assert (tmp_path / "b.zip").exists()


def test_the_restarted_app_keeps_its_data_folder_and_front_end() -> None:
    from weaksquare.app import after_restore_args, parse_args

    assert after_restore_args(parse_args([])) == ["--after-restore"]
    assert after_restore_args(parse_args(["--dev"])) == ["--dev", "--after-restore"]
    assert after_restore_args(parse_args(["--dev-server"])) == ["--dev-server", "--after-restore"]
    assert parse_args(["--after-restore"]).after_restore is True


# ---- v0.16 fix loop: regression tests ------------------------------------------------------------------------
def test_b5_a_swap_cut_off_between_the_renames_puts_the_original_back(paths: config.Paths, tmp_path: Path,
                                                                      clock: FixedClock) -> None:  # fmt: skip
    """v0.16-B5: a power cut after user.db was moved aside but before the backup took its place leaves no user.db.
    The next start puts the original back instead of starting empty (and instead of deleting the .replaced copy)."""
    migrate(paths.user_db, config.MIGRATIONS_DIR / "user", clock)
    set_raw(paths.user_db, "mixer.filters", '"original"')
    before = dump(paths.user_db)
    paths.user_db.replace(paths.user_db.with_name("user.db.replaced"))
    assert apply_staged_restore(paths, clock) is None
    assert dump(paths.user_db) == before
    assert not paths.user_db.with_name("user.db.replaced").exists()


def test_b2_an_incomplete_staging_changes_nothing_and_says_so(paths: config.Paths, tmp_path: Path,
                                                             clock: FixedClock) -> None:  # fmt: skip
    """v0.16-B2: user.restore.db without its manifest (the job was cut off) is never swapped in."""
    migrate(paths.user_db, config.MIGRATIONS_DIR / "user", clock)
    before = dump(paths.user_db)
    shutil.copyfile(paths.user_db, paths.user_restore_db)
    notice = apply_staged_restore(paths, clock)
    assert notice is not None and notice.error is not None and "nothing was changed" in notice.error
    assert dump(paths.user_db) == before
    assert not paths.user_restore_db.exists()
    assert not list(paths.backups_dir.glob("before-restore-*.zip"))


@pytest.mark.parametrize("folder", ["C#dev", "100%41 sure", "a&b=c mode=rw"])
def test_b7_the_puzzle_db_opens_read_only_in_a_folder_with_uri_characters(tmp_path: Path, folder: str,
                                                                          clock: FixedClock) -> None:  # fmt: skip
    """v0.16-B7: readonly_uri percent-encodes the path; it's also how puzzles.db is attached at every start."""
    from weaksquare.adapters.db.connection import readonly_uri

    d = tmp_path / folder
    d.mkdir()
    db = d / "user.db"
    migrate(db, config.MIGRATIONS_DIR / "user", clock)
    conn = sqlite3.connect(readonly_uri(db), uri=True)
    try:
        assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == KNOWN
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("CREATE TABLE nope (x)")  # still read-only
    finally:
        conn.close()
    assert check_db(db).schema_version == KNOWN


def set_raw(db: Path, key: str, value: str) -> None:
    conn = sqlite3.connect(db)
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()
