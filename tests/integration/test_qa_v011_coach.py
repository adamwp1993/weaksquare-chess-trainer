"""QA v0.11 (independent): whole-game coaching end to end on several distinct, fully-headed games
(REQUIREMENTS §10.11, FR-8.16). Every PGN here carries names, dates, a Site URL, ratings, clocks and
comments, so the prompt checks are meaningful. Tests marked QA v0.11-Bn were xfail for bugs in qa/QA-v0.11.md; they're regression tests now."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from tests.fakes.engine import FakeEngine, plant_managed_install
from tests.integration.test_coach_ai import _answer, _finding
from tests.integration.test_coach_run import ANY_GAME, _run
from tests.integration.test_game_explain import configure, fake
from tests.integration.test_game_puzzles import Recorder
from tests.unit.test_digest import make_rows
from weaksquare.adapters.db.repos.coach import ObservationsRepo
from weaksquare.adapters.db.repos.game_analysis import GameAnalysisRepo
from weaksquare.core.errors import AppError, ValidationError
from weaksquare.services.coach import CoachAiOptions

SHUFFLE = ["Nf3", "Nf6", "Ng1", "Ng8"]
MATE_TAIL = ["e4", "e5", "Qh5", "Nc6", "Bc4", "Nf6", "Qxf7#"]
LEAKS = (
    "player_a", "opponent_b", "2026", "lichess.org", "QaGameId", "[%clk", "%clk", "great move", "[White",
    "[Site", "WhiteElo", "1987", "180+0", "game_id", "UTCDate",
)  # fmt: skip


@pytest.fixture(autouse=True)
def _reset() -> None:
    FakeEngine.instances.clear()


def _pgn(k: int) -> tuple[str, list[str]]:
    sans = SHUFFLE * k + MATE_TAIL
    body = []
    for i, san in enumerate(sans):
        if i % 2 == 0:
            body.append(f"{i // 2 + 1}.")
        body.append(san)
        body.append("{ great move [%clk 0:02:30] }")
    pgn = (
        f'[Event "Rated blitz game"]\n[Site "https://lichess.org/QaGameId{k:02d}"]\n[Date "2026.10.{k + 1:02d}"]\n'
        f'[UTCDate "2026.10.{k + 1:02d}"]\n[UTCTime "10:00:00"]\n[White "player_a"]\n[Black "opponent_b"]\n'
        '[WhiteElo "1987"]\n[BlackElo "1987"]\n[Result "1-0"]\n[TimeControl "180+0"]\n[ECO "C20"]\n'
        '[Opening "King\'s Pawn Game: Wayward Queen Attack"]\n\n' + " ".join(body) + " 1-0\n"
    )
    return pgn, sans


def _games(services: Any, n: int) -> list[int]:
    """n distinct games of yours, oldest first, each analyzed with a White blunder at ply 4k+1 (0-based)."""
    services.game_puzzles._engine = Recorder()
    ids = []
    for k in range(n):
        pgn, sans = _pgn(k)
        gid = int(services.games.import_pgn(pgn).game_id)
        services.games.set_user_color(gid, "white")
        evals = [0] * (len(sans) + 1)
        for i in range(4 * k + 5, len(evals)):
            evals[i] = -350  # White's Bc4 (0-based ply 4k+4) loses 3.5 pawns
        rows = make_rows(sans, evals)
        GameAnalysisRepo(services.db).replace(gid, rows, "analyzed", 0.3, "Stockfish 19")
        ids.append(gid)
    return ids


def _report(services: Any, paths: Any, n: int) -> tuple[int, list[int]]:
    plant_managed_install(paths)
    ids = _games(services, n)
    return _run(services, {"source": "games", **ANY_GAME}), ids


def _wait(services: Any, job: str) -> None:
    st = services.coach._runner.wait(job, 20)
    assert st is not None and st.state == "done", st


def _labels_in_moves(user: str) -> list[str]:
    part = user.split("Move lists (Advanced analysis; SAN only):", 1)[1].split("\n\n", 1)[0]
    return re.findall(r"^(G\d+): ", part, flags=re.M)


def test_qa_twelve_games_all_get_a_digest_and_label(services, paths) -> None:  # type: ignore[no-untyped-def]
    rid, ids = _report(services, paths, 12)
    row, _ = services.coach.report(rid)
    assert sorted(row.game_ids) == sorted(ids) and row.report["measures"]["games"] == 12
    fam = {o["family"]: o for o in row.report["measures"]["openings"]}
    assert fam["King's Pawn Game"]["games"] == 12 and fam["King's Pawn Game"]["enough"] is True


def test_qa_no_header_name_date_url_rating_clock_or_comment_reaches_any_prompt(services, paths) -> None:  # type: ignore[no-untyped-def]
    rid, ids = _report(services, paths, 12)
    gid = ids[-1]
    services.review.set_game_reason(gid, 4 * 11 + 4, "didntLook", "they played it on lichess.org/abc")
    configure(services)
    for opts in (None, {"advanced": True, "game_cap": 10}, {"include_notes": True}):
        fake(services).queue(_answer(_finding(ply=1)))
        _wait(services, services.coach.start_ai(rid, opts))
        req = fake(services).requests[-1]
        text = req.system + req.user
        for leak in LEAKS:
            assert leak not in text, (opts, leak)
        assert str(gid) not in re.findall(r'"game":"?(\w+)', req.user)
    # Notes go as written, URL removed: a name you typed yourself is yours to send (FR-10.71 warns in v0.12).
    assert "[link removed]" in fake(services).requests[-1].user


def test_qa_advanced_sends_only_the_cap_and_the_most_recent_games(services, paths) -> None:  # type: ignore[no-untyped-def]
    rid, ids = _report(services, paths, 12)
    configure(services)
    q = services.coach.quote_ai(rid, {"advanced": True, "game_cap": 10})
    assert q.compare is not None and q.compare.games_with_moves == 10
    fake(services).queue(_answer(_finding(ply=1)))
    _wait(services, services.coach.start_ai(rid, {"advanced": True, "game_cap": 10}))
    user = fake(services).requests[-1].user
    sent_labels = _labels_in_moves(user)
    assert len(sent_labels) == 10
    run = services.coach.ai_runs(rid)[-1]
    labels = run.result["labels"]  # G label -> game id, kept on this PC
    newest_ten = set(ids[-10:])  # the games were dated oldest first
    assert {labels[lbl] for lbl in sent_labels} == newest_ten
    assert len(re.findall(r'^\{"game":"G\d+"', user, flags=re.M)) == 12  # every game still has its digest


def test_qa_advanced_is_blocked_by_the_cap_when_standard_still_fits(services, paths) -> None:  # type: ignore[no-untyped-def]
    rid, _ = _report(services, paths, 12)
    configure(services)
    std = services.coach.quote_ai(rid).quote.estimate.worst_usd
    adv = services.coach.quote_ai(rid, {"advanced": True, "game_cap": 50}).quote.estimate.worst_usd
    assert adv > std
    services.llm_settings.update("anthropic", "claude-haiku-5-5", "low", round((std + adv) / 2, 6), 5.00)
    assert services.coach.quote_ai(rid).quote.state == "ok"
    q = services.coach.quote_ai(rid, {"advanced": True, "game_cap": 50})
    assert q.quote.state == "over_cap"
    with pytest.raises(AppError):
        services.coach.start_ai(rid, {"advanced": True, "game_cap": 50})
    assert fake(services).requests == []


def test_qa_an_advanced_run_leaves_no_trace_in_settings(services, paths) -> None:  # type: ignore[no-untyped-def]
    rid, _ = _report(services, paths, 3)
    configure(services)
    fake(services).queue(_answer(_finding(ply=1)))
    _wait(services, services.coach.start_ai(rid, {"advanced": True, "game_cap": 10, "include_notes": True}))
    with services.db.session() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    blob = json.dumps([list(r) for r in rows])
    assert "advanced" not in blob and "include_notes" not in blob and "game_cap" not in blob
    assert services.coach.quote_ai(rid).quote.state == "ok"  # no options: a fresh standard quote, not the Advanced run


def test_qa_a_cited_ply_must_be_sent_for_that_game(services, paths) -> None:  # type: ignore[no-untyped-def]
    rid, _ = _report(services, paths, 3)
    configure(services)
    sent = services.coach._ai_request(rid, CoachAiOptions()).sent
    real = min(sent.plies["G1"])
    assert 2 not in sent.plies["G1"]  # a standard run sends key moments only
    fake(services).queue(
        _answer(
            _finding(ply=2, title="Not a key moment"),
            _finding(ply=real, key=None, title="Real", topic=None),
        )
    )
    _wait(services, services.coach.start_ai(rid))
    run = services.coach.ai_runs(rid)[-1]
    assert [f["title"] for f in run.result["findings"]] == ["Real"]


def test_qa_the_notes_preview_matches_what_is_sent_exactly(services, paths) -> None:  # type: ignore[no-untyped-def]
    rid, ids = _report(services, paths, 3)
    services.review.set_game_reason(ids[0], 4, "didntLook", "first note")
    services.review.set_game_reason(ids[0], 4, "rushed", "second note replaces it")
    services.review.set_game_reason(ids[1], 8, "miscalculated", "see https://example.org/x and bit.ly/y")
    preview = services.coach.notes_preview(rid)
    assert {n.text for n in preview} >= {"second note replaces it"} and "first note" not in {n.text for n in preview}
    configure(services)
    fake(services).queue(_answer(_finding(ply=1)))
    _wait(services, services.coach.start_ai(rid, {"include_notes": True}))
    user = fake(services).requests[-1].user
    notes_part = user.split("Your own notes on your mistakes (written by the player):", 1)[1].split("\n\n", 1)[0]
    sent = [json.loads(line)["note"] for line in notes_part.strip().splitlines()]
    assert sent == [n.text for n in preview]


# QA v0.11-B2 regression (fixed)
def test_qa_short_links_in_notes_are_removed(services, paths) -> None:  # type: ignore[no-untyped-def]
    rid, ids = _report(services, paths, 3)
    services.review.set_game_reason(ids[1], 8, "miscalculated", "video: youtu.be/abc and bit.ly/y")
    (n,) = services.coach.notes_preview(rid)
    assert "youtu.be" not in n.text and "bit.ly" not in n.text


def test_qa_notes_need_a_report_with_games(services) -> None:  # type: ignore[no-untyped-def]
    rid = _run(services, {"source": "puzzles"})
    with pytest.raises(ValidationError):
        services.coach.quote_ai(rid, {"include_notes": True})


def test_qa_lesson_targets_are_strict(services, paths) -> None:  # type: ignore[no-untyped-def]
    rid, _ = _report(services, paths, 1)
    for target in ("curated:", "curated:-1", "curated:1", "curated: 0", "curated:0x0", "CURATED:0", "YouTube",
                   "javascript:alert(1)", "", "custom"):  # fmt: skip
        with pytest.raises(ValidationError):
            services.coach.lesson_url(rid, "theme:fork", target)
    for bad in (None, 3, ["theme:fork"]):
        with pytest.raises(ValidationError):
            services.coach.lesson_url(rid, bad, "youtube")
    assert services.coach.lesson_url(rid, "opening:King's Pawn Game", "youtube") == (
        "https://www.youtube.com/results?search_query=chess+King%27s+Pawn+Game"
    )


# QA v0.11-B3 regression (fixed)
def test_qa_an_observation_counts_each_report_once_in_any_order(services) -> None:  # type: ignore[no-untyped-def]
    repo = ObservationsRepo(services.db)
    assert repo.note("me", "concept:trades", "", "", "Trades", 1) == 1
    assert repo.note("me", "concept:trades", "", "", "Trades", 2) == 2
    assert repo.note("me", "concept:trades", "", "", "Trades", 1) == 2  # report 1 again: still 2 reports


# QA v0.11-B5 regression (fixed)
def test_qa_two_quick_starts_send_one_request(services, paths) -> None:  # type: ignore[no-untyped-def]
    rid, _ = _report(services, paths, 2)
    configure(services)
    fake(services).queue(_answer(_finding(ply=1)))
    fake(services).queue(_answer(_finding(ply=1)))
    first, second = services.coach.start_ai(rid), services.coach.start_ai(rid)  # a double-click on Confirm
    for job in (first, second):
        services.coach._runner.wait(job, 20)
    assert len(fake(services).requests) == 1


# ---- Round 2 (QA, 2026-11-04): try to break the B3 and B5 fixes ----


def _hold(services: Any) -> Any:
    """Make the fake provider wait until released, so a run is still going when the next start comes."""
    import threading

    gate = threading.Event()
    prov = fake(services)
    real = prov.generate

    def slow(key: str, request: Any) -> Any:
        gate.wait(10)
        return real(key, request)

    prov.generate = slow  # type: ignore[method-assign]
    return gate


def test_qa_r2_starts_from_many_threads_send_one_request(services, paths) -> None:  # type: ignore[no-untyped-def]
    from concurrent.futures import ThreadPoolExecutor

    rid, _ = _report(services, paths, 2)
    configure(services)
    gate = _hold(services)
    with ThreadPoolExecutor(8) as pool:
        jobs = set(pool.map(lambda _: services.coach.start_ai(rid), range(8)))
    gate.set()
    assert len(jobs) == 1
    _wait(services, jobs.pop())
    assert len(fake(services).requests) == 1


def test_qa_r2_the_same_options_written_differently_join_the_run(services, paths) -> None:  # type: ignore[no-untyped-def]
    rid, _ = _report(services, paths, 2)
    configure(services)
    gate = _hold(services)
    a = services.coach.start_ai(rid, None)
    b = services.coach.start_ai(rid, {"advanced": False, "include_notes": False})
    c = services.coach.start_ai(rid, {"include_notes": False, "game_cap": 30, "advanced": False})
    gate.set()
    assert a == b == c
    _wait(services, a)
    assert len(fake(services).requests) == 1


def test_qa_r2_other_options_while_one_is_going_are_their_own_run(services, paths) -> None:  # type: ignore[no-untyped-def]
    """By design: Advanced is another estimate and another Confirm, so it isn't merged with the standard run."""
    rid, _ = _report(services, paths, 2)
    configure(services)
    gate = _hold(services)
    a = services.coach.start_ai(rid)
    b = services.coach.start_ai(rid, {"include_notes": True})
    gate.set()
    assert a != b
    _wait(services, a)
    _wait(services, b)
    assert len(fake(services).requests) == 2


