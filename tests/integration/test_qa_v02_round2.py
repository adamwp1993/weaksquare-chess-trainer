"""QA v0.2 round 2: a stronger regression test for v0.2-B3 (qa/QA-v0.2.md, Round 2).

The builder's test swaps puzzles.db between next_puzzle's version check and its read, but its new file
keeps many low-rated puzzles, so on the pre-fix code a stale key happened to land on a matching puzzle
and the test passed. Here the new file keeps *only* puzzles rated above the session's filter (plus a
few that match), so a stale key read from it serves an out-of-filter puzzle unless the fix catches it.
"""

from __future__ import annotations

from tests.integration.test_qa_v01_edges import _subset_db
from weaksquare.core.filters import FilterSpec


def test_stale_key_after_a_swap_inside_the_read_window_is_never_served(services, tmp_path) -> None:  # type: ignore[no-untyped-def]
    spec = FilterSpec(rating_max=900, queue_size=None, min_popularity=None, min_plays=None, exclude_solved_here=False)
    sid = services.sessions.start(spec).session_id
    assert services.sessions.next_puzzle(sid) is not None  # the queue now holds keys of the old file
    # Keep everything rated above 900, and only the matching puzzles whose rating is a multiple of 3.
    new_db = _subset_db(tmp_path / "newer.db", lambda r: r.rating > 900 or r.rating % 3 == 0)
    source = services.sessions._puzzles
    real_get = source.get
    swapped: list[bool] = []

    def get_with_a_swap_first(key, *args, **kwargs):  # type: ignore[no-untyped-def]
        if not swapped:
            swapped.append(True)
            services.db.swap_puzzles_db(new_db)  # after next_puzzle's version check, before the read
        return real_get(key, *args, **kwargs)

    source.get = get_with_a_swap_first
    try:
        served = []
        for _ in range(5):
            view = services.sessions.next_puzzle(sid)
            if view is None:
                break
            served.append(view)
    finally:
        source.get = real_get
    assert swapped and served
    assert all(v.rating <= 900 for v in served), [(v.puzzle_id, v.rating) for v in served]
