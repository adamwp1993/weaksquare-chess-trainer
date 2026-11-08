"""QA v0.14 (independent): studies through the service and the bridge, with the fake Lichess client. Covers what the
builder's tests leave open: the token never sent for a public study even when signed in with study:read, an unknown
author as the real API answers it, usernames checked before any request, Check for updates on a private study, and
study text never reaching any AI request (Explain my game run for real against the fake provider). A test exposing an
open bug is xfail (strict) with its ID."""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.fakes.lichess import FAKE_TOKEN
from tests.fakes.studies import fixture_pgn
from tests.integration.test_game_explain import NARRATIVE_ANSWER
from tests.integration.test_game_explain_bridge import api, configure, fake, finish, game, ok  # noqa: F401
from tests.integration.test_studies import Rig, rig  # noqa: F401
from weaksquare.adapters.http import HttpError
from weaksquare.core.errors import AppError, NotFoundError, ValidationError


def test_qa14_a_public_study_never_sends_the_token_even_with_study_read(rig: Rig) -> None:  # noqa: F811
    rig.tokens.value, rig.tokens.scopes = FAKE_TOKEN, {"study:read"}
    assert rig.add("TestNm02").state == "done"
    assert rig.run(rig.svc.check_updates("TestNm02")).state == "done"
    assert rig.client.calls == [("TestNm02", None), ("TestNm02", None)]


def test_qa14_check_for_updates_on_a_private_study_asks_without_the_token_first(rig: Rig) -> None:  # noqa: F811
    rig.tokens.value, rig.tokens.scopes = FAKE_TOKEN, {"study:read"}
    rig.client.private["TestPv01"] = fixture_pgn("TestGb01")
    assert rig.add("TestPv01").state == "done"
    row, _ = rig.svc.get("TestPv01")
    assert row.private
    rig.client.calls.clear()
    st = rig.run(rig.svc.check_updates("TestPv01"))
    assert st.state == "done"
    assert rig.client.calls == [("TestPv01", None), ("TestPv01", FAKE_TOKEN)]


def test_qa14_private_study_after_signing_out_keeps_your_copy(rig: Rig) -> None:  # noqa: F811
    rig.tokens.value, rig.tokens.scopes = FAKE_TOKEN, {"study:read"}
    rig.client.private["TestPv01"] = fixture_pgn("TestGb01")
    rig.add("TestPv01")
    rig.tokens.value, rig.tokens.scopes = None, set()
    st = rig.run(rig.svc.check_updates("TestPv01"))
    assert (st.state, st.error_code) == ("failed", "study_private")
    assert rig.svc.chapter("TestPv01", "Chap0001")[1].children  # your copy still opens


@pytest.mark.parametrize("name", ["../api/account", "a", "x" * 31, "name with space", "lichess.org/@/", "-bad-"])
def test_qa14_a_bad_username_makes_no_request(rig: Rig, name: str) -> None:  # noqa: F811
    with pytest.raises(ValidationError):
        rig.svc.studies_by(name)
    assert rig.client.calls == []


def test_qa14_an_author_with_no_public_studies_lists_nothing(rig: Rig) -> None:  # noqa: F811
    rig.client.authors["player_quiet"] = []
    assert rig.svc.studies_by("player_quiet") == []


def test_qa14_b2_an_unknown_user_gets_its_own_message(rig: Rig) -> None:  # noqa: F811
    """`GET /api/study/by/{unknown}` returned HTTP 200 with an empty body when checked by QA on 2026-11-08, so the
    app's 404 branch never runs and an unknown user reads 'No public studies.' FR-13.5a asks for a clear message for an
    unknown user, separate from 'no studies'."""
    # Regression for B2: the fake now answers an unknown user like real Lichess (200, empty), and the app asks
    # `/api/user/` only then. A user that exists with no public studies still gets an empty list (test above).
    with pytest.raises(NotFoundError) as e:
        rig.svc.studies_by("player_nobody")
    assert e.value.code == "user_not_found"
    assert rig.client.calls == [("by:player_nobody", None), ("user:player_nobody", None)]
    rig.client.errors["user:player_nobody"] = HttpError("Network error while fetching x: ConnectError")
    with pytest.raises(AppError) as e2:
        rig.svc.studies_by("player_nobody")
    assert e2.value.code == "offline"


