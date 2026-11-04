# QA report: v0.9 (Game Review AI)

Branch `v0.9` at `ebcc55c`. Run on 2026-11-04 by the independent `qa-tester`. I changed no product code, migrations, config or docs. New tests are under `tests/` only. `-m live` was **not** run (Adam's).

## Verdict: **PASS WITH ISSUES** (6 minor, no blocker or major)

All four *Done when* items and every decision in the plan pass with evidence, and the automated suites are green. The anonymization holds through the real service path, not only in the pure prompt builder: a PGN full of headers, names, ratings, a URL, dates, `%clk`/`%eval`, comments and NAGs leaves no trace in either request. The minor bugs:
- **B1:** in Settings → AI, changing Game Review's reasoning before the model you just picked has saved puts the old model back.
- **B2 (docs):** the User Guide says new grading thresholds give a new explanation. The cache key doesn't include the thresholds.
- **B3:** **Train these** also switches Match to ANY, the source to Lichess DB and clears ratios. The dialog and the User Guide say it replaces only themes and rating.
- **B4:** the Game Review model picker doesn't take a typed model ID (FR-1.15 says each picker works like FR-1.3).
- **B5:** Settings shows the Game Review picker only once puzzle Explain has a provider, although the backend runs Game Review on its own provider.
- **B6 (docs):** the User Guide screenshot `docs/img/game-review-ai.png` shows a raw `<i>Shown as typed.</i>` in the explanation, mock text meant for the escaping test.

---

## Evidence: commands run

Git Bash unless noted. PowerShell rows ran as `powershell.exe -NoProfile -ExecutionPolicy AllSigned -Command …`.

| Command (as written in the Developer Guide unless noted) | Result |
|---|---|
| `uv run pytest` | builder tests: **1559 passed, 1 skipped**, 414 deselected (255 s). With the QA tests: see the last row |
| `uv run pytest -m e2e` | **254 passed, 1 xfailed** (the QA B3 xfail), 643 s. `test_trainer_v02.py::test_answer_steps_back_and_forward_and_ends_the_puzzle` passed (the builder's possible flake; see Observations). QA `test_qa_v09_ui.py` re-run after adding tests: **6 passed, 3 xfailed** |
| `npm.cmd --prefix web run build` (PowerShell), then `uv run pytest -m smoke` | build rc 0. **32 passed, 1 skipped, 1 xfailed** (427 s). Builder `test_real_app_v09.py` passed; QA `test_qa_v09_game_ai_gates_and_ai_reviewed_in_the_real_app` passed; the xfail is QA B1 (confirmed with `--runxfail`: `('same', '', 'medium')`). The v0.4 shutdown flake from v0.8 QA didn't recur |
| `uv run pytest -m engine` | **15 passed** (55 s) |
| `uv run pytest -m fulldb` | dev `puzzles.db` is imported: **71 passed, 3 xfailed** (earlier QA xfails), 548 s |
| `uv run pytest -m docs_screenshots` | **33 passed** (107 s). `git status docs/` clean: the committed screenshots match |
| `uv run ruff check .` / `uv run ruff format --check .` | All checks passed / 340 files already formatted (builder code). My first QA file needed an import sort, fixed |
| `uv run mypy src` | Success: no issues found in 105 source files |
| `npm.cmd --prefix web run typecheck` / `npm.cmd --prefix web run lint` (Git Bash and PowerShell) | rc 0 / rc 0 |
| `uv run pre-commit run --all-files` (PowerShell) | gitleaks Passed; keyring-only Passed; rc 0. Also run on the 4 new QA files: Passed |
| `python scripts/check_docs.py` / `--strict` | `check_docs: 0 error(s), 0 warning(s) [version v0.9]`, both, rc 0 |
| `uv run python scripts/gen_types.py` | `types.ts` content unchanged (git saw only CRLF/LF; restored) |
| `uv run python scripts/make_icon.py --check` | icon is up to date |
| `uv run python scripts/fetch_stockfish.py --dev` | already installed: Stockfish 19 (nothing to do) |
| `python scripts/setup.py --no-shortcut --skip-puzzle-db --skip-engine` (temp `WEAKSQUARE_DATA_DIR`) | rc 0, "Setup complete" |
| `uv run python -m weaksquare --dev` (after the build) | Window up, closed with WM_CLOSE after ~12 s: rc 0, "Shutting down", 0 ERROR/CRITICAL lines in the dev log. No migration (v0.9 has none). Like in v0.8 QA, this starts the dev folder's own start-up jobs (sync on open, the saved AI key's free launch check); I didn't read or print any credential |
| `npm.cmd --prefix web run dev` + `uv run python -m weaksquare --dev-server` | Vite 200; app rc 0, "Shutting down", no ERROR/CRITICAL |
| `npm.cmd --prefix web run dev -- --mode mock`, open http://127.0.0.1:5173 | HTTP 200, "VITE … mock ready" |
| `set_test_token.py` (both rows), `uv run pytest -m live` (incl. `tests/live/test_game_review_live.py`), `fetch_puzzle_db.py --dev`, `record_db_update.py` | **Not run.** The first are Adam's (credentials). The other two replace the dev DB or call Lichess and are unchanged since v0.4. I read `tests/live/test_game_review_live.py`: it only checks a key *exists* (never prints it), uses a temp data folder, the cheapest model as Game Review's own, a $0.02 cap and a $0.05 budget |
| Final run with the QA tests: `uv run pytest` | **1584 passed, 1 skipped, 1 xfailed** (B2), rc 0 (262 s) |

No human-facing command uses a `.ps1` script, bare `npm`/`npx`, or venv activation.

---

## Traceability

| Item / requirement | Method | Result | Evidence |
|---|---|---|---|
| **Done when: anonymization test** (no names, URLs, dates or clocks in the prompt) | unit + integration (QA) | PASS | `test_the_narrative_prompt_holds_no_pgn_header_name_rating_date_url_clock_or_comment`, `test_the_move_prompt_holds_no_game_metadata_either`. QA `test_qa_a_metadata_heavy_pgn_sends_no_trace_of_it_through_the_service`: the PGN is *imported* and both requests (system + user + schema) are checked against 29 markers (names, Elo, title, URL, date, time, `%clk`, `%eval`, comment, `$4`, header names, `[%`, the result tag) |
| **Done when: cache-hit test** | integration | PASS | `test_explain_this_move_runs_once_then_comes_from_the_cache` (no 2nd request, $0, survives a restart), `test_explain_my_game_validates_caches_and_marks_the_game_ai_reviewed`; e2e `test_explain_my_game_confirm_cancel_then_run` ("(saved)"); QA `test_qa_review_and_explain_on_a_saved_game_opens_no_confirm` |
| **Done when: budget enforcement** | integration + e2e | PASS | `test_the_budget_blocks_a_new_request_but_a_saved_one_still_shows`, `test_the_per_run_cap_blocks_explain_my_game`, `test_the_budget_and_the_cap_are_shared`; QA `test_qa_a_saved_move_explanation_still_shows_over_budget`, `test_qa_a_blocked_start_is_an_apperror_with_the_guardrail_code`; e2e `test_over_budget_blocks_a_new_explanation`, QA screenshot `qa-v09-over-budget.png` |
| **Done when: each feature's request uses its model and is logged under its feature** | integration | PASS | `test_each_feature_uses_its_own_model_and_is_logged_under_it` (both files), `test_a_feature_can_use_the_other_provider_with_its_key`; QA `test_qa_game_review_can_use_its_own_provider_when_puzzle_explain_is_off` (`game_review`, `gpt-5.4-mini`, no Anthropic request) |
| FR-1.15 Same as Explain until you pick | integration + e2e + smoke | PASS | `test_game_review_follows_explain_until_you_pick`; QA `test_qa_same_as_explain_follows_a_later_change_of_explains_model` (incl. a provider switch); e2e `test_settings_have_a_game_review_model_that_follows_explain`; builder smoke |
| FR-1.15 reasoning per feature; cap and budget shared | integration + smoke | PASS (B1) | `test_reasoning_is_per_feature_and_sets_max_tokens`; QA `test_qa_game_review_reasoning_scales_its_max_tokens_and_leaves_explain_alone` (×3: 1,500/4,000, 3,000/8,000, 6,000/16,000; Explain stays Low); smoke `test_game_review_model_in_the_real_app`. Race: B1 |
| FR-1.15 pickers: price-table models with cost, typed IDs, unpriced model unusable | e2e + integration | PASS (B4) | e2e options "… · about $… per game"; `no_price` quote state; typed IDs: B4 |
| FR-1.15 startup page shows both pickers | e2e | PASS | `test_the_startup_page_shows_both_pickers`; QA screenshot `qa-v09-startup-both-pickers.png` |
| FR-1.15 Review page model dropdown | e2e | PASS | `test_the_review_page_model_dropdown_changes_game_reviews_model` |
| FR-1.15 spend per feature in Settings | integration + e2e | PASS | `test_the_settings_list_both_features_with_their_models_and_spend`; QA `test_qa_settings_ai_and_startup_screens` |
| FR-1.15 launch check covers each feature's provider | integration | PASS | `test_launch_check_tests_each_provider_a_feature_uses` |
| FR-8.14 `max_tokens` 1,500 / 4,000, ×2/×4 | integration | PASS | see the reasoning row; `req.max_tokens == 1500` / `4000` in the builder tests |
| FR-11.17 Explain this move: your moves only (every move for "both"); grounded context; reuses `validate` | unit + integration + e2e | PASS | `test_explain_this_move_is_for_your_analyzed_moves_only`, `test_move_input_uses_the_best_line_as_the_solution_and_the_played_move_as_the_refutation`, `test_both_sides_review_counts_every_move_as_yours`; e2e `test_explain_this_move_on_your_mistake` (no button on Black's move; HTML shown as text); QA board check: Show me draws green f3→d4 and red f3→e5 (`qa-v09-dark-show-me-board.png`) |
| FR-11.18 N key moments (default = setting, 1–10) | integration + e2e | PASS | `test_n_is_checked` (0, 11, True, "5"); QA e2e: 10 options, placeholder "Moments: default", `test_qa_fewer_key_moments_cover_only_the_largest`; QA smoke: the real bridge refuses 0/11/True/"5" as `invalid_argument` |
| FR-11.18 Confirm with tokens, cost, % of budget left, cap | e2e | PASS | `test_explain_my_game_confirm_cancel_then_run` (Cancel sends nothing); QA `test_qa_user_guide_explain_my_game_steps_and_screens` |
| FR-11.18 validated narrative (moment plies and played move, better line from Stockfish's best and legal, squares, turning point, text) | unit | PASS | builder: `test_moments_for_other_plies_or_moves_are_dropped`, `test_bad_better_lines_are_dropped_and_counted`, `test_bad_annotations_turning_point_and_texts_are_dropped`, `test_answers_that_arent_the_json_asked_for_are_refused`; QA: repeated moment, 8 arrows (cap 6), bool turning point, HTML kept as text, a bad stored engine line, a promotion (`e8=Q`) in the better line from a non-standard start FEN |
| FR-11.18 minimal preset (≤ 3 motif/mate themes, valid range, else dropped) | unit | PASS | `test_preset_validation_drops_unknown_themes_and_bad_ranges`; QA `test_qa_preset_limits` (×6: 4 themes, phase/length/source themes, string rating, min > max, out of range, duplicate), `test_qa_no_valid_theme_means_no_preset_and_only_motifs_and_mates_are_offered` |
| FR-11.18 Train these: confirm first, Mixer only, never a saved preset | e2e | PASS (B3) | `test_train_these_applies_the_preset_only_after_the_confirm`; QA `test_qa_train_these_changes_only_themes_and_rating` (xfail B3). Code: `App.tsx` calls `changeSpec` only; no preset API is called |
| FR-11.19 SAN only, rebuilt from UCI; You / Opponent | unit + integration | PASS | see anonymization; `test_san_moves_numbers_a_game_that_starts_with_black`; QA promotion test checks the start FEN and "1. Kf1 Kb2" |
| FR-11.20 cache key (game, ply / N, provider, model, analysis settings, key-moment plies) | integration | PASS (B2) | `test_explain_my_game_validates_caches_and_marks_the_game_ai_reviewed` (other think time misses; other N misses), `test_each_feature_uses_its_own_model_and_is_logged_under_it` (other model misses). Thresholds: B2 |
| FR-11.21 / §9.3 guardrails; cached result free and shown over budget | integration | PASS | see budget row; QA `test_qa_a_double_click_sends_one_request` (a 2nd start while the 1st runs returns the same job; 1 request, 1 usage row) |
| FR-8.8 readable errors (truncated, refused, bad answer) | integration | PASS | `test_a_bad_or_truncated_answer_shows_nothing_but_is_logged`; QA `test_qa_an_unknown_color_is_refused_with_a_readable_message`; QA smoke: unanalyzed game → "Analyze this game first…" |
| FR-11.25 AI-reviewed status, badge; re-analysis resets it | integration + e2e + smoke | PASS | `test_explain_my_game_validates_caches_and_marks_the_game_ai_reviewed`; e2e status badge; QA smoke: an `ai_reviewed` row shows **AI-reviewed** in the real My games |
| FR-11.26 status filter incl. AI-reviewed | integration + e2e + smoke | PASS | `test_the_library_filters_and_shows_ai_reviewed_games`, `test_the_library_filters_by_ai_reviewed`; QA smoke `list_games({"statuses": ["ai_reviewed"]})` through the real bridge |
| FR-11.29 Review + Explain my game (analyze first if needed, then Confirm) | e2e | PASS | `test_review_and_explain_my_game_from_the_library` (unanalyzed game 2); QA `test_qa_review_and_explain_on_a_saved_game_opens_no_confirm`; QA smoke: hidden with no model set up |
| FR-8.1 no AI configured → no AI UI | e2e + smoke | PASS | `test_no_ai_means_no_game_review_ai`; builder and QA smoke |
| FR-8.7 escaped text | e2e + unit | PASS | `<i>` shown literally in `test_explain_this_move_on_your_mistake`; QA unit keeps `<img onerror>` as text; all AI text renders through React text nodes in `GameAiPanel.tsx` (no `dangerouslySetInnerHTML` in `web/src`) |
| Bridge: 7 new methods, allowlist in the same commit | contract | PASS | `tests/contract/test_bridge_allowlist.py` (commit 8fe04a6 has both); all use `@bridge_call`; QA smoke drove them through the real pywebview bridge |
| No engine call (stored analysis only) | code review + smoke | PASS | `services/game_explain.py` takes no engine; QA smoke runs every quote with no Stockfish in the data folder |

---

## Bugs

### v0.9-B1 (minor): a reasoning change right after a model pick puts the old model back
- **Steps:** Settings → AI → Game Review model: pick **claude-sonnet-5-5**, then click **Medium** under *Game Review reasoning* before the first save has come back from the bridge (a slow or busy PC).
- **Expected:** Sonnet at Medium.
- **Actual:** the reasoning save sends the *old* model (`FeatureModelPicker` builds it from `f.choice` / `f.model`, which are still the props from before the pick), so the setting ends as **Same as Explain** at Medium. The order of the two writes decides which one wins. The opposite order (reasoning, then model) can likewise put the old reasoning back, because `save()` defaults `level` to the stale `f.reasoning`. The dropdown shows the result, so you can redo it. Only the Settings picker has the reasoning control; the Review page's compact picker doesn't.
- **Evidence:** `tests/smoke/test_qa_v09_real_app.py::test_qa_v09_reasoning_right_after_a_model_pick_keeps_the_model` (xfail strict; the real bridge's `set_llm_feature` is delayed 1.5 s from the page). With `--runxfail`, the saved choice was `('same', '', 'medium')` instead of `('anthropic', 'claude-sonnet-5-5', 'medium')`.

### v0.9-B2 (minor, docs): new grading thresholds don't give a new explanation
- **Where:** User Guide → AI explanations in Game Review → Gotchas: "A new analysis at other settings, **or other grading thresholds**, gets a new explanation."
- **Actual:** the cache key has the analysis settings (think time, engine) and, for the narrative, the key-moment plies, but not the thresholds. After a threshold change, Explain this move is always still **(saved)**, and Explain my game is too unless the set of key moments changed. The text may then name a grade the review no longer shows ("mistake" vs "blunder"). FR-11.20 doesn't require thresholds in the key, so fixing the sentence is enough (for example: "…or a change in which moves are key moments…").
- **Evidence:** `tests/integration/test_qa_v09_game_ai.py::test_qa_new_grading_thresholds_give_a_new_explanation_as_the_user_guide_says` (xfail strict: both quotes stay `cached`).

### v0.9-B3 (minor): Train these changes more than the themes and rating
- **Steps:** Puzzles → Match **ALL** (or Puzzles from **My puzzles**, or Mix by ratio on). My games → Review game 1 → Explain my game → Confirm → **Train these** → **Apply and go to puzzles**.
- **Expected:** what the dialog says ("This sets the Mixer's themes … and the rating range …, replacing the themes and rating you have now") and the User Guide ("It replaces only the themes and rating you had").
- **Actual:** `App.tsx` also sets `match: "any"`, `source: "lichess"` and `ratios: []`. Match goes from ALL to ANY without a word. These choices are reasonable (the themes are Lichess themes; ALL of three motifs can match nothing), so the fix can be the dialog and guide text.
- **Evidence:** `tests/e2e/test_qa_v09_ui.py::test_qa_train_these_changes_only_themes_and_rating` (xfail strict: Match is `any`); `qa-v09-after-train-these.png`.

### v0.9-B4 (minor): the Game Review picker doesn't take a typed model ID
- **Steps:** Settings → AI → Game Review model: try to type a model ID.
- **Expected:** FR-1.15: "Each picker works like FR-1.3: the price table's models …, **typed IDs allowed**, and a model with no price row can't be used." Explain's model field takes typed IDs.
- **Actual:** it's a read-only `Select` of the price table's models. Workaround: add the model to the price table first; it then appears in the list (and an unpriced model couldn't run anyway). The bridge (`set_llm_feature`) does accept any valid ID.
- **Evidence:** `tests/e2e/test_qa_v09_ui.py::test_qa_game_review_picker_takes_a_typed_model_id` (xfail strict: the input is `readonly`).

### v0.9-B5 (minor): Game Review's picker is hidden until puzzle Explain has a provider
- **Steps:** with no AI set up, open Settings → AI explanations.
- **Expected:** FR-1.15 gives each feature its own provider and model, so you can set up Game Review alone (the backend supports it: QA `test_qa_game_review_can_use_its_own_provider_when_puzzle_explain_is_off` passes).
- **Actual:** `AiSettingsPanel` renders the Game Review block only when `info` (Explain's provider) is set. To use Game Review only, you must first choose a provider for puzzle Explain. If you later set Explain back to *None*, the Game Review block vanishes from Settings while Game Review keeps running on its own model (its picker still shows on the Review page).
- **Evidence:** `tests/e2e/test_qa_v09_ui.py::test_qa_game_review_can_be_set_up_without_puzzle_explain` (xfail strict).

### v0.9-B6 (minor, docs): the Game Review AI screenshot shows raw HTML tags
- **Where:** User Guide → AI explanations in Game Review → `docs/img/game-review-ai.png` (also in the QA dark screenshot).
- **Actual:** the explanation panel reads "…it keeps your pieces covered. `<i>Shown as typed.</i>`". It comes from the mock's `moveExplanation` (`web/src/api/mockGameAi.ts`), which adds the tags so `test_explain_this_move_on_your_mistake` can prove AI text is escaped. In a user-facing screenshot it looks like a rendering bug. The red "Some annotations were discarded…" note is in the same shot.
- **Expected:** a clean example in the guide. For instance, the docs spec could use a mock answer without the tags, or the escaping test could check a separate answer.
- **Evidence:** `docs/img/game-review-ai.png` (regenerated by `uv run pytest -m docs_screenshots` with no change).

---

## Tests added (all pass, or xfail strict for an open bug)

- `tests/unit/test_qa_v09_core.py`: `test_qa_a_repeated_moment_is_dropped_and_the_first_kept`, `test_qa_arrows_past_the_cap_are_dropped_and_counted`, `test_qa_a_bool_turning_point_is_dropped`, `test_qa_html_in_the_text_is_kept_as_text_for_the_ui_to_escape`, `test_qa_a_bad_stored_engine_line_never_crashes_a_prompt`, `test_qa_a_promotion_in_the_better_line_is_validated`, `test_qa_preset_limits` (×6), `test_qa_no_valid_theme_means_no_preset_and_only_motifs_and_mates_are_offered`, `test_qa_the_narrative_round_trips_through_the_cache_json`.
- `tests/integration/test_qa_v09_game_ai.py`: `test_qa_a_metadata_heavy_pgn_sends_no_trace_of_it_through_the_service`, `test_qa_a_game_with_no_errors_on_your_side_can_still_be_explained`, `test_qa_game_review_reasoning_scales_its_max_tokens_and_leaves_explain_alone` (×3), `test_qa_a_double_click_sends_one_request`, `test_qa_a_saved_move_explanation_still_shows_over_budget`, `test_qa_game_review_can_use_its_own_provider_when_puzzle_explain_is_off`, `test_qa_same_as_explain_follows_a_later_change_of_explains_model`, `test_qa_an_unknown_color_is_refused_with_a_readable_message`, `test_qa_a_blocked_start_is_an_apperror_with_the_guardrail_code`, `test_qa_new_grading_thresholds_give_a_new_explanation_as_the_user_guide_says` (xfail B2).
- `tests/e2e/test_qa_v09_ui.py`: `test_qa_user_guide_explain_my_game_steps_and_screens`, `test_qa_fewer_key_moments_cover_only_the_largest`, `test_qa_review_and_explain_on_a_saved_game_opens_no_confirm`, `test_qa_settings_ai_and_startup_screens`, `test_qa_over_budget_review_screen`, `test_qa_dark_mode_narrative`, `test_qa_train_these_changes_only_themes_and_rating` (xfail B3), `test_qa_game_review_picker_takes_a_typed_model_id` (xfail B4), `test_qa_game_review_can_be_set_up_without_puzzle_explain` (xfail B5).
- `tests/smoke/test_qa_v09_real_app.py`: `test_qa_v09_game_ai_gates_and_ai_reviewed_in_the_real_app`, `test_qa_v09_reasoning_right_after_a_model_pick_keeps_the_model` (xfail B1).

Screenshots (gitignored), `tests/e2e/artifacts/qa-v09-*.png`: review-ai-before, narrative-confirm, narrative, moment-on-board, library-ai-reviewed, settings-ai, startup-both-pickers, over-budget, dark-narrative, dark-show-me-board, after-train-these, real-review-no-ai. I looked at all of them. No clipped text or broken layout. The element screenshots of the board show the right position and arrows (red e5→f7, green e5→g4 for 5.Nxf7; green f3→d4, red f3→e5 for 4.Nxe5). The full-page screenshots stitch the sticky header into the middle of the page and can catch a modal mid-fade; that's the screenshot method, not the app.

---

## Scope, architecture and security findings

- **Later versions:** nothing built. `FEATURES` is `("explain", "game_review")`; no Coach feature, no Send to Coach, no tagger, no theme tags on game moves (`themes=()` with a comment). `preset_suggestion.py` is a v0.9 deliverable that v0.10 will reuse, as the plan says.
- **`core/`:** `game_explain.py` and `preset_suggestion.py` do no I/O (python-chess, `json`, dataclasses). No `datetime.now()`, `time.time()` or global `random` in `core/` or `services/` (the `import random` hits are pre-existing type imports for the injected `rng`). The service uses the injected `Clock` for `created_at`.
- **Wiring and threads:** `GameExplainService` is built only in `app.py` with the repos on the shared `Database` (a connection per thread from `adapters/db/connection.py`). No engine is used. `keyring` only in `adapters/secret_store.py`. LLM calls go through the existing adapters on `adapters/http.py`.
- **Bridge:** `Api._game_explain` is an underscore attribute; the 7 new methods use `@bridge_call`; allowlist updated in the same commit (8fe04a6). No key or key-shaped value in any new DTO (`key_stored` booleans only).
- **Front end:** no localStorage, sessionStorage, IndexedDB or cookies in `web/src`. No model names outside `core/llm/defaults.py` and the mock (`test_no_model_names.py` passes). AI text is rendered as React text.
- **Migrations / dependencies:** no migration (none changed). No dependency added: `pyproject.toml`, `package.json`, `uv.lock` and `package-lock.json` changed only the version (0.9.0).
- **Data:** tests use temp folders; the smoke harness uses a temp `WEAKSQUARE_DATA_DIR`. The CDP port is set only by `tests/smoke/conftest.py`; `app.py` refuses it without `--dev` (SR-16).
- **Secrets / fixtures:** no `sk-ant-`, `sk-` or `lip_` value outside the `FAKE` placeholders (one `sk-ant-secret` string in a pre-existing scrub test). New fixtures use `player_*` / `opponent_*`. `tests/unit/test_game_explain.py` has `https://lichess.org/AbCdEfGh` as a *forbidden* marker. It's in a test, not a fixture, and plainly made up, but it's shaped like a real game URL; `GAMEID01` would follow SR-12a's convention.

## Observations (no bug filed)

- **Possible flake** `test_trainer_v02.py::test_answer_steps_back_and_forward_and_ends_the_puzzle`: it passed in my full e2e run, alone among other loads. I couldn't reproduce a failure; it doesn't touch v0.9 code.
- After a fresh Explain my game, reopening the review in the same run still shows its cost (`$0.0022`), not "saved, free"; the button says **(saved)**. Same as puzzle Explain (`_fresh`), so consistent.
- The "Some annotations were discarded…" note also counts dropped preset themes, takeaways and better lines, not only annotations.
- The cache key doesn't include your color. If you switch from Black to Both and the key moments happen to be the same plies, the narrative written for "You played Black" is shown for both sides. Very unlikely; noted only.
- The turning point may be any ply; when it isn't a key moment its button shows only the move number (e.g. "5.") without the move.

---

## Docs findings

- `check_docs.py` and `--strict`: 0 errors, 0 warnings [version v0.9].
- **Developer Guide:** every command run as written (table above), except the credential/live/network ones. The new *Live Explain my game* row and the `llm.feature.game_review.*` keys match the code.
- **User Guide, followed against the mock (`test_qa_user_guide_explain_my_game_steps_and_screens`) and the real app (smoke):**
  - *A model for each feature* (Added in v0.9): labels **Puzzle Explain**, **Game Review model**, **Same as Explain**, *Puzzle Explain reasoning*, *Game Review reasoning*, spend per feature, startup **Show all options** → both pickers: all as written. B5: the Game Review block isn't there until Explain has a provider; the guide doesn't say so.
  - *What it costs, and the limits* (Changed in v0.9): correct.
  - *AI explanations in Game Review* (Added in v0.9): steps 1–3, the Confirm contents, the result list, **Train these**, **AI-reviewed**: as written, except B2 (thresholds) and B3 ("replaces only the themes and rating").
  - *My games* (status and **Review + Explain my game**): as written.
  - *Your data and privacy*: Explain this move and Explain my game list exactly what the code sends (`build_prompt` with `GameMoveFact`; `build_narrative_prompt`: color, result, SAN list, error counts, key-moment facts, allowed theme keys). The Confirm dialog repeats it.
- **CHANGELOG `[Unreleased]`:** covers Explain this move, Explain my game (with what it sends), AI-reviewed and Review + Explain my game, a model per feature, and the limits now covering Game Review. The *Done when* items are tests; their user-visible effects (saved = free, budget) are in the entries.
- **README** status line is true ("v0.9 … is being built"). **ARCHITECTURE** §2 lists the new modules and §7 has the two v0.9 entries.
- `docs/img/game-review-ai.png`, `settings-ai.png`, `startup.png`: regenerated with no change; they match the app. `game-review-ai.png` shows raw `<i>…</i>` tags (B6).

---

## For Adam's manual test

- **Real AI calls:** nothing here sends a real request (no key used; `-m live` not run). Please run `uv run pytest -m live tests/live/test_game_review_live.py`, then the plan's checklist: Explain my game on a recent loss, compare the moment notes and better lines with the engine lines, and Haiku for Explain + a stronger model for Game Review, checking *Puzzle Explain $… · Game Review $…* in Settings.
- **Quality of the narrative** (whether the turning point and takeaways make sense) can only be judged with a real model.
- **B1** needs a slow round trip; try changing the model then the reasoning quickly in Settings → AI.
- **Review + Explain my game** on a game that needs the real Stockfish analysis first (the mock's analysis is simulated; the QA smoke planted the analysis because the temp folder has no engine).
