"""Install or repair Stockfish (FR-7.5): the pinned release from engine_manifest.json, hash-checked.

A thin CLI over services/engine_install.py: the same code the app's Install button runs.

Usage (from the repo root):
    uv run python scripts/fetch_stockfish.py            # into the real data folder's engines\\sf_19
    uv run python scripts/fetch_stockfish.py --dev      # into the dev data folder
    uv run python scripts/fetch_stockfish.py --force    # reinstall even if the install is fine

Running it again does nothing when the installed engine already matches the manifest.
Close WeakSquare first when using --force: a running engine can't be replaced.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from weaksquare import config  # noqa: E402
from weaksquare.adapters.http import HttpClient  # noqa: E402
from weaksquare.adapters.system_clock import SystemClock  # noqa: E402
from weaksquare.app import build_engine_installer  # noqa: E402
from weaksquare.core.errors import AppError  # noqa: E402
from weaksquare.jobs.runner import CancelToken, JobCancelled  # noqa: E402


class ConsoleProgress:
    def __init__(self) -> None:
        self._last = ""

    def __call__(self, fraction: float | None, message: str) -> None:
        pct = f"{fraction * 100:5.1f}%" if fraction is not None else "   … "
        line = f"\r   {pct}  {message}"[:110]
        if line != self._last:
            print(line.ljust(len(self._last)), end="", flush=True)
            self._last = line


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dev", action="store_true", help="use the dev data folder (%%LOCALAPPDATA%%\\WeakSquare-dev)")
    ap.add_argument("--force", action="store_true", help="reinstall even if the installed engine matches")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # progress text has "…"; never crash on a cp1252 console
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(errors="replace")

    paths = config.resolve_paths(dev=args.dev)
    paths.ensure()
    http = HttpClient()
    installer = build_engine_installer(paths, http, SystemClock())
    token = CancelToken()
    print(f"   Stockfish {installer.tag} -> {installer.target_dir}")
    try:
        result = installer.install(ConsoleProgress(), token, force=args.force)
    except KeyboardInterrupt:
        token.cancel()
        print("\n   cancelled", file=sys.stderr)
        return 1
    except JobCancelled:
        print("\n   cancelled", file=sys.stderr)
        return 1
    except AppError as e:
        print(f"\n   Stockfish install failed: {e.message}", file=sys.stderr)
        return 1
    finally:
        http.close()
    print()
    installed = installer.installed()
    if result == "already_installed":
        print(f"   already installed: {installed.name if installed else installer.tag} (nothing to do)")
    else:
        print(f"   installed {installed.name if installed else installer.tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
