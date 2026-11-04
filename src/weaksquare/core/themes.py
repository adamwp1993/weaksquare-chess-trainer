"""Lichess puzzle theme catalog: keys, English names and picker groups (FR-3.1).

Keys and names follow Lichess's theme list (lila `translation/source/puzzleTheme.xml`, AGPL-3.0).
The picker only shows themes that exist in the imported database; a theme this table doesn't know
goes in the "Other" group with a name derived from its key, so a newer export never breaks the app.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

GROUP_ORDER: tuple[str, ...] = (
    "Motifs",
    "Advanced",
    "Mates",
    "Mate patterns",
    "Phases",
    "Special moves",
    "Goals",
    "Lengths",
    "Origin",
    "Other",
)

# (key, display name), per group, in picker order.
_CATALOG: dict[str, list[tuple[str, str]]] = {
    "Motifs": [
        ("advancedPawn", "Advanced pawn"),
        ("attackingF2F7", "Attacking f2 or f7"),
        ("capturingDefender", "Capture the defender"),
        ("discoveredAttack", "Discovered attack"),
        ("discoveredCheck", "Discovered check"),
        ("doubleCheck", "Double check"),
        ("exposedKing", "Exposed king"),
        ("fork", "Fork"),
        ("hangingPiece", "Hanging piece"),
        ("kingsideAttack", "Kingside attack"),
        ("pin", "Pin"),
        ("queensideAttack", "Queenside attack"),
        ("sacrifice", "Sacrifice"),
        ("skewer", "Skewer"),
        ("trappedPiece", "Trapped piece"),
    ],
    "Advanced": [
        ("attraction", "Attraction"),
        ("clearance", "Clearance"),
        ("defensiveMove", "Defensive move"),
        ("deflection", "Deflection"),
        ("interference", "Interference"),
        ("intermezzo", "Intermezzo"),
        ("quietMove", "Quiet move"),
        ("xRayAttack", "X-Ray attack"),
        ("zugzwang", "Zugzwang"),
    ],
    "Mates": [
        ("mateIn1", "Mate in 1"),
        ("mateIn2", "Mate in 2"),
        ("mateIn3", "Mate in 3"),
        ("mateIn4", "Mate in 4"),
        ("mateIn5", "Mate in 5 or more"),
    ],
    "Mate patterns": [
        ("anastasiaMate", "Anastasia's mate"),
        ("arabianMate", "Arabian mate"),
        ("backRankMate", "Back rank mate"),
        ("balestraMate", "Balestra mate"),
        ("blindSwineMate", "Blind swine mate"),
        ("bodenMate", "Boden's mate"),
        ("cornerMate", "Corner mate"),
        ("doubleBishopMate", "Double bishop mate"),
        ("dovetailMate", "Dovetail mate"),
        ("epauletteMate", "Epaulette mate"),
        ("hookMate", "Hook mate"),
        ("killBoxMate", "Kill box mate"),
        ("morphysMate", "Morphy's mate"),
        ("operaMate", "Opera mate"),
        ("pillsburysMate", "Pillsbury's mate"),
        ("smotheredMate", "Smothered mate"),
        ("swallowstailMate", "Swallow's tail mate"),
        ("triangleMate", "Triangle mate"),
        ("vukovicMate", "Vukovič mate"),
    ],
    "Phases": [
        ("opening", "Opening"),
        ("middlegame", "Middlegame"),
        ("endgame", "Endgame"),
        ("rookEndgame", "Rook endgame"),
        ("bishopEndgame", "Bishop endgame"),
        ("pawnEndgame", "Pawn endgame"),
        ("knightEndgame", "Knight endgame"),
        ("queenEndgame", "Queen endgame"),
        ("queenRookEndgame", "Queen and rook"),
    ],
    "Special moves": [
        ("castling", "Castling"),
        ("enPassant", "En passant"),
        ("promotion", "Promotion"),
        ("underPromotion", "Underpromotion"),
    ],
    "Goals": [
        ("equality", "Equality"),
        ("advantage", "Advantage"),
        ("crushing", "Crushing"),
        ("mate", "Checkmate"),
    ],
    "Lengths": [
        ("oneMove", "One-move puzzle"),
        ("short", "Short puzzle"),
        ("long", "Long puzzle"),
        ("veryLong", "Very long puzzle"),
    ],
    "Origin": [
        ("master", "Master games"),
        ("masterVsMaster", "Master vs Master games"),
        ("superGM", "Super GM games"),
    ],
}

THEME_KEY = re.compile(r"^[A-Za-z0-9]{1,40}$")


@dataclass(frozen=True)
class ThemeInfo:
    key: str
    name: str
    group: str
    order: int  # position within the whole catalog, for stable sorting


_INFO: dict[str, ThemeInfo] = {}
_n = 0
for _group in GROUP_ORDER:
    for _key, _name in _CATALOG.get(_group, []):
        _INFO[_key] = ThemeInfo(_key, _name, _group, _n)
        _n += 1


def humanize(key: str) -> str:
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Za-z])(?=[0-9])", " ", key).split()
    text = " ".join(words).lower()
    return text[:1].upper() + text[1:]


def info(key: str) -> ThemeInfo:
    """Catalog entry for a theme key; unknown keys go in "Other"."""
    found = _INFO.get(key)
    if found:
        return found
    return ThemeInfo(key, humanize(key), "Other", 10_000)


def display_name(key: str) -> str:
    return info(key).name


def keys_in_groups(groups: tuple[str, ...]) -> tuple[str, ...]:
    """The catalog's keys in these groups, in picker order."""
    return tuple(k for g in GROUP_ORDER if g in groups for k, _ in _CATALOG.get(g, []))


def is_valid_key(key: str) -> bool:
    return isinstance(key, str) and bool(THEME_KEY.match(key))


# ---- Name the idea first (FR-4.3, v0.6) -----------------------------------------------------------
# Your tags are graded against the puzzle's motif themes: its themes in these groups.
IDEA_GROUPS: tuple[str, ...] = ("Motifs", "Advanced", "Mate patterns", "Special moves")
# The two pickers. The split only helps you think (Lichess doesn't record which role a theme plays):
# a tag counts wherever you put it.
_SETUP_EXTRA = ("sacrifice", "capturingDefender", "discoveredAttack")
IDEA_SETUP: tuple[str, ...] = tuple(k for k, _ in _CATALOG["Advanced"]) + _SETUP_EXTRA
IDEA_PAYOFF: tuple[str, ...] = tuple(k for g in IDEA_GROUPS for k, _ in _CATALOG[g] if k not in IDEA_SETUP)


def motif_themes(themes: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """The puzzle's themes that idea tags are graded against (unknown "Other" themes don't count)."""
    return tuple(dict.fromkeys(t for t in themes if info(t).group in IDEA_GROUPS))