def test_qa_r2_after_a_run_ends_the_same_options_reuse_it_or_retry(services, paths) -> None:  # type: ignore[no-untyped-def]
    from weaksquare.core.llm.provider import LLMError

    rid, _ = _report(services, paths, 2)
    configure(services)
    fake(services).queue(LLMError("server", 500))
    first = services.coach.start_ai(rid)
    st = services.coach._runner.wait(first, 20)
    assert st is not None and st.state == "failed"
    n = len(fake(services).requests)
    second = services.coach.start_ai(rid)  # a failed run doesn't block a retry
    assert second != first
    _wait(services, second)
    assert len(fake(services).requests) == n + 1
    third = services.coach.start_ai(rid)  # done: the saved answer, nothing sent
    _wait(services, third)
    assert len(fake(services).requests) == n + 1


def test_qa_r2_migration_0010_backfills_every_shape(tmp_path) -> None:  # type: ignore[no-untyped-def]
    import shutil
    import sqlite3

    from tests.integration.test_migration_0009 import CLOCK
    from weaksquare.adapters.db.connection import Database
    from weaksquare.adapters.db.migrate import migrate
    from weaksquare.config import MIGRATIONS_DIR

    old = tmp_path / "v9"
    old.mkdir()
    for f in sorted((MIGRATIONS_DIR / "user").glob("000[1-9]_*.sql")):
        shutil.copy(f, old / f.name)
    db_path = tmp_path / "user.db"
    migrate(db_path, old, CLOCK)
    conn = sqlite3.connect(db_path)
    rows = [("a", None, None, 1), ("b", 4, 4, 1), ("c", 1, 2, 2), ("d", 2, 1, 2)]
    for key, first, last, seen in rows:
        conn.execute(
            "INSERT INTO coach_observations (subject, topic_key, category, title_key, title, first_report_id,"
            " last_report_id, times_seen) VALUES ('me', ?, '', '', 'T', ?, ?, ?)",
            (f"concept:{key}", first, last, seen),
        )
    conn.commit()
    conn.close()
    migrate(db_path, MIGRATIONS_DIR / "user", CLOCK)
    conn = sqlite3.connect(db_path)
    got = dict(conn.execute("SELECT topic_key, report_ids FROM coach_observations").fetchall())
    assert max(r[0] for r in conn.execute("SELECT version FROM schema_version")) == 10
    conn.close()
    assert {k: json.loads(v) for k, v in got.items()} == {
        "concept:a": [], "concept:b": [4], "concept:c": [1, 2], "concept:d": [2, 1],
    }  # fmt: skip
    repo = ObservationsRepo(Database(db_path, tmp_path / "puzzles.db"))
    assert repo.note("me", "concept:b", "", "", "T", 4) == 1
    assert repo.note("me", "concept:c", "", "", "T", 2) == 2
    assert repo.note("me", "concept:d", "", "", "T", 3) == 3
    assert repo.note("me", "concept:new", "", "", "T", 9) == 1
    # Migrating again is a no-op
    migrate(db_path, MIGRATIONS_DIR / "user", CLOCK)
    assert repo.note("me", "concept:c", "", "", "T", 1) == 2


@pytest.mark.xfail(strict=True, reason="QA v0.11-B9: a note's address on an unlisted TLD reaches the LLM")
def test_qa_r2_a_note_with_an_address_on_another_tld_is_not_sent(services, paths) -> None:  # type: ignore[no-untyped-def]
    rid, ids = _report(services, paths, 3)
    services.review.set_game_reason(ids[1], 8, "miscalculated", "course: chess.academy/rook-endings")
    configure(services)
    fake(services).queue(_answer(_finding(ply=1)))
    _wait(services, services.coach.start_ai(rid, {"include_notes": True}))
    assert "chess.academy" not in fake(services).requests[-1].user
