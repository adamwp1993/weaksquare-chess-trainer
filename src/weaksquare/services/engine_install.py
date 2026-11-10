"""The one Stockfish installer (FR-7.5): used by scripts/fetch_stockfish.py, scripts/setup.py and the
in-app Install button (and the first-run wizard's Stockfish step, v1.0).

1. Pinned: the manifest names the release, the asset, its URL and GitHub's SHA-256. Never "latest".
2. Download through the shared HTTP client, then verify the SHA-256 *before* opening the archive.
   A mismatch deletes the file and stops.
3. Refuse the whole archive if any entry is absolute or has a `..` part; extract only the expected .exe.
4. Install into a temp folder, smoke-test the engine there, then rename the folder into place, so a
   failed install leaves nothing half-written. The download is always deleted afterwards.
5. Idempotent: an install that already matches the manifest (and whose exe still has the recorded
   hash) is left alone. `force` reinstalls.
"""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from weaksquare.core.clock import Clock
from weaksquare.core.engine import (
    EngineError,
    EngineManifest,
    EngineProbe,
    InstallError,
    ManifestAsset,
    check_zip_names,
)
from weaksquare.jobs.runner import CancelToken, JobCancelled, JobFailed, ProgressFn

log = logging.getLogger(__name__)

EXE_NAME = "stockfish.exe"
MARKER = "install.json"


class Downloader(Protocol):
    def download(
        self,
        url: str,
        dest: Path,
        *,
        progress: Callable[[int, int | None], None] | None = None,
        cancelled: Callable[[], bool] = ...,
    ) -> Any: ...


@dataclass(frozen=True)
class InstallDeps:
    http: Downloader | None  # None: read-only use (status, the log banner)
    manifest: EngineManifest
    platform: str  # core.engine.platform_key(...)
    engines_dir: Path
    downloads_dir: Path
    sha256: Callable[[Path, Callable[[], bool]], str]
    zip_names: Callable[[Path], list[str]]
    extract: Callable[[Path, str, Path], None]  # (zip, member, dest file)
    probe: EngineProbe
    clock: Clock
    rename: Callable[[Path, Path], object] = Path.rename  # the app passes files.rename_with_retry


@dataclass(frozen=True)
class InstalledEngine:
    tag: str
    exe: Path
    name: str  # the engine's `id name`, e.g. "Stockfish 19"
    asset_sha256: str
    exe_sha256: str


InstallResult = Literal["installed", "already_installed"]


