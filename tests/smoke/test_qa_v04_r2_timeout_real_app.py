"""QA v0.4 round 2: v0.4-B1 in the real app. A custom UCI engine that passes the self-test but never
answers a search from a puzzle position forces the engine timeout (think time + 10 s); afterwards
closing the window must end the app process and release the single-instance lock (NFR-6).

The engine is a few lines of C#, compiled at test time with the .NET Framework's csc.exe (part of
Windows). Skips if csc.exe isn't there. Written by the independent QA pass (qa/QA-v0.4.md).
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

import pytest

from tests.smoke.conftest import attach, free_port, launch_app
from weaksquare.adapters import instance_lock

pytestmark = pytest.mark.smoke

CSC = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe")
HANGFISH = r"""
using System;
class HangFish {
  static void Main() {
    bool startpos = true;
    string line;
    while ((line = Console.ReadLine()) != null) {
      line = line.Trim();
      if (line == "uci") {
        Console.WriteLine("id name HangFish 1");
        Console.WriteLine("option name Threads type spin default 1 min 1 max 64");
        Console.WriteLine("option name Hash type spin default 16 min 1 max 4096");
        Console.WriteLine("option name MultiPV type spin default 1 min 1 max 50");
        Console.WriteLine("uciok");
      }
      else if (line == "isready") Console.WriteLine("readyok");
      else if (line.StartsWith("position")) startpos = line.StartsWith("position startpos") && !line.Contains(" moves ");
      else if (line.StartsWith("go")) {
        if (startpos) { Console.WriteLine("info depth 1 multipv 1 score cp 20 pv e2e4"); Console.WriteLine("bestmove e2e4"); }
        else { while (true) System.Threading.Thread.Sleep(1000); }
      }
      else if (line == "quit") return;
      Console.Out.Flush();
    }
  }
}
"""


def _count(image: str) -> int:
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {image}", "/NH"], capture_output=True, text=True).stdout
    return sum(1 for line in out.splitlines() if line.lower().startswith(image.lower()))


def _pid_alive(pid: int) -> bool:
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
    return str(pid) in out


@pytest.mark.skipif(not CSC.is_file(), reason="needs the .NET Framework csc.exe")
def test_app_exits_after_an_engine_timeout(pw, tmp_path: Path, fixture_puzzles_db: Path) -> None:  # type: ignore[no-untyped-def]
    tool = tmp_path / "tool"
    tool.mkdir()
    (tool / "HangFish.cs").write_text(HANGFISH, encoding="utf-8")
    subprocess.run([str(CSC), "-nologo", "-out:hangfish.exe", "HangFish.cs"], cwd=tool, check=True, capture_output=True)
    exe = tool / "hangfish.exe"
    before = _count("hangfish.exe")

    data_dir = tmp_path / "app-data"
    data_dir.mkdir()
    shutil.copyfile(fixture_puzzles_db, data_dir / "puzzles.db")
    app = launch_app(data_dir, free_port())
    app_pid = None
    try:
        with attach(pw, app) as page:
            app_pid = app.app_pid()
            job = page.evaluate(f"async () => await window.pywebview.api.start_custom_engine_check({str(exe)!r})")
            assert job["ok"], job
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                st = page.evaluate(f"async () => await window.pywebview.api.get_job({job['data']!r})")["data"]
                if st["state"] != "running":
                    break
                time.sleep(0.3)
            assert st["state"] == "done", st  # the self-test (start position) passes
            page.get_by_test_id("match-count").filter(has_text="puzzles match").wait_for(timeout=30_000)
            page.get_by_role("button", name="Start").click()
            page.get_by_test_id("hint-button").click(timeout=30_000)
            page.get_by_test_id("answer-button").click()
            page.get_by_test_id("engine-panel").wait_for(timeout=10_000)
            # the panel's search of a puzzle position hangs: wait for the timeout (1 s + 10 s)
            page.get_by_test_id("engine-error").wait_for(timeout=40_000)
            assert "didn't answer in time" in page.get_by_test_id("engine-error").inner_text()
        started = time.monotonic()
        assert app.close(timeout=30) == 0
        exit_s = time.monotonic() - started
    finally:
        if app.process.poll() is None:
            app.process.kill()
    print(f"\napp exit after an engine timeout took {exit_s:.1f} s")
    assert app_pid is not None and not _pid_alive(app_pid)  # the real python.exe is gone
    lock = instance_lock.acquire(data_dir / "weaksquare.lock")  # released: a new launch could take it
    assert lock is not None
    lock.release()
    time.sleep(1)
    assert _count("hangfish.exe") <= before  # no engine process left behind
    log = (data_dir / "logs" / "weaksquare.log").read_text(encoding="utf-8")
    assert "engine timed out" in log and "engine restarted after a timeout" in log
