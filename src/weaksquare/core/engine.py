"""Engine rules (FR-7.x), pure: the install manifest, zip-entry safety, input validation, eval wording.

- The manifest pins one Stockfish release per OS/CPU key (FR-7.5). Only `windows-x86_64` exists until v1.1.
- Stockfish 19 terminates on an invalid FEN or an illegal move (FR-7.6), so every position and move
  list is checked here with python-chess before anything is sent to the engine.
- Evals are worded from the solver's side (FR-7.2): "+3.2 for you", "You're mated in 2".
- `EngineClient` is the protocol the services use. v0.8 adds a second (background) instance of the
  same protocol for the analysis queue; it doesn't add methods.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import chess

from weaksquare.core.errors import AppError, ValidationError
from weaksquare.core.puzzle import Color

SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
MAX_FEN_LEN = 100
MAX_LINE_LEN = 400  # plies; far more than any line we send
REFUTATION_MIN_PLIES = 3
REFUTATION_MAX_PLIES = 5


class EngineError(AppError):
    """The engine failed one request (crash, timeout, bad output). The next request may work."""

    code = "engine_error"
    retryable = True


class EngineNotInstalled(AppError):
    code = "engine_not_installed"
    retryable = False


class UnsupportedPlatform(AppError):
    code = "unsupported_platform"
    retryable = False


class InstallError(AppError):
    code = "install_failed"
    retryable = True


# ---- manifest (FR-7.5) ----------------------------------------------------------------------------


@dataclass(frozen=True)
class ManifestAsset:
    name: str  # the release asset's file name
    url: str
    sha256: str  # GitHub's published digest for the asset, lowercase hex
    size: int
    exe_member: str  # the .exe's path inside the zip


@dataclass(frozen=True)
class EngineManifest:
    tag: str
    assets: dict[str, ManifestAsset]

    def asset_for(self, key: str) -> ManifestAsset:
        asset = self.assets.get(key)
        if asset is None:
            raise UnsupportedPlatform(
                f"There's no Stockfish build for this computer ({key}) yet. Only Windows (x86-64) is supported "
                "for now. You can point Settings → Engine at your own Stockfish instead."
            )
        return asset


def parse_manifest(data: Any) -> EngineManifest:
    """Parse and check `engine_manifest.json`. Any problem is a ValueError: the file ships with the app."""
    try:
        sf = data["engines"]["stockfish"]
        tag = sf["tag"]
        raw_assets = sf["assets"]
    except (KeyError, TypeError):
        raise ValueError("engine manifest: missing engines.stockfish.{tag,assets}") from None
    if not isinstance(tag, str) or not re.fullmatch(r"[A-Za-z0-9._-]+", tag):
        raise ValueError("engine manifest: bad tag")
    if not isinstance(raw_assets, dict) or not raw_assets:
        raise ValueError("engine manifest: no assets")
    assets: dict[str, ManifestAsset] = {}
    for key, a in raw_assets.items():
        try:
            asset = ManifestAsset(
                name=str(a["name"]),
                url=str(a["url"]),
                sha256=str(a["sha256"]),
                size=int(a["size"]),
                exe_member=str(a["exe_member"]),
            )
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"engine manifest: asset {key} is incomplete") from None
        if not re.fullmatch(r"[a-z]+-[a-z0-9_]+", key):
            raise ValueError(f"engine manifest: bad platform key {key}")
        if not SHA256_HEX.match(asset.sha256):
            raise ValueError(f"engine manifest: asset {key} sha256 must be 64 lowercase hex characters")
        if not asset.url.startswith("https://github.com/") or not asset.url.endswith("/" + asset.name):
            raise ValueError(f"engine manifest: asset {key} URL must be the https GitHub release URL of {asset.name}")
        if not asset.name.endswith(".zip") or asset.size <= 0:
            raise ValueError(f"engine manifest: asset {key} must be a non-empty .zip")
        if _unsafe_name(asset.exe_member) or not asset.exe_member.lower().endswith(".exe"):
            raise ValueError(f"engine manifest: asset {key} exe_member must be a relative .exe path")
        assets[key] = asset
    return EngineManifest(tag=tag, assets=assets)


_SYSTEMS = {"windows": "windows", "darwin": "macos", "linux": "linux"}
_MACHINES = {"amd64": "x86_64", "x86_64": "x86_64", "x64": "x86_64", "arm64": "arm64", "aarch64": "arm64"}


def platform_key(system: str, machine: str) -> str:
    """`platform.system()` / `platform.machine()` → the manifest key, e.g. `windows-x86_64`."""
    s = _SYSTEMS.get(system.strip().lower(), system.strip().lower() or "unknown")
    m = _MACHINES.get(machine.strip().lower(), machine.strip().lower() or "unknown")
    return f"{s}-{m}"


def _unsafe_name(name: str) -> bool:
    n = name.replace("\\", "/")
    if not n or n.startswith("/") or re.match(r"^[A-Za-z]:", n) or "\x00" in n:
        return True
    return any(part == ".." for part in n.split("/"))


def check_zip_names(names: list[str], exe_member: str) -> str:
    """Refuse the whole archive if any entry is absolute, has a drive letter or a `..` part.

    Returns the entry to extract (only that one is ever written). Raises InstallError otherwise.
    """
    bad = [n for n in names if _unsafe_name(n)]
    if bad:
        raise InstallError(
            "The downloaded archive contains unsafe paths, so nothing was extracted.", code="unsafe_archive"
        )
    if exe_member not in names:
        raise InstallError(
            "The downloaded archive doesn't contain the expected Stockfish program.", code="unexpected_archive"
        )
    return exe_member


# ---- input validation (FR-7.6) --------------------------------------------------------------------


def validate_fen(fen: Any) -> chess.Board:
    """A legal position python-chess accepts, or ValidationError. Never send anything else."""
    if not isinstance(fen, str) or not fen.strip() or len(fen) > MAX_FEN_LEN:
        raise ValidationError("That isn't a valid position.")
    try:
        board = chess.Board(fen.strip())
    except ValueError:
        raise ValidationError("That isn't a valid position.") from None
    if not board.is_valid():
        raise ValidationError("That position isn't legal.")
    return board


def validate_line(fen: Any, moves: Any) -> chess.Board:
    """The position after playing `moves` (UCI) from `fen`, every move checked for legality."""
    board = validate_fen(fen)
    if not isinstance(moves, list | tuple) or len(moves) > MAX_LINE_LEN:
        raise ValidationError("That isn't a valid move list.")
    for uci in moves:
        try:
            move = chess.Move.from_uci(uci) if isinstance(uci, str) else None
        except ValueError:
            move = None
        if move is None or move not in board.legal_moves:
            raise ValidationError("That move list contains an illegal move.")
        board.push(move)
    return board


# ---- engine output ----------------------------------------------------------------------------


@dataclass(frozen=True)
class EngineLine:
    """One MultiPV line. The score is from White's point of view; exactly one of cp / mate is set."""

    cp: int | None
    mate: int | None  # moves to mate; positive means White mates
    pv: tuple[str, ...]  # UCI


