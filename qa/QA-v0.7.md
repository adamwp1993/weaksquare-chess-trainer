# QA report: v0.7 (LLM Explain + cost guardrails)

Branch `v0.7` at `3b935c7`, run 2026-11-03 by the independent `qa-tester`. No product code, migrations, config or docs were changed. New tests are under `tests/` only.

## Verdict: **PASS WITH ISSUES** (7 minor, no blocker or major)

All three *Done when* items are met, except the live call itself, which only Adam can run (see "For Adam's manual test"). Every automated suite passes. The 7 bugs are all minor:
- B1: a null move passes the check on the AI's example lines.
- B2: an Anthropic key is accepted as an OpenAI key.
- B3: the price table accepts impossible "as of" dates.
- B4: an emptied cap or budget field saves $0.
- B5: the spend indicator opens Settings at the top, not at the AI section.
- B6: once a model is picked, the model list shows only that model.
- B7: the version number is still 0.6.0.

**Disclosure (my own process, not the app):** I closed the `--dev` window with a script that sent `WM_CLOSE` to every visible window with "WeakSquare" in its title. It found a matching window before the app's own window existed, so it may have closed one of your windows whose title contains "WeakSquare" (an editor, Explorer or terminal on the repo) at about 20:19 local time. The app itself was then closed by its process ID. Please check that nothing of yours was closed unexpectedly.

---

## Evidence: commands run

| Command (as written in the Developer Guide unless noted) | Result |
|---|---|
| `uv run pytest` | builder tests: **1197 passed**, 354 deselected (215 s). With the QA tests: **1243 passed, 6 xfailed** (B1 ×4, B2, B3), 362 deselected (217 s) |
| `uv run pytest -m e2e` | **206 passed, 1 failed** (554 s). The failure was `test_lichess_ui.py::test_rating_trend_on_stats`, `Page.goto: net::ERR_CONNECTION_TIMED_OUT` on the local static server. It passed when re-run (a flaky environment, not v0.7). `test_explain_ui.py`: 10/10. QA `test_qa_v07_ui.py`: 3 passed, 2 xfailed (B4, B5) |
| `npm.cmd --prefix web run build`, then `uv run pytest -m smoke` | build rc 0. **26 passed, 1 failed, 1 skipped** (373 s). The failure was in an older QA test, `test_qa_v06_real_app.py::test_v06_danger…`, which timed out waiting for "Solved". It passed in 2 re-runs (a known timing race in that test). `test_real_app_v07.py`: passed. QA `test_qa_v07_real_app.py`: passed |
| `uv run pytest -m engine` | **11 passed** (37 s). The builder added no real-Stockfish Explain test, although the plan lists one, so I added `tests/engine/test_qa_v07_explain_real.py` (2 passed, 7 s) |
| `uv run pytest -m fulldb` (dev `puzzles.db`, 1.67 GB) | **71 passed, 3 xfailed** (539 s); v0.7 doesn't touch filters, so no new full-DB tests |
| `uv run pytest -m docs_screenshots` | **27 passed**; `docs/img` unchanged (`git status` clean), so the screenshots are current |
| `uv run ruff check .` / `uv run ruff format --check .` | All checks passed / already formatted (QA files included) |
| `uv run mypy src` | Success: no issues found in 87 source files |
| `npm.cmd --prefix web run typecheck` / `npm.cmd --prefix web run lint` | rc 0 / rc 0 |
| `uv run pre-commit run --all-files` | gitleaks Passed; keyring-only Passed |
| `python scripts/check_docs.py` / `--strict` | `check_docs: 0 error(s), 0 warning(s) [version v0.7]` (both) |
| `uv run python scripts/gen_types.py` | `types.ts` unchanged |
| `uv run python scripts/make_icon.py --check` | icon is up to date |
| `uv run python scripts/fetch_stockfish.py --dev` | already installed: Stockfish 19 (nothing to do) |
| `python scripts/setup.py --no-shortcut --skip-puzzle-db --skip-engine` (temp `WEAKSQUARE_DATA_DIR`) | rc 0, "Setup complete" |
| `uv run python -m weaksquare --dev` (after the build) | window up; dev `user.db` migrated 5 → 6 with backup `user-5-20261104-011912.db`; closed with WM_CLOSE → "Shutting down"; 0 ERROR/Traceback lines. The banner says **0.6.0** (B7) |
| `npm.cmd --prefix web run dev` + `uv run python -m weaksquare --dev-server` | Vite 200; window up; app rc 0; 0 ERROR lines |
| `npm.cmd --prefix web run dev -- --mode mock`, open http://127.0.0.1:5173 | HTTP 200, Vite "mock" ready |
| `set_test_token.py --llm …`, `uv run pytest -m live`, `fetch_puzzle_db.py --dev`, `record_db_update.py` | **not run.** The first two are Adam-only (credentials, real spend); the others would replace the dev DB or call Lichess, and they haven't changed since v0.4. The live test's code was reviewed instead (below) |

