# Manual test, v0.10 (Adam)

## M1: AI coaching has no model choice (fixed for v0.10-rc2)
- **Steps:** Coach → a report → AI coaching (optional).
- **Expected:** choose which model the AI coaching uses right there, like the model dropdown next to Explain my game in Game Review.
- **Actual (rc1):** only the model's name, and a pointer to Settings → AI → Coach.
- **Fix:** the Coach's model picker (the same setting as Settings → AI → Coach) is in the AI coaching box. With a saved answer from another model, **Ask <model> instead** asks again. Regression test: `tests/e2e/test_v010_ui.py::test_manual_the_coach_model_is_picked_in_the_ai_coaching_box`.

## Requests for later versions
- A **training plan** and a **training journal**, with AI coaching including the plan: written up as REQUIREMENTS §10.12 and ROADMAP v0.12 (Adam, 2026-11-04).
