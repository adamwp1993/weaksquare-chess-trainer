"""Test-side composition: builds an Api the way app.py does, with fakes where needed."""

from __future__ import annotations

from pathlib import Path

from weaksquare.adapters.desktop import Desktop
from weaksquare.bridge.api import Api
from weaksquare.config import Paths
from weaksquare.core.clock import FixedClock


class FakeDesktop(Desktop):
    def __init__(self) -> None:
        super().__init__()
        self.opened: list[Path] = []

    def open_folder(self, path: Path) -> None:
        self.opened.append(path)


def build_api(paths: Paths, clock: FixedClock, desktop: Desktop | None = None) -> Api:
    return Api(paths=paths, desktop=desktop or FakeDesktop(), clock=clock, dev_mode=True)
