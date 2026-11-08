"""core/engine.py: manifest, platform key, zip-entry safety, validation, eval wording (FR-7.2, 7.5, 7.6)."""

from __future__ import annotations

import copy

import chess
import pytest

from weaksquare.core.engine import (
    EngineLine,
    InstallError,
    UnsupportedPlatform,
    check_zip_names,
    format_score,
    game_over_text,
    parse_manifest,
    platform_key,
    refutation_plies,
    validate_fen,
    validate_line,
)
from weaksquare.core.errors import ValidationError

SHA = "a" * 64
GOOD = {
    "engines": {
        "stockfish": {
            "tag": "sf_19",
            "assets": {
                "windows-x86_64": {
                    "name": "sf.zip",
                    "url": "https://github.com/official-stockfish/Stockfish/releases/download/sf_19/sf.zip",
                    "sha256": SHA,
                    "size": 123,
                    "exe_member": "stockfish/stockfish.exe",
                }
            },
        }
    }
}


def _with(**changes: object) -> dict:
    data = copy.deepcopy(GOOD)
    data["engines"]["stockfish"]["assets"]["windows-x86_64"].update(changes)
    return data


# ---- manifest ---------------------------------------------------------------------------------


def test_parse_manifest_good() -> None:
    m = parse_manifest(GOOD)
    assert m.tag == "sf_19"
    a = m.asset_for("windows-x86_64")
    assert (a.name, a.sha256, a.size, a.exe_member) == ("sf.zip", SHA, 123, "stockfish/stockfish.exe")


@pytest.mark.parametrize(
    "changes",
    [
        {"sha256": "A" * 64},  # uppercase
        {"sha256": "a" * 63},
        {"url": "http://github.com/x/sf.zip"},
        {"url": "https://example.com/x/sf.zip"},
        {"url": "https://github.com/x/other.zip"},  # must end in the asset name
        {"name": "sf.tar"},
        {"size": 0},
        {"exe_member": "../stockfish.exe"},
        {"exe_member": "C:/stockfish.exe"},
        {"exe_member": "stockfish/readme.txt"},
    ],
)
def test_parse_manifest_rejects_bad_assets(changes: dict) -> None:
    with pytest.raises(ValueError):
        parse_manifest(_with(**changes))


def test_parse_manifest_rejects_missing_parts() -> None:
    with pytest.raises(ValueError):
        parse_manifest({})
    with pytest.raises(ValueError):
        parse_manifest({"engines": {"stockfish": {"tag": "sf_19", "assets": {}}}})


def test_unsupported_platform_is_a_clear_refusal() -> None:
    m = parse_manifest(GOOD)
    with pytest.raises(UnsupportedPlatform) as e:
        m.asset_for("linux-x86_64")
    assert "linux-x86_64" in e.value.message and e.value.code == "unsupported_platform"


@pytest.mark.parametrize(
    ("system", "machine", "key"),
    [
        ("Windows", "AMD64", "windows-x86_64"),
        ("Windows", "ARM64", "windows-arm64"),
        ("Linux", "x86_64", "linux-x86_64"),
        ("Darwin", "arm64", "macos-arm64"),
        ("", "", "unknown-unknown"),
    ],
)
def test_platform_key(system: str, machine: str, key: str) -> None:
    assert platform_key(system, machine) == key


# ---- zip entries ------------------------------------------------------------------------------

EXE = "stockfish/stockfish.exe"


def test_check_zip_names_returns_the_exe() -> None:
    assert check_zip_names(["stockfish/", EXE, "stockfish/README.md"], EXE) == EXE


@pytest.mark.parametrize(
    "bad",
    [
        "../evil.exe",
        "stockfish/../../evil.exe",
        "/abs/evil.exe",
        "\\abs\\evil.exe",
        "C:/evil.exe",
        "c:evil.exe",
        "stockfish\\..\\..\\evil.exe",
    ],
)
def test_check_zip_names_rejects_the_whole_archive(bad: str) -> None:
    with pytest.raises(InstallError) as e:
        check_zip_names([EXE, bad], EXE)
    assert e.value.code == "unsafe_archive"


