"""QA v0.14 (independent): study parsing edges, fixture anonymity for studies, the starter list, the Lichess window's
import isolation from LLM code, and FR-11.36's strengths under Show best moves. A test exposing an open bug is xfail
(strict) with its ID."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import chess
import pytest

from weaksquare import config
from weaksquare.core.engine import EngineLine
from weaksquare.core.game_review import MoveRow, Score, game_story
from weaksquare.core.study_links import parse_study_ref
from weaksquare.core.study_pgn import mainline, node_from_json, node_to_json, parse_study
from weaksquare.services.studies import STARTER_FIELDS, load_starter

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "weaksquare"
FIXTURES = ROOT / "tests" / "fixtures"

# Adam's test studies (ROADMAP v0.14 manual test). Links only: their content must never be committed.
REAL_TEST_STUDIES = ("ZCPaIb70", "nq1GGbNO", "swkkeUJZ", "RVTx2uvp", "AT2Sw8JB")


def _chapter(study: str, n: int, movetext: str, extra: str = "") -> str:
    return (
        f'[Event "S: C{n}"]\n[StudyName "S"]\n[ChapterName "C{n}"]\n'
        f'[ChapterURL "https://lichess.org/study/{study}/Chap000{n}"]\n{extra}\n{movetext} *\n\n\n'
    )


def _long_movetext(plies: int) -> str:
    cycle = ["Nf3", "Nf6", "Ng1", "Ng8"]
    out = []
    for i in range(plies):
        if i % 2 == 0:
            out.append(f"{i // 2 + 1}.")
        out.append(cycle[i % 4])
    return " ".join(out)


# ---- v0.14-B1: a long main line is cut off silently ----------------------------------------------------------------
def test_qa14_b1_a_long_main_line_is_kept_whole() -> None:
    """Every move of a chapter is kept (or the chapter is rejected with a reason); never silently cut short. A 130-move
    annotated game is a normal chapter."""
    st = parse_study("TestLg01", _chapter("TestLg01", 1, _long_movetext(260)))
    c = st.chapters[0]
    assert c.rejected is None
    assert len(mainline(c.root)) == 260


def test_qa14_a_100_move_main_line_is_kept() -> None:
    """Just under the cap: kept whole and round-trips through storage."""
    st = parse_study("TestLg01", _chapter("TestLg01", 1, _long_movetext(200)))
    c = st.chapters[0]
    assert len(mainline(c.root)) == 200
    back = node_from_json(node_to_json(c.root), chess.Board(c.start_fen))
    assert node_to_json(back) == node_to_json(c.root)


# ---- parsing edges ---------------------------------------------------------------------------------------------------
def test_qa14_a_chapter_with_no_moves_on_a_normal_board_is_usable_not_text() -> None:
    """Real studies often open with a no-move introduction on the start position (seen in all three of Adam's test
    studies). It's usable (not rejected, not text-only) and keeps its comment."""
    pgn = _chapter("TestIn01", 1, "{ Welcome to the study. }") + _chapter("TestIn01", 2, "1. e4 e5")
    st = parse_study("TestIn01", pgn)
    intro = st.chapters[0]
    assert (intro.rejected, intro.text_only, intro.move_count) == (None, False, 0)
    assert intro.root.comment == "Welcome to the study."
    assert len(st.usable) == 2


def test_qa14_markup_and_script_in_comments_stay_text() -> None:
    pgn = _chapter("TestXs01", 1, '1. e4 { <img src=x onerror=alert(1)> <a href="https://evil.example">x</a> }')
    node = parse_study("TestXs01", pgn).chapters[0].root.children[0]
    assert node.comment == '<img src=x onerror=alert(1)> <a href="https://evil.example">x</a>'  # kept, escaped by React


