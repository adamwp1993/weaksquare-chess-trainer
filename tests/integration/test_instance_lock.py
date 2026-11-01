"""NFR-1: a second copy can't take the lock while the first holds it."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from weaksquare.adapters import instance_lock


def test_second_acquire_fails_until_released(tmp_path: Path) -> None:
    lock_file = tmp_path / "weaksquare.lock"
    first = instance_lock.acquire(lock_file)
    assert first is not None
    # A separate process, like a second launch of the app.
    code = (
        "import sys; from pathlib import Path; from weaksquare.adapters import instance_lock;"
        f"sys.exit(0 if instance_lock.acquire(Path(r'{lock_file}')) is None else 1)"
    )
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0
    first.release()
    assert subprocess.run([sys.executable, "-c", code]).returncode == 1


def test_lock_survives_reacquire_in_same_process_after_release(tmp_path: Path) -> None:
    lock_file = tmp_path / "weaksquare.lock"
    a = instance_lock.acquire(lock_file)
    assert a is not None
    a.release()
    b = instance_lock.acquire(lock_file)
    assert b is not None
    b.release()
