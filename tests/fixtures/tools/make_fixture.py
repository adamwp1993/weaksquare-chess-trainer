"""Build tests/fixtures/puzzles_sample.csv from a full Lichess puzzle export (dev-only, run once).

    uv run python tests/fixtures/tools/make_fixture.py PATH\\TO\\lichess_db_puzzle.csv.zst

Deterministic (seeded) sample of ~300 puzzles, plus puzzles that exercise edge cases (mate-in-1
with an alternative mate, promotion, en passant, castling, very long lines). GameUrl is replaced by
an obvious placeholder so the public repo holds no real game IDs or URLs (SR-12a). All other
columns are kept, including extra ones such as DailyDate, so the header-name parsing is exercised.
"""

from __future__ import annotations

import csv
import io
import random
import sys
from pathlib import Path

import chess
import zstandard

OUT = Path(__file__).resolve().parents[1] / "puzzles_sample.csv"
TARGET = 300
TOTAL_ESTIMATE = 6_000_000


def has_alternative_mate(fen: str, moves: list[str]) -> bool:
    board = chess.Board(fen)
    board.push_uci(moves[0])
    expected = chess.Move.from_uci(moves[1])
    mates = []
    for m in board.legal_moves:
        board.push(m)
        if board.is_checkmate():
            mates.append(m)
        board.pop()
    return len(mates) >= 2 and expected in mates


def main() -> int:
    src = Path(sys.argv[1])
    rng = random.Random(2026)
    reader = csv.reader(io.TextIOWrapper(zstandard.ZstdDecompressor().stream_reader(src.open("rb")), encoding="utf-8"))
    header = next(reader)
    idx = {h: i for i, h in enumerate(header)}
    picked: list[list[str]] = []
    wanted = {"altMate": 3, "underPromotion": 3, "enPassant": 3, "castling": 3, "veryLong": 6, "mateIn1": 6}
    for row in reader:
        themes = row[idx["Themes"]].split()
        moves = row[idx["Moves"]].split()
        take = rng.random() < TARGET / TOTAL_ESTIMATE
        for key in ("underPromotion", "enPassant", "castling", "veryLong", "mateIn1"):
            if key in themes and wanted[key] > 0 and rng.random() < 0.01:
                wanted[key] -= 1
                take = True
        if "mateIn1" in themes and wanted["altMate"] > 0 and has_alternative_mate(row[idx["FEN"]], moves):
            wanted["altMate"] -= 1
            take = True
        if take:
            picked.append(row)
    for n, row in enumerate(picked, 1):
        row[idx["GameUrl"]] = f"https://lichess.org/GAMEID{n:02d}"
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(picked)
    print(f"wrote {len(picked)} puzzles to {OUT} (unfilled quotas: {wanted})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
