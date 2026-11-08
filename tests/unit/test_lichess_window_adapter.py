"""FR-13.3, 13.4 (v0.14): the app's end of the Lichess window, with a fake window process.

The fake is a tiny Python script that prints the given JSON lines and echoes the commands it reads, so the real pipe and
reader-thread code runs without WebView2.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from weaksquare.adapters.lichess_window import LichessWindow
from weaksquare.core.study_links import StudyRef, ref_from_ids

FAKE = """
import sys, json
for line in json.loads(sys.argv[1]):
    print(line, flush=True)
for cmd in sys.stdin:
    print(json.dumps({"type": "echo", "cmd": cmd.strip()}), flush=True)
    if cmd.strip() == "close":
        break
print(json.dumps({"type": "closed"}), flush=True)
"""


def fake_popen(tmp_path: Path, lines: list[str], seen: dict[str, object]):  # type: ignore[no-untyped-def]
    script = tmp_path / "fake_window.py"
    script.write_text(FAKE, encoding="utf-8")

    def popen(args, **kw):  # type: ignore[no-untyped-def]
        seen["args"], seen["env"] = args, kw.get("env")
        return subprocess.Popen(
            [sys.executable, str(script), json.dumps(lines)],
            stdin=kw["stdin"], stdout=kw["stdout"], stderr=kw["stderr"], text=True, encoding="utf-8",
        )  # fmt: skip

    return popen


def wait(cond, timeout=10.0):  # type: ignore[no-untyped-def]
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_adds_are_re_checked_and_bad_ones_dropped(tmp_path: Path) -> None:
    lines = [
        json.dumps({"type": "ready"}),
        json.dumps({"type": "add", "study": "ZCPaIb70", "chapter": None}),
        json.dumps({"type": "add", "study": "nq1GGbNO", "chapter": "rWqJitDx"}),
        json.dumps({"type": "add", "study": "../../etc", "chapter": None}),
        json.dumps({"type": "add", "study": "ZCPaIb70/x", "chapter": None}),
        json.dumps({"type": "add", "study": "ZCPaIb70", "chapter": 5}),
        json.dumps({"type": "add", "study": "allstudy"}),
        "not json",
        json.dumps(["not", "a", "dict"]),
        json.dumps({"type": "add", "study": "A" * 3000}),
    ]
    added: list[StudyRef] = []
    closed = threading.Event()
    w = LichessWindow(added.append, on_closed=closed.set, popen=fake_popen(tmp_path, lines, {}))
    assert w.open()
    assert wait(lambda: len(added) >= 2)
    w.close()
    assert closed.wait(10)
    assert added == [StudyRef("ZCPaIb70"), StudyRef("nq1GGbNO", "rWqJitDx")]
    assert not w.is_open()


def test_page_events_and_focus_when_already_open(tmp_path: Path) -> None:
    lines = [
        json.dumps({"type": "page", "study": "ZCPaIb70", "chapter": None}),
        json.dumps({"type": "page", "study": None, "chapter": None}),
    ]
    pages: list[StudyRef | None] = []
    w = LichessWindow(lambda r: None, on_page=pages.append, popen=fake_popen(tmp_path, lines, {}))
    assert w.open()
    assert wait(lambda: len(pages) == 2)
    assert pages == [StudyRef("ZCPaIb70"), None]
    assert w.is_open()
    assert w.open() is False  # second Open brings it forward instead of starting another
    w.close()
    assert wait(lambda: not w.is_open())


def test_runs_the_window_module_without_webview2_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "--remote-debugging-port=9222")
    seen: dict[str, object] = {}
    w = LichessWindow(lambda r: None, popen=fake_popen(tmp_path, [], seen))
    w.open()
    w.close()
    assert seen["args"][1:3] == ["-m", "weaksquare.lichess_window"]  # type: ignore[index]
    env = seen["env"]
    assert isinstance(env, dict)
    assert not any(k.upper().startswith("WEBVIEW2_") for k in env)


def test_close_without_a_window_is_harmless() -> None:
    LichessWindow(lambda r: None).close()


@pytest.mark.parametrize(
    ("study", "chapter", "expected"),
    [
        ("ZCPaIb70", None, StudyRef("ZCPaIb70")),
        ("nq1GGbNO", "rWqJitDx", StudyRef("nq1GGbNO", "rWqJitDx")),
        (None, None, None),
        ("ZCPaIb70", "", StudyRef("ZCPaIb70")),
        ("ZCPaIb7", None, None),
        ("ZCPaIb70?x", None, None),
        ("ZCPaIb70", "rWqJitDx/../x", None),
    ],
)
def test_ref_from_ids(study: object, chapter: object, expected: StudyRef | None) -> None:
    assert ref_from_ids(study, chapter) == expected