No human-facing command uses a `.ps1` script, bare `npm` / `npx`, or venv activation.

---

## Traceability

| Item / requirement | Method | Result | Evidence |
|---|---|---|---|
| **Done when: budget enforcement (blocked when over)** | integration | PASS | `test_llm_guardrails.py::test_blocked_once_the_month_reaches_the_budget_and_unblocked_by_raising_it`, `test_explain_service.py::test_budget_enforcement_through_explain`; unit `test_blocked_at_exactly_100_percent_of_the_budget`; QA `test_qa_budget_a_hair_under_100_percent_still_runs`, `test_qa_cap_zero_blocks_and_budget_zero_blocks` |
| **Done when: cap enforcement** | integration | PASS | `test_blocked_when_over_the_per_run_cap_and_unblocked_by_raising_it`, `test_cap_enforcement_through_explain`; QA `test_qa_worst_case_exactly_at_the_cap_is_allowed` (equal → ok; 0.1+0.2 vs 0.3 → ok) |
| **Done when: annotation validation drops illegal moves and squares** | unit + integration | PASS (B1) | `test_explain.py` (11 validation tests), `test_invalid_annotations_are_dropped_and_reported`; QA `test_qa_annotation_edge_squares_and_case`, `test_qa_huge_and_nested_junk_is_tolerated`. A null move in a variation gets through: B1 |
| **Done when: live test, 1 real Explain under the cap** | code review | PENDING (Adam) | `tests/live/test_llm_live.py`, reviewed below |
| FR-1.2 provider None/Anthropic/OpenAI | e2e + smoke | PASS | `test_set_up_a_provider_nothing_preselected`, `test_ai_settings_in_the_real_app` |
| FR-1.3 nothing pre-selected; dropdown from the price table with cost; typed IDs; no price row → unusable | integration + e2e + smoke | PASS (B6) | `test_nothing_is_preselected`, `test_defaults_nothing_preselected`, `test_price_row_needed_even_with_a_key`, `test_no_model_picked`; QA `test_qa_odd_model_ids_are_refused` (7 odd IDs), `test_qa_model_ids_with_slash_are_url_encoded_in_test_key`; QA smoke (a typed `qa-model` with a price row appears in the dropdown). Once a model is picked, the list hides the others: B6 |
| FR-1.3 model names only in `core/llm/defaults.py` | contract | PASS | `test_no_model_names.py` (src + web/src, mocks excluded) |
| FR-1.4 masked key, Test key is the free lookup | integration + e2e | PASS | `test_test_key_uses_the_free_check_and_reports_failures`, `test_anthropic_test_key_is_the_free_model_lookup`, `test_test_key_job`; e2e key-save flow (field emptied, key not in the page) |
| FR-1.6 fast path needs the silent AI check | integration + e2e | PASS | `test_launch_check`, `test_startup_fast_path_and_a_failed_ai_key`; screenshot `qa-v07-startup-ai-failed.png`. Implemented in `llm_settings.start_launch_check` + `StartupView`, not `services/account.py` as the plan said (it works the same) |
| FR-1.8 gear → AI settings, price table, budget | e2e + smoke | PASS (B4, B5) | `test_price_table_add_and_delete`, `test_over_budget_blocks_explain`; my guide walk (Edit → Save price, reasoning changes the dropdown cost from $0.0005 to $0.0014) |
| FR-1.10 spend indicator, 80% yellow, 100% red | e2e | PASS (B5) | `test_warning_level_at_80_percent`, `test_over_budget_blocks_explain`, `test_no_ai_set_up_means_no_explain_and_no_indicator` |
| FR-8.1 button only with provider+key; needs Stockfish; only once over; every mode | integration + e2e + smoke | PASS | `test_only_after_the_puzzle_is_over`, `test_requires_stockfish`, `test_explain_needs_stockfish`, `test_danger_spotting_explains_the_candidate`; QA `test_qa_explain_in_a_practice_run` (refused mid-run, works once over), `test_qa_explain_after_commit_the_line`, QA smoke (no key → no button; `start_explain` refused) |
| FR-8.2 grounded facts, allowlist | unit + integration + engine | PASS | `test_prompt_has_the_facts`, `test_prompt_never_names_the_puzzle_or_its_rating`, `test_explain_after_a_wrong_move` (no puzzle ID); QA engine `test_qa_real_engine_facts_standard` / `_danger_spotting` (real Stockfish lines and refutation present, every SAN replays legally) |
| FR-8.3 structured output | unit + adapters | PASS | `test_schema_is_strict_mode_shaped`, `test_anthropic_request_shape_and_usage`, `test_openai_request_shape_and_usage` |
| FR-8.4 validation + "discarded" note | unit + e2e | PASS (B1) | see the Done-when row; e2e `explanation-discarded` |
| FR-8.5 Show me draws shapes | e2e | PASS | `test_explain_after_the_puzzle_draws_on_the_board`; QA `test_qa_show_me_steps_with_the_arrow_keys` |
| FR-8.6 cache by (puzzle, path, provider, model); free; works over budget | integration | PASS | `test_cache_hit_is_free_and_keyed_by_provider_and_model`, `test_cache_key_includes_your_moves`; QA `test_qa_cache_hit_runs_while_over_budget_and_makes_no_request` (a full run at budget $0: done, cost 0, no request) |
| FR-8.7 escaped text | unit + e2e | PASS | `test_html_is_kept_as_text_for_the_ui_to_escape`; e2e (`<b>` shown as text, no `<b>` element); no `dangerouslySetInnerHTML`/`innerHTML` in `web/src` |
| FR-8.8 timeouts, readable errors | integration | PASS | `test_failures_are_readable_and_cache_nothing`, `test_errors_map_to_readable_kinds_without_retrying`; QA `test_qa_openai_errors_through_the_http_client` (429 `insufficient_quota` → quota, 429 rate limit → rate_limited, 401, 404, 400, 503 HTML; 1 call each, our message only), `test_qa_anthropic_errors_through_the_http_client` (529, billing_error, 403, 404, 500) |
| FR-8.9 editable price table, long tier | unit + integration | PASS (B3) | `test_long_context_tier_applies_above_the_threshold_only`, `test_price_rows_are_validated`, `test_edited_and_deleted_seed_rows_stay_as_you_left_them`; QA `test_qa_price_rows_are_validated` (11 bad rows refused), `test_qa_delete_unknown_price_row_is_not_found` |
| FR-8.10 usage log incl. truncated/refused | integration | PASS | `test_a_run_is_logged_with_the_cost_from_the_price_table`, `test_truncated_and_refused_answers_are_still_logged`; QA `test_qa_bad_answer_is_logged_but_not_cached` |
| FR-8.11 inline estimate, no confirm | e2e | PASS | "Explain (≈ $0.0…)" in `test_explain_after_the_puzzle_draws_on_the_board` |
| FR-8.12 cap vs worst case | unit + integration | PASS | `test_estimate_has_a_typical_and_a_worst_case`, the cap rows above |
| FR-8.13 budget 80%/100%, local month | unit + integration | PASS | `test_spend_level_warns_at_80_percent`, `test_thresholds_survive_float_sums`, `test_the_budget_resets_with_the_local_month` (UTC Dec 1 03:00 = local Nov 30) |
| FR-8.14 hard max_tokens | integration | PASS | `test_explain_after_a_wrong_move` (1500), adapter shape tests (`max_tokens` / `max_output_tokens` always present) |
| FR-8.15 reasoning Low/Medium/High raises max_tokens | unit + integration | PASS | `test_reasoning_raises_max_tokens`, `test_reasoning_raises_max_tokens_on_the_request`, `test_reasoning_level_changes_the_per_model_cost` |
| No automatic retry of generation | integration | PASS | QA HTTP-client error tests: exactly 1 request per error; `retry=False` in both adapters |
| SR-1 / SR-7 key never in DTO / job / user.db / logs / errors | integration + smoke | PASS | `test_keys_are_stored_in_the_secret_store_and_never_returned`, `test_saving_a_key_never_returns_it`; QA `test_qa_key_never_in_dtos_jobs_user_db_or_logs` (settings, spend, prices, two key-test jobs, quote, a failed and a good Explain, an `iterdump` of user.db, the log folder), `test_qa_wrong_provider_key_errors_never_echo_the_key`; QA smoke (refused keys never echoed; real `user.db` dump has no `sk-`) |
| SR-5 / SR-10 redaction of `x-api-key` / `sk-` | unit | PASS | `test_redacts_llm_api_keys` |
| SR-11 allowlist | unit + integration | PASS | see FR-8.2 |
| SR-12 / 12a fixtures scrubbed and anonymized | contract + review | PASS | the existing fixture secret-scan test passes; `tests/fixtures/http/llm/*` are hand-written, with no IDs, model names or URLs; `git grep` finds no `sk-…`/`lip_…` except `FAKE` placeholders |
| SR-13 live test opt-in, separate entry | review | PASS | `pytestmark = live`; `KeyringSecretStore(SERVICE_TEST)`; skips without a key |
| ARCH §3 decisions 12–17 | grep + tests | PASS | no browser storage in `web/src`; no `datetime.now()`/`time.time()`/global random in the new core/services (they use the injected `Clock`); `Api` dependencies are `_llm_settings`/`_llm_usage`/`_explain`; allowlist contract test passes; the usage service serializes requests with a lock and connections come from `Database` |

