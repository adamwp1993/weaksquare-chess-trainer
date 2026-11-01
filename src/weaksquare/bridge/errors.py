"""`@bridge_call`: the one wrapper every public `Api` method uses (ARCHITECTURE §3 decision 13, NFR-5).

It validates argument types against the method's annotations, logs the call, converts the result to
plain JSON data, and turns every exception into `{code, message, retryable}`. Tracebacks, file paths
and request details stay in the local log; they never reach the UI.
"""

from __future__ import annotations

import dataclasses
import functools
import inspect
import logging
import types
import typing
from collections.abc import Callable
from typing import Any, TypeVar

from weaksquare.core.errors import AppError, ValidationError
from weaksquare.jobs.runner import JobFailed

log = logging.getLogger("weaksquare.bridge")

F = TypeVar("F", bound=Callable[..., Any])
BRIDGE_MARK = "__bridge_call__"

INTERNAL_MESSAGE = "Something went wrong. The details are in the log file (About → Logs)."


def error_payload(code: str, message: str, retryable: bool) -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message, "retryable": retryable}}


def to_json(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_json(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, dict):
        return {str(k): to_json(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [to_json(v) for v in value]
    return value


def _check(value: Any, annotation: Any, name: str) -> None:
    """Shallow type check of a JS-provided argument against a JSON-ish annotation."""
    if annotation is inspect.Parameter.empty or annotation is Any:
        return
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        errors = []
        for option in typing.get_args(annotation):
            try:
                _check(value, option, name)
                return
            except ValidationError as e:
                errors.append(e)
        raise ValidationError(f"'{name}' has the wrong type")
    if annotation is type(None):
        if value is not None:
            raise ValidationError(f"'{name}' must be null")
        return
    if origin is typing.Literal:
        if value not in typing.get_args(annotation):
            raise ValidationError(f"'{name}' must be one of {list(typing.get_args(annotation))}")
        return
    base = origin or annotation
    if base is bool:
        ok = isinstance(value, bool)
    elif base is int:
        ok = isinstance(value, int) and not isinstance(value, bool)
    elif base is float:
        ok = isinstance(value, int | float) and not isinstance(value, bool)
    elif base in (str, list, dict):
        ok = isinstance(value, base)
    else:
        ok = True
    if not ok:
        raise ValidationError(f"'{name}' has the wrong type")


def bridge_call[F: Callable[..., Any]](fn: F) -> F:
    sig = inspect.signature(fn)
    hints = typing.get_type_hints(fn)

    @functools.wraps(fn)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
        name = fn.__name__
        try:
            try:
                bound = sig.bind(self, *args, **kwargs)
            except TypeError:
                raise ValidationError(f"wrong arguments for {name}") from None
            for pname, value in list(bound.arguments.items())[1:]:
                _check(value, hints.get(pname, inspect.Parameter.empty), pname)
            log.debug("bridge %s", name)
            result = fn(*bound.args, **bound.kwargs)
            return {"ok": True, "data": to_json(result)}
        except AppError as e:
            log.info("bridge %s -> %s: %s", name, e.code, e.message)
            return error_payload(e.code, e.message, e.retryable)
        except JobFailed as e:
            log.info("bridge %s -> %s", name, e.code)
            return error_payload(e.code, e.message, e.retryable)
        except Exception:
            log.exception("bridge %s crashed", name)
            return error_payload("internal", INTERNAL_MESSAGE, False)

    setattr(wrapper, BRIDGE_MARK, True)
    return typing.cast(F, wrapper)