def test_qa14_author_search_offline_and_rate_limited(rig: Rig) -> None:  # noqa: F811
    from tests.fakes.studies import rate_limited

    # What adapters/http.py's stream_ndjson raises for a transport error.
    rig.client.errors["by:player_author"] = HttpError("Network error while fetching x: ConnectError")
    with pytest.raises(AppError) as e:
        rig.svc.studies_by("player_author")
    assert e.value.code == "offline" and "reached" in str(e.value)
    rig.client.errors["by:player_author"] = rate_limited()
    with pytest.raises(AppError) as e2:
        rig.svc.studies_by("player_author")
    assert e2.value.code == "rate_limited"


def test_qa14_b3_author_search_on_a_lichess_5xx_doesnt_blame_your_connection(rig: Rig) -> None:  # noqa: F811
    """adapters/http.py raises a retryable HttpError for a 5xx, which is_network_error counts as offline. Downloading a
    study says 'Lichess is having trouble' for the same answer (v0.14a note in plans/v0.14.md); Studies by author
    should too."""
    rig.client.errors["by:player_author"] = HttpError("x returned HTTP 503", status=503)
    with pytest.raises(AppError) as e:
        rig.svc.studies_by("player_author")
    assert e.value.code != "offline"
    assert "connection" not in str(e.value)


def test_qa14_restart_clears_place_and_finished_but_keeps_hearts(rig: Rig) -> None:  # noqa: F811
    rig.add("TestNm02")
    rig.svc.heart("TestNm02", True)
    rig.svc.set_place("TestNm02", "Chap0001", "e2e4 e7e5")
    rig.svc.set_done("TestNm02", "Chap0003", True)
    rig.svc.restart("TestNm02")
    row, _ = rig.svc.get("TestNm02")
    assert (row.place_key, row.done, row.hearted) == (None, 0, True)


def test_qa14_a_place_in_a_side_line_is_accepted_and_one_off_the_tree_refused(rig: Rig) -> None:  # noqa: F811
    rig.add("TestNm02")
    rig.svc.set_place("TestNm02", "Chap0001", "e2e4 e7e5 b1c3 b8c6 f2f4")  # 2... Nc6 3. f4 side line
    assert rig.svc.continue_target("TestNm02") == ("Chap0001", "e2e4 e7e5 b1c3 b8c6 f2f4")
    for bad in ("e2e4 e7e5 g1f3", "e2e4 zz", "e2e4;drop"):
        with pytest.raises(ValidationError):
            rig.svc.set_place("TestNm02", "Chap0001", bad)
    with pytest.raises(ValidationError):
        rig.svc.set_place("TestNm02", "Chap0002", "")  # a rejected chapter


# ---- FR-13.12: study text never reaches an AI, even when AI features run after a study was added -------------------
STUDY_STRINGS = ("Invented analysis", "The quiet move", "player_author", "example.com", "Invented gamebook",
                 "TestNm02", "TestGb01")  # fmt: skip


def test_qa14_study_text_is_absent_from_explain_my_game_and_explain_this_move(api: Any, game: int) -> None:  # noqa: F811
    for sid in ("TestNm02", "TestGb01"):
        job = ok(api.add_study(sid))
        st = api._runner.wait(job, 10)
        assert st is not None and st.state == "done", st
        ok(api.get_study_chapter(sid, "Chap0001"))
    configure(api)
    fake(api).queue(json.dumps(NARRATIVE_ANSWER))
    finish(api, ok(api.start_game_narrative(game, None)))
    requests = fake(api).requests
    assert requests, "Explain my game made no request"
    for r in requests:
        blob = r.system + "\n" + r.user
        for s in STUDY_STRINGS:
            assert s not in blob, f"study text {s!r} reached the AI"
    # FR-11.36: the prompt lists the computed strengths section, and nothing else claims praise.
    assert "What you did well (computed from Stockfish's numbers" in requests[-1].user