---

## Bugs

### v0.7-B1 (minor): a null move passes the check on a variation
- **Steps:** have the model's step 0 answer with `"variation": ["--", "Nxe4"]` (or `Z0`, `0000`, `@@@@`).
- **Expected:** the variation is dropped and counted (FR-8.4: legal in sequence).
- **Actual:** kept as `("--", "Nxe4")`: one side "passes" and the other moves twice. `chess.Board.parse_san` returns `Move.null()` for those strings without a legality check, and `core/explain.py::_variation` accepts it. Only shown as text ("for example -- Nxe4"), never drawn.
- **Evidence:** `tests/integration/test_qa_v07_edges.py::test_qa_null_move_in_a_variation_is_dropped` (4 strict xfails).

### v0.7-B2 (minor): an Anthropic key is accepted as the OpenAI key
- **Steps:** Settings → AI, provider OpenAI, paste an `sk-ant-…` key, Save key.
- **Expected:** refused as the wrong provider's key (the shape check's stated purpose).
- **Actual:** stored, because `sk-ant-` also starts with OpenAI's `sk-`. Test key / Explain later fail with "API key was rejected". The reverse direction is caught.
- **Evidence:** `test_qa_an_anthropic_key_is_refused_as_an_openai_key` (strict xfail).

### v0.7-B3 (minor): the price table's "as of" accepts impossible dates
- **Steps:** `save_llm_price("anthropic","m",1,1,None,None,None,"2026-13-45")`.
- **Expected:** refused. **Actual:** saved (`ISO_DATE` is a digits-only regex). The UI form sends today's date, so this is bridge-only today.
- **Evidence:** `test_qa_impossible_as_of_date_is_refused` (strict xfail).

