"""OAuth 2.0 with PKCE for Lichess (FR-6.1–6.3, SR-4). Pure: the random verifier and state are
made by the caller (with `secrets`, never the app's seeded rng) and passed in.
"""

from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass
from urllib.parse import urlencode

from weaksquare.core.errors import AppError

LICHESS_OAUTH_URL = "https://lichess.org/oauth"
CLIENT_ID = "weaksquare-chess-trainer"  # Lichess accepts unregistered public clients
# FR-6.1. `study:read` (v0.14) lets the app read private studies you own or belong to (FR-13.7). Lichess's token
# response doesn't say what was granted, so the account service records these at each sign-in.
SCOPES = "puzzle:read puzzle:write study:read"
# RFC 7636: 43–128 characters from the unreserved set.
_VERIFIER = re.compile(r"^[A-Za-z0-9\-._~]{43,128}$")


class OAuthError(AppError):
    code = "sign_in_failed"


def challenge(verifier: str) -> str:
    """S256: BASE64URL(SHA256(verifier)) without padding."""
    if not _VERIFIER.match(verifier):
        raise ValueError("the PKCE verifier must be 43-128 unreserved characters")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def authorize_url(*, verifier: str, state: str, redirect_uri: str) -> str:
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": redirect_uri,
        "code_challenge_method": "S256",
        "code_challenge": challenge(verifier),
        "scope": SCOPES,
        "state": state,
    }
    return f"{LICHESS_OAUTH_URL}?{urlencode(params)}"


@dataclass(frozen=True)
class Callback:
    code: str


def parse_callback(params: dict[str, list[str]], expected_state: str) -> Callback:
    """Check the loopback callback's query (already parsed). The messages are shown to the user and
    never contain the code or the state."""
    state = params.get("state", [""])
    if len(state) != 1 or state[0] != expected_state:
        raise OAuthError("Sign-in failed: the reply didn't match this sign-in. Try again.")
    error = params.get("error", [""])[0]
    if error:
        if error == "access_denied":
            raise OAuthError("Sign-in was cancelled on Lichess.")
        raise OAuthError("Sign-in failed: Lichess refused the request.")
    code = params.get("code", [""])
    if len(code) != 1 or not code[0] or len(code[0]) > 2000:
        raise OAuthError("Sign-in failed: Lichess didn't send an authorization code.")
    return Callback(code[0])


def token_form(*, code: str, verifier: str, redirect_uri: str) -> dict[str, str]:
    """The body of POST /api/token (FR-6.3)."""
    return {
        "grant_type": "authorization_code",
        "code": code,
        "code_verifier": verifier,
        "redirect_uri": redirect_uri,
        "client_id": CLIENT_ID,
    }