@dataclass(frozen=True)
class EngineInfo:
    name: str  # the engine's `id name`, e.g. "Stockfish 19"


class EngineClient(Protocol):
    """One running UCI engine. Calls are serialized by the implementation and never hang (FR-7.6)."""

    def analyse(self, board: chess.Board, think_s: float, multipv: int) -> list[EngineLine]: ...

    def configure(self, threads: int, hash_mb: int) -> None: ...

    def info(self) -> EngineInfo: ...

    def close(self) -> None: ...


class EngineProbe(Protocol):
    """FR-7.5 smoke test: `uci` → `uciok`, and a short search from the start returns a legal move."""

    def __call__(self, path: str, /) -> EngineInfo: ...


def _relative(cp: int | None, mate: int | None, player: Color) -> tuple[int | None, int | None]:
    sign = 1 if player == "white" else -1
    return (None if cp is None else cp * sign, None if mate is None else mate * sign)


def score_for(line: EngineLine, player: Color) -> tuple[int | None, int | None]:
    """The score from the solver's side: (cp, mate), positive = good for you."""
    return _relative(line.cp, line.mate, player)


Viewpoint = Color | Literal["both"]  # v0.15: "both" is the Analysis tab, where you play either side


def format_score(line: EngineLine, player: Viewpoint) -> str:
    """FR-7.2: "+3.2 for you", "−1.4 for you", "0.0 (level)", "You mate in 3", "You're mated in 2". From the
    viewpoint "both" (the Analysis tab, FR-14.4) it's White's side, as on Lichess: "+3.2", "White mates in 3"."""
    if player == "both":
        return _neutral_score(line)
    cp, mate = score_for(line, player)
    if mate is not None:
        n = abs(mate)
        if mate > 0:
            return f"You mate in {n}"
        return f"You're mated in {n}" if n else "You're mated"
    value = (cp or 0) / 100
    if round(value, 1) == 0:
        return "0.0 (level)"
    sign = "+" if value > 0 else "−"
    return f"{sign}{abs(value):.1f} for you"


def _neutral_score(line: EngineLine) -> str:
    cp, mate = score_for(line, "white")
    if mate is not None:
        n = abs(mate)
        if n == 0:
            return "Checkmate"
        return f"{'White' if mate > 0 else 'Black'} mates in {n}"
    value = (cp or 0) / 100
    if round(value, 1) == 0:
        return "0.0 (level)"
    return f"{'+' if value > 0 else '−'}{abs(value):.1f}"


def game_over_text(board: chess.Board, player: Viewpoint) -> str | None:
    """The result text for a position the engine needn't see (mate, stalemate, draw), else None."""
    if board.is_checkmate():
        mated_white = board.turn == chess.WHITE
        if player == "both":
            return "Checkmate: Black wins" if mated_white else "Checkmate: White wins"
        return "You're checkmated" if (player == "white") == mated_white else "Checkmate: you win"
    if board.is_stalemate():
        return "Stalemate: a draw"
    if board.is_insufficient_material():
        return "Draw: insufficient material"
    return None


def refutation_plies(pv: tuple[str, ...]) -> tuple[str, ...]:
    """The best reply line, at most 5 plies (§7.2: 3–5; shorter only when the game ends sooner)."""
    return pv[:REFUTATION_MAX_PLIES]
