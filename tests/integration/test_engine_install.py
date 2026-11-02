"""services/engine_install.py against a local fake download (FR-7.5, SR-6; v0.4 Done when).

The real HttpClient, hashing and zip code run; only the network (httpx.MockTransport) and the engine
smoke test (a fake probe) are replaced.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest

from weaksquare.adapters.files import extract_member, sha256_file, zip_names
from weaksquare.adapters.http import HttpClient
from weaksquare.core.clock import FixedClock
from weaksquare.core.engine import EngineError, EngineInfo, InstallError, UnsupportedPlatform, parse_manifest
from weaksquare.jobs.runner import CancelToken, JobCancelled, JobFailed
from weaksquare.services.engine_install import EngineInstaller, InstallDeps, run_install

EXE_MEMBER = "stockfish/stockfish-windows-x86-64-universal.exe"
URL = "https://github.com/official-stockfish/Stockfish/releases/download/sf_19/sf.zip"


def make_zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


GOOD_ZIP = make_zip({"stockfish/": b"", EXE_MEMBER: b"MZ fake stockfish", "stockfish/Copying.txt": b"GPL"})


class Server:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.requests = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests += 1
        assert str(request.url) == URL
        return httpx.Response(200, content=self.body, headers={"content-length": str(len(self.body))})


class Probe:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[str] = []

    def __call__(self, exe_path: str) -> EngineInfo:
        self.calls.append(exe_path)
        assert Path(exe_path).read_bytes() == b"MZ fake stockfish"
        if self.fail:
            raise EngineError("uci did not answer uciok")
        return EngineInfo("Stockfish 19")


def manifest(sha: str, platform: str = "windows-x86_64"):
    return parse_manifest(
        {
            "engines": {
                "stockfish": {
                    "tag": "sf_19",
                    "assets": {
                        platform: {"name": "sf.zip", "url": URL, "sha256": sha, "size": 100, "exe_member": EXE_MEMBER}
                    },
                }
            }
        }
    )


def build(
    tmp_path: Path,
    body: bytes = GOOD_ZIP,
    *,
    sha: str | None = None,
    probe: Probe | None = None,
    platform: str = "windows-x86_64",
) -> tuple[EngineInstaller, Server, Probe]:
    server = Server(body)
    probe = probe or Probe()
    http = HttpClient(transport=httpx.MockTransport(server.handler), retries=0, sleep=lambda s: None)
    deps = InstallDeps(
        http=http,
        manifest=manifest(sha or hashlib.sha256(body).hexdigest()),
        platform=platform,
        engines_dir=tmp_path / "engines",
        downloads_dir=tmp_path / "downloads",
        sha256=sha256_file,
        zip_names=zip_names,
        extract=extract_member,
        probe=probe,
        clock=FixedClock(),
    )
    return EngineInstaller(deps), server, probe


def noop(fraction: float | None, message: str) -> None:
    pass


def leftovers(tmp_path: Path) -> list[str]:
    """Everything on disk except a completed engines/sf_19 install."""
    out = [p.name for p in (tmp_path / "downloads").glob("*")] if (tmp_path / "downloads").exists() else []
    if (tmp_path / "engines").exists():
        out += [p.name for p in (tmp_path / "engines").iterdir() if p.name != "sf_19"]
    return out


def test_clean_install(tmp_path: Path) -> None:
    inst, _server, probe = build(tmp_path)
    assert inst.installed() is None
    assert inst.install(noop, CancelToken()) == "installed"
    exe = tmp_path / "engines" / "sf_19" / "stockfish.exe"
    assert exe.read_bytes() == b"MZ fake stockfish"
    assert not (tmp_path / "engines" / "sf_19" / "Copying.txt").exists()  # only the exe is extracted
    marker = json.loads((tmp_path / "engines" / "sf_19" / "install.json").read_text())
    assert marker["tag"] == "sf_19" and marker["name"] == "Stockfish 19"
    assert marker["installed_at"].startswith("2026-01-01T12:00:00")
    assert inst.installed() is not None and inst.installed().exe == exe  # type: ignore[union-attr]
    assert leftovers(tmp_path) == []  # the zip is deleted, no temp folder remains
    assert len(probe.calls) == 1


def test_hash_mismatch_refuses_and_leaves_nothing_behind(tmp_path: Path) -> None:
    inst, _, probe = build(tmp_path, sha="0" * 64)
    with pytest.raises(InstallError) as e:
        inst.install(noop, CancelToken())
    assert getattr(e.value, "code", None) == "checksum_mismatch"
    assert not (tmp_path / "engines" / "sf_19").exists()
    assert leftovers(tmp_path) == []
    assert probe.calls == []  # never extracted, never run


@pytest.mark.parametrize("evil", ["../evil.exe", "stockfish/../../evil.exe", "/abs/evil.exe", "C:/evil.exe"])
def test_zip_with_unsafe_paths_is_rejected(tmp_path: Path, evil: str) -> None:
    body = make_zip({EXE_MEMBER: b"MZ fake stockfish", evil: b"pwned"})
    inst, _, probe = build(tmp_path, body)
    with pytest.raises(InstallError) as e:
        inst.install(noop, CancelToken())
    assert getattr(e.value, "code", None) == "unsafe_archive"
    assert not (tmp_path / "engines" / "sf_19").exists()
    assert leftovers(tmp_path) == []
    assert not any(p.name == "evil.exe" for p in tmp_path.rglob("*"))
    assert probe.calls == []


def test_second_run_does_nothing(tmp_path: Path) -> None:
    inst, server, probe = build(tmp_path)
    inst.install(noop, CancelToken())
    before = (tmp_path / "engines" / "sf_19" / "install.json").stat().st_mtime_ns
    assert inst.install(noop, CancelToken()) == "already_installed"
    assert server.requests == 1 and len(probe.calls) == 1
    assert (tmp_path / "engines" / "sf_19" / "install.json").stat().st_mtime_ns == before


def test_force_reinstalls(tmp_path: Path) -> None:
    inst, server, _ = build(tmp_path)
    inst.install(noop, CancelToken())
    assert inst.install(noop, CancelToken(), force=True) == "installed"
    assert server.requests == 2
    assert leftovers(tmp_path) == []  # the old install folder is gone too


def test_a_tampered_exe_is_reinstalled(tmp_path: Path) -> None:
    inst, server, _ = build(tmp_path)
    inst.install(noop, CancelToken())
    (tmp_path / "engines" / "sf_19" / "stockfish.exe").write_bytes(b"MZ something else")
    assert inst.install(noop, CancelToken()) == "installed"
    assert server.requests == 2


def test_smoke_test_failure_removes_the_install(tmp_path: Path) -> None:
    inst, _, _ = build(tmp_path, probe=Probe(fail=True))
    with pytest.raises(InstallError) as e:
        inst.install(noop, CancelToken())
    assert getattr(e.value, "code", None) == "smoke_test_failed"
    assert not (tmp_path / "engines" / "sf_19").exists()
    assert leftovers(tmp_path) == []


def test_failed_force_reinstall_keeps_the_working_install(tmp_path: Path) -> None:
    inst, _, probe = build(tmp_path)
    inst.install(noop, CancelToken())
    probe.fail = True
    with pytest.raises(InstallError):
        inst.install(noop, CancelToken(), force=True)
    assert inst.installed() is not None
    assert leftovers(tmp_path) == []


def test_not_a_zip(tmp_path: Path) -> None:
    inst, _, _ = build(tmp_path, b"<html>not a zip</html>")
    with pytest.raises(InstallError) as e:
        inst.install(noop, CancelToken())
    assert getattr(e.value, "code", None) == "unexpected_archive"
    assert leftovers(tmp_path) == []


def test_cancel_cleans_up(tmp_path: Path) -> None:
    inst, _, _ = build(tmp_path)
    token = CancelToken()

    def progress(fraction: float | None, message: str) -> None:
        if message.startswith("Verifying"):
            token.cancel()

    with pytest.raises(JobCancelled):
        inst.install(progress, token)
    assert not (tmp_path / "engines" / "sf_19").exists()
    assert leftovers(tmp_path) == []


def test_unsupported_platform_refuses_before_downloading(tmp_path: Path) -> None:
    inst, server, _ = build(tmp_path, platform="linux-x86_64")
    with pytest.raises(UnsupportedPlatform):
        inst.install(noop, CancelToken())
    assert server.requests == 0


def test_run_install_turns_errors_into_failed_jobs(tmp_path: Path) -> None:
    inst, _, _ = build(tmp_path, sha="0" * 64)
    with pytest.raises(JobFailed) as e:
        run_install(inst, noop, CancelToken())
    assert e.value.code == "checksum_mismatch"
    inst2, _, _ = build(tmp_path / "x")
    assert run_install(inst2, noop, CancelToken()) == "Stockfish is installed."
    assert run_install(inst2, noop, CancelToken()) == "Stockfish is already installed."


def test_sha256_file_matches_hashlib(tmp_path: Path) -> None:
    f = tmp_path / "f.bin"
    f.write_bytes(GOOD_ZIP)
    assert sha256_file(f) == hashlib.sha256(GOOD_ZIP).hexdigest()


def test_rename_with_retry_survives_a_briefly_locked_folder(tmp_path: Path, monkeypatch) -> None:
    """Regression (v0.4 build): right after the self-test, Windows briefly denied the rename of the new
    engine folder (Defender scanning the fresh exe). The install now retries for a few seconds."""
    from weaksquare.adapters import files

    monkeypatch.setattr(files.time, "sleep", lambda s: None)
    src, dst = tmp_path / "a", tmp_path / "b"
    src.mkdir()
    real_rename = Path.rename
    fails = [3]

    def flaky(self: Path, target: Path) -> Path:
        if fails[0]:
            fails[0] -= 1
            raise PermissionError(13, "Access is denied")
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", flaky)
    files.rename_with_retry(src, dst)
    assert dst.is_dir() and not src.exists()


def test_a_persistently_locked_folder_fails_cleanly(tmp_path: Path) -> None:
    inst, _, _ = build(tmp_path)

    def locked(src: Path, dst: Path) -> None:
        raise PermissionError(13, "Access is denied")

    inst._d = InstallDeps(**{**inst._d.__dict__, "rename": locked})
    with pytest.raises(InstallError) as e:
        inst.install(noop, CancelToken())
    assert getattr(e.value, "code", None) == "engine_in_use"
    assert not (tmp_path / "engines" / "sf_19").exists()
    assert leftovers(tmp_path) == []
