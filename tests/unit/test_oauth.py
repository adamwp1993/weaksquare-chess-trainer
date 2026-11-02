"""FR-6.1–6.3 / SR-4: PKCE helpers."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from weaksquare.core.oauth import CLIENT_ID, OAuthError, authorize_url, challenge, parse_callback, token_form

# RFC 7636 appendix B test vector.
RFC_VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
RFC_CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_s256_challenge_matches_the_rfc_vector() -> None:
    assert challenge(RFC_VERIFIER) == RFC_CHALLENGE


def test_verifier_must_be_rfc_shaped() -> None:
    with pytest.raises(ValueError):
        challenge("short")


def test_authorize_url_has_every_required_parameter() -> None:
    url = authorize_url(verifier=RFC_VERIFIER, state="st4te", redirect_uri="http://127.0.0.1:5555/callback")
    u = urlparse(url)
    assert (u.scheme, u.netloc, u.path) == ("https", "lichess.org", "/oauth")
    q = {k: v[0] for k, v in parse_qs(u.query).items()}
    assert q == {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": "http://127.0.0.1:5555/callback",
        "code_challenge_method": "S256",
        "code_challenge": RFC_CHALLENGE,
        "scope": "puzzle:read puzzle:write",
        "state": "st4te",
    }
    assert RFC_VERIFIER not in url  # only the challenge leaves the app


def test_callback_with_matching_state_gives_the_code() -> None:
    assert parse_callback({"code": ["abc"], "state": ["s1"]}, "s1").code == "abc"


@pytest.mark.parametrize(
    "params",
    [
        {"code": ["abc"], "state": ["other"]},
        {"code": ["abc"]},
        {"code": ["abc"], "state": ["s1", "s1"]},
    ],
)
def test_state_mismatch_is_refused_without_echoing_the_code(params: dict[str, list[str]]) -> None:
    with pytest.raises(OAuthError) as e:
        parse_callback(params, "s1")
    assert "abc" not in e.value.message


def test_denied_and_missing_code() -> None:
    with pytest.raises(OAuthError, match="cancelled"):
        parse_callback({"error": ["access_denied"], "state": ["s1"]}, "s1")
    with pytest.raises(OAuthError, match="authorization code"):
        parse_callback({"state": ["s1"]}, "s1")


def test_token_form() -> None:
    form = token_form(code="c", verifier=RFC_VERIFIER, redirect_uri="http://127.0.0.1:1/callback")
    assert form == {
        "grant_type": "authorization_code",
        "code": "c",
        "code_verifier": RFC_VERIFIER,
        "redirect_uri": "http://127.0.0.1:1/callback",
        "client_id": CLIENT_ID,
    }
