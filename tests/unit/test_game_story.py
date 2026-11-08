"""FR-11.36 (v0.14): Game Review in three parts. The Summary and What you did well come from stored analysis only, and
every strength is backed by a number the engine measured. Synthetic rows; positive and negative cases per rule."""

from __future__ import annotations

from weaksquare.core.engine import EngineLine
from weaksquare.core.game_review import MoveRow, Score, game_story, move_label

W, B = "white", "black"


def row(
    ply: int,
    mover: str,
    *,
    before: int = 0,
    after: int | None = None,
    cls: str = "good",
    loss: int = 0,
    phase: str = "middlegame",
    san: str = "Nf3",
    uci: str = "g1f3",
    best: str | None = None,
    lines: tuple[EngineLine, ...] = (),
) -> MoveRow:
    """Evals from the mover's side, like the stored rows."""
    return MoveRow(
        ply, "", uci, san, mover, Score(before), Score(before - loss if after is None else after), best, lines, (),
        loss, cls, None, phase, None, None,
    )  # fmt: skip


def white_line(cp: int) -> EngineLine:
    return EngineLine(cp, None, ("g1f3",))


def kinds(story) -> list[str]:  # type: ignore[no-untyped-def]
    return [s.kind for s in story.strengths]


# ---- the summary -----------------------------------------------------------------------------------------------------
def test_summary_says_how_it_went_without_praise_or_blame() -> None:
    rows = [row(0, W), row(1, B, cls="blunder", loss=400, san="Qxb2"), row(2, W, before=400)]
    story = game_story(rows, W, "1-0", platform_accuracy=91.6)
    assert story.result == "won"
    assert story.summary[0] == "You won, with accuracy 92% and an average loss of 0 centipawns a move."
    assert story.summary[1] == "Stockfish found 0 inaccuracies, 0 mistakes and 0 blunders in your moves."
    assert story.summary[2] == "The turning point: 1... Qxb2, your opponent's blunder, which cost 4.0."
    assert story.summary[3] == "The middlegame was clean."


def test_summary_with_no_swings_and_results_from_each_side() -> None:
    rows = [row(0, W), row(1, B)]
    assert "No big swings" in game_story(rows, W, "1/2-1/2").summary[2]
    assert game_story(rows, B, "1-0").result == "lost"
    assert game_story(rows, B, "0-1").result == "won"
    assert game_story(rows, W, "*").summary[0].startswith("The game wasn't finished")


def test_move_labels() -> None:
    assert move_label(0, "e4") == "1. e4"
    assert move_label(5, "Nc6") == "3... Nc6"
    assert move_label(0, "e5", start_fullmove=10, black_first=True) == "10... e5"


# ---- only move found -------------------------------------------------------------------------------------------------
def test_only_move_found() -> None:
    lines = (white_line(50), white_line(-150))  # second choice 2.0 worse for White
    story = game_story([row(0, W, best="g1f3", lines=lines)], W, "*")
    assert kinds(story) == ["only_move"]
    assert story.strengths[0].text == "1. Nf3: you found the only good move. Anything else was at least 2.0 worse."
    assert story.strengths[0].ply == 0


def test_only_move_needs_the_best_move_a_real_gap_and_a_live_position() -> None:
    small_gap = (white_line(50), white_line(-50))
    big_gap = (white_line(50), white_line(-150))
    assert kinds(game_story([row(0, W, best="g1f3", lines=small_gap)], W, "*")) == []
    assert kinds(game_story([row(0, W, best="e2e4", lines=big_gap)], W, "*")) == []  # not the move you played
    assert kinds(game_story([row(0, W, best="g1f3", lines=big_gap[:1])], W, "*")) == []  # only one line known
    assert kinds(game_story([row(0, W, before=700, best="g1f3", lines=big_gap)], W, "*")) == []  # already decided


def test_only_move_from_blacks_side() -> None:
    lines = (white_line(-50), white_line(150))  # good for Black, the second choice much worse for Black
    story = game_story([row(1, B, best="g1f3", lines=lines)], B, "*")
    assert kinds(story) == ["only_move"]


