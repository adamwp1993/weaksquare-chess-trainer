"""A tiny UCI engine for tests, run as `[sys.executable, this file, mode, state_file]`.

It behaves like Stockfish 19 where that matters (FR-7.6): an invalid position makes it print
`info string CRITICAL ERROR …` and exit. Modes:
- normal: answers every search; mating moves first, then captures, then the rest (by UCI)
- hang: never answers `go` (and ignores `stop`)
- once: the first launch works; every later launch (counted in state_file) exits before `uciok`
- noise: prints `uciok` without an `id name`
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import chess


def out(line: str) -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def ranked(board: chess.Board) -> list[tuple[chess.Move, str]]:
    scored = []
    for move in board.legal_moves:
        board.push(move)
        mate = board.is_checkmate()
        board.pop()
        if mate:
            scored.append((0, move.uci(), move, "mate 1"))
        elif board.is_capture(move):
            scored.append((1, move.uci(), move, "cp 300"))
        else:
            scored.append((2, move.uci(), move, "cp 10"))
    scored.sort(key=lambda t: (t[0], t[1]))
    return [(m, s) for _, _, m, s in scored]


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "normal"
    state = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    if state is not None:
        launches = int(state.read_text() or "0") + 1 if state.exists() else 1
        state.write_text(str(launches))
        if mode == "once" and launches > 1:
            return 3
    board = chess.Board()
    multipv = 1
    for raw in sys.stdin:
        line = raw.strip()
        if line == "uci":
            if mode != "noise":
                out("id name FakeFish 1")
            out("option name Threads type spin default 1 min 1 max 512")
            out("option name Hash type spin default 16 min 1 max 33554432")
            out("option name MultiPV type spin default 1 min 1 max 500")
            out("uciok")
        elif line == "isready":
            out("readyok")
        elif line.startswith("setoption name MultiPV value"):
            multipv = int(line.rsplit(" ", 1)[1])
        elif line.startswith("position"):
            parts = line.split(" moves ")
            head = parts[0]
            try:
                board = (
                    chess.Board() if head.strip() == "position startpos" else chess.Board(head[len("position fen ") :])
                )
                for uci in parts[1].split() if len(parts) > 1 else []:
                    move = chess.Move.from_uci(uci)
                    if move not in board.legal_moves:
                        raise ValueError("illegal move")
                    board.push(move)
                if not board.is_valid():
                    raise ValueError("invalid position")
            except ValueError as e:
                out(f"info string CRITICAL ERROR: {e}")
                return 1
        elif line.startswith("go"):
            if mode == "hang":
                while True:
                    time.sleep(1)
            moves = ranked(board)
            if not moves:
                out("info depth 0 score mate 0")
                out("bestmove (none)")
                continue
            for i, (move, score) in enumerate(moves[:multipv], start=1):
                board.push(move)
                reply = next(iter(board.legal_moves), None)
                board.pop()
                pv = move.uci() + (f" {reply.uci()}" if reply and score != "mate 1" else "")
                out(f"info depth 1 multipv {i} score {score} pv {pv}")
            out(f"bestmove {moves[0][0].uci()}")
        elif line == "quit":
            return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