def test_qa14_shapes_with_bad_colours_or_squares_are_dropped_item_by_item() -> None:
    pgn = _chapter("TestSh01", 1, "1. e4 { [%cal Ge2e4,Xa1a2,Ri9a1,Bh8h1] [%csl Yd4,Gz0,Rd4] }")
    shapes = parse_study("TestSh01", pgn).chapters[0].root.children[0].shapes
    assert [(s.orig, s.dest, s.color) for s in shapes] == [("e2", "e4", "green"), ("h8", "h1", "blue"),
                                                           ("d4", None, "yellow")]  # fmt: skip


def test_qa14_a_chapter_after_a_broken_one_keeps_its_own_headers() -> None:
    pgn = _chapter("TestBr01", 1, "1. e4 e5 2. Ke3 Nf6 3. Nf3") + _chapter(
        "TestBr01", 2, "1. d4", '[Orientation "black"]\n[ChapterMode "gamebook"]'
    )
    st = parse_study("TestBr01", pgn)
    assert st.chapters[0].rejected and "illegal" in st.chapters[0].rejected
    second = st.chapters[1]
    assert (second.chapter_id, second.orientation, second.mode, second.move_count) == (
        "Chap0002",
        "black",
        "gamebook",
        1,
    )


@pytest.mark.parametrize(
    "text",
    [
        "https://lichess.org/study/embed/AbCd1234/EfGh5678",  # embed link: not accepted (documented gap, not a bug)
        "https://lichess.org.evil.com/study/AbCd1234",
        "https://evil.com/?u=https://lichess.org/study/AbCd1234",
        "https://lichess.org/study/AbCd1234/EfGh5678/extra",
        "https://user@lichess.org/study/AbCd1234",
        "AbCd123",
        "AbCd12345",
        "lichess.org/study/AbCd12!4",
        "allstudy",
    ],
)
def test_qa14_non_study_addresses_are_refused(text: str) -> None:
    assert parse_study_ref(text) is None


# ---- fixtures: studies are invented (SR-12a, Done when "scrubbed and anonymized") -----------------------------------
def _fixture_texts() -> list[tuple[Path, str]]:
    out = []
    for p in FIXTURES.rglob("*"):
        if p.is_file() and "__pycache__" not in p.parts:
            try:
                out.append((p, p.read_text(encoding="utf-8")))
            except UnicodeDecodeError:
                continue
    return out


def test_qa14_study_fixtures_use_invented_ids_and_no_real_study_or_starter_id() -> None:
    starter_ids = {e.study_id for e in load_starter(config.STUDY_STARTER_FILE.read_text(encoding="utf-8"))}
    banned = set(REAL_TEST_STUDIES) | starter_ids
    study_url = re.compile(r"lichess\.org/study/([A-Za-z0-9]{8})(?:/([A-Za-z0-9]{8}))?")
    for path, text in _fixture_texts():
        for word in banned:
            assert word not in text, f"{path.name} contains the real study id {word}"
        for m in study_url.finditer(text):
            assert m.group(1).startswith("Test"), f"{path.name}: study id {m.group(1)} isn't an invented Test… id"
            assert m.group(2) is None or m.group(2).startswith("Chap"), f"{path.name}: chapter id {m.group(2)}"


def test_qa14_study_fixture_authors_are_placeholders() -> None:
    folder = FIXTURES / "http" / "lichess_studies"
    for p in folder.glob("*.pgn"):
        for m in re.finditer(r'\[Annotator "([^"]*)"\]', p.read_text(encoding="utf-8")):
            assert m.group(1) == "https://lichess.org/@/player_author", p.name


# ---- the starter list (FR-13.6) -----------------------------------------------------------------------------------
def test_qa14_starter_list_holds_only_links_titles_authors_and_openings() -> None:
    raw = json.loads(config.STUDY_STARTER_FILE.read_text(encoding="utf-8"))
    assert isinstance(raw, list) and raw
    assert all(set(e) == STARTER_FIELDS for e in raw)
    entries = load_starter(config.STUDY_STARTER_FILE.read_text(encoding="utf-8"))
    assert len(entries) == len(raw) == 24
    # Short strings only: no PGN, comments or moves smuggled into a title.
    for e in entries:
        assert len(e.title) <= 120 and "\n" not in e.title and "[%" not in e.title and "{" not in e.title
        assert parse_study_ref(e.study_id) is not None
    assert config.STUDY_STARTER_FILE.stat().st_size < 10_000


