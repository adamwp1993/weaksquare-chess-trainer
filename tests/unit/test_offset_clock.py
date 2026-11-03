"""FR-4.6 fast-forward time (dev runs only): the wall clock moves by whole days, timings don't."""

from __future__ import annotations

from datetime import timedelta

import pytest

from weaksquare.adapters.system_clock import MAX_OFFSET_DAYS, OffsetClock, SystemClock


def test_offset_moves_now_by_whole_days_and_not_monotonic() -> None:
    real = SystemClock()
    clock = OffsetClock(3)
    assert abs((clock.now() - real.now()) - timedelta(days=3)) < timedelta(seconds=5)
    assert abs(clock.monotonic_ms() - real.monotonic_ms()) < 5000
    clock.set_offset_days(0)
    assert abs(clock.now() - real.now()) < timedelta(seconds=5)
    assert clock.offset_days == 0


@pytest.mark.parametrize("bad", [-1, MAX_OFFSET_DAYS + 1, 1.5, True, "2", None])
def test_bad_offsets_are_refused(bad: object) -> None:
    with pytest.raises(ValueError):
        OffsetClock().set_offset_days(bad)  # type: ignore[arg-type]
