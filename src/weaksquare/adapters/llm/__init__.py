"""LLM provider adapters (v0.7): Anthropic and OpenAI over the shared HTTP client (ARCHITECTURE §3 decision 9).

No vendor SDK: every call goes through `adapters/http.py`, which sets the User-Agent and timeouts and
keeps headers out of errors and logs. Keys are passed per request and never stored here.
"""

from __future__ import annotations

from weaksquare.adapters.http import HttpError
from weaksquare.core.llm.provider import ErrorKind, LLMError

QUOTA_CODES = {"insufficient_quota", "billing_error", "billing_hard_limit_reached"}
BAD_KEY_CODES = {"authentication_error", "invalid_api_key", "permission_error"}
BAD_MODEL_CODES = {"not_found_error", "model_not_found"}


def llm_error(e: HttpError) -> LLMError:
    """Map an HTTP failure to one of the readable kinds (FR-8.8). Only the status and the API's short
    error code are used, never its message text."""
    code = e.error_code or ""
    kind: ErrorKind
    if e.status is None:
        kind = "timeout" if e.timeout else "network"
    elif code in QUOTA_CODES or e.status == 402:
        kind = "quota"
    elif e.status in (401, 403) or code in BAD_KEY_CODES:
        kind = "bad_key"
    elif e.status == 404 or code in BAD_MODEL_CODES:
        kind = "bad_model"
    elif e.status in (429, 529) or code in {"rate_limit_error", "overloaded_error"}:
        kind = "rate_limited"
    elif e.status >= 500:
        kind = "server"
    else:
        kind = "bad_request"
    return LLMError(kind, e.status)


def as_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0
