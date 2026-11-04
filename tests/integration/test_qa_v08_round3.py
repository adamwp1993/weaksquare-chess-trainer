"""QA v0.8 round 3 (independent): edge cases of the B11 and B12 fixes."""

from __future__ import annotations

from tests.integration.test_game_library import Rig, rig  # noqa: F401  (the fixture)
from weaksquare.core.puzzle_files import EntryError, ImportedPuzzle, parse_csv

ROW = "6k1/5ppp/8/8/8/8/8/RR4K1 w - - 0 1,a1a8"


def test_qa_r3_a_found_game_links_the_typed_name_only_when_none_is_linked(rig: Rig) -> None:  # noqa: F811
    rig.acct.id = None
    rig.svc.set_chesscom_username("player_b")  # already linked: a typed name never replaces it
    job = rig.svc.start_url_import("https://www.chess.com/game/live/100000001", chesscom_username="player_a")
    st = rig.runner.wait(job, 5)
    assert st is not None and st.state == "done", st
    res = rig.svc.url_result(job)
    assert res is not None and not res.needs_color  # the typed name still finds your color
    assert rig.svc.settings().chesscom_username == "player_b"


def test_qa_r3_blank_rows_keep_their_row_numbers_and_dont_count() -> None:
    text = "fen,solution\n" + ROW + "\n\n\n" + "bad fen,a1a8\n" + ROW + "\n\n"
    out = parse_csv(text, max_entries=3)
    assert [type(e).__name__ for e in out] == ["ImportedPuzzle", "EntryError", "ImportedPuzzle"]
    assert isinstance(out[1], EntryError) and out[1].n == 4  # the file's row number, blanks included
    assert isinstance(out[2], ImportedPuzzle) and out[2].n == 5
    over = parse_csv("fen,solution\n" + ROW + "\n\n" + ROW + "\n\n" + ROW + "\n", max_entries=2)
    assert isinstance(over[-1], EntryError) and "more than 2" in over[-1].reason and over[-1].n == 5