def test_qa14_starter_list_rejects_content_fields() -> None:
    entry = {"study_id": "AbCd1234", "title": "T", "author": "player_a", "opening": "Italian Game"}
    load_starter(json.dumps([entry]))
    extras: list[dict[str, object]] = [{"pgn": "1. e4"}, {"chapters": []}, {"url": "https://x"}]
    for extra in extras:
        with pytest.raises(ValueError):
            load_starter(json.dumps([{**entry, **extra}]))


# ---- FR-13.12: no LLM code can reach study text -------------------------------------------------------------------
def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


STUDY_MODULES = {
    "weaksquare.core.study_pgn",
    "weaksquare.core.study_repertoire",
    "weaksquare.adapters.db.repos.studies",
    "weaksquare.services.studies",
    "weaksquare.adapters.lichess_studies",
}


def test_qa14_no_module_that_talks_to_an_llm_imports_study_code() -> None:
    llm_marks = ("weaksquare.core.llm", "weaksquare.adapters.llm", "weaksquare.services.llm")
    offenders = []
    for p in SRC.rglob("*.py"):
        rel = p.relative_to(SRC).as_posix()
        if rel == "app.py" or rel.startswith("bridge/"):
            continue  # the wiring and the bridge see every service; neither builds a prompt
        imps = _imports(p)
        if any(i.startswith(llm_marks) for i in imps) and imps & STUDY_MODULES:
            offenders.append(p.relative_to(SRC).as_posix())
    assert offenders == []
    studies_imports = _imports(SRC / "services" / "studies.py")
    assert not any("llm" in i or "explain" in i or "coach" in i for i in studies_imports)


# ---- FR-11.36 with Show best moves: an only-move item never names the engine's alternative -------------------------
def _row(ply: int, mover: str, before: int, uci: str, san: str, best: str | None, lines: tuple[EngineLine, ...],
         cls: str = "best", loss: int = 0) -> MoveRow:  # fmt: skip
    return MoveRow(ply, "", uci, san, mover, Score(before), Score(before - loss), best, lines, (), loss, cls, None,
                   "middlegame", None, None)  # fmt: skip


def test_qa14_strength_texts_never_name_the_engines_other_moves() -> None:
    # White's only move Re8+ (best); the second line Qd2 is far worse. The text names Re8+ only.
    lines = (EngineLine(80, None, ("e1e8", "f8e8")), EngineLine(-200, None, ("d1d2", "a7a6")))
    rows = [_row(0, "white", 80, "e1e8", "Re8+", "e1e8", lines)]
    story = game_story(rows, "white", "*")
    assert [s.kind for s in story.strengths] == ["only_move"]
    text = story.strengths[0].text
    assert "Re8+" in text and "Qd2" not in text and "d1d2" not in text and "d2" not in text


def test_qa14_only_move_from_a_decided_position_is_not_praised() -> None:
    lines = (EngineLine(700, None, ("e1e8",)), EngineLine(100, None, ("d1d2",)))
    rows = [_row(0, "white", 700, "e1e8", "Re8+", "e1e8", lines)]
    assert game_story(rows, "white", "*").strengths == ()


def test_qa14_a_mate_only_move_counts_against_a_drawn_second_line() -> None:
    lines = (EngineLine(None, 2, ("e1e8",)), EngineLine(0, None, ("d1d2",)))
    rows = [_row(0, "white", 300, "e1e8", "Re8+", "e1e8", lines)]
    assert [s.kind for s in game_story(rows, "white", "*").strengths] == ["only_move"]
