"""Fakes for the sign-in plumbing: loopback listener, browser, scheduler (v0.3)."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import count

from weaksquare.adapters.oauth_loopback import LoopbackCancelled, LoopbackTimeout

VERIFIER = "v" * 43
STATE = "state" + "s" * 20
REDIRECT = "http://127.0.0.1:5555/callback"


class FakeListener:
    """Returns `query` from wait(), or raises `error`. `hold` keeps wait() blocked until cancel()."""

    def __init__(self, accept: Callable[[dict[str, list[str]]], bool], query: dict[str, list[str]] | None,
                 error: BaseException | None = None, hold: bool = False) -> None:  # fmt: skip
        self.accept = accept
        self.query = query
        self.error = error
        self.hold = hold
        self.cancelled = threading.Event()
        self.started = threading.Event()
        self.page_ok: bool | None = None

    def start(self) -> str:
        self.started.set()
        return REDIRECT

    def wait(self) -> dict[str, list[str]]:
        if self.hold:
            self.cancelled.wait(5)
            raise LoopbackCancelled()
        if self.error:
            raise self.error
        assert self.query is not None
        self.page_ok = self.accept(self.query)
        return self.query

    def cancel(self) -> None:
        self.cancelled.set()


@dataclass
class ListenerFactory:
    query: dict[str, list[str]] | None = field(default_factory=lambda: {"code": ["code1"], "state": [STATE]})
    error: BaseException | None = None
    hold: bool = False
    made: list[FakeListener] = field(default_factory=list)

    def __call__(self, accept: Callable[[dict[str, list[str]]], bool]) -> FakeListener:
        listener = FakeListener(accept, self.query, self.error, self.hold)
        self.made.append(listener)
        return listener


@dataclass
class FakeBrowser:
    opened: list[str] = field(default_factory=list)
    raised: int = 0

    def open_in_browser(self, url: str) -> None:
        self.opened.append(url)

    def bring_to_front(self) -> None:
        self.raised += 1


@dataclass
class FakeScheduler:
    pending: list[tuple[float, Callable[[], None]]] = field(default_factory=list)

    def call_later(self, delay_s: float, fn: Callable[[], None]) -> None:
        self.pending.append((delay_s, fn))

    def run_next(self) -> float:
        delay, fn = self.pending.pop(0)
        fn()
        return delay

    @property
    def delays(self) -> list[float]:
        return [d for d, _ in self.pending]


def secrets_sequence() -> Callable[[], str]:
    """new_secret for tests: the verifier, then the state, then numbered values."""
    n = count()
    fixed = [VERIFIER, STATE]

    def make() -> str:
        i = next(n)
        return fixed[i] if i < len(fixed) else f"secret{i:040d}"

    return make


__all__ = ["LoopbackCancelled", "LoopbackTimeout"]