# ---- mistake punished ---------------------------------------------------------------------------------------------
def test_mistake_punished() -> None:
    rows = [row(0, W, cls="mistake", loss=150, san="Bd3"), row(1, B, before=150, cls="best", san="Nb4")]
    story = game_story(rows, B, "*")
    assert kinds(story) == ["punished"]
    assert story.strengths[0].text == "1... Nb4: you punished your opponent's mistake 1. Bd3 straight away."


def test_not_punished_when_you_slipped_or_it_was_an_inaccuracy() -> None:
    slipped = [row(0, W, cls="blunder", loss=300), row(1, B, before=300, cls="inaccuracy", loss=60)]
    small = [row(0, W, cls="inaccuracy", loss=60), row(1, B, cls="best")]
    assert "punished" not in kinds(game_story(slipped, B, "*"))
    assert "punished" not in kinds(game_story(small, B, "*"))


# ---- hard defence ---------------------------------------------------------------------------------------------------
def test_hard_defence() -> None:
    story = game_story([row(0, W, before=-220, cls="best")], W, "*")
    assert kinds(story) == ["defence"]
    assert "(-2.2)" in story.strengths[0].text


def test_no_defence_credit_when_not_difficult_lost_already_or_a_bad_move() -> None:
    assert kinds(game_story([row(0, W, before=-100, cls="best")], W, "*")) == []
    assert kinds(game_story([row(0, W, before=-800, cls="best")], W, "*")) == []
    assert kinds(game_story([row(0, W, before=-220, cls="mistake", loss=120)], W, "*")) == []


# ---- conversion ------------------------------------------------------------------------------------------------------
def test_conversion() -> None:
    rows = [row(0, W, after=250), row(1, B, before=-250, after=-220), row(2, W, before=220, after=300)]
    story = game_story(rows, W, "1-0")
    assert kinds(story) == ["conversion"]
    assert story.strengths[0].ply == 0


def test_no_conversion_if_it_slipped_or_you_didnt_win() -> None:
    slipped = [row(0, W, after=250), row(1, B, before=-250, after=-50), row(2, W, before=50, after=300)]
    # It slipped below +1 after move 1, so credit can only start from a later +2 that held: here move 2.
    s = game_story(slipped, W, "1-0")
    assert [x.ply for x in s.strengths if x.kind == "conversion"] == [2]
    drawn = [row(0, W, after=250), row(1, B, before=-250, after=-250)]
    assert "conversion" not in kinds(game_story(drawn, W, "1/2-1/2"))


# ---- clean phase -----------------------------------------------------------------------------------------------------
def test_clean_phase_needs_enough_moves_and_no_mistake() -> None:
    clean = [row(2 * i, W, phase="opening") for i in range(8)]
    story = game_story(clean, W, "*")
    assert kinds(story) == ["clean_phase"]
    assert story.strengths[0].text == "A clean opening: 8 moves without a mistake or blunder."
    assert kinds(game_story(clean[:7], W, "*")) == []
    dirty = [*clean[:7], row(14, W, phase="opening", cls="mistake", loss=120)]
    assert "clean_phase" not in kinds(game_story(dirty, W, "*"))


# ---- nothing invented ----------------------------------------------------------------------------------------------
def test_a_game_with_nothing_to_praise_lists_nothing() -> None:
    rows = [row(0, W, cls="blunder", loss=400), row(1, B, before=400)]
    assert game_story(rows, W, "0-1").strengths == ()


def test_strengths_are_capped_and_in_game_order() -> None:
    lines = (white_line(50), white_line(-150))
    rows = [row(2 * i, W, best="g1f3", lines=lines) for i in range(6)]
    story = game_story(rows, W, "*")
    assert kinds(story) == ["only_move"] * 3  # at most 3 of a kind
    assert [s.ply for s in story.strengths] == sorted(s.ply for s in story.strengths if s.ply is not None)


def test_only_your_moves_count() -> None:
    lines = (white_line(50), white_line(-150))
    assert game_story([row(0, W, best="g1f3", lines=lines)], B, "*").strengths == ()
