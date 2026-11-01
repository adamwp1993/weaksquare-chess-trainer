"""SQLite connections (ARCHITECTURE §3 decisions 1, 12 and 17).

- One connection per thread, opened lazily. A connection is never used by two threads at once.
- user.db is opened read-write in WAL mode with a 5 s busy timeout. puzzles.db, when it exists, is
  ATTACHed read-only as schema `pz`.
- Every use goes through `session()`, which holds a shared lock. `swap_puzzles_db()` takes the
  exclusive lock, so when it closes the registered connections none of them is in use. That is the
  only time a connection is touched from another thread, which is why connections are opened with
  check_same_thread=False. Each thread reopens lazily afterwards.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

log = logging.getLogger(__name__)

PUZZLES_MMAP_BYTES = 2 * 1024**3


class _RWLock:
    """Many readers (sessions) or one writer (swap / close). Waiting writers block new readers."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._readers = 0
        self._writer = False
        self._writers_waiting = 0
        self._local = threading.local()

    @contextmanager
    def shared(self) -> Iterator[None]:
        depth = getattr(self._local, "depth", 0)
        if depth:  # re-entrant for nested sessions on the same thread
            self._local.depth = depth + 1
            try:
                yield
            finally:
                self._local.depth -= 1
            return
        with self._cond:
            while self._writer or self._writers_waiting:
                self._cond.wait()
            self._readers += 1
        self._local.depth = 1
        try:
            yield
        finally:
            self._local.depth = 0
            with self._cond:
                self._readers -= 1
                self._cond.notify_all()

    @contextmanager
    def exclusive(self) -> Iterator[None]:
        with self._cond:
            self._writers_waiting += 1
            while self._writer or self._readers:
                self._cond.wait()
            self._writers_waiting -= 1
            self._writer = True
        try:
            yield
        finally:
            with self._cond:
                self._writer = False
                self._cond.notify_all()


def readonly_uri(path: Path) -> str:
    """SQLite URI that opens `path` read-only."""
    return "file:" + path.resolve().as_posix() + "?mode=ro"


class Database:
    def __init__(self, user_db: Path, puzzles_db: Path) -> None:
        self._user_db = user_db
        self._puzzles_db = puzzles_db
        self._local = threading.local()
        self._lock = _RWLock()
        self._registry_lock = threading.Lock()
        self._registry: set[sqlite3.Connection] = set()
        self._generation = 0
        self._closed = False
        # WAL is a property of the file; set it once here rather than racing on every thread's open.
        init = sqlite3.connect(user_db, timeout=5.0)
        try:
            init.execute("PRAGMA journal_mode=WAL")
        finally:
            init.close()

    @property
    def puzzles_db_path(self) -> Path:
        return self._puzzles_db

    def _open(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._user_db, timeout=5.0, check_same_thread=False, isolation_level=None, uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        if self._puzzles_db.exists():
            conn.execute("ATTACH DATABASE ? AS pz", (readonly_uri(self._puzzles_db),))
            # Memory-mapped reads make the full-range count scans ~20% faster (measured in v0.1).
            conn.execute(f"PRAGMA pz.mmap_size={PUZZLES_MMAP_BYTES}")
        with self._registry_lock:
            self._registry.add(conn)
        return conn

    def _thread_conn(self) -> sqlite3.Connection:
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is not None and getattr(self._local, "gen", -1) != self._generation:
            conn = None  # closed by a swap; reopen
        if conn is None:
            conn = self._open()
            self._local.conn = conn
            self._local.gen = self._generation
        return conn

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        """The calling thread's connection, held under the shared lock for the block."""
        if self._closed:
            raise RuntimeError("database is closed")
        with self._lock.shared():
            yield self._thread_conn()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.session() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")

    def puzzles_attached(self) -> bool:
        with self.session() as conn:
            return any(row["name"] == "pz" for row in conn.execute("PRAGMA database_list"))

    def _close_registered(self) -> None:
        with self._registry_lock:
            conns, self._registry = self._registry, set()
        for conn in conns:
            try:
                conn.close()
            except sqlite3.Error:  # pragma: no cover
                log.exception("closing a connection failed")
        self._generation += 1

    def swap_puzzles_db(self, new_file: Path) -> None:
        """Replace puzzles.db with `new_file` while no query is running (FR-2.3)."""
        with self._lock.exclusive():
            self._close_registered()
            os.replace(new_file, self._puzzles_db)
            log.info("puzzles.db replaced")

    def close_all(self) -> None:
        with self._lock.exclusive():
            self._close_registered()
            self._closed = True
