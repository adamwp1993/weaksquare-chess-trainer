"""QA v0.6 (independent pass, qa/QA-v0.6.md) against the mock client: edge cases for Name the idea first,
Danger spotting and the reason chips, plus screenshots of every v0.6 screen into tests/e2e/artifacts/.
Tests marked xfail(strict=True) pin a reported bug."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.e2e.conftest import play
from tests.e2e.test_modes import calls, choose_mode, open_app

pytestmark = pytest.mark.e2e
ART = Path(__file__).resolve().parent / "artifacts"


def shot(page, name: str) -> None:  # type: ignore[no-untyped-def]
    ART.mkdir(parents=True, exist_ok=True)
    page.wait_for_timeout(350)
    page.screenshot(path=str(ART / f"qa-v06-{name}.png"), full_page=True)


def start(page, wait_ms: int = 700) -> None:  # type: ignore[no-untyped-def]
    page.get_by_role("button", name="Start").click()
    page.get_by_test_id("trainer-message").wait_for()
    page.wait_for_timeout(wait_ms)


def lose_first(page) -> None:  # type: ignore[no-untyped-def]
    open_app(page)
    start(page)
    play(page, "f7f6", "black")
    page.get_by_test_id("outcome").filter(has_text="Failed").wait_for()
    page.get_by_test_id("answer-button").click()
    page.get_by_test_id("reason-chips").wait_for()


# ---- reason chips -----------------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="v0.6-B2: keys 1-6 save the reason without the note you wrote")
def test_b2_changing_the_reason_with_a_key_keeps_the_note(page) -> None:  # type: ignore[no-untyped-def]
    lose_first(page)
    page.get_by_test_id("reason-add-note").click()
    page.get_by_test_id("reason-note").fill("saw it too late")
    page.get_by_test_id("reason-didntLook").click()  # a click saves the note with the reason
    page.get_by_test_id("reason-saved").wait_for()
    page.get_by_test_id("board").click(position={"x": 2, "y": 2})  # leave the note field
    page.keyboard.press("5")  # change it to Rushed with the key
    page.wait_for_timeout(200)
    reasons = [c for c in calls(page) if c.startswith("reason:")]
    assert reasons[-1] == "reason:1=rushed:saw it too late", reasons


def test_typing_digits_in_the_note_doesnt_pick_a_reason(page) -> None:  # type: ignore[no-untyped-def]
    lose_first(page)
    page.get_by_test_id("reason-add-note").click()
    page.get_by_test_id("reason-note").type("missed 2 checks 1 6")
    page.wait_for_timeout(200)
    assert not [c for c in calls(page) if c.startswith("reason:")]
    assert page.get_by_test_id("reason-saved").count() == 0


def test_a_201_character_note_is_refused_in_the_ui(page) -> None:  # type: ignore[no-untyped-def]
    lose_first(page)
    page.get_by_test_id("reason-add-note").click()
    page.get_by_test_id("reason-note").fill("x" * 201)
    page.get_by_test_id("reason-rushed").click()
    page.wait_for_timeout(200)
    reasons = [c for c in calls(page) if c.startswith("reason:")]
    assert reasons == ["reason:1=rushed"]  # the reason is saved, the over-long note isn't
    assert "under 200" in page.get_by_test_id("reason-chips").inner_text()


def test_practice_run_asks_nothing_new(page) -> None:  # type: ignore[no-untyped-def]
    lose_first(page)
    page.get_by_test_id("try-again").click()
    page.wait_for_timeout(800)
    # the original miss's chips stay for the practice run (FR-5.8), but practice asks nothing new
    assert calls(page).count("reasonPrompt") == 1


def test_rapid_number_keys_save_in_order_and_end_on_the_last(page) -> None:  # type: ignore[no-untyped-def]
    lose_first(page)
    for k in "123456":
        page.keyboard.press(k)
    page.wait_for_timeout(600)
    reasons = [c for c in calls(page) if c.startswith("reason:")]
    assert reasons[-1].endswith("=misclick"), reasons  # the last key wins
    assert page.get_by_test_id("reason-misclick").get_attribute("aria-pressed") == "true"
    pressed = page.locator("[data-testid^='reason-'][aria-pressed='true']")
    assert pressed.count() == 1
    print(f"\nQA-OBS rapid keys 1-6 -> {reasons}")


# ---- Name the idea first ----------------------------------------------------------------------------


def test_board_takes_no_moves_before_start_solving(page) -> None:  # type: ignore[no-untyped-def]
    open_app(page)
    choose_mode(page, "Name the idea first")
    start(page)
    page.get_by_test_id("idea-tags").wait_for()
    before = page.get_by_test_id("board").get_attribute("data-fen")
    play(page, "d5c3", "black")  # the solution's first move, before tagging
    page.wait_for_timeout(300)
    assert page.get_by_test_id("board").get_attribute("data-fen") == before
    assert page.get_by_test_id("outcome").count() == 0
    assert page.get_by_test_id("hint-button").is_disabled()
    shot(page, "name-idea-tagging")


def test_more_than_three_tags_per_slot_cant_be_picked(page) -> None:  # type: ignore[no-untyped-def]
    open_app(page)
    choose_mode(page, "Name the idea first")
    start(page)
    page.get_by_test_id("idea-payoff").click()
    for name in ("Fork", "Pin", "Skewer", "Hanging piece"):
        opt = page.get_by_role("option", name=name, exact=True)
        if opt.count() and opt.is_enabled():
            opt.click()
    page.keyboard.press("Escape")
    page.wait_for_timeout(100)
    page.get_by_test_id("idea-start").click()
    page.wait_for_timeout(300)
    tags = [c for c in calls(page) if c.startswith("tags:")]
    assert tags and len(tags[0].split(":")[1].split(",")) <= 3, tags


def test_name_the_idea_result_screens(page) -> None:  # type: ignore[no-untyped-def]
    open_app(page)
    choose_mode(page, "Name the idea first")
    start(page)
    page.get_by_test_id("idea-payoff").click()
    page.get_by_role("option", name="Pin", exact=True).click()
    page.keyboard.press("Escape")
    page.get_by_test_id("idea-start").click()
    play(page, "f7f6", "black")
    page.get_by_test_id("outcome").filter(has_text="Failed").wait_for()
    page.get_by_test_id("answer-button").click()
    page.get_by_test_id("reason-chips").wait_for()
    shot(page, "name-idea-miss-with-chips")


# ---- Danger spotting --------------------------------------------------------------------------------


def test_double_pressing_s_calls_once(page) -> None:  # type: ignore[no-untyped-def]
    open_app(page, "?mode=danger_spotting")
    start(page, 200)
    page.get_by_test_id("danger-call").wait_for()
    shot(page, "danger-call")
    page.keyboard.press("s")
    page.keyboard.press("s")
    page.keyboard.press("u")
    page.wait_for_timeout(400)
    assert [c for c in calls(page) if c.startswith("danger:")] == ["danger:safe"]
    shot(page, "danger-safe-verdict")


def test_show_answer_before_the_call_is_a_loss_and_ends_the_call(page) -> None:  # type: ignore[no-untyped-def]
    open_app(page, "?mode=danger_spotting")
    start(page, 200)
    page.get_by_test_id("danger-call").wait_for()
    page.get_by_test_id("answer-button").click()
    page.get_by_test_id("outcome").filter(has_text="Failed").wait_for()
    page.wait_for_timeout(300)
    assert page.get_by_test_id("danger-call").count() == 0
    page.keyboard.press("u")
    page.wait_for_timeout(200)
    assert not [c for c in calls(page) if c.startswith("danger:")]
    shot(page, "danger-answer-before-call")


def test_s_and_u_do_nothing_outside_danger_spotting(page) -> None:  # type: ignore[no-untyped-def]
    open_app(page)
    start(page)
    page.keyboard.press("s")
    page.keyboard.press("u")
    page.wait_for_timeout(200)
    assert not [c for c in calls(page) if c.startswith("danger:")]
    assert page.get_by_test_id("outcome").count() == 0


def test_danger_refute_and_blunder_screens(page) -> None:  # type: ignore[no-untyped-def]
    open_app(page, "?mode=danger_spotting")
    start(page, 200)
    page.get_by_test_id("danger-safe").click()
    page.get_by_test_id("next-button").click()
    page.get_by_test_id("danger-call").wait_for()
    page.get_by_test_id("danger-unsafe").click()
    page.get_by_test_id("trainer-message").filter(has_text="punish it").wait_for()
    header = page.get_by_test_id("puzzle-header").inner_text()
    assert "you play white" in header, header
    shot(page, "danger-refute")
    import chess

    board = chess.Board(page.get_by_test_id("board").get_attribute("data-fen"))
    wrong = next(m.uci() for m in board.legal_moves if m.uci() != "d4e2")  # not the punishing move
    play(page, wrong, "white")
    page.get_by_test_id("outcome").filter(has_text="Failed").wait_for()
    page.get_by_test_id("reason-chips").wait_for()
    shot(page, "danger-wrong-refutation")


def test_danger_dark_mode(page) -> None:  # type: ignore[no-untyped-def]
    open_app(page, "?mode=danger_spotting")
    page.emulate_media(color_scheme="dark")
    page.get_by_role("button", name="Menu").click()
    page.get_by_role("menuitem", name="Settings").click()
    dark = page.get_by_text("Dark", exact=True)
    if dark.count():
        dark.first.click()
    page.keyboard.press("Escape")
    start(page, 200)
    page.get_by_test_id("danger-call").wait_for()
    shot(page, "danger-call-dark")


# ---- Settings and Stats screens ---------------------------------------------------------------------


def test_settings_and_stats_screens(page) -> None:  # type: ignore[no-untyped-def]
    open_app(page)
    page.get_by_role("button", name="Menu").click()
    page.get_by_role("menuitem", name="Settings").click()
    page.get_by_test_id("reasons-ask").wait_for()
    shot(page, "settings-training")
    page.keyboard.press("Escape")
    page.get_by_role("button", name="Menu").click()
    page.get_by_role("menuitem", name="Stats").click()
    page.get_by_test_id("stats-mode-tab").click()
    page.get_by_test_id("stats-mode-details").wait_for()
    shot(page, "stats-mode-details")
    page.get_by_test_id("stats-reasons-tab").click()
    page.get_by_test_id("reasons-table").wait_for()
    shot(page, "stats-reasons")
