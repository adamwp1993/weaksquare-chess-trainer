"""Parse rows of the Lichess puzzle CSV by header name (FR-2.2). Extra columns (e.g. DailyDate) are ignored.

Validation here is cheap shape checking only (6M rows must import in minutes). Full legality is
checked with python-chess when a puzzle is served (core.chess_rules.start_position); the few
puzzles that fail are skipped then.
"""

from __future__ import annotations

from dataclasses import dataclass

from weaksquare.core.chess_rules import PuzzleDataError, looks_like_move_list, player_color_from_fen
from weaksquare.core.puzzle import Color
from weaksquare.core.themes import is_valid_key

REQUIRED = ("PuzzleId", "FEN", "Moves", "Rating", "RatingDeviation", "Popularity", "NbPlays", "Themes", "GameUrl")
OPTIONAL = ("OpeningTags",)


class HeaderError(ValueError):
    """The CSV doesn't have the columns a Lichess puzzle export must have."""


@dataclass(frozen=True)
class PuzzleRow:
    id: str
    fen: str
    moves: str
    rating: int
    rating_dev: int
    popularity: int
    nb_plays: int
    themes: tuple[str, ...]
    game_url: str
    opening_tags: str
    length: int
    player_color: Color


def header_index(header: list[str]) -> dict[str, int]:
    """Map column names to positions. Raises HeaderError if a required column is missing."""
    index = {name.strip().lstrip("﻿"): i for i, name in enumerate(header)}
    missing = [c for c in REQUIRED if c not in index]
    if missing:
        raise HeaderError(f"not a Lichess puzzle CSV: missing column(s) {', '.join(missing)}")
    return index


def parse_row(index: dict[str, int], row: list[str]) -> PuzzleRow | None:
    """A parsed row, or None if the row is malformed (it's skipped and counted)."""
    try:
        moves = row[index["Moves"]].split()
        fen = row[index["FEN"]].strip()
        pid = row[index["PuzzleId"]].strip()
        if not pid or not pid.isalnum() or not looks_like_move_list(moves):
            return None
        themes = tuple(t for t in row[index["Themes"]].split() if is_valid_key(t))
        opening = (
            row[index["OpeningTags"]].strip() if "OpeningTags" in index and index["OpeningTags"] < len(row) else ""
        )
        return PuzzleRow(
            id=pid,
            fen=fen,
            moves=" ".join(moves),
            rating=int(row[index["Rating"]]),
            rating_dev=int(row[index["RatingDeviation"]]),
            popularity=int(row[index["Popularity"]]),
            nb_plays=int(row[index["NbPlays"]]),
            themes=themes,
            game_url=row[index["GameUrl"]].strip(),
            opening_tags=opening,
            length=len(moves) // 2,
            player_color=player_color_from_fen(fen),
        )
    except (IndexError, ValueError, PuzzleDataError):
        return None
