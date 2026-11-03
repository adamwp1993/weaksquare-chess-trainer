"""Reason-suggestion rules (FR-5.9) and the reason set (FR-5.6). ROADMAP v0.6 Done when."""

from __future__ import annotations

import pytest

from weaksquare.core.errors import ValidationError
from weaksquare.core.reasons import (
    MAX_NOTE,
    REASON_KEYS,
    ReasonContext,
    is_forcing_reply,
    misclick_warning,
    reason_info,
    suggest,
    validate_note,
    validate_rushed_s,
)

RUSHED = 3000


def ctx(**kw: object) -> ReasonContext:
    base: dict[str, object] = {"decisive_ms": 10_000, "rushed_ms": RUSHED}
    base.update(kw)
    return ReasonContext(**base)  # type: ignore[arg-type]


def test_reason_set_is_in_fr_5_6_order_for_keys_1_to_6() -> None:
    assert REASON_KEYS == ("didntLook", "missedResource", "miscalculated", "unknownPattern", "rushed", "misclick")
    assert reason_info("unknownPattern").gap == "knowledge"
    assert reason_info("misclick").gap == "noise"
    with pytest.raises(ValidationError):
        reason_info("bored")


def test_no_rule_matches_means_no_suggestion() -> None:
    assert suggest(ctx()) is None


def test_rushed_is_strictly_under_the_threshold() -> None:
    assert suggest(ctx(decisive_ms=2999)) == "rushed"
    assert suggest(ctx(decisive_ms=RUSHED)) is None  # "under 3 s": exactly 3 s isn't rushed
    assert suggest(ctx(decisive_ms=0)) == "rushed"


def test_help_decided_attempts_are_never_rushed() -> None:
    assert suggest(ctx(decisive_ms=None)) is None


def test_miscalculated_when_first_move_right_and_a_later_one_wrong() -> None:
    assert suggest(ctx(first_right_later_wrong=True)) == "miscalculated"


def test_missed_resource_from_a_forcing_or_mating_refutation() -> None:
    assert suggest(ctx(reply_forcing=True)) == "missedResource"
    assert suggest(ctx(reply_mates=True)) == "missedResource"


def test_danger_spotting_calling_the_blunder_safe_suggests_missed_resource() -> None:
    assert suggest(ctx(called_blunder_safe=True)) == "missedResource"


def test_unknown_pattern_when_no_tag_was_a_motif() -> None:
    assert suggest(ctx(idea_found=0, idea_total=2)) == "unknownPattern"
    assert suggest(ctx(idea_found=1, idea_total=2)) is None
    assert suggest(ctx(idea_found=0, idea_total=0)) is None  # no motif themes: no tag score
    assert suggest(ctx(idea_found=None, idea_total=None)) is None  # not Name the idea


def test_rule_order_rushed_then_miscalculated_then_missed_resource_then_unknown_pattern() -> None:
    every = {"first_right_later_wrong": True, "reply_forcing": True, "idea_found": 0, "idea_total": 1}
    assert suggest(ctx(decisive_ms=100, **every)) == "rushed"
    assert suggest(ctx(**every)) == "miscalculated"
    assert suggest(ctx(**{**every, "first_right_later_wrong": False})) == "missedResource"
    assert suggest(ctx(idea_found=0, idea_total=1)) == "unknownPattern"


def test_forcing_reply_detection() -> None:
    # 1. e4 d5: exd5 is a capture; after 1. e4 e5 2. Qh5, Qxf7 would be a capture and check.
    after_e4_d5 = "rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq d6 0 2"
    assert is_forcing_reply(after_e4_d5, "e4d5")
    assert not is_forcing_reply(after_e4_d5, "g1f3")
    check = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2"
    assert is_forcing_reply(check, "f1b5") is False  # Bb5 isn't check here (d7 pawn blocks)
    assert is_forcing_reply("4k3/8/8/8/8/8/8/R3K3 w - - 0 1", "a1a8")  # check
    assert not is_forcing_reply(after_e4_d5, "e4e6")  # illegal
    assert not is_forcing_reply("not a fen", "e2e4")


def test_note_and_threshold_validation() -> None:
    assert validate_note(None) is None
    assert validate_note("   ") is None
    assert validate_note("  saw it late ") == "saw it late"
    assert validate_note("x" * MAX_NOTE) == "x" * MAX_NOTE
    with pytest.raises(ValidationError):
        validate_note("x" * (MAX_NOTE + 1))
    with pytest.raises(ValidationError):
        validate_note(5)
    assert validate_rushed_s(3) == 3
    for bad in (0, 31, 2.5, True, "3"):
        with pytest.raises(ValidationError):
            validate_rushed_s(bad)


def test_misclick_warning_needs_a_quarter_of_at_least_eight_tagged_misses() -> None:
    assert not misclick_warning(7, 7)  # too few tagged
    assert misclick_warning(2, 8)
    assert not misclick_warning(1, 8)
    assert misclick_warning(5, 20)
    assert not misclick_warning(4, 20)
