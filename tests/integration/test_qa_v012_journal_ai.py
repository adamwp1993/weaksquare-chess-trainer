"""QA v0.12: the journal, the daily log against Stats, AI coaching's new prompt parts and the saved-answer rules,
through the real bridge (FR-8.14, FR-8.16, FR-10.66-10.71, FR-10.73). The LLM is the fake provider; everything else is
real. A test exposing an open bug is marked xfail with its ID.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from tests.fakes.engine import plant_managed_install
from tests.helpers import FakeDesktop
from tests.integration.test_coach_ai import _answer
from tests.integration.test_coach_run import ANY_GAME, _run
from tests.integration.test_game_explain import configure, fake
from tests.integration.test_qa_v011_coach import _games
from tests.integration.test_qa_v012_plan import (
    _api,
    _ok,
    _plan_with,
    _puzzles_task,
    _solve_next,
    _svc,
)
from tests.unit.test_digest import make_rows
from weaksquare.adapters.db.repos.coach import AiRunsRepo, CoachReportsRepo
from weaksquare.adapters.db.repos.game_analysis import GameAnalysisRepo
from weaksquare.bridge.api import Api
from weaksquare.core.clock import FixedClock
from weaksquare.core.plan import REFLECTION, REVIEW, Task
from weaksquare.core.report_compare import Side, compare
from weaksquare.core.stats import build_report
from weaksquare.core.themes import display_name


@pytest.fixture
def desktop() -> FakeDesktop:
    return FakeDesktop()


@pytest.fixture
def api(paths: Any, clock: Any, desktop: FakeDesktop, fixture_puzzles_db: Any) -> Api:
    return _api(paths, clock, desktop, fixture_puzzles_db)


SENTINELS = (
    "SecretWhiteName", "SecretBlackName", "secret-event", "ZZSECRETGAME", "lichess.org", "chess.com", "2019.03.04",
    "2019-03-04", "[%clk", "SECRETCOMMENT", "1973", "TimeControl", "evil.example",
)  # fmt: skip


def _secret_game(api: Api, k: int) -> int:
    """A game whose PGN carries everything that must never go to the LLM. Each is distinct by its first moves."""
    svc = _svc(api)
    knights = ["Nf3 Nf6 2. Ng1 Ng8", "Nc3 Nc6 2. Nb1 Nb8", "Nh3 Nh6 2. Ng1 Ng8", "Na3 Na6 2. Nb1 Nb8"][k % 4]
    pad = " ".join(f"{i}. Nf3 Nf6 {i + 1}. Ng1 Ng8" for i in range(3, 3 + 2 * (k // 4), 2))
    start = 3 + 2 * (k // 4)
    moves = f"1. {knights} {pad} {start}. e4 {{ SECRETCOMMENT [%clk 0:03:00] }} e5 {start + 1}. Bc4 Nc6 {start + 2}. Qh5 Nf6 {start + 3}. Qxf7# 1-0"
    pgn = (
        f'[Event "secret-event {k}"]\n[Site "https://lichess.org/ZZSECRETGAME{k}"]\n[Date "2019.03.04"]\n'
        f'[UTCDate "2019.03.04"]\n[White "SecretWhiteName"]\n[Black "SecretBlackName"]\n[WhiteElo "1973"]\n'
        f'[BlackElo "1973"]\n[TimeControl "180+0"]\n[Result "1-0"]\n\n{moves}\n'
    )
    gid = int(svc.games.import_pgn(pgn).game_id)
    svc.games.set_user_color(gid, "white")
    from io import StringIO

    import chess.pgn

    game = chess.pgn.read_game(StringIO(pgn))
    assert game is not None
    board = game.board()
    sans = []
    for mv in game.mainline_moves():
        sans.append(board.san(mv))
        board.push(mv)
    evals = [0] * (len(sans) + 1)
    for i in range(len(sans) - 3, len(evals)):
        evals[i] = -350
    GameAnalysisRepo(svc.db).replace(gid, make_rows(sans, evals), "analyzed", 0.3, "Stockfish 19")
    return gid


def _with(plan: Any = None, trend: Any = None) -> str:
    data = json.loads(_answer())
    data["plan"] = plan if plan is not None else {"weeks": []}
    data["trend"] = trend or []
    return json.dumps(data)


def _wait(api: Api, job: dict[str, Any]) -> None:
    jid = _ok(job)
    st = api._coach._runner.wait(jid, 20)
    assert st is not None and st.state == "done", st


def _journal_lines(user: str) -> list[dict[str, Any]]:
    marker = "The player's journal (written by the player):\n"
    if marker not in user:
        return []
    return [json.loads(x) for x in user.split(marker, 1)[1].splitlines() if x.startswith("{")]


def _section(user: str, title: str) -> Any:
    lines = user.split("\n")
    at = lines.index(title)
    return json.loads(lines[at + 1])


def _report_row(api: Api, day: int, game_ids: list[int], data: dict[str, Any], subject: str = "me") -> int:
    return int(
        CoachReportsRepo(_svc(api).db).add(
            f"2026-01-{day:02d}T10:00:00+00:00", subject, "You" if subject == "me" else "someone", "games",
            {"detail": "summary"},
            {"source": "games", "games": len(game_ids), "weaknesses": [], "missed": [], "whole_game": [], **data},
            game_ids,
        )
    )  # fmt: skip


# ---- FR-8.16: everything v0.12 adds to the prompt ----


def test_qa_no_name_date_url_id_clock_or_comment_reaches_the_llm_with_plan_trend_and_journal(
    api: Api, paths: Any, clock: Any
) -> None:
    plant_managed_install(paths)
    svc = _svc(api)
    ids = [_secret_game(api, k) for k in range(6)]
    first = _run(svc, {"source": "games", **ANY_GAME})
    # The plan's titles carry the opponent's name and the date; they must stay on this PC.
    plan = _plan_with(
        api,
        [
            [
                Task(REVIEW, 10, "Review your game against SecretBlackName (2019-03-04)", {"game_id": ids[0]}),
                _puzzles_task(1),
            ]
        ],
    )
    assert plan["days"][0]["tasks"][0]["title"].startswith("Review")
    _ok(api.start_plan_task(plan["days"][0]["tasks"][0]["id"]))
    _ok(api.set_plan_task_tick(plan["days"][0]["tasks"][1]["id"], True))
    clock.advance(days=3)
    more = [_secret_game(api, k) for k in range(6, 12)]
    second = _run(svc, {"source": "games", **ANY_GAME})
    assert _ok(api.get_coach_report(second))["comparison"] is not None and first != second
    _ok(
        api.add_journal_entry(
            {"text": "See https://lichess.org/ZZSECRETGAME0 and www.evil.example/x here.", "game_id": more[0], "ply": 3}
        )
    )
    configure(svc)
    fake(svc).queue(_with())
    _wait(api, api.start_coach_ai(second, {"include_journal": True, "include_notes": True}))
    req = fake(svc).requests[-1]
    blob = req.user + req.system
    for leak in SENTINELS:
        assert leak not in blob, leak
    for gid in [*ids, *more]:
        assert f'"game_id":{gid}' not in blob
    assert "here." in blob  # the journal did go, with its web addresses removed


def test_qa_plan_progress_in_the_prompt_is_aggregates_only(api: Api, paths: Any) -> None:
    plant_managed_install(paths)
    svc = _svc(api)
    gid = _games(svc, 1)[0]
    rid = _run(svc, {"source": "games", **ANY_GAME})
    plan = _plan_with(
        api,
        [[Task(REVIEW, 10, "Review your game against opponent_b", {"game_id": gid}, "missed:fork"),
          Task(REFLECTION, 5, "Reflection: PRIVATE PROMPT", {"prompt": "PRIVATE PROMPT"}, "missed:fork"), _puzzles_task(2, 5)]],
    )  # fmt: skip
    refl = plan["days"][0]["tasks"][1]
    _ok(api.add_journal_entry({"text": "PRIVATE JOURNAL", "plan_task_id": refl["id"]}))
    a = _ok(api.start_plan_task(plan["days"][0]["tasks"][2]["id"], False))
    assert _solve_next(api, paths, a["session"]["session_id"])
    configure(svc)
    fake(svc).queue(_with())
    _wait(api, api.start_coach_ai(rid))
    user = fake(svc).requests[-1].user
    assert "PRIVATE" not in user and "opponent_b" not in user
    prog = _section(user, "How the current training plan went (aggregates only):")
    assert set(prog) == {
        "weeks", "days_per_week", "minutes_per_day", "training_days_so_far", "training_days_total", "tasks_by_type",
        "tasks_by_weakness", "minutes_spent", "puzzle_first_try_by_theme",
    }  # fmt: skip
    assert prog["tasks_by_type"]["reflection"] == {"done": 1}
    assert set(prog["tasks_by_weakness"]) == {"missed:fork"}
    # Nothing but numbers under the keys: no id, title or text anywhere.
    flat = json.dumps(prog)
    assert not re.search(r'"(id|title|prompt|text|game|game_id|date)"', flat)
    for row in prog["puzzle_first_try_by_theme"].values():
        assert set(row) == {"attempts", "first_try"}


def test_qa_the_trend_part_has_aggregates_only_and_nothing_from_another_player(api: Api, paths: Any) -> None:
    plant_managed_install(paths)
    svc = _svc(api)
    ids = _games(svc, 6)
    w = {"key": "missed:fork", "kind": "missed", "name": "fork", "label": "Forks SECRETLABEL", "count": 4, "per10": 4.0,
         "severity": 300, "score": 3.0, "themes": ["fork"], "mode": None, "reasons": {},
         "examples": [{"game_id": ids[0], "ply": 4, "cp_loss": 300}]}  # fmt: skip
    _report_row(api, 1, list(range(9000, 9010)), {"weaknesses": [w], "missed": [w], "notes": ["SECRETNOTE"]})
    _report_row(
        api,
        2,
        list(range(9100, 9110)),
        {"weaknesses": [{**w, "per10": 99.0}], "missed": [{**w, "per10": 99.0}]},
        subject="lichess:someone",
    )
    now = {**w, "per10": 2.0}
    rid = _report_row(api, 3, ids, {"weaknesses": [now], "missed": [now]})
    configure(svc)
    fake(svc).queue(_with())
    _wait(api, api.start_coach_ai(rid))
    user = fake(svc).requests[-1].user
    trend = _section(user, "Since last report (aggregates only):")
    assert "SECRET" not in json.dumps(trend) and "2026" not in json.dumps(trend)
    assert [r["label"] for r in trend["reports"]] == ["1 report ago", "this report"]
    row = trend["weaknesses"][0]
    assert row["key"] == "missed:fork" and row["rates"] == {"1 report ago": 4.0, "this report": 2.0}  # not 99.0
    assert set(row) <= {"key", "rates", "flag", "change", "puzzle_first_try_pct"}
    assert not re.search(r'"(game_id|ply|examples|name|created_at|earlier_id|id)"', json.dumps(trend))


@pytest.mark.xfail(
    strict=True, reason="v0.12-B10: a journal entry's weakness tag isn't checked or cleaned before it goes to the LLM"
)
def test_qa_a_weakness_tag_can_not_carry_a_url_to_the_llm(api: Api, paths: Any) -> None:
    plant_managed_install(paths)
    svc = _svc(api)
    _games(svc, 1)
    rid = _run(svc, {"source": "games", **ANY_GAME})
    got = api.add_journal_entry({"text": "plain", "weakness_key": "https://evil.example/u", "entry_date": "2030-01-01"})
    if got["ok"]:
        lines = _ok(api.get_coach_journal_preview(rid))
        assert all("evil.example" not in str(x) for x in lines)


# ---- FR-10.71: scope, limits and the preview ----


def test_qa_the_preview_is_exactly_what_is_sent_in_scope_order_cut_and_labels(api: Api, paths: Any, clock: Any) -> None:
    plant_managed_install(paths)
    svc = _svc(api)
    ids = _games(svc, 2)
    outside = _secret_game(api, 7)
    with svc.db.transaction() as conn:  # keep this one out of the report
        conn.execute("UPDATE game_subjects SET subject = 'lichess:other' WHERE game_id = ?", (outside,))
    rid = _run(svc, {"source": "games", **ANY_GAME})
    row = api._coach.report(rid)[0]
    assert set(row.game_ids) == set(ids)
    since = str(row.report["first_played"])[:10]
    before = (datetime.fromisoformat(since) - timedelta(days=1)).date().isoformat()
    after = (datetime.fromisoformat(since) + timedelta(days=1)).date().isoformat()
    tagged_old = _ok(
        api.add_journal_entry({"text": "Tagged, dated before.", "game_id": ids[1], "ply": 2, "entry_date": before})
    )
    _ok(api.add_journal_entry({"text": "Untagged, dated before: stays home.", "entry_date": before}))
    _ok(api.add_journal_entry({"text": "Dated the first day.", "entry_date": since}))
    _ok(
        api.add_journal_entry(
            {"text": "On a game outside the report.", "game_id": outside, "ply": 1, "entry_date": after}
        )
    )
    long = "x" * 1400
    _ok(api.add_journal_entry({"text": f"See https://example.org/a {long}", "entry_date": after}))
    _ok(api.add_journal_entry({"text": "https://example.org/only", "entry_date": after, "weakness_key": "missed:fork"}))
    preview = _ok(api.get_coach_journal_preview(rid))
    texts = [p["text"] for p in preview]
    assert "Untagged, dated before: stays home." not in texts
    assert "Tagged, dated before." in texts and "Dated the first day." in texts
    cut = next(p for p in preview if p["text"].startswith("See "))
    assert len(cut["text"]) == 1000 and "example.org" not in cut["text"]
    off = next(p for p in preview if p["text"].startswith("On a game outside"))
    assert off["game"] is None and off["ply"] is None and off["move"] is None
    tagged = next(p for p in preview if p["text"] == "Tagged, dated before.")
    assert tagged["game"] in ("G1", "G2") and tagged["ply"] == 3 and tagged_old["ply"] == 2

    configure(svc)
    fake(svc).queue(_with())
    _wait(api, api.start_coach_ai(rid, {"include_journal": True}))
    sent = _journal_lines(fake(svc).requests[-1].user)
    assert [s["note"] for s in sent] == texts  # the same entries, the same text, the same order
    assert [s.get("game") for s in sent] == [p["game"] for p in preview]
    assert [s.get("ply") for s in sent] == [p["ply"] for p in preview]
    assert [s.get("weakness") for s in sent] == [p["weakness"] for p in preview]


def test_qa_only_the_newest_30_entries_go(api: Api, paths: Any) -> None:
    plant_managed_install(paths)
    svc = _svc(api)
    _games(svc, 1)
    rid = _run(svc, {"source": "games", **ANY_GAME})
    for i in range(35):
        _ok(api.add_journal_entry({"text": f"Entry {i}", "entry_date": "2030-01-01"}))
    preview = _ok(api.get_coach_journal_preview(rid))
    assert [p["text"] for p in preview] == [f"Entry {i}" for i in range(34, 4, -1)]


def test_qa_journal_text_never_goes_without_the_option_even_from_a_task(api: Api, paths: Any) -> None:
    plant_managed_install(paths)
    svc = _svc(api)
    gid = _games(svc, 1)[0]
    rid = _run(svc, {"source": "games", **ANY_GAME})
    _ok(api.add_journal_entry({"text": "PRIVATE ONE", "game_id": gid, "ply": 2}))
    _ok(api.add_journal_entry({"text": "PRIVATE TWO", "entry_date": "2030-01-01"}))
    configure(svc)
    fake(svc).queue(_with())
    _wait(api, api.start_coach_ai(rid))
    fake(svc).queue(_with())
    _wait(api, api.start_coach_ai(rid, {"include_notes": True}))
    for req in fake(svc).requests:
        assert "PRIVATE" not in req.user and "journal" not in req.user.lower()


def test_qa_another_players_report_never_sends_your_journal_or_your_plan(api: Api, paths: Any) -> None:
    plant_managed_install(paths)
    svc = _svc(api)
    gid = _games(svc, 1)[0]
    _ok(api.add_journal_entry({"text": "PRIVATE", "game_id": gid, "ply": 1}))
    _plan_with(api, [[_puzzles_task(1), Task(REFLECTION, 10, "PRIVATE TITLE", {"prompt": "x"})]])
    with svc.db.transaction() as conn:
        conn.execute("UPDATE game_subjects SET subject = 'lichess:someone' WHERE game_id = ?", (gid,))
    rid = _report_row(api, 1, [gid], {}, subject="lichess:someone")
    configure(svc)
    assert _ok(api.get_coach_journal_preview(rid)) == []
    fake(svc).queue(_with())
    _wait(api, api.start_coach_ai(rid, {"include_journal": True}))
    req = fake(svc).requests[-1]
    assert "PRIVATE" not in req.user and "training plan" not in req.user and "Plan shape" not in req.user
    assert "plan" not in req.schema["required"]


def test_qa_the_new_limits_at_each_detail_and_reasoning_reach_the_request(api: Api, paths: Any) -> None:
    plant_managed_install(paths)
    svc = _svc(api)
    _games(svc, 1)
    configure(svc)
    for detail, level, want in (
        ("summary", "low", 7500),
        ("detailed", "low", 10000),
        ("summary", "medium", 15000),
        ("detailed", "high", 40000),
    ):
        rid = _run(svc, {"source": "games", "detail": detail, **ANY_GAME})
        svc.llm_settings.update_feature("coach", "anthropic", "claude-haiku-5-5", level)
        fake(svc).queue(_with())
        _wait(api, api.start_coach_ai(rid))
        assert fake(svc).requests[-1].max_tokens == want, (detail, level)


# ---- the saved-answer rules ----


def _estimate(api: Api, rid: int, opts: Any = None) -> str:
    return str(_ok(api.get_coach_ai_quote(rid, opts))["quote"]["state"])


def _setup_saved(api: Api, paths: Any) -> tuple[int, int, Any]:
    plant_managed_install(paths)
    svc = _svc(api)
    gid = _games(svc, 1)[0]
    rid = _run(svc, {"source": "games", **ANY_GAME})
    configure(svc)
    return rid, gid, svc


def test_qa_saved_answers_follow_the_journal_text_in_scope_not_anything_else(api: Api, paths: Any) -> None:
    rid, gid, svc = _setup_saved(api, paths)
    on = {"include_journal": True}
    entry = _ok(api.add_journal_entry({"text": "First.", "game_id": gid}))
    fake(svc).queue(_with())
    _wait(api, api.start_coach_ai(rid, on))
    sent = len(fake(svc).requests)
    assert _estimate(api, rid, on) == "cached"
    # A plan shape change, an out-of-scope entry and a run with the option off: none reuses or rebills wrongly.
    _ok(api.set_setting("plan.params", {"weeks": 4, "weekdays": [0], "minutes": 60}))
    assert _estimate(api, rid, on) == "cached"
    _ok(api.add_journal_entry({"text": "Out of scope.", "entry_date": "2001-01-01"}))
    assert _estimate(api, rid, on) == "cached"
    assert _estimate(api, rid) == "ok"  # option off: never the answer that had your journal
    # The text changes: added, edited, deleted.
    second = _ok(api.add_journal_entry({"text": "Second.", "entry_date": "2030-01-01"}))
    assert _estimate(api, rid, on) == "ok"
    _ok(api.delete_journal_entry(second["id"]))
    assert _estimate(api, rid, on) == "cached"  # the very same text again
    _ok(api.edit_journal_entry(entry["id"], "First, changed."))
    assert _estimate(api, rid, on) == "ok"
    assert len(fake(svc).requests) == sent  # estimates never send anything


def test_qa_a_saved_answer_is_shown_free_and_keeps_the_shape_it_was_made_with(api: Api, paths: Any) -> None:
    rid, _gid, svc = _setup_saved(api, paths)
    _ok(api.set_setting("plan.params", {"weeks": 1, "weekdays": [0, 1], "minutes": 20}))
    fake(svc).queue(_with())
    _wait(api, api.start_coach_ai(rid))
    run = _ok(api.list_coach_ai_runs(rid))[-1]
    assert len(_ok(api.get_coach_ai_run(rid, run["id"]))["plan"]["days"]) == 2
    _ok(api.set_setting("plan.params", {"weeks": 3, "weekdays": [0, 1, 2], "minutes": 40}))
    sent = len(fake(svc).requests)
    _wait(api, api.start_coach_ai(rid))
    assert len(fake(svc).requests) == sent
    assert len(_ok(api.list_coach_ai_runs(rid))) == 1
    plan = _ok(api.get_coach_ai_run(rid, run["id"]))["plan"]
    assert len(plan["days"]) == 2 and plan["minutes"] == 20
    made = _ok(api.use_ai_plan(run["id"]))
    assert len(made["days"]) == 2 and made["source"] == "ai"


def test_qa_a_v011_answer_is_not_reused_for_you_but_is_for_another_player(api: Api, paths: Any) -> None:
    rid, gid, svc = _setup_saved(api, paths)
    cfg = svc.llm_settings.config("coach")
    add = AiRunsRepo(svc.db).add
    add(rid, "2026-01-01T10:00:00+00:00", "diagnosis", advanced=False, include_notes=False, game_cap=None,
        provider=cfg.provider, model=cfg.model, cost_usd=0.01, result={"summary": "v0.11", "weaknesses": []})  # fmt: skip
    assert _estimate(api, rid) == "ok"
    with svc.db.transaction() as conn:
        conn.execute("UPDATE game_subjects SET subject = 'lichess:someone' WHERE game_id = ?", (gid,))
    other = _report_row(api, 9, [gid], {}, subject="lichess:someone")
    add(other, "2026-01-09T10:00:00+00:00", "diagnosis", advanced=False, include_notes=False, game_cap=None,
        provider=cfg.provider, model=cfg.model, cost_usd=0.01, result={"summary": "v0.11", "weaknesses": []})  # fmt: skip
    assert _estimate(api, other) == "cached"


def test_qa_an_ai_plan_with_invalid_tasks_is_filled_and_can_be_used(api: Api, paths: Any) -> None:
    rid, gid, svc = _setup_saved(api, paths)
    _ok(api.set_setting("plan.params", {"weeks": 1, "weekdays": [0, 1], "minutes": 20}))
    bad = {"type": "teleport", "minutes": 10}
    url = {"type": "reflection", "minutes": 5, "prompt": "See https://evil.example/x"}
    only_url = {"type": "reflection", "minutes": 5, "prompt": "https://evil.example/x"}
    html = {"type": "reflection", "minutes": 5, "prompt": "<img src=x onerror=alert(1)>"}
    wrong_game = {"type": "review", "minutes": 10, "game": f"G{gid + 77}"}
    raw_id = {"type": "review", "minutes": 10, "game": str(gid)}
    theme = {"type": "puzzles", "minutes": 10, "themes": ["notATheme"], "mode": "standard", "count": 5}
    mode = {"type": "puzzles", "minutes": 10, "themes": ["fork"], "mode": "hack", "count": 5}
    huge = {"type": "puzzles", "minutes": 10, "themes": ["fork"], "mode": "standard", "count": 10**9}
    plan = {
        "weeks": [{"days": [{"tasks": [bad, url, only_url, wrong_game, raw_id]}, {"tasks": [html, theme, mode, huge]}]}]
    }
    fake(svc).queue(_with(plan))
    _wait(api, api.start_coach_ai(rid))
    run_id = _ok(api.list_coach_ai_runs(rid))[-1]["id"]
    got = _ok(api.get_coach_ai_run(rid, run_id))
    titles = [t["title"] for d in got["plan"]["days"] for t in d["tasks"]]
    assert not any("evil.example" in t for t in titles)
    assert got["plan_check"]["fallback"] is False and got["plan_check"]["dropped"] >= 5
    for d in got["plan"]["days"]:
        assert sum(t["minutes"] for t in d["tasks"]) == 20 and 2 <= len(d["tasks"]) <= 4
    made = _ok(api.use_ai_plan(run_id))
    for d in made["days"]:
        for t in d["tasks"]:
            assert api.start_plan_task(t["id"], False)["ok"], t


@pytest.mark.parametrize(
    "raw",
    [
        "null",
        "[]",
        '"plan"',
        "{}",
        '{"weeks": 3}',
        '{"weeks": [{"days": 3}]}',
        '{"weeks": [{"days": [{"tasks": "x"}]}]}',
    ],
)
def test_qa_a_broken_plan_falls_back_to_the_free_plan_whole(api: Api, paths: Any, raw: str) -> None:
    rid, _gid, svc = _setup_saved(api, paths)
    data = json.loads(_answer())
    data["plan"] = json.loads(raw)
    data["trend"] = []
    fake(svc).queue(json.dumps(data))
    _wait(api, api.start_coach_ai(rid))
    run_id = _ok(api.list_coach_ai_runs(rid))[-1]["id"]
    got = _ok(api.get_coach_ai_run(rid, run_id))
    assert got["plan_check"]["fallback"] is True and got["plan"]["days"]


# ---- FR-10.73 ----


def _weak(key: str, per10: float, **kw: Any) -> dict[str, Any]:
    kind, name = key.split(":", 1)
    return {"key": key, "kind": kind, "name": name, "label": key, "count": 3, "per10": per10, "severity": 200, "score": 3.0,
            "themes": [], "mode": None, "reasons": {}, "examples": [], **kw}  # fmt: skip


@pytest.mark.xfail(
    strict=True, reason="v0.12-B2: a whole-game weakness gone below the 5-game group guard is called better"
)
def test_qa_a_whole_game_weakness_whose_group_fell_below_5_games_is_not_called_better() -> None:
    w = _weak("opening:Sicilian", 6.0)
    old = {"source": "games", "games": 20, "whole_game": [w], "weaknesses": [],
           "measures": {"openings": [{"family": "Sicilian", "games": 8, "score": 30.0}]}}  # fmt: skip
    # 20 new games, but only 2 in that opening: it has no group, so it can't be a weakness this time.
    new = {"source": "games", "games": 20, "whole_game": [], "weaknesses": [],
           "measures": {"openings": [{"family": "Sicilian", "games": 2, "score": 50.0}]}}  # fmt: skip
    c = compare(
        Side(2, "2026-01-02T10:00:00+00:00", new, frozenset(range(100, 120))),
        [Side(1, "2026-01-01T10:00:00+00:00", old, frozenset(range(20)))],
    )
    assert c is not None
    row = c.weaknesses[0]
    assert row.flag == "gone" and row.verdict == "not_enough", row


def test_qa_since_last_report_from_real_runs_matches_the_two_stored_reports(api: Api, paths: Any, clock: Any) -> None:
    plant_managed_install(paths)
    svc = _svc(api)
    _games(svc, 6)
    first = _run(svc, {"source": "games", **ANY_GAME})
    clock.advance(days=4)
    _games(svc, 12)[6:]
    second = _run(svc, {"source": "games", **ANY_GAME})
    a, b = api._coach.report(first)[0], api._coach.report(second)[0]
    c = _ok(api.get_coach_report(second))["comparison"]
    assert c["earlier_id"] == first and c["days_between"] == 4
    assert c["new_games"] == len(set(b.game_ids) - set(a.game_ids)) and c["shared_games"] == len(
        set(b.game_ids) & set(a.game_ids)
    )

    def rates(r: Any) -> dict[str, float]:
        groups = ("missed", "allowed", "habits", "whole_game")
        return {w["key"]: w["per10"] for g in groups for w in r.report.get(g) or []}

    ra, rb = rates(a), rates(b)
    assert c["weaknesses"]
    for w in c["weaknesses"]:
        assert w["then"] == ra.get(w["key"])
        assert w["now"] == rb.get(w["key"], 0.0)
        assert (w["flag"] == "new") == (w["key"] not in ra)
    assert c["settings"] == "same"


def test_qa_puzzle_accuracy_windows_with_real_attempts_do_not_crash_on_times(api: Api, paths: Any, clock: Any) -> None:
    plant_managed_install(paths)
    svc = _svc(api)
    _games(svc, 6)
    first = _run(svc, {"source": "games", **ANY_GAME})
    info = _ok(api.start_session({"queue_size": 15}, False, "standard", False))
    for _ in range(14):
        _ok(api.next_puzzle(info["session_id"]))
    clock.advance(days=1)
    second = _run(svc, {"source": "games", **ANY_GAME})
    assert _ok(api.get_coach_report(second))["comparison"]["earlier_id"] == first
    # A pre-v0.12 report and a puzzle-history one never mix.
    p1 = _run(svc, {"source": "puzzles"})
    assert _ok(api.get_coach_report(p1))["comparison"] is None
    clock.advance(days=1)
    third = _run(svc, {"source": "games", **ANY_GAME})
    assert _ok(api.get_coach_report(third))["comparison"]["earlier_id"] == second


# ---- FR-10.67-10.70 ----


def _jdates(t: dict[str, Any]) -> list[str]:
    return [str(i["entry"]["text"]) for i in t["items"] if i["entry"]]


def test_qa_a_reflection_shows_in_game_and_journal_and_survives_the_game_notes_read(api: Api) -> None:
    gid = _secret_game(api, 0)
    e = _ok(api.add_journal_entry({"text": "On a move.", "game_id": gid, "ply": 2}))
    whole = _ok(api.add_journal_entry({"text": "On the game.", "game_id": gid}))
    assert [n["id"] for n in _ok(api.get_game_notes(gid))] == [whole["id"], e["id"]]
    t = _ok(api.get_journal({"game_id": gid}))
    assert {i["entry"]["id"] for i in t["items"]} == {e["id"], whole["id"]}
    assert all(i["log"] is None for i in t["items"])
    assert e["ply"] == 2 and e["move"]


@pytest.mark.xfail(strict=True, reason="v0.12-B8: a note can be saved on a move the game doesn't have")
def test_qa_a_note_on_a_move_past_the_end_of_the_game_is_refused(api: Api) -> None:
    gid = _secret_game(api, 0)
    assert api.add_journal_entry({"text": "No such move.", "game_id": gid, "ply": 9999})["ok"] is False


def test_qa_an_entry_of_exactly_the_limit_is_kept_and_one_more_is_refused(api: Api) -> None:
    assert _ok(api.add_journal_entry({"text": "y" * 5000}))["text"] == "y" * 5000
    assert api.add_journal_entry({"text": "y" * 5001})["ok"] is False
    assert api.add_journal_entry({"text": "   "})["ok"] is False
    e = _ok(api.add_journal_entry({"text": "Keep my tag.", "weakness_key": "missed:fork"}))
    assert _ok(api.edit_journal_entry(e["id"], "Edited.", "missed:fork"))["weakness_key"] == "missed:fork"
    assert api.edit_journal_entry(e["id"], "y" * 5001, "missed:fork")["ok"] is False


@pytest.mark.xfail(
    strict=True, reason="v0.12-B8: a task or day that doesn't exist crashes the call instead of a plain refusal"
)
def test_qa_bad_links_on_a_journal_entry_get_a_plain_refusal(api: Api) -> None:
    for field in ("plan_task_id", "plan_day_id"):
        got = api.add_journal_entry({"text": "x", field: 987654})
        assert got["ok"] is False and got["error"]["code"] != "internal", got
    assert api.add_journal_entry({"text": "x", "game_id": 987654})["ok"] is False
    assert api.add_journal_entry({"text": "x", "ply": 3})["ok"] is False
    assert api.add_journal_entry({"text": "x", "entry_date": "not a date"})["ok"] is False


def test_qa_search_treats_wildcards_literally_and_is_case_insensitive(api: Api) -> None:
    _ok(api.add_journal_entry({"text": "100% sure about Fork_one"}))
    _ok(api.add_journal_entry({"text": "plain words"}))
    assert _jdates(_ok(api.get_journal({"query": "%"}))) == ["100% sure about Fork_one"]
    assert _jdates(_ok(api.get_journal({"query": "_"}))) == ["100% sure about Fork_one"]
    assert _jdates(_ok(api.get_journal({"query": "PLAIN"}))) == ["plain words"]
    assert _jdates(_ok(api.get_journal({"query": "' OR 1=1 --"}))) == []


@pytest.mark.xfail(
    strict=True, reason="v0.12-B7: search and filters only look at the newest 30 days until you page back"
)
def test_qa_search_finds_an_old_entry(api: Api, clock: Any) -> None:
    _ok(api.add_journal_entry({"text": "An old thought about pins."}))
    clock.advance(days=60)
    assert _jdates(_ok(api.get_journal({"query": "pins"}))) == ["An old thought about pins."]


@pytest.mark.xfail(strict=True, reason="v0.12-B8: an entry dated in the future is stored but never shown")
def test_qa_an_entry_dated_tomorrow_is_not_lost(api: Api, clock: Any) -> None:
    tomorrow = (clock.now() + timedelta(days=1)).date().isoformat()
    got = api.add_journal_entry({"text": "From the future.", "entry_date": tomorrow})
    assert got["ok"] is False or _jdates(_ok(api.get_journal({}))) == ["From the future."]


# ---- FR-10.68: the daily log against Stats ----


def test_qa_the_daily_log_matches_stats_for_a_mixed_day_with_real_attempts(api: Api, paths: Any) -> None:
    sid = _ok(api.start_session({"queue_size": 6}, False, "standard", False))["session_id"]
    assert _solve_next(api, paths, sid)  # a win
    assert _solve_next(api, paths, sid)
    _ok(api.next_puzzle(sid))
    _ok(api.next_puzzle(sid))  # a loss
    svc = _svc(api)
    with svc.db.transaction() as conn:  # the attempts Stats treats specially, in their stored form
        first = conn.execute("SELECT MIN(id) FROM attempts WHERE win = 0").fetchone()[0]
        conn.execute(
            "INSERT INTO mistake_reasons (source, ref_id, reason, created_at) VALUES ('puzzle', ?, 'misclick', ?)",
            (str(first), "2026-01-01T12:00:00+00:00"),
        )
        row = conn.execute("SELECT * FROM attempts LIMIT 1").fetchone()
        cols = [d[1] for d in conn.execute("PRAGMA table_info(attempts)").fetchall()]
        values = dict(zip(cols, row, strict=True))
        values.pop("id")
        values.update(mode="danger_spotting", danger_safe=1, win=1)
        conn.execute(
            f"INSERT INTO attempts ({','.join(values)}) VALUES ({','.join('?' * len(values))})",
            tuple(values.values()),
        )
    logs = [i["log"] for i in _ok(api.get_journal({}))["items"] if i["log"]]
    assert len(logs) == 1
    log = logs[0]
    stats = _ok(api.get_stats())
    assert log["overall"]["attempts"] == stats["overall"]["attempts"]
    assert log["overall"]["solved"] == stats["overall"]["solved"]
    assert log["misclicks"] == stats["misclicks"]
    assert {m["key"]: m["attempts"] for m in log["by_mode"]} == {m["key"]: m["attempts"] for m in stats["by_mode"]}
    assert {m["key"]: m["solved"] for m in log["by_mode"]} == {m["key"]: m["solved"] for m in stats["by_mode"]}
    report = build_report(svc_rows(api), display_name)
    assert log["overall"]["attempts"] == report.overall.attempts
    assert sum(s["attempts"] for s in log["by_source"]) == report.overall.attempts  # danger is its own mode only


def svc_rows(api: Api) -> list[Any]:
    return [r for r, _ in api._journal._stats.attempt_rows_between("2000-01-01", "2100-01-01")]


def test_qa_the_log_files_an_attempt_on_your_local_day_not_the_utc_one(
    paths: Any, desktop: FakeDesktop, fixture_puzzles_db: Any
) -> None:
    clock = FixedClock(
        datetime(2026, 3, 10, 23, 30, tzinfo=UTC), timezone(timedelta(hours=2))
    )  # 01:30 local on the 11th
    api = _api(paths, clock, desktop, fixture_puzzles_db)
    sid = _ok(api.start_session({"queue_size": 3}, False, "standard", False))["session_id"]
    _ok(api.next_puzzle(sid))
    _ok(api.next_puzzle(sid))
    logs = [i for i in _ok(api.get_journal({}))["items"] if i["log"]]
    assert [i["date"] for i in logs] == ["2026-03-11"]
    e = _ok(api.add_journal_entry({"text": "Late."}))
    assert e["entry_date"] == "2026-03-11"


def test_qa_the_daily_log_counts_each_fact_on_its_day(api: Api, paths: Any, clock: Any) -> None:
    plant_managed_install(paths)
    svc = _svc(api)
    gid = _games(svc, 1)[0]
    _run(svc, {"source": "games", **ANY_GAME})
    rev = _ok(api.get_review(gid))
    for m in [*rev["key_moments"], len(rev["moves"]) - 1]:
        _ok(api.mark_review_ply(gid, m))
    ply = rev["retry_plies"][0]
    _ok(api.retry_move(gid, ply, rev["moves"][ply]["best_move"] or rev["moves"][ply]["uci"]))
    plan = _plan_with(api, [[Task(REFLECTION, 10, "x", {"prompt": "x"}), _puzzles_task(1)]])
    _ok(api.add_journal_entry({"text": "From the task.", "plan_task_id": plan["days"][0]["tasks"][0]["id"]}))
    _ok(api.get_today_plan())
    log = next(i["log"] for i in _ok(api.get_journal({}))["items"] if i["log"])
    assert log["games_reviewed"] == 1 and log["retries"] == 1 and log["plan_tasks_done"] == 1
    assert log["games_synced"] == 1 and len(log["coach_runs"]) == 1
    clock.advance(days=1)
    items = [i for i in _ok(api.get_journal({}))["items"] if i["log"]]
    assert len(items) == 1 and items[0]["log"]["games_reviewed"] == 1  # nothing moved to the new day


@pytest.mark.xfail(
    strict=True, reason="v0.12-B6: a task you ticked by hand isn't counted under Plan tasks done in the daily log"
)
def test_qa_the_daily_log_counts_a_task_ticked_by_hand(api: Api) -> None:
    plan = _plan_with(api, [[Task(REFLECTION, 10, "x", {"prompt": "x"}), _puzzles_task(1)]])
    _ok(api.set_plan_task_tick(plan["days"][0]["tasks"][0]["id"], True))
    assert _ok(api.get_current_plan())["done"] == 1
    log = next((i["log"] for i in _ok(api.get_journal({}))["items"] if i["log"]), None)
    assert log is not None and log["plan_tasks_done"] == 1


def test_qa_the_log_needs_no_coach_or_plan_and_a_new_journal_is_empty(api: Api) -> None:
    t = _ok(api.get_journal({}))
    assert t["items"] == []
    assert api.get_journal({"kinds": ["nope"]})["ok"] is False
    assert api.get_journal({"evil": 1})["ok"] is False
    assert api.get_journal({"date_from": "x"})["ok"] is False


def test_qa_sqlite_journal_tables_hold_no_journal_copy_in_ai_runs(api: Api, paths: Any) -> None:
    rid, gid, svc = _setup_saved(api, paths)
    _ok(api.add_journal_entry({"text": "PRIVATE WORDS", "game_id": gid}))
    fake(svc).queue(_with())
    _wait(api, api.start_coach_ai(rid, {"include_journal": True}))
    conn = sqlite3.connect(paths.user_db)
    try:
        blob = repr(conn.execute("SELECT * FROM coach_ai_runs").fetchall()) + repr(
            conn.execute("SELECT * FROM llm_usage").fetchall()
        )
    finally:
        conn.close()
    assert "PRIVATE WORDS" not in blob


def test_qa_the_new_limits_block_a_costly_model_at_confirm_never_silently(api: Api, paths: Any) -> None:
    rid, _gid, svc = _setup_saved(api, paths)
    svc.llm_settings.update_feature("coach", "anthropic", "claude-fable-5-1", "high")
    q = _ok(api.get_coach_ai_quote(rid))["quote"]
    assert (
        q["state"] not in ("ok", "cached") and q["worst_usd"] > 0.50
    )  # 4 x 7,500 tokens at the seeded price: over the cap
    assert fake(svc).requests == []
    svc.llm_settings.update_feature("coach", "anthropic", "claude-haiku-5-5", "high")
    assert _ok(api.get_coach_ai_quote(rid))["quote"]["state"] == "ok"


def test_qa_opening_a_report_and_the_today_card_stay_fast_with_a_big_history(api: Api, paths: Any, clock: Any) -> None:
    plant_managed_install(paths)
    svc = _svc(api)
    _games(svc, 6)
    _run(svc, {"source": "games", **ANY_GAME})
    sid = _ok(api.start_session({"queue_size": 3}, False, "standard", False))["session_id"]
    _ok(api.next_puzzle(sid))
    _ok(api.next_puzzle(sid))
    with svc.db.transaction() as conn:
        cols = [d[1] for d in conn.execute("PRAGMA table_info(attempts)").fetchall()]
        row = dict(zip(cols, conn.execute("SELECT * FROM attempts LIMIT 1").fetchone(), strict=True))
        row.pop("id")
        conn.executemany(
            f"INSERT INTO attempts ({','.join(row)}) VALUES ({','.join('?' * len(row))})",
            [tuple(row.values())] * 100_000,
        )
    clock.advance(days=1)
    second = _run(svc, {"source": "games", **ANY_GAME})
    _plan_with(api, [[_puzzles_task(1), Task(REFLECTION, 10, "x", {"prompt": "x"})]])
    api._coach._comparisons.clear()  # the first read after a restart
    started = time.perf_counter()
    assert _ok(api.get_coach_report(second))["comparison"] is not None
    report_s = time.perf_counter() - started
    started = time.perf_counter()
    _ok(api.get_today_plan())
    today_s = time.perf_counter() - started
    started = time.perf_counter()
    _ok(api.get_journal({}))
    journal_s = time.perf_counter() - started
    print(f"100,000 attempts: report {report_s:.2f}s, today {today_s:.3f}s, journal {journal_s:.2f}s")
    assert report_s < 5 and today_s < 1 and journal_s < 5, (report_s, today_s, journal_s)
