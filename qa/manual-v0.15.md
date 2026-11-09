# Manual test, v0.15 (Adam)

## M1: Explain my game doesn't read as a three-part review (fixed for v0.15-rc2)
- **Steps:** My games → Review a game → Explain my game.
- **Expected:**
  - The review is in three parts: 1. a general summary, 2. What to improve, 3. What you did well.
  - Parts 2 and 3 each open with their own short summary, followed by the moves and recommendations.
  - The summaries read as a summary of what you struggled with (a move number at most), not a list of moves.
  - Each key moment is tagged with the training ideas that go with it.
- **Actual (rc1):**
  - The AI wrote its own block above the review: an opening summary, theme badges, takeaways, and a second What you did well.
  - What you did well had no summary paragraph of its own and appeared twice on the screen.
- **Fix:**
  - Explain my game now fills the review's three parts.
  - **Summary** shows the AI's general summary and the turning point.
  - **What to improve** shows the AI's summary, then the key moments; each note now ends with what to look for next time and has **Train:** theme tags. The recommended puzzles come last (see M3).
  - **What you did well** shows the AI's summary, then each computed strength with the AI's words under it.
  - The narrative panel keeps only the controls and the cost. The prompt asks for prose, not a walk through the moves. Training ideas are checked against the preset's allowed themes.
  - Regression tests:
    - `tests/unit/test_game_explain.py`: the v0.15 section
    - `tests/e2e/test_review_parts_v015_ui.py`

## M2: Text can't be copied out of the app (fixed for v0.15-rc2)
- **Steps:** try to select and copy any text, such as an AI explanation.
- **Expected:** select with the mouse, copy with Ctrl+C.
- **Actual (rc1):** nothing can be selected. pywebview disables text selection on the whole page unless the window asks for it.
- **Fix:**
  - The window is created with `text_select=True`.
  - The board keeps its own `user-select: none`, so dragging pieces never highlights anything.
  - The right-click menu stays off, because WebView2's default menu has Reload, which would drop the screen's state.
  - Recorded as NFR-8b.
  - Regression test: `tests/smoke/test_real_app_text_select.py` (fails without the fix).

## M3: The recommended puzzles are easy to miss (fixed for v0.15-rc2)
- **Steps:** Explain my game → the end of What to improve.
- **Expected:** a clear "suggested training" part that links the recommended puzzle set, spelled "practice".
- **Actual (rc1 + M1):** one small "Practise: Hanging piece, Fork (1200–1700)" line with a tiny Train these button.
- **Fix:**
  - A **Suggested training** box (tinted, bordered) with the themes as badges, the rating range, and a full-size **Train these puzzles** button.
  - The button still confirms before changing the Mixer.
  - Regression test: `tests/e2e/test_review_parts_v015_ui.py::test_suggested_training_is_its_own_box_and_takes_you_to_those_puzzles`.
