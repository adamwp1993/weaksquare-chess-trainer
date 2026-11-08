"""Your Lichess account (FR-1.1, 1.6, 1.7, FR-6.1–6.7, FR-6.11a).

Sign-in is OAuth with PKCE through a loopback listener, in your default browser (FR-6.1a). The token
lives only in the secret store (FR-6.5) and is fetched per request; it never goes into a DTO, a log
line or a message (SR-7). Your puzzle rating comes only from Lichess's responses: the account
endpoint, then each sync response (FR-6.11a). Nothing here computes or estimates it.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from weaksquare.core.errors import AppError, ConflictError
from weaksquare.core.lichess import Account, LichessClient
from weaksquare.core.oauth import SCOPES, OAuthError, authorize_url, parse_callback, token_form
from weaksquare.jobs.runner import CancelToken, JobCancelled, JobFailed, JobRunner, ProgressFn

log = logging.getLogger(__name__)

SIGN_IN_JOB = "lichess_sign_in"
CHECK_JOB = "lichess_account_check"
ACCOUNT_KEY = "lichess.account"  # {"id", "username"}: not a secret (SR-1)
SECRET_ACCOUNT = "lichess"
# v0.14: the scopes requested at the last sign-in (Lichess doesn't report what a token has). A sign-in from before v0.14
# has none recorded, so it's known to lack `study:read`. Not a secret.
SCOPES_KEY = "lichess.scopes"
RECHECK_DELAYS_S = (30, 60, 120, 300, 600)

AccountState = Literal["signed_out", "checking", "signed_in", "offline", "expired"]


class Secrets(Protocol):
    def get(self, account: str) -> str | None: ...

    def set(self, account: str, secret: str) -> None: ...

    def delete(self, account: str) -> None: ...


class Settings(Protocol):
    def get(self, key: str) -> Any | None: ...

    def set(self, key: str, value: Any) -> None: ...


class Listener(Protocol):
    def start(self) -> str: ...

    def wait(self) -> dict[str, list[str]]: ...

    def cancel(self) -> None: ...


class Browser(Protocol):
    def open_in_browser(self, url: str) -> None: ...

    def bring_to_front(self) -> None: ...


class Scheduler(Protocol):
    def call_later(self, delay_s: float, fn: Callable[[], None]) -> None: ...


@dataclass(frozen=True)
class ListenerErrors:
    """The loopback adapter's exception types (kept out of this module's imports)."""

    timeout: type[BaseException]
    cancelled: type[BaseException]


@dataclass(frozen=True)
class AccountStatus:
    state: AccountState
    username: str | None  # the signed-in account, or the cached one while checking or offline
    rating: int | None  # only when signed in, and only from Lichess
    provisional: bool


@dataclass(frozen=True)
class AccountDeps:
    lichess: LichessClient
    secrets: Secrets
    settings: Settings
    runner: JobRunner
    make_listener: Callable[[Callable[[dict[str, list[str]]], bool]], Listener]
    listener_errors: ListenerErrors
    browser: Browser
    scheduler: Scheduler
    new_secret: Callable[[], str]  # a fresh random string (secrets.token_urlsafe), never the seeded rng
    is_network_error: Callable[[BaseException], bool]
    is_unauthorized: Callable[[BaseException], bool]


class AccountService:
    def __init__(self, deps: AccountDeps, notify: Callable[[AccountStatus], None] = lambda s: None) -> None:
        self._d = deps
        self._notify = notify
        self._lock = threading.Lock()
        self._state: AccountState = "signed_out"
        self._account: Account | None = None
        self._rating: int | None = None
        self._provisional = False
        self._listener: Listener | None = None
        self._sign_in_job: str | None = None
        self._recheck_step = 0
        self._on_signed_in: list[Callable[[], None]] = []

    def on_signed_in(self, fn: Callable[[], None]) -> None:
        """Called after a sign-in or a successful check (history import, then sync)."""
        self._on_signed_in.append(fn)

    # ---- state ------------------------------------------------------------------------------
    def _cached(self) -> dict[str, str] | None:
        v = self._d.settings.get(ACCOUNT_KEY)
        if isinstance(v, dict) and isinstance(v.get("id"), str) and isinstance(v.get("username"), str):
            return v
        return None

    def status(self) -> AccountStatus:
        with self._lock:
            state, account, rating, prov = self._state, self._account, self._rating, self._provisional
        if account is not None:
            name: str | None = account.username
        else:
            cached = self._cached() if state in ("checking", "offline", "expired") else None
            name = cached["username"] if cached else None
        return AccountStatus(
            state, name, rating if state == "signed_in" else None, prov if state == "signed_in" else False
        )

    def _set_state(self, state: AccountState, account: Account | None = None, *, keep_account: bool = False) -> None:
        with self._lock:
            self._state = state
            if not keep_account:
                self._account = account
                if account is not None:
                    self._rating, self._provisional = account.rating, account.provisional
                else:
                    self._rating, self._provisional = None, False
        self._notify(self.status())

    def is_signed_in(self) -> bool:
        with self._lock:
            return self._state == "signed_in"

    def token(self) -> str | None:
        return self._d.secrets.get(SECRET_ACCOUNT)

    def has_scope(self, scope: str) -> bool:
        """Whether the stored sign-in was granted `scope` (v0.14: `study:read` for private studies, FR-13.7)."""
        if not self.token():
            return False
        granted = self._d.settings.get(SCOPES_KEY)
        return isinstance(granted, str) and scope in granted.split()

    def account_id(self) -> str | None:
        """Who solves are queued for: the signed-in account, or the stored one while offline."""
        with self._lock:
            state, account = self._state, self._account
        if state == "signed_in" and account is not None:
            return account.id
        if state in ("offline", "checking") and self.token():
            cached = self._cached()
            return cached["id"] if cached else None
        return None

    def update_rating(self, rating: int | None, provisional: bool | None) -> None:
        """From a sync response's glicko (FR-6.11a). Ignored when Lichess sent no rating."""
        if rating is None:
            return
        with self._lock:
            self._rating = rating
            if provisional is not None:
                self._provisional = provisional
        self._notify(self.status())

    def mark_expired(self) -> None:
        """A 401 from Lichess: the token is gone or revoked (FR-6.4). Discard it."""
        self._d.secrets.delete(SECRET_ACCOUNT)
        self._d.settings.set(SCOPES_KEY, None)
        self._set_state("expired")

    def note_reachable(self) -> None:
        """Something reached Lichess with the token while we thought we were offline."""
        if self.status().state == "offline":
            self.check()

    # ---- launch check and reconnect (FR-1.6, 1.7) ---------------------------------------------
    def check(self) -> str | None:
        """Validate a stored token with GET /api/account in a short job. None if there's no token."""
        if not self.token():
            self._set_state("signed_out")
            return None
        running = self._d.runner.active(CHECK_JOB)
        if running:
            return running[0].id
        if self.status().state != "signed_in":
            self._set_state("checking")
        return self._d.runner.submit(CHECK_JOB, self._check_job)

    def _check_job(self, progress: ProgressFn, token: CancelToken) -> str:
        secret = self.token()
        if not secret:
            self._set_state("signed_out")
            return "Not signed in"
        try:
            account = self._d.lichess.account(secret)
        except Exception as e:
            if self._d.is_unauthorized(e):
                self.mark_expired()
                return "Sign in again"
            if self._d.is_network_error(e):
                self._went_offline()
                return "Offline"
            raise
        self._signed_in(account)
        return f"Signed in as {account.username}"

    def _went_offline(self) -> None:
        self._set_state("offline")
        delay = RECHECK_DELAYS_S[min(self._recheck_step, len(RECHECK_DELAYS_S) - 1)]
        self._recheck_step += 1
        self._d.scheduler.call_later(delay, self._recheck)

    def _recheck(self) -> None:
        if self.status().state == "offline":
            self.check()

    def _signed_in(self, account: Account) -> None:
        self._recheck_step = 0
        self._d.settings.set(ACCOUNT_KEY, {"id": account.id, "username": account.username})
        self._set_state("signed_in", account)
        for fn in self._on_signed_in:
            try:
                fn()
            except Exception:
                log.exception("after-sign-in step failed")

    # ---- sign in (FR-6.1–6.3) -----------------------------------------------------------------
    def start_sign_in(self) -> str:
        with self._lock:
            running = self._d.runner.status(self._sign_in_job) if self._sign_in_job else None
            if running is not None and running.state == "running":
                raise ConflictError("A sign-in is already waiting for you in your browser.")
            job = self._d.runner.submit(SIGN_IN_JOB, self._sign_in)
            self._sign_in_job = job
        return job

    def cancel_sign_in(self) -> None:
        """Cancel works at any moment of the sign-in: the job is marked cancelled too, so a Cancel that
        arrives before the loopback listener exists isn't lost (v0.5-B9)."""
        with self._lock:
            listener = self._listener
            job = self._sign_in_job
        if job is not None:
            self._d.runner.cancel(job)
        if listener is not None:
            listener.cancel()

    def _sign_in(self, progress: ProgressFn, cancel: CancelToken) -> str:
        verifier, state = self._d.new_secret(), self._d.new_secret()

        def accept(query: dict[str, list[str]]) -> bool:
            try:
                parse_callback(query, state)
                return True
            except OAuthError:
                return False

        cancel.raise_if_cancelled()
        listener = self._d.make_listener(accept)
        redirect = listener.start()
        with self._lock:
            self._listener = listener
        try:
            if cancel.cancelled:  # Cancel arrived while the listener was starting (v0.5-B9)
                listener.cancel()
                raise JobCancelled()
            self._d.browser.open_in_browser(authorize_url(verifier=verifier, state=state, redirect_uri=redirect))
            progress(None, "Waiting for you to approve in your browser…")
            try:
                query = listener.wait()
            except self._d.listener_errors.timeout:
                raise JobFailed("sign_in_timeout", "Sign-in timed out after 5 minutes. Try again.") from None
            except self._d.listener_errors.cancelled:
                raise JobCancelled() from None
        finally:
            with self._lock:
                self._listener = None
        try:
            code = parse_callback(query, state).code
        except OAuthError as e:
            raise JobFailed(e.code, e.message, retryable=True) from None
        progress(None, "Finishing sign-in…")
        old = self.token()
        secret: str | None = None
        try:
            secret = self._d.lichess.exchange_code(token_form(code=code, verifier=verifier, redirect_uri=redirect))
            account = self._d.lichess.account(secret)
        except Exception as e:
            if secret is not None:
                self._revoke_quietly(secret)  # never leave a valid token behind that nothing holds (v0.3-B3)
            if self._d.is_network_error(e):
                raise JobFailed(
                    "offline", "Sign-in failed: Lichess couldn't be reached. Check your connection."
                ) from None
            log.warning("sign-in: Lichess refused the token exchange (%s)", type(e).__name__)
            raise JobFailed("sign_in_failed", "Sign-in failed: Lichess refused the request. Try again.") from None
        try:
            self._d.secrets.set(SECRET_ACCOUNT, secret)
        except Exception as e:
            log.error("sign-in: couldn't store the token (%s)", type(e).__name__)
            self._revoke_quietly(secret)
            raise JobFailed("secret_store", "Sign-in failed: Windows Credential Manager refused the token.") from None
        self._d.settings.set(
            SCOPES_KEY, SCOPES
        )  # what this sign-in asked for (and Lichess's consent is all or nothing)
        if old and old != secret:
            self._revoke_quietly(old)  # signing in again replaces the old token
        self._d.browser.bring_to_front()
        self._signed_in(account)
        return f"Signed in as {account.username}"

    def _revoke_quietly(self, token: str) -> None:
        try:
            self._d.lichess.revoke(token)
        except Exception as e:
            log.info("couldn't revoke the previous token (%s)", type(e).__name__)

    # ---- sign out (FR-6.6) ---------------------------------------------------------------------
    def sign_out(self, force_local: bool = False) -> None:
        """Revoke the token on Lichess, then delete it here. If Lichess can't be reached, raises
        `revoke_failed` unless `force_local` (remove it from this PC anyway). Pending solves stay queued."""
        secret = self.token()
        if secret:
            try:
                self._d.lichess.revoke(secret)
            except Exception as e:
                if self._d.is_unauthorized(e):
                    pass  # already invalid on Lichess
                elif not force_local:
                    raise AppError(
                        "Lichess couldn't be reached, so the sign-in wasn't revoked there.",
                        code="revoke_failed",
                        retryable=True,
                    ) from None
            self._d.secrets.delete(SECRET_ACCOUNT)
        self._d.settings.set(ACCOUNT_KEY, None)
        self._d.settings.set(SCOPES_KEY, None)
        self._set_state("signed_out")
