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
  - **What to improve** shows the AI's summary, then the key moments; each note now ends with what to look for next time and has **Train:** theme tags. Practise / Train these comes last.
  - **What you did well** shows the AI's summary, then each computed strength with the AI's words under it.
  - The narrative panel keeps only the controls and the cost. The prompt asks for prose, not a walk through the moves. Training ideas are checked against the preset's allowed themes.
  - Regression tests:
    - `tests/unit/test_game_explain.py`: the v0.15 section
    - `tests/e2e/test_review_parts_v015_ui.py`
