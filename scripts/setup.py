"""One-command setup for a fresh clone (NFR-8). Safe to re-run: every step skips what's already done.

Usage (from the repo root, in PowerShell, cmd or Git Bash):
    python scripts/setup.py                      # everything
    python scripts/setup.py --no-desktop-shortcut  # the Start-menu shortcut only
    python scripts/setup.py --no-shortcut        # neither shortcut
    python scripts/setup.py --skip-puzzle-db     # don't download/import the puzzle database now
    python scripts/setup.py --puzzle-file PATH   # import a lichess_db_puzzle.csv.zst you already have
    python scripts/setup.py --dev                # import the puzzles into the dev data folder instead

Steps: uv (installed with pip if missing) -> Python packages from uv.lock -> npm packages from
package-lock.json -> front-end build -> Playwright's Chromium -> pre-commit hooks -> puzzle database
(the entire Lichess puzzle database: about 300 MB to download, about 6 million puzzles, roughly
1.5 GB once imported; skipped if already imported) -> Start-menu and desktop shortcuts, with the
WeakSquare icon (NFR-8a). Standard library only, because it runs before anything is installed.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
SHORTCUT_NAME = "WeakSquare Chess Trainer.lnk"
ICON = ROOT / "assets" / "icon" / "weaksquare.ico"
FOLDERID_DESKTOP = "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}"


def step(title: str) -> None:
    print(f"\n==> {title}", flush=True)


def run(cmd: list[str], **kwargs: object) -> None:
    print("   $ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=kwargs.pop("cwd", ROOT), **kwargs)  # type: ignore[call-overload]


def fail(msg: str) -> None:
    print(f"\nSetup stopped: {msg}", file=sys.stderr)
    sys.exit(1)


def check_prerequisites() -> str:
    step("Checking prerequisites")
    if sys.version_info < (3, 12):  # noqa: UP036 - runs on whatever Python the user has
        fail(f"Python 3.12 or newer is needed (this is {sys.version.split()[0]}).")
    if sys.platform != "win32":
        fail("WeakSquare runs on Windows 10 or 11 only.")
    npm = shutil.which("npm")  # resolves npm.cmd, which works under any PowerShell execution policy
    if not npm:
        fail("Node.js LTS isn't installed (npm wasn't found). Install it from nodejs.org and re-run.")
    if not shutil.which("git"):
        fail("Git for Windows isn't installed.")
    print("   Python, Node.js and Git found.")
    return npm


def ensure_uv() -> list[str]:
    step("uv (Python package manager)")
    found = shutil.which("uv")
    if found:
        print(f"   found {found}")
        return [found]
    probe = subprocess.run([sys.executable, "-m", "uv", "--version"], capture_output=True)
    if probe.returncode != 0:
        run([sys.executable, "-m", "pip", "install", "--user", "uv"])
    print(
        "   Note: uv isn't on your PATH, so this setup runs it as `python -m uv`. The commands in the\n"
        "   Developer Guide use `uv run …`; either add Python's user Scripts folder to PATH, or type\n"
        "   `python -m uv run …` instead."
    )
    return [sys.executable, "-m", "uv"]


def sync_python(uv: list[str]) -> None:
    step("Python packages (uv sync --locked)")
    run([*uv, "sync", "--locked"])


def _lock_digest() -> str:
    return hashlib.sha256((WEB / "package-lock.json").read_bytes()).hexdigest()


def sync_npm(npm: str) -> None:
    step("Front-end packages (npm ci)")
    marker = WEB / "node_modules" / ".weaksquare-lock-sha256"
    if marker.is_file() and marker.read_text().strip() == _lock_digest():
        print("   already installed from the current package-lock.json")
        return
    run([npm, "ci"], cwd=WEB)
    marker.write_text(_lock_digest())


def build_front_end(npm: str) -> None:
    step("Front-end build (web/dist)")
    run([npm, "run", "build"], cwd=WEB)


def install_playwright(uv: list[str]) -> None:
    step("Playwright's Chromium (for the UI tests)")
    run([*uv, "run", "playwright", "install", "chromium"])


def install_pre_commit(uv: list[str]) -> None:
    step("pre-commit hooks")
    if (ROOT / ".git" / "hooks" / "pre-commit").is_file():
        print("   already installed")
        return
    run([*uv, "run", "pre-commit", "install"])


def import_puzzles(uv: list[str], args: argparse.Namespace) -> None:
    step("Puzzle database")
    if args.skip_puzzle_db:
        print("   skipped (--skip-puzzle-db). You can import it from inside the app instead.")
        return
    cmd = [*uv, "run", "python", "scripts/fetch_puzzle_db.py", "--skip-if-present"]
    if args.puzzle_file:
        cmd += ["--file", str(Path(args.puzzle_file).resolve())]
    if args.dev:
        cmd.append("--dev")
    run(cmd)


def desktop_folder() -> Path:
    """The Desktop through the Windows known-folder API: it's often redirected to OneDrive, so
    %USERPROFILE%\\Desktop can be the wrong place (NFR-8a)."""

    class GUID(ctypes.Structure):
        _fields_ = [
            ("d1", ctypes.c_ulong),
            ("d2", ctypes.c_ushort),
            ("d3", ctypes.c_ushort),
            ("d4", ctypes.c_ubyte * 8),
        ]

    guid = GUID()
    ole32 = ctypes.windll.ole32  # type: ignore[attr-defined]
    if ole32.CLSIDFromString(ctypes.c_wchar_p(FOLDERID_DESKTOP), ctypes.byref(guid)) != 0:
        raise OSError("CLSIDFromString failed")
    path_ptr = ctypes.c_wchar_p()
    if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(path_ptr)) != 0:  # type: ignore[attr-defined]
        raise OSError("SHGetKnownFolderPath failed")
    try:
        return Path(path_ptr.value or "")
    finally:
        ole32.CoTaskMemFree(path_ptr)


def start_menu_folder() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def make_shortcut(link: Path, target: Path, run: Callable[..., Any] = subprocess.run) -> None:
    """Create or replace `link` (saving to the same path overwrites, so re-runs never duplicate).
    An inline -Command (not a .ps1 file), so it runs under any execution policy, including AllSigned.
    Values travel in environment variables to avoid quoting problems."""
    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:WS_LINK);"
        "$s.TargetPath = $env:WS_TARGET; $s.Arguments = '-m weaksquare';"
        "$s.WorkingDirectory = $env:WS_DIR; $s.Description = 'WeakSquare Chess Trainer';"
        "$s.IconLocation = $env:WS_ICON; $s.Save()"
    )
    env = dict(os.environ, WS_LINK=str(link), WS_TARGET=str(target), WS_DIR=str(ROOT), WS_ICON=f"{ICON},0")
    run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], check=True, env=env)
    print(f"   {link}")


def create_shortcuts(
    args: argparse.Namespace,
    run: Callable[..., Any] = subprocess.run,
    desktop: Callable[[], Path] = desktop_folder,
    start_menu: Callable[[], Path] = start_menu_folder,
) -> list[Path]:
    """The Start-menu shortcut, and a desktop one unless --no-desktop-shortcut (NFR-8a).
    --no-shortcut skips both. Returns the shortcuts written."""
    step("Shortcuts")
    if args.no_shortcut:
        print("   skipped (--no-shortcut)")
        return []
    pythonw = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    if not pythonw.is_file():
        fail(f"{pythonw} is missing; the Python step didn't finish.")
    links = [start_menu() / SHORTCUT_NAME]
    if args.no_desktop_shortcut:
        print("   desktop shortcut skipped (--no-desktop-shortcut)")
    else:
        try:
            links.append(desktop() / SHORTCUT_NAME)
        except OSError as e:
            print(f"   couldn't find your Desktop folder ({e}); skipping the desktop shortcut")
    for link in links:
        make_shortcut(link, pythonw, run)
    return links


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-shortcut", action="store_true", help="create neither shortcut")
    ap.add_argument("--no-desktop-shortcut", action="store_true", help="create the Start-menu shortcut only")
    ap.add_argument("--skip-puzzle-db", action="store_true")
    ap.add_argument("--puzzle-file", metavar="PATH")
    ap.add_argument("--dev", action="store_true", help="import the puzzles into the dev data folder")
    args = ap.parse_args()

    npm = check_prerequisites()
    uv = ensure_uv()
    sync_python(uv)
    sync_npm(npm)
    build_front_end(npm)
    install_playwright(uv)
    install_pre_commit(uv)
    import_puzzles(uv, args)
    create_shortcuts(args)
    print("\nSetup complete. Start WeakSquare Chess Trainer from the Start menu or your desktop.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as e:
        fail(f"a step failed (exit code {e.returncode}): {' '.join(map(str, e.cmd))}")
