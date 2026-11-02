"""An in-process EngineClient for service tests, and a helper that plants a managed install.

The fake ranks moves like tests/fakes/uci_engine.py: mates first, then captures, then by UCI. Its
pv is the move followed by up to six more plies of the same ranking, so refutations have length.
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import ClassVar

import chess

from weaksquare.config import ENGINE_MANIFEST, Paths
from weaksquare.core.engine import EngineError, EngineInfo, EngineLine, parse_manifest


def _ranked(board: chess.Board) -> list[tuple[chess.Move, int | None, int | None]]:
    out = []
    for move in board.legal_moves:
        board.push(move)
        mate = board.is_checkmate()
        board.pop()
        sign = 1 if board.turn == chess.WHITE else -1
        if mate:
            out.append((0, move.uci(), move, None, sign))
        elif board.is_capture(move):
            out.append((1, move.uci(), move, 300 * sign, None))
        else:
            out.append((2, move.uci(), move, 10 * sign, None))
    out.sort(key=lambda t: (t[0], t[1]))
    return [(m, cp, mate) for _, _, m, cp, mate in out]


class FakeEngine:
    instances: ClassVar[list[FakeEngine]] = []

    def __init__(self, path: str = "fake.exe", threads: int = 1, hash_mb: int = 16) -> None:
        self.path = path
        self.options = (threads, hash_mb)
        self.calls: list[tuple[str, float, int]] = []
        self.closed = False
        self.fail: EngineError | None = None
        self.gate: threading.Event | None = None  # set: analyse waits until it's released
        self.entered = threading.Event()
        FakeEngine.instances.append(self)

    def analyse(self, board: chess.Board, think_s: float, multipv: int) -> list[EngineLine]:
        assert board.is_valid(), "validation must happen before the engine (FR-7.6)"
        self.calls.append((board.fen(), think_s, multipv))
        self.entered.set()
        if self.gate is not None:
            self.gate.wait(5)
        if self.fail is not None:
            raise self.fail
        lines = []
        for move, cp, mate in _ranked(board)[:multipv]:
            b = board.copy()
            b.push(move)
            pv = [move.uci()]
            while len(pv) < 7 and not b.is_game_over():
                nxt = _ranked(b)[0][0]
                pv.append(nxt.uci())
                b.push(nxt)
            lines.append(EngineLine(cp, mate, tuple(pv)))
        return lines

    def configure(self, threads: int, hash_mb: int) -> None:
        self.options = (threads, hash_mb)

    def info(self) -> EngineInfo:
        return EngineInfo("FakeFish 1")

    def close(self) -> None:
        self.closed = True


def fake_probe(path: str) -> EngineInfo:
    if "broken" in path:
        raise EngineError("no uciok")
    return EngineInfo("Custom Fish 2")


def plant_managed_install(paths: Paths) -> Path:
    """Make `paths` look like it has the managed sf_19 install (the marker the installer writes)."""
    manifest = parse_manifest(json.loads(ENGINE_MANIFEST.read_text(encoding="utf-8")))
    asset = manifest.asset_for("windows-x86_64")
    folder = paths.engines_dir / manifest.tag
    folder.mkdir(parents=True, exist_ok=True)
    exe = folder / "stockfish.exe"
    exe.write_bytes(b"MZ fake")
    marker = {
        "tag": manifest.tag,
        "asset": asset.name,
        "asset_sha256": asset.sha256,
        "exe_sha256": hashlib.sha256(b"MZ fake").hexdigest(),
        "name": "Stockfish 19",
        "installed_at": "2026-01-01T12:00:00+00:00",
    }
    (folder / "install.json").write_text(json.dumps(marker), encoding="utf-8")
    return exe