class EngineInstaller:
    def __init__(self, deps: InstallDeps) -> None:
        self._d = deps

    @property
    def tag(self) -> str:
        return self._d.manifest.tag

    @property
    def target_dir(self) -> Path:
        return self._d.engines_dir / self._d.manifest.tag

    def asset(self) -> ManifestAsset:
        return self._d.manifest.asset_for(self._d.platform)  # UnsupportedPlatform elsewhere

    def installed(self) -> InstalledEngine | None:
        """The managed install, if one matches the manifest (cheap: no hashing)."""
        marker = self.target_dir / MARKER
        exe = self.target_dir / EXE_NAME
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
            asset = self.asset()
        except Exception:
            return None
        if data.get("tag") != self.tag or data.get("asset_sha256") != asset.sha256 or not exe.is_file():
            return None
        return InstalledEngine(self.tag, exe, str(data.get("name", "Stockfish")), asset.sha256, str(data["exe_sha256"]))

    def describe(self) -> str:
        """For the log banner (NFR-4): "Stockfish 19 (sf_19, managed)" or "not installed (sf_19 pinned)"."""
        current = self.installed()
        if current is None:
            return f"not installed ({self.tag} pinned)"
        return f"{current.name} ({self.tag}, managed)"

    def _is_current(self) -> bool:
        current = self.installed()
        if current is None:
            return False
        try:
            return self._d.sha256(current.exe, lambda: False) == current.exe_sha256
        except OSError:
            return False

    def install(self, progress: ProgressFn, token: CancelToken, force: bool = False) -> InstallResult:
        d = self._d
        asset = self.asset()
        if not force and self._is_current():
            log.info("Stockfish %s is already installed; nothing to do", self.tag)
            return "already_installed"

        d.engines_dir.mkdir(parents=True, exist_ok=True)
        d.downloads_dir.mkdir(parents=True, exist_ok=True)
        zip_path = d.downloads_dir / asset.name
        leftovers = [
            zip_path,
            zip_path.with_name(zip_path.name + ".part"),
            zip_path.with_name(zip_path.name + ".part.json"),
        ]
        for f in leftovers:
            f.unlink(missing_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix=f".{self.tag}.tmp-", dir=d.engines_dir))
        try:
            self._download(asset, zip_path, progress, token)
            progress(0.88, "Verifying the download…")
            actual = self._hash(zip_path, token)
            if actual != asset.sha256:
                log.warning("Stockfish download hash mismatch (expected %s, got %s)", asset.sha256, actual)
                raise InstallError(
                    "The downloaded Stockfish doesn't match the pinned checksum, so it was deleted and nothing "
                    "was installed. Try again later.",
                    code="checksum_mismatch",
                )
            member = check_zip_names(self._names(zip_path), asset.exe_member)
            exe = tmp / EXE_NAME
            progress(0.92, "Extracting Stockfish…")
            try:
                d.extract(zip_path, member, exe)
            except Exception as e:
                raise InstallError(f"Couldn't extract Stockfish ({e}).", code="extract_failed") from None
            token.raise_if_cancelled()
            progress(0.95, "Testing Stockfish…")
            try:
                info = d.probe(str(exe))
            except EngineError as e:
                raise InstallError(
                    f"The installed Stockfish didn't pass its self-test, so it was removed. ({e.message})",
                    code="smoke_test_failed",
                ) from None
            exe_sha = d.sha256(exe, lambda: False)
            marker = {
                "tag": self.tag,
                "asset": asset.name,
                "asset_sha256": asset.sha256,
                "exe_sha256": exe_sha,
                "name": info.name,
                "installed_at": d.clock.now().isoformat(timespec="seconds"),
            }
            (tmp / MARKER).write_text(json.dumps(marker, indent=2), encoding="utf-8")
            token.raise_if_cancelled()
            self._swap_in(tmp)
            log.info("installed %s (%s) into %s", info.name, self.tag, self.target_dir)
            return "installed"
        finally:
            for f in leftovers:
                f.unlink(missing_ok=True)
            if tmp.exists():
                shutil.rmtree(tmp, ignore_errors=True)

    def _download(self, asset: ManifestAsset, dest: Path, progress: ProgressFn, token: CancelToken) -> None:
        def on_bytes(done: int, total: int | None) -> None:
            total = total or asset.size
            mb = done / 1_048_576
            progress(min(done / total, 1.0) * 0.85 if total else None, f"Downloading Stockfish… {mb:,.0f} MB")

        progress(0.0, "Downloading Stockfish…")
        if self._d.http is None:
            raise InstallError("No download client.", code="download_failed")
        try:
            self._d.http.download(asset.url, dest, progress=on_bytes, cancelled=lambda: token.cancelled)
        except Exception as e:
            token.raise_if_cancelled()
            raise InstallError(f"The Stockfish download failed: {e}", code="download_failed") from None
        token.raise_if_cancelled()

    def _hash(self, path: Path, token: CancelToken) -> str:
        try:
            digest = self._d.sha256(path, lambda: token.cancelled)
        except Exception:
            token.raise_if_cancelled()  # a cancel mid-hash is a cancel, not a failure
            raise
        token.raise_if_cancelled()
        return digest

    def _names(self, zip_path: Path) -> list[str]:
        try:
            return self._d.zip_names(zip_path)
        except Exception:
            raise InstallError("The downloaded file isn't a readable zip archive.", code="unexpected_archive") from None

    def _swap_in(self, tmp: Path) -> None:
        target = self.target_dir
        old: Path | None = None
        try:
            if target.exists():
                old = Path(tempfile.mkdtemp(prefix=f".{self.tag}.old-", dir=self._d.engines_dir))
                old.rmdir()
                self._d.rename(target, old)
            self._d.rename(tmp, target)
        except OSError as e:
            log.warning("couldn't move the engine folder into place: %s", type(e).__name__)
            if old is not None and old.exists() and not target.exists():
                self._d.rename(old, target)  # put the previous install back
            raise InstallError(
                "Couldn't replace the installed Stockfish: it's in use. Close WeakSquare (or stop the engine) "
                "and try again.",
                code="engine_in_use",
            ) from None
        if old is not None:
            shutil.rmtree(old, ignore_errors=True)


def run_install(installer: EngineInstaller, progress: ProgressFn, token: CancelToken, force: bool = False) -> str:
    """The job body: an InstallError becomes a failed job with its code; cancel stays a cancel."""
    try:
        result = installer.install(progress, token, force)
    except JobCancelled:
        raise
    except InstallError as e:
        raise JobFailed(e.code, e.message, e.retryable) from None
    except Exception as e:  # UnsupportedPlatform and other AppErrors carry a message for the user
        message = getattr(e, "message", None)
        if message is None:
            raise
        raise JobFailed(getattr(e, "code", "install_failed"), message, False) from None
    return "Stockfish is already installed." if result == "already_installed" else "Stockfish is installed."