### v0.7-B4 (minor): emptying the cap (or budget) field saves $0
- **Steps:** Settings → AI explanations, clear **Per-run cap ($)**, click elsewhere.
- **Expected:** the old value stays, or there's a message.
- **Actual:** `Number("")` = 0 is saved silently. From then on every Explain is blocked ("more than your per-run cap of $0.00"). The **Monthly budget** field behaves the same, blocking at $0.00 of $0.00. The reason shows under the button, so you can recover.
- **Evidence:** `tests/e2e/test_qa_v07_ui.py::test_qa_clearing_the_cap_field_does_not_silently_set_zero` (strict xfail; the cap reads "0").

### v0.7-B5 (minor): the spend indicator opens Settings at the top, not at the AI section
- **Steps:** with `?ai=warn`, click **AI $… / $5.00**.
- **Expected (plan §6):** "clicking it opens the AI settings". **Actual:** the Settings dialog opens at Lichess account; the AI section starts at y = 1450 px in a 900 px viewport. The User Guide only promises "open the settings", so the guide isn't wrong.
- **Evidence:** `test_qa_spend_indicator_opens_settings_at_the_ai_section` (strict xfail); `tests/e2e/artifacts/qa-v07-spend-click.png`.

### v0.7-B6 (minor): once a model is picked, the model list shows only that model
- **Steps:** Settings → AI with a model picked (`?ai=on`), open the **Model** dropdown.
- **Expected:** every price-table model for the provider, with its cost (User Guide step 4; Adam's manual test compares two models).
- **Actual:** 1 option. Mantine `Autocomplete` filters by the current text, so you must clear the field to see the others.
- **Evidence:** a guide walk script against the mock dev server, which printed "options shown with a model picked: 1".

### v0.7-B7 (minor): the version is still 0.6.0
- **Steps:** run the app on branch `v0.7`.
- **Actual:** the log banner says "WeakSquare 0.6.0 starting". `pyproject.toml` and `web/package.json` are 0.6.0, so the About screen and the HTTP User-Agent (now also sent to Anthropic/OpenAI) say 0.6.0. v0.4–v0.6 bumped the version during the build. The README status still says "v0.7 … is next", although plan step 12 is ticked ("README status").
- **Expected:** 0.7.0 before `v0.7-rc1`.

### Observations (not bugs)
- **Offline launch:** the silent key check treats a network failure as a failed key. Offline, the startup page opens in full with "Your AI key didn't work: Couldn't reach the provider…". That's consistent with FR-1.6, but the wording blames the key.
- **Shared cache entry:** the cache key doesn't include whether you solved it or used Show answer with no wrong move (both are `("standard",)`). The prompt differs ("The player solved it." vs "used help"), so a cached explanation can speak to the other case. This is what FR-8.6 specifies.
- **No provider column:** the price table has no provider column. Two providers with the same model ID would look alike.
- **Dead fake default:** `tests/fakes/llm.py::explain_json()` (the fake's default answer) uses `"square"` and no `"move"`, so validation drops all of its steps. No builder test relies on it for steps, but it's a misleading default.
- **No v0.7 engine test:** the plan's verification lists `-m engine` "Explain context with real Stockfish", but no such builder test exists. QA added one (it passes).

---

## Tests added (all under `tests/`)
- `tests/integration/test_qa_v07_edges.py` (46 passed, 6 strict xfails):
  - Validation: `test_qa_null_move_in_a_variation_is_dropped` (xfail B1), `test_qa_annotation_edge_squares_and_case`, `test_qa_huge_and_nested_junk_is_tolerated`, `test_qa_board_is_never_mutated_by_validation`.
  - Guardrails: `test_qa_worst_case_exactly_at_the_cap_is_allowed`, `test_qa_budget_a_hair_under_100_percent_still_runs`, `test_qa_cap_and_budget_fields_refuse_bad_values`.
  - Models and keys: `test_qa_odd_model_ids_are_refused` (7 IDs), `test_qa_model_ids_with_slash_are_url_encoded_in_test_key`, `test_qa_an_anthropic_key_is_refused_as_an_openai_key` (xfail B2), `test_qa_wrong_provider_key_errors_never_echo_the_key`.
  - Prices: `test_qa_price_rows_are_validated` (11 cases), `test_qa_impossible_as_of_date_is_refused` (xfail B3), `test_qa_delete_unknown_price_row_is_not_found`.
  - Explain end to end: `test_qa_cache_hit_runs_while_over_budget_and_makes_no_request`, `test_qa_cap_zero_blocks_and_budget_zero_blocks`, `test_qa_bad_answer_is_logged_but_not_cached`, `test_qa_rapid_double_start_sends_one_request`, `test_qa_explain_in_a_practice_run`, `test_qa_explain_after_commit_the_line`, `test_qa_late_result_never_lands_on_the_next_puzzle`.
  - The key: `test_qa_key_never_in_dtos_jobs_user_db_or_logs`.
  - Provider errors: `test_qa_openai_errors_through_the_http_client` (6), `test_qa_anthropic_errors_through_the_http_client` (5).
- `tests/engine/test_qa_v07_explain_real.py`: `test_qa_real_engine_facts_standard`, `test_qa_real_engine_facts_danger_spotting`.
- `tests/e2e/test_qa_v07_ui.py`: `test_qa_explanation_does_not_follow_you_to_the_next_puzzle`, `test_qa_show_me_steps_with_the_arrow_keys`, `test_qa_clearing_the_cap_field_does_not_silently_set_zero` (xfail B4), `test_qa_spend_indicator_opens_settings_at_the_ai_section` (xfail B5), `test_qa_screenshots_of_the_new_screens`.
- `tests/smoke/test_qa_v07_real_app.py`: `test_qa_v07_real_bridge_gates`. Real app; it never stores a key: only key shapes the backend refuses before it reaches `secret_store`.

## Scope, architecture, security
- **Scope:**
  - No SDK or markdown dependency. `pyproject.toml`, `uv.lock`, `web/package.json` and `package-lock.json` are unchanged on the branch.
  - No Game Review AI or Coach code. `llm_usage` only mentions its future callers in a docstring.
  - `help_used = 'explain'` is never written.
- **Model names and prices:** model names appear only in `core/llm/defaults.py` (contract test, plus my grep). No prices are hard-coded outside the seed.
- **Layers:**
  - `core/` does no I/O. Only `app.py` wires `AnthropicProvider`/`OpenAIProvider`.
  - `keyring` is imported only in `secret_store.py` (pre-commit hook passes).
  - Both adapters go through `adapters/http.py`, with `retry=False` and per-request headers and timeout.
- **Migrations:** `0006_llm.sql` is new; no applied migration was edited (`git diff main...HEAD` touches only the new file).
- **Secrets:**
  - No `sk-`/`lip_` value except `FAKE` placeholders in the repo, `docs/img` or `tests/e2e/artifacts`; gitleaks passes.
  - `bridge_call` logs only the method name and our error message.
  - `HttpError` carries only the URL and status, plus a validated short error code.
  - The CDP port is set only by the smoke harness (`tests/smoke/conftest.py`, `test_real_app.py`). The app refuses it without `--dev` (`test_sr16_refusal.py`).
- **Live test (`tests/live/test_llm_live.py`), reviewed:**
  - It goes through the real bridge, the real adapter and a temp data folder.
  - The key comes from `KeyringSecretStore(SERVICE_TEST)` and is never printed.
  - It sets the cap to $0.01 and the budget to $0.05, and asserts the quote's worst case is ≤ $0.01 before the call.
  - It asserts exactly 1 generation request (`len(bodies) == 1`) and 1 usage row, with 0 < cost ≤ $0.01 and positive tokens. A second quote must be `cached`, with no request.
  - `--record-llm` keeps only `type/role/content/stop_reason/usage` (Anthropic) or `object/status/incomplete_details/output/usage` minus item IDs (OpenAI). The option is registered in `tests/conftest.py`.
  - **Pending Adam's run.**

## Docs
- `check_docs.py` and `--strict`: 0 errors, 0 warnings [v0.7].
- **Developer Guide:**
  - Every command was run as written (the table above), except the Adam-only and network/DB-replacing rows.
  - The AI settings keys, the live-test key command and the "Add an LLM provider" recipe match the code (`KEY_PREFIX`, `KEY_SHAPE`, `fake_providers`, `KEEP`/`FILE` all exist).
- **User Guide, followed against the mock (`?ai=on|over|warn|failed|nomodel`):**
  - The *AI explanations and what they cost* steps 1–6 work, and the labels match ("AI provider", "Model", "Save key", "Remove key", "Test key", "Explain (≈ $…)", "Explain (saved)", Back/Forward, Done, "Some annotations were discarded", Edit / Save price / Delete).
  - Two small mismatches: error and tooltip text says "Settings → AI" while the section is titled "AI explanations", and step 4's list hides the other models once one is picked (B6).
  - The startup page (*Changed in v0.7*) is accurate.
  - Privacy: the section lists exactly what the prompt contains (position, solution, themes, your moves, Stockfish lines and refutation, attack/defence facts, the Danger candidate and call) and no IDs, ratings or names, which matches `build_prompt` and the tests.
- **CHANGELOG `[Unreleased]`:** covers every user-visible item (Explain, AI settings and Test key, the launch check, the spending limits, the spend indicator, caching).
- **ARCHITECTURE:** §7 has the four v0.7 entries; §2 lists `core/llm/`, `services/llm_*` and `explain.py`.
- **Screenshots:** regenerated, with no diff.
- **Visual check:**
  - Mock screenshots in `tests/e2e/artifacts/qa-v07-*.png`: explain, explain-narrow, settings-ai-over, startup-ai-failed, startup-all-options, spend-click.
  - No clipped text or broken layout. The explain panel, price table and startup alert read correctly at 1280 px and 900 px.

## For Adam's manual test
1. **The live test** (`uv run python scripts/set_test_token.py --llm anthropic`, then `uv run pytest -m live`). QA can't run it.
   - `adapters/llm/anthropic.py` sends `anthropic-version: 2026-10-21` and `output_config.effort` / `output_config.format`. I couldn't verify these against the live API offline.
   - If the call fails with "The provider refused the request" (`llm_bad_request`), check the version header and request shape first.
   - Do the same for OpenAI's `/v1/responses` with `store: false` and `reasoning.effort` on `gpt-5.4-nano`. Its fixture is still hand-written.
2. **The ROADMAP manual test:** $0.05 budget → Explain until blocked → raise it → compare one puzzle across two models. To switch models you'll need to clear the Model field first (B6), and don't leave the cap or budget field empty (B4).
3. **Real-money spend:** check the spend indicator against your provider console after a few Explains. Token counts are only verified against fixtures.
4. **Offline start-up with a saved key:** check the wording is acceptable to you (see Observations).
5. **Your windows:** check nothing of yours was closed by my WM_CLOSE script at about 20:19 (see Disclosure).
