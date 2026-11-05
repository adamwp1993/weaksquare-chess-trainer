"""Lesson pointers (v0.11, FR-10.59). Pure: the topic catalog the AI may pick from, the in-app drill for a
topic, a curated map of stable free pages, and search links. **Every URL is built here**: the AI only
names a topic id, and the screen only sends a topic id and a target, so nothing the AI wrote can become a
link (FR-10.59, v0.11 planning).

The curated map is **Lichess Practice and Lichess Learn only** (Adam, v0.11 planning). Lichess Practice
links are `/practice/<section>/<slug>/<study id>`; the study id is what Lichess resolves (any slug
works), so each was checked against https://lichess.org/practice on 2026-11-04.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote_plus, urlsplit

from weaksquare.core import themes
from weaksquare.core.digest import ENDGAME_TYPES

ALLOWED_HOSTS = frozenset({"lichess.org"})
LOWER_BAND = 200  # FR-10.59: "Learn X" drills 200 below your band
BAND = 150
DRILL_SIZE = 20
MAX_CUSTOM_URL = 300
THEME_GROUPS = ("Motifs", "Advanced", "Mates", "Mate patterns", "Special moves")
ENDGAME_THEMES = ("endgame", "rookEndgame", "bishopEndgame", "pawnEndgame", "knightEndgame", "queenEndgame")

SEARCH_SITES: dict[str, tuple[str, str]] = {
    "youtube": ("YouTube", "https://www.youtube.com/results?search_query={q}"),
    "chesscom": ("chess.com", "https://www.chess.com/search?q={q}"),
}
DEFAULT_SITES = ("youtube", "chesscom")

_P = "https://lichess.org/practice/"
_PIN = ("Lichess Practice: The Pin", _P + "fundamental-tactics/the-pin/9ogFv8Ac")
_SKEWER = ("Lichess Practice: The Skewer", _P + "fundamental-tactics/the-skewer/tuoBxVE5")
_FORK = ("Lichess Practice: The Fork", _P + "fundamental-tactics/the-fork/Qj281y1p")
_DISCOVERED = ("Lichess Practice: Discovered Attacks", _P + "fundamental-tactics/discovered-attacks/MnsJEWnI")
_DOUBLE = ("Lichess Practice: Double Check", _P + "fundamental-tactics/double-check/RUQASaZm")
_OVERLOADED = ("Lichess Practice: Overloaded Pieces", _P + "fundamental-tactics/overloaded-pieces/o734CNqp")
_ZWISCHENZUG = ("Lichess Practice: Zwischenzug", _P + "fundamental-tactics/zwischenzug/ITWY4GN2")
_XRAY = ("Lichess Practice: X-Ray", _P + "fundamental-tactics/x-ray/lyVYjhPG")
_ZUGZWANG = ("Lichess Practice: Zugzwang", _P + "advanced-tactics/zugzwang/9cKgYrHb")
_INTERFERENCE = ("Lichess Practice: Interference", _P + "advanced-tactics/interference/g1fxVZu9")
_GREEK = ("Lichess Practice: Greek Gift", _P + "advanced-tactics/greek-gift/s5pLU7Of")
_DEFLECTION = ("Lichess Practice: Deflection", _P + "advanced-tactics/deflection/kdKpaYLW")
_ATTRACTION = ("Lichess Practice: Attraction", _P + "advanced-tactics/attraction/jOZejFWk")
_UNDERPROMOTION = ("Lichess Practice: Underpromotion", _P + "advanced-tactics/underpromotion/49fDW0wP")
_DESPERADO = ("Lichess Practice: Desperado", _P + "advanced-tactics/desperado/0YcGiH4Y")
_COUNTER_CHECK = ("Lichess Practice: Counter Check", _P + "advanced-tactics/counter-check/CgjKPvxQ")
_UNDERMINING = ("Lichess Practice: Undermining", _P + "advanced-tactics/undermining/udx042D6")
_CLEARANCE = ("Lichess Practice: Clearance", _P + "advanced-tactics/clearance/Grmtwuft")
_MATES = [
    ("Lichess Practice: Checkmate Patterns I", _P + "checkmates/checkmate-patterns-i/fE4k21MW"),
    ("Lichess Practice: Checkmate Patterns II", _P + "checkmates/checkmate-patterns-ii/8yadFPpU"),
    ("Lichess Practice: Checkmate Patterns III", _P + "checkmates/checkmate-patterns-iii/PDkQDt6u"),
    ("Lichess Practice: Checkmate Patterns IV", _P + "checkmates/checkmate-patterns-iv/96Lij7wH"),
]
_PIECE_MATES = [
    ("Lichess Practice: Piece Checkmates I", _P + "checkmates/piece-checkmates-i/BJy6fEDf"),
    ("Lichess Practice: Piece Checkmates II", _P + "checkmates/piece-checkmates-ii/Rg2cMBZ6"),
    ("Lichess Practice: Knight & Bishop Mate", _P + "checkmates/knight-and-bishop-mate/ByhlXnmM"),
]
_PAWN_ENDINGS = [
    ("Lichess Practice: Key Squares", _P + "pawn-endgames/key-squares/xebrDvFe"),
    ("Lichess Practice: Opposition", _P + "pawn-endgames/opposition/A4ujYOer"),
    ("Lichess Practice: 7th-Rank Rook Pawn (pawn endgames)", _P + "pawn-endgames/7th-rank-rook-pawn/pt20yRkT"),
]
_ROOK_ENDINGS = [
    ("Lichess Practice: Basic Rook Endgames", _P + "rook-endgames/basic-rook-endgames/pqUSUw8Y"),
    ("Lichess Practice: Intermediate Rook Endings", _P + "rook-endgames/intermediate-rook-endings/heQDnvq7"),
    ("Lichess Practice: Practical Rook Endings", _P + "rook-endgames/practical-rook-endings/wS23j5Tm"),
    ("Lichess Practice: 7th-Rank Rook Pawn (rook endgames)", _P + "rook-endgames/7th-rank-rook-pawn/MkDViieT"),
]
_LEARN = ("Lichess Learn: chess basics", "https://lichess.org/learn")

CURATED: dict[str, list[tuple[str, str]]] = {
    "theme:pin": [_PIN],
    "theme:skewer": [_SKEWER],
    "theme:fork": [_FORK],
    "theme:discoveredAttack": [_DISCOVERED],
    "theme:discoveredCheck": [_DISCOVERED],
    "theme:doubleCheck": [_DOUBLE],
    "theme:intermezzo": [_ZWISCHENZUG, _COUNTER_CHECK],
    "theme:xRayAttack": [_XRAY],
    "theme:zugzwang": [_ZUGZWANG],
    "theme:interference": [_INTERFERENCE],
    "theme:deflection": [_DEFLECTION, _OVERLOADED],
    "theme:attraction": [_ATTRACTION],
    "theme:underPromotion": [_UNDERPROMOTION],
    "theme:clearance": [_CLEARANCE],
    "theme:capturingDefender": [_UNDERMINING, _OVERLOADED],
    "theme:sacrifice": [_GREEK, _DESPERADO],
    "theme:kingsideAttack": [_GREEK],
    "theme:mate": _PIECE_MATES,
    "theme:pawnEndgame": _PAWN_ENDINGS,
    "theme:rookEndgame": _ROOK_ENDINGS,
    "endgame:pawn": _PAWN_ENDINGS,
    "endgame:rook": _ROOK_ENDINGS,
    "theme:castling": [_LEARN],
    "theme:enPassant": [_LEARN],
    "theme:promotion": [_LEARN],
    "concept:development": [_LEARN],
}
for _mate in ("mateIn1", "mateIn2", "mateIn3", "mateIn4", "mateIn5"):
    CURATED[f"theme:{_mate}"] = _MATES
for _key in themes.keys_in_groups(("Mate patterns",)):
    CURATED[f"theme:{_key}"] = _MATES

ENDGAME_LABELS = {
    "pawn": "King and pawn endgames",
    "rook": "Rook endgames",
    "minor": "Minor-piece endgames",
    "queen": "Queen endgames",
    "mixed": "Endgames with mixed pieces",
}
ENDGAME_DRILL: dict[str, tuple[str, ...]] = {
    "pawn": ("pawnEndgame",),
    "rook": ("rookEndgame",),
    "minor": ("bishopEndgame", "knightEndgame"),
    "queen": ("queenEndgame",),
    "mixed": ("endgame",),
}
CONCEPTS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    # id: (label, search words, drill themes)
    "kingSafety": ("King safety and castling", "chess king safety castling", ("kingsideAttack", "exposedKing")),
    "development": ("Development in the opening", "chess opening development principles", ()),
    "pawnStructure": ("Pawn structure", "chess pawn structure", ()),
    "isolatedPawn": ("Playing with and against an isolated pawn", "chess isolated queen pawn", ()),
    "conversion": ("Converting a winning position", "chess how to convert a winning position", ("crushing",)),
    "defence": ("Defending worse positions", "chess defending worse positions", ("defensiveMove",)),
    "trades": ("When to trade pieces", "chess when to trade pieces", ()),
    "timeManagement": ("Time management", "chess time management clock", ()),
    "calculation": ("Calculation", "chess calculation training", ("long", "veryLong")),
    "blunderCheck": ("Checking for threats before you move", "chess blunder check threats", ("hangingPiece",)),
}


@dataclass(frozen=True)
class Topic:
    id: str
    label: str
    query: str  # the words a search link sends
    drill: tuple[str, ...]  # puzzle themes for "Learn X", empty when there's no drill


def theme_topics() -> list[Topic]:
    keys = [*themes.keys_in_groups(THEME_GROUPS), *ENDGAME_THEMES, "mate"]
    return [Topic(f"theme:{k}", themes.display_name(k), f"chess {themes.display_name(k).lower()}", (k,)) for k in keys]


def catalog(families: list[str] | tuple[str, ...] = ()) -> list[Topic]:
    """Every topic the AI may pick (FR-10.59): themes, endgame types, the opening families of this run's
    games and a few concepts."""
    out = theme_topics()
    out += [Topic(f"endgame:{t}", ENDGAME_LABELS[t], f"chess {ENDGAME_LABELS[t].lower()}", ENDGAME_DRILL[t])
            for t in ENDGAME_TYPES]  # fmt: skip
    out += [Topic(f"concept:{k}", lbl, q, d) for k, (lbl, q, d) in CONCEPTS.items()]
    for fam in dict.fromkeys(families):
        if fam and fam != "Unknown":
            out.append(Topic(f"opening:{fam}", fam, f"chess {fam}", ()))
    return out


def topic(topic_id: str, families: list[str] | tuple[str, ...] = ()) -> Topic | None:
    if topic_id.startswith("opening:"):
        fam = topic_id.split(":", 1)[1]
        return Topic(topic_id, fam, f"chess {fam}", ()) if fam in families else None
    return next((t for t in catalog() if t.id == topic_id), None)


def curated(topic_id: str) -> list[tuple[str, str]]:
    return list(CURATED.get(topic_id, []))


def is_allowed(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.hostname in ALLOWED_HOSTS and not parts.username and not parts.port


def validate_custom_template(template: str) -> str:
    """A custom search site (FR-10.59 settings): an https URL with exactly one `{q}`. Raises ValueError."""
    t = template.strip()
    if not t:
        return ""
    if len(t) > MAX_CUSTOM_URL or any(c.isspace() for c in t):
        raise ValueError("The search address can't contain spaces and must be at most 300 characters.")
    if t.count("{q}") != 1:
        raise ValueError("Put {q} once in the search address, where the search words go.")
    parts = urlsplit(t.replace("{q}", "x"))
    if parts.scheme != "https" or not parts.hostname or "." not in parts.hostname or parts.username:
        raise ValueError("The search address must start with https:// and name a website.")
    return t


def search_url(site: str, t: Topic, custom_template: str = "") -> str:
    """A search link built by the app: the topic's words, URL-encoded, in the site's template."""
    if site == "custom":
        template = validate_custom_template(custom_template)
        if not template:
            raise ValueError("No custom search site is set.")
    elif site in SEARCH_SITES:
        template = SEARCH_SITES[site][1]
    else:
        raise ValueError("Unknown search site.")
    return template.replace("{q}", quote_plus(t.query))


def drill_preset(t: Topic, center: int) -> dict[str, object] | None:
    """FR-10.59 "Learn X": the topic's puzzles in Standard mode, 200 below your band (Explain encouraged),
    in the AI preset's shape (validated by `preset_suggestion.validate_coach_preset`)."""
    if not t.drill:
        return None
    c = max(600, center - LOWER_BAND)
    return {
        "name": f"Learn: {t.label}",
        "themes": list(t.drill),
        "rating_min": c - BAND,
        "rating_max": c + BAND,
        "lengths": [],
        "mode": "standard",
        "queue_size": DRILL_SIZE,
    }
