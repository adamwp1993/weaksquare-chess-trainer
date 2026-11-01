"""FR-2.1–2.3: import into a new file and swap; a cancelled or failed import leaves puzzles.db working."""

from __future__ import annotations

import csv
import dataclasses
import hashlib
import threading
from pathlib import Path
from typing import ClassVar

import httpx
import pytest
import zstandard

from tests.helpers import FIXTURE_CSV, FakeHttp, fixture_rows
from weaksquare.adapters.db.repos import puzzle_import
from weaksquare.adapters.http import HttpClient
from weaksquare.app import Services, build_services
from weaksquare.config import Paths
from weaksquare.core.clock import FixedClock
from weaksquare.jobs.runner import JobRunner
from weaksquare.services import puzzle_db


@pytest.fixture
def zst_file(tmp_path: Path) -> Path:
    out = tmp_path / "lichess_db_puzzle.csv.zst"
    out.write_bytes(zstandard.ZstdCompressor(write_checksum=True).compress(FIXTURE_CSV.read_bytes()))
    return out


@pytest.fixture
def runner() -> JobRunner:
    return JobRunner()


def make(paths: Paths, clock: FixedClock, runner: JobRunner, http: object | None = None) -> Services:
    from weaksquare.adapters.db.migrate import migrate
    from weaksquare.config import MIGRATIONS_DIR

    migrate(paths.user_db, MIGRATIONS_DIR / "user", clock)
    return build_services(paths, clock, runner, http=http)  # type: ignore[arg-type]


def run_import(services: Services, runner: JobRunner, local: Path | None = None) -> str:
    job = services.puzzle_db.start_import(str(local) if local else None)
    status = runner.wait(job, 60)
    assert status is not None
    return status.state


def count(services: Services) -> int:
    with services.db.session() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM pz.puzzles").fetchone()[0])


def test_import_local_zst(paths: Paths, clock: FixedClock, runner: JobRunner, zst_file: Path) -> None:
    s = make(paths, clock, runner)
    assert not s.puzzle_db.status().installed
    assert run_import(s, runner, zst_file) == "done"
    st = s.puzzle_db.status()
    assert st.installed and st.puzzle_count == len(fixture_rows()) == count(s)
    assert st.rating_min is not None and st.rating_max is not None and st.rating_min < st.rating_max
    assert not paths.puzzles_new_db.exists()
    with s.db.session() as conn:
        row = conn.execute("SELECT * FROM pz.puzzles WHERE id = '001KR'").fetchone()
        assert row["player_color"] == 0 and row["length"] == 1
        assert conn.execute("SELECT COUNT(*) FROM pz.theme_bits").fetchone()[0] > 30
    s.close()


def test_reads_by_header_name_with_extra_columns(
    paths: Paths, clock: FixedClock, runner: JobRunner, tmp_path: Path
) -> None:
    rows = fixture_rows()
    header = ["Extra", *reversed(list(rows[0].keys()))]
    out = tmp_path / "shuffled.csv"
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in rows:
            w.writerow(["junk" if h == "Extra" else r[h] for h in header])
    s = make(paths, clock, runner)
    assert run_import(s, runner, out) == "done"
    assert count(s) == len(rows)
    s.close()


def test_download_verifies_checksum_and_records_export_date(
    paths: Paths, clock: FixedClock, runner: JobRunner, zst_file: Path
) -> None:
    http = FakeHttp(zst_file, sha256=hashlib.sha256(zst_file.read_bytes()).hexdigest())
    s = make(paths, clock, runner, http)
    assert run_import(s, runner) == "done"
    st = s.puzzle_db.status()
    assert st.puzzle_count == len(fixture_rows())
    assert st.export_date == "2026-10-02"
    assert not (paths.downloads_dir / "lichess_db_puzzle.csv.zst").exists()  # cleaned up after success
    s.close()


def test_checksum_mismatch_refuses_and_deletes(
    paths: Paths, clock: FixedClock, runner: JobRunner, zst_file: Path
) -> None:
    s = make(paths, clock, runner, FakeHttp(zst_file, sha256="0" * 64))
    job = s.puzzle_db.start_import(None)
    st = runner.wait(job, 30)
    assert st is not None and (st.state, st.error_code) == ("failed", "checksum_mismatch")
    assert not (paths.downloads_dir / "lichess_db_puzzle.csv.zst").exists()
    assert not s.puzzle_db.status().installed
    s.close()


class CancelAfterFirstBatch(puzzle_import.PuzzleDbWriter):
    """Cancels the running job as soon as one batch has been written."""

    runner: JobRunner
    job: ClassVar[list[str]] = []

    def add(self, rows):  # type: ignore[no-untyped-def]
        super().add(rows)
        self.runner.cancel(self.job[0])


