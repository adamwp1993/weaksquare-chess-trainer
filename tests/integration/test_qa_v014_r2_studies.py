"""QA v0.14 round 2 (independent): the service and bridge after the B1-B3 fixes. The new stored tree format keeps Check
for updates' chapter fingerprints stable, a long chapter works end to end (open, your place, repertoire), text chapters
still open, a row in the old nested format is reported as damaged rather than crashing, and B2's extra request
carries no token and is made only when the listing is empty."""

from __future__ import annotations

import json
import sqlite3

import pytest

from tests.fakes.lichess import FAKE_TOKEN
from tests.fakes.studies import fixture_pgn
from tests.integration.test_studies import Rig, rig  # noqa: F401
from weaksquare.core.errors import AppError, ValidationError
from weaksquare.core.study_pgn import walk


def _shuffle(plies: int) -> str:
    cycle = ["Nf3", "Nf6", "Ng1", "Ng8"]
    out = []
    for i in range(plies):
        if i % 2 == 0:
            out.append(f"{i // 2 + 1}.")
        out.append(cycle[i % 4])
    return " ".join(out)


def _long_study(plies: int) -> str:
    return (
        '[Event "Long: Game"]\n[StudyName "Long"]\n[ChapterName "Game"]\n'
        '[ChapterURL "https://lichess.org/study/TestLg02/Chap0001"]\n'
        '[Annotator "https://lichess.org/@/player_author"]\n\n' + _shuffle(plies) + " *\n"
    )


def test_qa14r2_a_byte_change_with_the_same_content_lists_every_chapter_unchanged(rig: Rig) -> None:  # noqa: F811
    """The stored tree and a fresh parse fingerprint the same way, text and rejected chapters included."""
    rig.add("TestNm02")
    rig.client.public["TestNm02"] = fixture_pgn("TestNm02") + "\n\n"  # same study, different bytes
    st = rig.run(rig.svc.check_updates("TestNm02"))
    assert st.message == "Only small changes: review them before updating"
    p = rig.svc.pending_update("TestNm02")
    assert p is not None
    assert (p.diff.added, p.diff.removed, p.diff.changed, p.diff.unchanged) == ([], [], [], 3)


def test_qa14r2_a_260_move_chapter_opens_saves_your_place_and_adds_to_the_repertoire(rig: Rig) -> None:  # noqa: F811
    rig.client.public["TestLg02"] = _long_study(520)
    assert rig.add("TestLg02").state == "done"
    row, tree = rig.svc.chapter("TestLg02", "Chap0001")
    assert row.move_count == 520 and len(walk(tree)) == 521
    path = " ".join(["g1f3", "g8f6", "f3g1", "f6g8"] * 130)
    rig.svc.set_place("TestLg02", "Chap0001", path)
    assert rig.svc.continue_target("TestLg02") == ("Chap0001", path)


def test_qa14r2_your_place_is_limited_to_600_moves_deep(rig: Rig) -> None:  # noqa: F811
    """Not filed: `parse_path` caps a place at 600 plies, so in a chapter longer than 300 moves the place stops being
    saved past ply 600 (the UI ignores the error). Real games essentially never get there; recorded so a change is seen."""
    rig.client.public["TestLg02"] = _long_study(640)
    rig.add("TestLg02")
    moves = ["g1f3", "g8f6", "f3g1", "f6g8"] * 160
    rig.svc.set_place("TestLg02", "Chap0001", " ".join(moves[:600]))
    with pytest.raises(ValidationError):
        rig.svc.set_place("TestLg02", "Chap0001", " ".join(moves[:601]))


def test_qa14r2_text_chapters_still_open_with_their_text(rig: Rig) -> None:  # noqa: F811
    rig.add("TestNm02")
    row, tree = rig.svc.chapter("TestNm02", "Chap0003")
    assert row.text_only and tree.children == []
    assert tree.comment == "Thanks for studying! This board is empty on purpose."


def test_qa14r2_a_row_in_the_old_nested_format_reads_as_damaged(rig: Rig) -> None:  # noqa: F811
    """A copy saved before the fix (nested `children`) can't be re-checked: it says so instead of crashing."""
    rig.add("TestNm02")
    with sqlite3.connect(rig.paths.user_db) as conn:
        conn.execute(
            "UPDATE study_chapters SET tree = ? WHERE study_id = 'TestNm02' AND chapter_key = 'Chap0001'",
            (json.dumps({"children": [{"san": "e4", "uci": "e2e4"}]}),),
        )
    with pytest.raises(AppError) as e:
        rig.svc.chapter("TestNm02", "Chap0001")
    assert e.value.code == "chapter_damaged"


def test_qa14r2_b2_the_user_check_sends_no_token_and_only_follows_an_empty_listing(rig: Rig) -> None:  # noqa: F811
    rig.tokens.value, rig.tokens.scopes = FAKE_TOKEN, {"study:read"}
    found = rig.svc.studies_by("player_author")
    assert found and rig.client.calls == [("by:player_author", None)]  # a listing: no second request
    rig.client.calls.clear()
    rig.client.authors["player_quiet"] = []
    assert rig.svc.studies_by("player_quiet") == []
    assert rig.client.calls == [("by:player_quiet", None), ("user:player_quiet", None)]
