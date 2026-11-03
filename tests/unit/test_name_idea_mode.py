"""FR-4.3 Name the idea first: tagging before moving, Standard's rules, and the tag grade."""

from __future__ import annotations

import pytest

from weaksquare.core.errors import ConflictError, ValidationError
from weaksquare.core.modes.name_idea import IdeaTags, NameIdeaMode, grade_tags, parse_tags
from weaksquare.core.modes.standard import StandardMode
from weaksquare.core.puzzle import Puzzle, PuzzleRef
from weaksquare.core.themes import IDEA_PAYOFF, IDEA_SETUP, motif_themes


def puzzle(themes: str) -> Puzzle:
    return Puzzle(
        PuzzleRef("lichess", "T1"),
        "6rk/2p2q2/1p4rp/2PR1b1p/P6Q/1P2p1PP/5P1N/3R2K1 w - - 0 36",
        tuple(["h2f3", "f5g4", "h3g4", "f7f3", "d5h5", "f3d1"]),
        1500,
        tuple(themes.split()),
        "",
        (),
    )


P = puzzle("crushing deflection fork middlegame long")
mode = NameIdeaMode()


def test_pickers_split_the_motifs_without_overlap() -> None:
    assert set(IDEA_SETUP).isdisjoint(IDEA_PAYOFF)
    assert {"deflection", "attraction", "sacrifice"} <= set(IDEA_SETUP)
    assert {"fork", "pin", "backRankMate", "promotion"} <= set(IDEA_PAYOFF)
    # Phases, goals, lengths, mate-in-N and origin aren't motifs.
    for t in ("middlegame", "crushing", "mate", "mateIn2", "long", "master", "endgame"):
        assert t not in IDEA_SETUP and t not in IDEA_PAYOFF


def test_motif_themes_keep_only_graded_groups() -> None:
    assert motif_themes(P.themes) == ("deflection", "fork")
    assert motif_themes(("mate", "mateIn2", "short", "someNewTheme")) == ()


def test_no_move_before_tagging() -> None:
    s = mode.start(P, 0)
    with pytest.raises(ConflictError):
        mode.on_move(s, "f5g4", 10)
    mode.set_tags(s, ["deflection"], ["fork"], 50)
    assert mode.on_move(s, "f5g4", 60).kind == "correct"


def test_tags_are_validated() -> None:
    with pytest.raises(ValidationError):
        parse_tags([], [])  # at least one
    with pytest.raises(ValidationError):
        parse_tags(["fork"], [])  # fork is a payoff motif
    with pytest.raises(ValidationError):
        parse_tags(None, ["fork", "pin", "skewer", "hangingPiece"])  # at most 3 per slot
    with pytest.raises(ValidationError):
        parse_tags("fork", None)
    with pytest.raises(ValidationError):
        parse_tags(None, ["<script>"])
    assert parse_tags(None, ["fork", "fork"]) == IdeaTags((), ("fork",))


def test_tagging_twice_is_refused() -> None:
    s = mode.start(P, 0)
    mode.set_tags(s, None, ["fork"], 1)
    with pytest.raises(ConflictError):
        mode.set_tags(s, None, ["pin"], 2)


def test_scoring_is_standards() -> None:
    s = mode.start(P, 0)
    mode.set_tags(s, None, ["fork"], 0)
    mode.on_move(s, "f5g4", 1)
    mode.on_move(s, "f7f3", 2)
    f = mode.on_move(s, "f3d1", 3)
    std = StandardMode()
    t = std.start(P, 0)
    std.on_move(t, "f5g4", 1)
    std.on_move(t, "f7f3", 2)
    g = std.on_move(t, "f3d1", 3)
    assert f.attempt == g.attempt


def test_grade_found_and_extras_ignore_the_slot() -> None:
    score = grade_tags(IdeaTags((), ("fork", "pin")), P.themes)
    assert (score.found, score.total, score.extra) == (1, 2, 1)
    assert score.correct == ("fork",) and score.wrong == ("pin",) and score.missed == ("deflection",)
    both = grade_tags(IdeaTags(("deflection",), ("fork",)), P.themes)
    assert (both.found, both.total, both.extra) == (2, 2, 0)


def test_puzzle_without_motifs_has_no_tag_score() -> None:
    plain = puzzle("crushing middlegame long")
    score = grade_tags(IdeaTags((), ("fork",)), plain.themes)
    assert score.total == 0 and score.found == 0 and score.extra == 1


def test_think_time_starts_at_start_solving() -> None:
    s = mode.start(P, 0)
    mode.set_tags(s, None, ["fork"], 20_000)
    f = mode.on_move(s, "f7f6", 21_000)  # wrong
    assert f.attempt is not None and not f.attempt.win
    assert s.decisive_ms == 1000


def test_hint_before_tagging_is_a_loss() -> None:
    s = mode.start(P, 0)
    h = mode.on_help(s, "hint", 5)
    assert h.attempt is not None and h.attempt.help_used == "hint"


def test_score_only_after_tagging_and_never_in_practice() -> None:
    s = mode.start(P, 0)
    assert mode.score(s) is None
    mode.set_tags(s, None, ["fork"], 0)
    assert mode.score(s) is not None
    practice = mode.start_practice(P, 0)
    assert mode.on_move(practice, "f5g4", 1).kind == "correct"  # no tagging in a practice run
    assert mode.score(practice) is None
