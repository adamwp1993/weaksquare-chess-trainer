"""AccountService (FR-1.1, 1.6, 1.7, FR-6.1–6.7, FR-6.11a) against fakes: the sign-in job, the launch
check, offline and expired states, sign-out and token handling (SR-7)."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from tests.fakes.desktop import STATE, VERIFIER, FakeBrowser, FakeScheduler, ListenerFactory, secrets_sequence
from tests.fakes.lichess import FAKE_TOKEN, FakeLichess, network_error
from weaksquare.adapters.http import HttpError, Unauthorized
from weaksquare.adapters.lichess import is_network_error, is_unauthorized
from weaksquare.adapters.oauth_loopback import LoopbackCancelled, LoopbackTimeout
from weaksquare.adapters.secret_store import MemorySecretStore
from weaksquare.core.errors import AppError
from weaksquare.core.oauth import challenge
from weaksquare.jobs.runner import JobRunner
from weaksquare.services.account import ACCOUNT_KEY, AccountDeps, AccountService, AccountStatus, ListenerErrors


class MemSettings(dict):
    def set(self, key, value):  # type: ignore[no-untyped-def]
        self[key] = value


class Harness:
    def __init__(self, lichess: FakeLichess | None = None, listeners: ListenerFactory | None = None) -> None:
        self.lichess = lichess or FakeLichess()
        self.secrets = MemorySecretStore()
        self.settings = MemSettings()
        self.runner = JobRunner()
        self.listeners = listeners or ListenerFactory()
        self.browser = FakeBrowser()
        self.scheduler = FakeScheduler()
        self.events: list[AccountStatus] = []
        self.signed_in_calls = 0
        self.svc = AccountService(
            AccountDeps(
                lichess=self.lichess,
                secrets=self.secrets,
                settings=self.settings,
                runner=self.runner,
                make_listener=self.listeners,
                listener_errors=ListenerErrors(LoopbackTimeout, LoopbackCancelled),
                browser=self.browser,
                scheduler=self.scheduler,
                new_secret=secrets_sequence(),
                is_network_error=is_network_error,
                is_unauthorized=is_unauthorized,
            ),
            notify=self.events.append,
        )
        self.svc.on_signed_in(self._signed_in)

    def _signed_in(self) -> None:
        self.signed_in_calls += 1

    def run(self, job: str | None):  # type: ignore[no-untyped-def]
        assert job is not None
        return self.runner.wait(job, 5)


def test_sign_in_flow_stores_the_token_and_reads_the_rating() -> None:
    h = Harness()
    st = h.run(h.svc.start_sign_in())
    assert st.state == "done" and st.message == "Signed in as player_a"
    # PKCE request: the browser got the challenge, never the verifier (FR-6.1, 6.1a).
    q = parse_qs(urlparse(h.browser.opened[0]).query)
    assert q["code_challenge"] == [challenge(VERIFIER)] and q["state"] == [STATE]
    assert VERIFIER not in h.browser.opened[0]
    # Token exchange (FR-6.3) with the verifier and the same redirect URI.
    form = h.lichess.exchange_forms[0]
    assert (
        form["code"] == "code1" and form["code_verifier"] == VERIFIER and form["redirect_uri"] == q["redirect_uri"][0]
    )
    assert h.listeners.made[0].page_ok is True
    assert h.secrets.get("lichess") == FAKE_TOKEN  # FR-6.5
    assert h.browser.raised == 1
    s = h.svc.status()
    assert (s.state, s.username, s.rating, s.provisional) == ("signed_in", "player_a", 1834, False)
    assert h.settings[ACCOUNT_KEY] == {"id": "player_a", "username": "player_a"}
    assert h.signed_in_calls == 1
    assert all(FAKE_TOKEN not in repr(e) for e in h.events)  # SR-7: no token in what the UI gets


def test_state_mismatch_fails_without_storing_anything() -> None:
    h = Harness(listeners=ListenerFactory(query={"code": ["code1"], "state": ["forged"]}))
    st = h.run(h.svc.start_sign_in())
    assert st.state == "failed" and st.error_code == "sign_in_failed"
    assert h.listeners.made[0].page_ok is False
    assert h.lichess.exchange_forms == []
    assert h.secrets.get("lichess") is None
    assert h.svc.status().state == "signed_out"


@pytest.mark.parametrize(
    ("factory", "state", "code"),
    [
        (ListenerFactory(error=LoopbackTimeout()), "failed", "sign_in_timeout"),
        (ListenerFactory(query={"error": ["access_denied"], "state": [STATE]}), "failed", "sign_in_failed"),
    ],
)
def test_timeout_and_denied(factory: ListenerFactory, state: str, code: str) -> None:
    h = Harness(listeners=factory)
    st = h.run(h.svc.start_sign_in())
    assert (st.state, st.error_code) == (state, code)
    assert h.secrets.get("lichess") is None


def test_cancel_sign_in() -> None:
    h = Harness(listeners=ListenerFactory(hold=True))
    job = h.svc.start_sign_in()
    h.listeners.made and h.listeners.made[0].started.wait(5)  # may run before the listener exists (v0.5-B9)
    with pytest.raises(AppError):  # only one sign-in at a time
        h.svc.start_sign_in()
    h.svc.cancel_sign_in()
    assert h.run(job).state == "cancelled"


def test_offline_or_refused_exchange() -> None:
    h = Harness(FakeLichess(exchange_error=network_error()))
    st = h.run(h.svc.start_sign_in())
    assert (st.state, st.error_code) == ("failed", "offline")
    h2 = Harness(FakeLichess(exchange_error=HttpError("x returned HTTP 400", status=400, retryable=False)))
    st2 = h2.run(h2.svc.start_sign_in())
    assert (st2.state, st2.error_code) == ("failed", "sign_in_failed")
    assert FAKE_TOKEN not in st2.message


def test_signing_in_again_revokes_the_previous_token() -> None:
    h = Harness()
    h.secrets.set("lichess", "lip_FAKEoldtoken")
    h.run(h.svc.start_sign_in())
    assert h.lichess.revoked == ["lip_FAKEoldtoken"]


def test_launch_check_fast_path() -> None:
    """FR-1.6: a stored token that validates gives 'Continue as <username>'."""
    h = Harness()
    assert h.svc.check() is None and h.svc.status().state == "signed_out"
    h.secrets.set("lichess", FAKE_TOKEN)
    h.run(h.svc.check())
    s = h.svc.status()
    assert (s.state, s.username, s.rating) == ("signed_in", "player_a", 1834)
    assert h.svc.account_id() == "player_a"
    assert h.signed_in_calls == 1


def test_launch_check_expired_token_is_discarded() -> None:
    """FR-6.4: a 401 discards the token and asks you to sign in again."""
    h = Harness(FakeLichess(account_error=Unauthorized("x", status=401, retryable=False)))
    h.secrets.set("lichess", FAKE_TOKEN)
    h.settings.set(ACCOUNT_KEY, {"id": "player_a", "username": "player_a"})
    h.run(h.svc.check())
    assert h.svc.status().state == "expired"
    assert h.secrets.get("lichess") is None
    assert h.svc.account_id() is None


def test_offline_at_launch_keeps_the_token_and_rechecks_with_backoff() -> None:
    """FR-1.7: you can continue offline; solves wait for the stored account; it reconnects later."""
    h = Harness(FakeLichess(account_error=network_error()))
    h.secrets.set("lichess", FAKE_TOKEN)
    h.settings.set(ACCOUNT_KEY, {"id": "player_a", "username": "player_a"})
    h.run(h.svc.check())
    s = h.svc.status()
    assert (s.state, s.username, s.rating) == ("offline", "player_a", None)  # no rating unless from Lichess
    assert h.svc.account_id() == "player_a"
    assert h.secrets.get("lichess") == FAKE_TOKEN
    assert h.scheduler.delays == [30]
    h.scheduler.pending.pop(0)[1]()  # still offline
    h.runner.wait(h.runner.active()[0].id if h.runner.active() else "none", 5)
    assert h.scheduler.delays == [60]
    h.lichess.account_error = None
    h.scheduler.pending.pop(0)[1]()
    for j in h.runner.active():
        h.runner.wait(j.id, 5)
    assert h.svc.status().state == "signed_in"
    assert h.signed_in_calls == 1


def test_rating_updates_only_from_lichess() -> None:
    h = Harness()
    h.secrets.set("lichess", FAKE_TOKEN)
    h.run(h.svc.check())
    h.svc.update_rating(1842, None)
    assert h.svc.status().rating == 1842
    h.svc.update_rating(None, None)  # Lichess sent no rating: nothing changes
    assert h.svc.status().rating == 1842


def test_sign_out_revokes_then_deletes() -> None:
    h = Harness()
    h.run(h.svc.start_sign_in())
    h.svc.sign_out()
    assert h.lichess.revoked == [FAKE_TOKEN]  # FR-6.6
    assert h.secrets.get("lichess") is None
    assert h.svc.status() == AccountStatus("signed_out", None, None, False)


def test_sign_out_offline_needs_confirmation() -> None:
    h = Harness()
    h.run(h.svc.start_sign_in())
    h.lichess.revoke_error = network_error()
    with pytest.raises(AppError) as e:
        h.svc.sign_out()
    assert e.value.code == "revoke_failed"
    assert h.secrets.get("lichess") == FAKE_TOKEN  # nothing removed yet
    h.svc.sign_out(force_local=True)
    assert h.secrets.get("lichess") is None


def test_sign_out_with_an_already_revoked_token() -> None:
    h = Harness()
    h.run(h.svc.start_sign_in())
    h.lichess.revoke_error = Unauthorized("x", status=401, retryable=False)
    h.svc.sign_out()
    assert h.secrets.get("lichess") is None


def test_cancel_right_after_sign_in_is_never_lost() -> None:
    """Regression v0.5-B9: a Cancel before the loopback listener existed did nothing, so the sign-in kept
    waiting (and this module's test_cancel_sign_in failed about 1 run in 5)."""
    for _ in range(20):
        h = Harness(listeners=ListenerFactory(hold=True))
        job = h.svc.start_sign_in()
        h.svc.cancel_sign_in()  # immediately: usually before the job has made its listener
        assert h.run(job).state == "cancelled"


def test_v014_sign_in_records_study_read_and_old_sign_ins_lack_it() -> None:
    """FR-6.1, FR-13.7 (v0.14): Lichess doesn't report a token's scopes, so the sign-in records what it asked for. A
    sign-in from before v0.14 has nothing recorded and so lacks study:read; sign-out and expiry clear it."""
    from weaksquare.services.account import SCOPES_KEY

    h = Harness()
    assert h.svc.has_scope("study:read") is False  # signed out
    h.run(h.svc.start_sign_in())
    assert "scope=puzzle%3Aread+puzzle%3Awrite+study%3Aread" in h.browser.opened[0]
    assert h.settings[SCOPES_KEY] == "puzzle:read puzzle:write study:read"
    assert h.svc.has_scope("study:read") and h.svc.has_scope("puzzle:write")
    assert not h.svc.has_scope("study:write")

    h.settings[SCOPES_KEY] = None  # what a v0.13 sign-in looks like: a token, no record
    assert h.svc.has_scope("study:read") is False
    assert h.svc.has_scope("puzzle:read") is False

    h.settings[SCOPES_KEY] = "puzzle:read puzzle:write study:read"
    h.svc.mark_expired()
    assert h.settings[SCOPES_KEY] is None and not h.svc.has_scope("study:read")

    h.run(h.svc.start_sign_in())
    h.svc.sign_out()
    assert h.settings[SCOPES_KEY] is None and not h.svc.has_scope("study:read")
