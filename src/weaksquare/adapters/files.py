"""File helpers for the puzzle import: hashing and reading the (optionally zstd-compressed) CSV."""

from __future__ import annotations

import csv
import hashlib
import io
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
