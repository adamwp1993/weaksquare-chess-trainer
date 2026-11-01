"""NFR-8a: setup.py makes the Start-menu and desktop shortcuts with the WeakSquare icon, honors
--no-desktop-shortcut and --no-shortcut, finds the Desktop through the known-folder API (OneDrive
redirection), and re-running doesn't duplicate. The shell call is faked: nothing is created."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import setup as setup_script  # noqa: E402

START = Path(r"C:\Users\you\AppData\Roaming\Microsoft\Windows\Start Menu\Programs")
ONEDRIVE_DESKTOP = Path(r"C:\Users\you\OneDrive\Desktop")


class FakeShell:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, cmd: list[str], check: bool, env: dict[str, str]) -> None:
        assert cmd[:4] == ["powershell", "-NoProfile", "-NonInteractive", "-Command"]
        assert check and not any(c.endswith(".ps1") for c in cmd)  # inline, works under AllSigned
        self.calls.append(
            {"link": env["WS_LINK"], "icon": env["WS_ICON"], "target": env["WS_TARGET"], "script": cmd[4]}
        )


@pytest.fixture(autouse=True)
def venv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / ".venv" / "Scripts").mkdir(parents=True)
    (root / ".venv" / "Scripts" / "pythonw.exe").write_bytes(b"")
    monkeypatch.setattr(setup_script, "ROOT", root)


def run(*flags: str) -> tuple[list[Path], FakeShell]:
    ap = argparse.Namespace(no_shortcut="--no-shortcut" in flags, no_desktop_shortcut="--no-desktop-shortcut" in flags)
    shell = FakeShell()
    links = setup_script.create_shortcuts(ap, run=shell, desktop=lambda: ONEDRIVE_DESKTOP, start_menu=lambda: START)
    return links, shell


def test_both_shortcuts_with_the_icon_on_the_known_folder_desktop() -> None:
    links, shell = run()
    name = "WeakSquare Chess Trainer.lnk"
    assert [c["link"] for c in shell.calls] == [str(START / name), str(ONEDRIVE_DESKTOP / name)]
    for c in shell.calls:
        assert c["icon"] == f"{setup_script.ICON},0" and c["icon"].endswith("weaksquare.ico,0")
        assert c["target"].endswith("pythonw.exe") and "IconLocation" in c["script"]
        assert "--dev" not in c["script"]  # SR-16: shortcuts never start a dev run
    assert links == [START / name, ONEDRIVE_DESKTOP / name]


def test_no_desktop_shortcut() -> None:
    _, shell = run("--no-desktop-shortcut")
    assert [Path(c["link"]).parent for c in shell.calls] == [START]


def test_no_shortcut_skips_both() -> None:
    links, shell = run("--no-shortcut")
    assert links == [] and shell.calls == []


def test_rerun_writes_the_same_two_paths() -> None:
    first, _ = run()
    second, _ = run()
    assert first == second and len(set(first)) == 2  # saving to the same path replaces the shortcut


def test_desktop_lookup_failure_still_makes_the_start_menu_one() -> None:
    def broken() -> Path:
        raise OSError("no known folder")

    shell = FakeShell()
    ap = argparse.Namespace(no_shortcut=False, no_desktop_shortcut=False)
    links = setup_script.create_shortcuts(ap, run=shell, desktop=broken, start_menu=lambda: START)
    assert links == [START / "WeakSquare Chess Trainer.lnk"]


def test_the_icon_file_exists() -> None:
    assert (ROOT / "assets" / "icon" / "weaksquare.ico").is_file()


@pytest.mark.skipif(sys.platform != "win32", reason="the known-folder API is Windows-only")
def test_real_known_folder_lookup_returns_an_existing_folder() -> None:
    assert setup_script.desktop_folder().is_dir()


def test_finish_message_names_only_the_shortcuts_made() -> None:
    """v0.2-B6: with --no-shortcut, setup said to start the app from the Start menu or desktop."""
    name = "WeakSquare Chess Trainer.lnk"
    both = setup_script.finish_message([START / name, ONEDRIVE_DESKTOP / name])
    assert both.endswith("from the Start menu or your desktop.")
    assert setup_script.finish_message([START / name]).endswith("from the Start menu.")
    assert "uv run python -m weaksquare" in setup_script.finish_message([])


def test_help_describes_the_whole_download() -> None:
    """v0.2-B6 / FR-2.1a: --help says it's the entire database, with its sizes."""
    import subprocess

    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "setup.py"), "--help"], capture_output=True, text=True)
    assert out.returncode == 0
    for words in ("entire Lichess puzzle database", "300 MB", "6 million", "1.5 GB", "--no-desktop-shortcut"):
        assert words in out.stdout, words
