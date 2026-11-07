"""Paths and app-wide constants. Every file path in the app comes from here (NFR-2)."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_dir

from weaksquare import __version__

APP_VERSION = __version__
APP_TITLE = "WeakSquare Chess Trainer"
REPO_URL = "https://github.com/adamwp1993/weaksquare-chess-trainer"
LICENSE_NAME = "AGPL-3.0-or-later"
DATA_DIR_ENV = "WEAKSQUARE_DATA_DIR"
PUZZLE_DB_URL = "https://database.lichess.org/lichess_db_puzzle.csv.zst"
PUZZLE_SUMS_URL = "https://database.lichess.org/sha256sums.txt"
PUZZLE_PAGE_URL = "https://database.lichess.org/"  # the approximate puzzle count (FR-2.5)

PACKAGE_DIR = Path(__file__).resolve().parent
MIGRATIONS_DIR = PACKAGE_DIR / "adapters" / "db" / "migrations"
ENGINE_MANIFEST = PACKAGE_DIR / "engine_manifest.json"  # pinned Stockfish release (FR-7.5)
OPENING_BOOK_DIR = PACKAGE_DIR / "opening_book"  # the bundled chess-openings files, pinned (FR-12.1)
REPO_ROOT = PACKAGE_DIR.parent.parent
WEB_DIST = REPO_ROOT / "web" / "dist"
ICON_FILE = REPO_ROOT / "assets" / "icon" / "weaksquare.ico"  # built by scripts/make_icon.py (NFR-8a)


class DataDirError(RuntimeError):
    """The data folder resolved somewhere it must not be (for example the real folder in a test)."""


@dataclass(frozen=True)
class Paths:
    data_dir: Path

    @property
    def user_db(self) -> Path:
        return self.data_dir / "user.db"

    @property
    def puzzles_db(self) -> Path:
        return self.data_dir / "puzzles.db"

    @property
    def puzzles_new_db(self) -> Path:
        return self.data_dir / "puzzles.new.db"

    @property
    def downloads_dir(self) -> Path:
        return self.data_dir / "downloads"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def engines_dir(self) -> Path:
        """Managed engine installs, one folder per release tag (FR-7.5; per data folder, NFR-2)."""
        return self.data_dir / "engines"

    @property
    def lock_file(self) -> Path:
        return self.data_dir / "weaksquare.lock"

    def ensure(self) -> None:
        for d in (self.data_dir, self.backups_dir, self.logs_dir, self.downloads_dir):
            d.mkdir(parents=True, exist_ok=True)


def default_data_dir(dev: bool) -> Path:
    r"""%LOCALAPPDATA%\WeakSquare, or WeakSquare-dev for dev runs."""
    return Path(user_data_dir("WeakSquare-dev" if dev else "WeakSquare", appauthor=False, roaming=False))


def _under_pytest() -> bool:
    return "pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ


def resolve_paths(dev: bool, env: Mapping[str, str] | None = None) -> Paths:
    """Resolve the data folder: WEAKSQUARE_DATA_DIR wins, then the dev or real default.

    Under pytest, resolving to either real folder is refused so tests can never touch real history.
    """
    env = os.environ if env is None else env
    override = env.get(DATA_DIR_ENV, "").strip()
    data_dir = Path(override).expanduser().resolve() if override else default_data_dir(dev)
    if _under_pytest():
        real = {default_data_dir(False).resolve(), default_data_dir(True).resolve()}
        if data_dir.resolve() in real:
            raise DataDirError(f"tests must not use the real data folder: {data_dir}")
    return Paths(data_dir)