def test_check_zip_names_missing_exe() -> None:
    with pytest.raises(InstallError) as e:
        check_zip_names(["stockfish/README.md"], EXE)
    assert e.value.code == "unexpected_archive"


# ---- validation (FR-7.6) ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fen",
    [
        "",
        None,
        42,
        "not a fen",
        "8/8/8/8/8/8/8/8 w - - 0 1",  # no kings
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1 " + "x" * 200,
        "4k3/8/8/8/8/8/8/4K2R b K - 0 1 extra",
        "4k3/4Q3/8/8/8/8/8/4K3 w - - 0 1",  # the side not to move is in check
    ],
)
def test_validate_fen_rejects(fen: object) -> None:
    with pytest.raises(ValidationError):
        validate_fen(fen)


def test_validate_fen_accepts_a_legal_position() -> None:
    assert validate_fen(chess.STARTING_FEN).fen() == chess.STARTING_FEN


def test_validate_line_plays_legal_moves_and_refuses_illegal_ones() -> None:
    board = validate_line(chess.STARTING_FEN, ["e2e4", "e7e5"])
    assert board.fen().startswith("rnbqkbnr/pppp1ppp/8/4p3/4P3")
    for bad in (["e2e5"], ["e2e4", "e2e4"], ["zz"], [None], "e2e4"):
        with pytest.raises(ValidationError):
            validate_line(chess.STARTING_FEN, bad)


# ---- eval wording (FR-7.2: from your side) ----------------------------------------------------


@pytest.mark.parametrize(
    ("cp", "mate", "player", "text"),
    [
        (320, None, "white", "+3.2 for you"),
        (320, None, "black", "\u22123.2 for you"),
        (-140, None, "black", "+1.4 for you"),
        (4, None, "white", "0.0 (level)"),
        (None, 3, "white", "You mate in 3"),
        (None, 3, "black", "You're mated in 3"),
        (None, -2, "black", "You mate in 2"),
        (None, -2, "white", "You're mated in 2"),
    ],
)
def test_format_score_from_your_side(cp: int | None, mate: int | None, player: str, text: str) -> None:
    assert format_score(EngineLine(cp, mate, ()), player) == text  # type: ignore[arg-type]


def test_game_over_text() -> None:
    mated = chess.Board("rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3")  # fool's mate
    assert game_over_text(mated, "white") == "You're checkmated"
    assert game_over_text(mated, "black") == "Checkmate: you win"
    assert game_over_text(chess.Board("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"), "white") == "Stalemate: a draw"
    assert game_over_text(chess.Board(), "white") is None


def test_refutation_is_at_most_five_plies() -> None:
    assert refutation_plies(("a", "b", "c", "d", "e", "f", "g")) == ("a", "b", "c", "d", "e")
    assert refutation_plies(("a", "b")) == ("a", "b")


# ---- v0.15 (FR-14.4): the Analysis tab words evals from White's side, since you play both -------------------------
@pytest.mark.parametrize(
    ("cp", "mate", "text"),
    [(30, None, "+0.3"), (-140, None, "−1.4"), (0, None, "0.0 (level)"), (None, 3, "White mates in 3"),
     (None, -2, "Black mates in 2")],
)  # fmt: skip
def test_the_both_viewpoint_is_whites_side_and_never_says_you(cp: int | None, mate: int | None, text: str) -> None:
    from weaksquare.core.engine import EngineLine, format_score

    assert format_score(EngineLine(cp, mate, ("e2e4",)), "both") == text
    assert "you" not in format_score(EngineLine(cp, mate, ("e2e4",)), "both").lower()


def test_the_both_viewpoint_names_the_winner_of_a_checkmate() -> None:
    import chess

    from weaksquare.core.engine import game_over_text

    fools_mate = chess.Board("rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3")
    assert game_over_text(fools_mate, "both") == "Checkmate: Black wins"
    assert game_over_text(fools_mate, "white") == "You're checkmated"
