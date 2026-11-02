"""File helpers: hashing, the puzzle CSV (optionally zstd-compressed), and the engine zip (FR-7.5)."""

from __future__ import annotations

import csv
import hashlib
import io
import shutil
import time
import zipfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

import zstandard

CHUNK = 1024 * 1024


class CancelledError(Exception):
    pass


def sha256_file(path: Path, cancelled: Callable[[], bool] = lambda: False) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(CHUNK):
            if cancelled():
                raise CancelledError()
            digest.update(chunk)
    return digest.hexdigest()


MAX_ENGINE_BYTES = 512 * 1024 * 1024  # the sf_19 exe is ~100 MB; refuse anything absurd (zip bomb)


class ZipError(Exception):
    """The archive can't be read, or the member is missing or too large."""


def zip_names(path: Path) -> list[str]:
    try:
        with zipfile.ZipFile(path) as z:
            return z.namelist()
    except (zipfile.BadZipFile, OSError) as e:
        raise ZipError(f"not a readable zip: {type(e).__name__}") from None


def extract_member(path: Path, member: str, dest: Path, max_bytes: int = MAX_ENGINE_BYTES) -> None:
    """Write exactly one archive member to `dest`. The caller has already vetted every entry name."""
    try:
        with zipfile.ZipFile(path) as z:
            info = z.getinfo(member)
            if info.file_size > max_bytes:
                raise ZipError("archive member is too large")
            dest.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, dest.open("wb") as out:
                shutil.copyfileobj(src, out, CHUNK)
    except KeyError:
        raise ZipError("archive member is missing") from None
    except (zipfile.BadZipFile, OSError) as e:
        raise ZipError(f"couldn't extract: {type(e).__name__}") from None


def rename_with_retry(src: Path, dst: Path, *, attempts: int = 40, wait_s: float = 0.25) -> None:
    """Rename, retrying "access denied" for up to ~10 s. A freshly written exe is briefly locked on
    Windows (Defender scans it; a just-closed engine process takes a moment to exit)."""
    for attempt in range(attempts):
        try:
            src.rename(dst)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(wait_s)


class PuzzleCsv:
    """Streams CSV rows from a `.csv.zst` or plain `.csv` file and reports how far it has read."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._raw: BinaryIO | None = None
        self._size = max(path.stat().st_size, 1)

    def fraction(self) -> float:
        if self._raw is None or self._raw.closed:
            return 0.0
        return min(self._raw.tell() / self._size, 1.0)

    @contextmanager
    def rows(self) -> Iterator[Iterator[list[str]]]:
        """Yields a row iterator (the header row first). Raises ValueError for a corrupt zstd stream."""
        with self.path.open("rb") as raw:
            self._raw = raw
            if self.path.suffix.lower() == ".zst":
                stream: BinaryIO = zstandard.ZstdDecompressor().stream_reader(raw, read_across_frames=True)  # type: ignore[assignment]
            else:
                stream = raw
            text = io.TextIOWrapper(stream, encoding="utf-8", newline="")
            try:
                yield csv.reader(text)
            except zstandard.ZstdError as e:
                raise ValueError(f"the file isn't a valid zstd stream: {e}") from None