def test_cancel_midway_keeps_existing_db(
    paths: Paths, clock: FixedClock, runner: JobRunner, zst_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = make(paths, clock, runner)
    assert run_import(s, runner, zst_file) == "done"
    before = count(s)

    # Second import: small batches, cancelled after the first one.
    monkeypatch.setattr(puzzle_db, "BATCH", 50)
    started = threading.Event()
    CancelAfterFirstBatch.runner = runner
    CancelAfterFirstBatch.job = []
    s2 = make(paths, clock, runner)
    s2.puzzle_db._d = dataclasses.replace(s2.puzzle_db._d, make_writer=lambda p: CancelAfterFirstBatch(p, clock))
    gate = threading.Lock()
    gate.acquire()

    def go(progress, token):  # type: ignore[no-untyped-def]
        started.set()
        with gate:
            s2.puzzle_db.run(progress, token, zst_file)

    job = runner.submit(puzzle_db.JOB_KIND, go)
    CancelAfterFirstBatch.job.append(job)
    started.wait(5)
    gate.release()
    st = runner.wait(job, 30)
    assert st is not None and st.state == "cancelled"

    assert not paths.puzzles_new_db.exists()
    assert count(s) == before  # the old database still answers queries
    assert s.puzzle_db.status().puzzle_count == before
    # Restarting simply starts over and works.
    assert run_import(s, runner, zst_file) == "done"
    assert count(s) == before
    s.close()
    s2.close()


def test_failed_integrity_keeps_existing_db(
    paths: Paths, clock: FixedClock, runner: JobRunner, zst_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = make(paths, clock, runner)
    assert run_import(s, runner, zst_file) == "done"
    before_bytes = paths.puzzles_db.read_bytes()

    def broken_finish(self, meta):  # type: ignore[no-untyped-def]
        raise puzzle_import.IntegrityError("integrity check failed: simulated")

    monkeypatch.setattr(puzzle_import.PuzzleDbWriter, "finish", broken_finish)
    assert run_import(s, runner, zst_file) == "failed"
    assert not paths.puzzles_new_db.exists()
    assert paths.puzzles_db.read_bytes() == before_bytes
    assert count(s) == len(fixture_rows())
    s.close()


def test_bad_file_is_rejected(paths: Paths, clock: FixedClock, runner: JobRunner, tmp_path: Path) -> None:
    bad = tmp_path / "not_puzzles.csv"
    bad.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    s = make(paths, clock, runner)
    job = s.puzzle_db.start_import(str(bad))
    st = runner.wait(job, 30)
    assert st is not None and (st.state, st.error_code) == ("failed", "bad_file")
    corrupt = tmp_path / "corrupt.csv.zst"
    corrupt.write_bytes(b"\x28\xb5\x2f\xfd" + b"garbage" * 100)
    st = runner.wait(s.puzzle_db.start_import(str(corrupt)), 30)
    assert st is not None and (st.state, st.error_code) == ("failed", "bad_file")
    assert not s.puzzle_db.status().installed
    s.close()


def test_swap_with_open_connections_on_other_threads(
    paths: Paths, clock: FixedClock, runner: JobRunner, zst_file: Path, tmp_path: Path
) -> None:
    s = make(paths, clock, runner)
    small = tmp_path / "small.csv"
    rows = fixture_rows()[:10]
    with small.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    assert run_import(s, runner, small) == "done"

    # Other threads hold idle connections with the old puzzles.db attached.
    seen: dict[str, int] = {}
    go_again = threading.Event()

    def reader(name: str) -> None:
        seen[name + "-before"] = count(s)
        go_again.wait(30)
        seen[name + "-after"] = count(s)

    threads = [threading.Thread(target=reader, args=(f"t{i}",)) for i in range(3)]
    for t in threads:
        t.start()
    while len(seen) < 3:
        threading.Event().wait(0.01)
    assert run_import(s, runner, zst_file) == "done"  # os.replace would fail on Windows with open handles
    go_again.set()
    for t in threads:
        t.join()
    assert all(seen[f"t{i}-before"] == 10 for i in range(3))
    assert all(seen[f"t{i}-after"] == len(fixture_rows()) for i in range(3))
    s.close()


def test_second_import_while_running_conflicts(
    paths: Paths, clock: FixedClock, runner: JobRunner, zst_file: Path
) -> None:
    from weaksquare.core.errors import ConflictError

    s = make(paths, clock, runner)
    hold = threading.Event()
    runner.submit(puzzle_db.JOB_KIND, lambda p, t: hold.wait(10))
    with pytest.raises(ConflictError):
        s.puzzle_db.start_import(str(zst_file))
    hold.set()
    s.close()


def test_download_resumes_with_range(tmp_path: Path) -> None:
    payload = bytes(range(256)) * 4000
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        rng = request.headers.get("range")
        if rng is None:
            # First attempt: the connection drops halfway through.
            return httpx.Response(200, headers={"etag": '"v1"', "content-length": str(len(payload))},
                                  stream=_Broken(payload[: len(payload) // 2]))  # fmt: skip
        start = int(rng.split("=")[1].rstrip("-"))
        assert request.headers.get("if-range") == '"v1"'
        return httpx.Response(
            206,
            headers={"etag": '"v1"', "content-length": str(len(payload) - start), "last-modified": "Fri, 02 Oct 2026 08:51:45 GMT"},
            content=payload[start:],
        )  # fmt: skip

    http = HttpClient(transport=httpx.MockTransport(handler), sleep=lambda s: None)
    result = http.download("https://example.invalid/f.zst", tmp_path / "f.zst")
    assert (tmp_path / "f.zst").read_bytes() == payload
    assert result.last_modified == "2026-10-02"
    ranges = [r.headers.get("range") for r in requests]
    assert len(ranges) == 2 and ranges[0] is None
    resumed_from = int(ranges[1].split("=")[1].rstrip("-"))
    assert 0 < resumed_from <= len(payload) // 2  # resumed from what had reached the disk
    assert not (tmp_path / "f.zst.part").exists()


class _Broken(httpx.SyncByteStream):
    def __init__(self, data: bytes) -> None:
        self._data = data

    def __iter__(self):  # type: ignore[no-untyped-def]
        yield self._data
        raise httpx.ReadError("connection reset")
