# QA report: v0.11 (Whole-game coaching), round 1

Branch `v0.11` at `f2b1081`. Run on 2026-11-04 by the independent `qa-tester`. I changed no product code, migrations, config or docs. New tests are under `tests/` only. `-m live` was **not** run (Adam's). No network was available from this machine, so the curated lesson links were not opened.

## Verdict: **FAIL** (3 major, 5 minor; no blocker)

Most of v0.11 works, in the mock, the integration tests and the real app. Digests and measures are right on fixture games, and the evidence rule drops invented labels and plies. Advanced sends SAN only, for the newest N games up to the cap. The cap blocks Advanced even when a standard run still fits. Advanced and Include my notes are never saved, and lesson URLs are built only by the backend. All automated suites are green.

Two *Done when* items are not fully met, and one guardrail can be bypassed, so the gate (minor issues only) isn't met yet. Each fix is small:
- **B1 (major):** a URL written by the LLM **is shown**: in the name of an AI preset (both answer formats) and anywhere in the puzzle-history-only coaching (summary, explanation, drill). Breaks the Done-when item "a URL written by the LLM is never shown" and FR-10.59.
- **B2 (major):** `strip_urls` misses common web addresses: `youtu.be/…`, `bit.ly/…`, `chessable.co.uk/…`, any `.de`, and `ftp://`. These reach the LLM from **Include my notes**, and they're shown from the LLM's text. It also mangles ordinary words: `Qd1.Coming` becomes `[link removed]ing`. Breaks FR-8.16 ("no URLs, ever") and FR-10.60.
- **B5 (major):** a double-click on **Confirm** starts two AI runs, and both are sent and billed. The backend has no guard either. Breaks FR-8.11: you confirm one estimate and pay twice. The same pattern was already in v0.10's Coach box.
- **B3 (minor):** an observation is counted twice when a report is re-run after another report (A, B, A gives 3, not 2).
- **B4 (minor):** **Mistakes per 10 games** by phase has no sample-size guard. It shows "endgame 30" from a single game. Breaks the Done-when item "the guard applies to every whole-game measure".
- **B6 (minor):** the whole-game prompt silently drops v0.10's puzzles-vs-games table. The privacy section still says it's sent, and it doesn't say that key moments carry their themes and your mistake-reason labels.
- **B7 (minor):** "Mixed endgames: 1 games" in the measures.
- **B8 (minor, docs):** `plans/v0.11.md` item 8 (lesson pointers) is not ticked, but it's built.

---

## Evidence: commands run

Git Bash. `npm.cmd` was used as written.

| Command (as in the Developer Guide) | Result |
|---|---|
| `uv run pytest` | builder tests: **1820 passed, 1 skipped**, 488 deselected (315 s), rc 0. With the QA tests: see the last row |
| `uv run pytest -m e2e` | **304 passed** (733 s), rc 0. QA `test_qa_v011_ui.py`: **6 passed, 1 xfailed** (B5) |
| `npm.cmd --prefix web run build`, then `uv run pytest -m smoke` | build rc 0; **36 passed, 1 skipped** (473 s), rc 0, including QA `test_qa_v011_real_app.py` (also passed on its own). No flakes this time |
| `uv run pytest -m engine` | **19 passed** (69 s) |
| `uv run pytest -m fulldb` | dev `puzzles.db` imported: **73 passed, 3 xfailed** (562 s), rc 0 |
| `uv run pytest -m docs_screenshots` | **41 passed** (125 s). Only `docs/img/stats-reasons.png` changed. I compared the two images: identical apart from the tab-underline animation frame. I restored the committed file. All four new v0.11 screenshots regenerate byte-identical |
| `uv run ruff check .` / `uv run ruff format --check .` | All checks passed / 388 files already formatted (my files included) |
| `uv run mypy src` | Success: no issues found in 123 source files |
| `npm.cmd --prefix web run typecheck` / `npm.cmd --prefix web run lint` | rc 0 / rc 0 |
| `uv run pre-commit run --all-files` | Detect hardcoded secrets Passed; keyring only in secret_store.py Passed; rc 0 |
| `python scripts/check_docs.py` / `--strict` | `check_docs: 0 error(s), 0 warning(s) [version v0.11]`, both rc 0 |
| `uv run python scripts/gen_types.py` | `types.ts` content unchanged (`git status web/src` clean) |
| `uv run python scripts/make_icon.py --check` | icon is up to date |
| `uv run python scripts/fetch_stockfish.py --dev` | already installed: Stockfish 19 (nothing to do) |
| `npm.cmd --prefix web run dev -- --mode mock`, open http://127.0.0.1:5173 | HTTP 200, "VITE v8.3.5 mock ready" |
| Run the app / `--dev-server` | covered by the smoke harness: the real app with a temp `WEAKSQUARE_DATA_DIR`. Not run against the dev folder, so the dev `user.db` isn't migrated to 0009 |
| `python scripts/setup.py --no-shortcut --skip-puzzle-db --skip-engine` (temp `WEAKSQUARE_DATA_DIR`; the documented flags, minus the network and shortcut steps) | rc 0, "Setup complete"; `git status` shows only my new files afterwards |
| `uv run pytest` with the QA tests | **1865 passed, 1 skipped, 14 xfailed** (319 s), rc 0 (14 xfails = the QA unit and integration bug tests) |
| `set_test_token.py` (both rows), `-m live` (three rows), `fetch_puzzle_db.py --dev`, `record_db_update.py` | **Not run.** The first are Adam's (credentials). The others need the network and are unchanged since v0.4 |

No human-facing command uses a `.ps1` script, bare `npm`/`npx`, or venv activation. The new Developer Guide how-to ("Add a curated lesson link or a search site") matches the code: `CURATED`, `ALLOWED_HOSTS`, `CONCEPTS`, `SEARCH_SITES`, `LESSON_SITES`, `CoachSettingsPanel.tsx` and `SITE` all exist as described.

---

## Traceability

| Item / requirement | Method | Result | Evidence |
|---|---|---|---|
| **DW: digest fields on fixture games:** castling move, moves before castling, endgame type, +2 conversion, −2 saves, low-clock blunders | unit + QA unit | PASS | `test_digest.py`: `test_castling_move_and_moves_before_castling`, `test_endgame_type_from_the_material_signature`, `test_conversion_from_plus_two_needs_a_full_move` (one-ply blip ignored), `test_save_from_minus_two`, `test_low_clock_blunders_and_clock_percentages`, pawn structure, trades, family. QA `test_qa_digest_for_black_held_and_castling` (Black's view) |
| **DW: each whole-game measure unit-tested** | unit | PASS | `test_game_measures.py` (openings, endgames, conversion, saves, low clock, castling late, per-phase errors, ranking) |
| **DW: the sample-size guard on every measure** | unit + QA unit + smoke | **FAIL (B4)** | Guarded: openings, endgames, conversion, saves, time, king (`test_every_measure_is_guarded_below_five_games`; QA `test_qa_conversion_with_four_games…`, `…endgame_type_with_four_games…`, `test_qa_low_clock_needs_five_clocked_games`). Not guarded: errors per phase (QA xfail `test_qa_errors_per_phase_are_guarded_below_five_games`; real-app screenshot shows "endgame 30" from one game) |
| **DW: a standard prompt has no full move lists** | unit + integration + QA | PASS | `test_a_standard_prompt_has_no_move_lists`, `test_the_prompt_is_anonymized`. QA `test_qa_a_standard_prompt_never_lists_a_whole_game` (only key-moment plies are citable) |
| **DW: Advanced is SAN only, with no headers, names, dates, URLs, clocks or comments** | unit + integration + QA | PASS | `test_an_advanced_prompt_adds_san_only`, `test_advanced_adds_san_move_lists_and_is_kept_as_its_own_run`. QA `test_qa_no_header_name_date_url_rating_clock_or_comment_reaches_any_prompt`: 12 distinct games whose PGNs carry Event, Site URL, Date/UTCDate, names, Elo, TimeControl, `{ comment [%clk] }` on every move. Standard, Advanced and notes prompts contain none of them |
| **DW: notes only with Include my notes** | unit + integration + e2e + QA + smoke | PASS (B2 for URLs) | `test_notes_go_only_with_include_my_notes_and_match_the_preview`, `test_notes_appear_only_when_included_and_without_urls`. QA `test_qa_the_notes_preview_matches_what_is_sent_exactly` (latest entry per move, preview == sent, in order). QA smoke: the preview in the real app shows `missed Rd8#, see [link removed]` |
| **DW: an invented game label or ply is dropped** | unit + QA | PASS | `test_an_invented_game_label_or_ply_is_dropped`. QA `test_qa_any_malformed_citation_is_dropped` (12 cases: float, bool, lower-case label, E-label, ply 0 or negative, another game's ply…), `test_qa_a_cited_ply_must_be_sent_for_that_game` (end to end) |
| **DW: a weakness with no valid evidence is dropped** | unit | PASS | `test_a_weakness_with_no_valid_evidence_is_dropped` |
| **DW: fewer than 3 cited games is tentative** | unit + QA | PASS | `test_fewer_than_three_games_is_tentative`. QA `test_qa_duplicate_citations_count_once_for_tentative` |
| **DW: every curated link's domain is in the allowlist** | unit + QA | PASS (manual: liveness) | `test_every_curated_link_is_on_the_allowlist`. QA `test_qa_every_curated_url_is_https_lichess_practice_or_learn`. **Not checked:** whether the 33 URLs load (no network here) |
| **DW: a URL written by the LLM is never shown** | unit + QA | **FAIL (B1, B2)** | Diagnosis text is stripped (`test_a_url_written_by_the_llm_is_never_kept`), but: preset names keep URLs (QA xfail `test_qa_a_url_in_an_ai_preset_name_is_never_kept`); the keyed path keeps them (QA xfail `test_qa_a_url_in_puzzle_history_coaching_is_never_kept`); short or other-TLD URLs pass (QA xfail `test_qa_strip_urls_removes_every_web_address[…]`) |
| **DW: search links are built only by the app** | unit + integration + e2e + QA | PASS | `test_open_lesson_builds_the_url_in_the_backend` (FakeBrowser), `test_a_lesson_click_sends_only_the_topic_and_target` (no `http` in the calls or page). QA `test_qa_lesson_targets_are_strict` (`curated:-1`, `curated: 0`, `CURATED:0`, `javascript:…`, non-string topics refused), `test_qa_search_links_stay_on_the_site_whatever_the_topic`, `test_qa_a_custom_search_site_must_be_https_with_a_host` |
| **DW: the Advanced estimate is blocked by the per-run cap and the budget** | integration + QA | PASS | `test_the_cap_and_the_budget_block_the_request`. QA `test_qa_advanced_is_blocked_by_the_cap_when_standard_still_fits` (cap set between the two estimates: standard ok, Advanced `over_cap`, start refused, no request) |
| **DW: a checkpoint never uses Advanced** | integration + QA + smoke | PASS (by design until v1.0) | `test_advanced_and_notes_are_never_remembered` (`start_run({"advanced":…})` refused, nothing in `last_params`). QA `test_qa_an_advanced_run_leaves_no_trace_in_settings`. QA smoke: after ticking both and relaunching, both are off and no settings row mentions them. No checkpoint code exists yet (v1.0) |
| FR-10.52 digests, stored and reused, no engine | integration + smoke | PASS | `test_digests_are_reused_and_need_no_engine`, `test_a_changed_analysis_rebuilds_its_digest`. QA smoke: `game_digests` row after a real Stockfish run |
| FR-10.53 measures in the free report | e2e + smoke | PASS (B4, B7) | `test_the_report_shows_whole_game_measures_with_the_guard`. QA smoke `coach-measures` with ≥ 3 *not enough data yet* badges |
| FR-10.54 open-ended diagnosis, G labels, 3–8 weaknesses | unit + integration | PASS (B6) | `test_the_prompt_is_anonymized` ("including but not limited to"), `test_at_most_eight_weaknesses`, `test_a_puzzle_history_report_keeps_the_keyed_prompt` |
| FR-10.55 citations open Review at that ply; text escaped | e2e + code | PASS | `test_a_standard_run_shows_the_diagnosis_with_evidence` (G1 chip, then Review at the position before 4.Nxe5, "← Coach"). No `dangerouslySetInnerHTML` or `innerHTML` in `web/src` |
| FR-10.56 Advanced: cap 10–50, newest games, comparison, minutes, 180 s timeout, every answer kept | integration + e2e + QA | PASS (B5) | `test_advanced_shows_the_comparison_before_confirm`, `test_the_run_picker_switches_answers`, `req.timeout_s == 180`. QA `test_qa_advanced_sends_only_the_cap_and_the_most_recent_games` (12 games, cap 10: exactly the 10 newest are sent, and all 12 digests), `test_qa_an_out_of_range_cap_is_never_sent`, `test_qa_unticking_advanced_drops_the_comparison`, `test_qa_the_same_options_show_the_saved_answer` |
| FR-10.57 tracked vs observation, recurring | unit + integration + QA | PASS (B3) | `test_keys_topics_and_categories_are_checked`, `test_an_observation_is_noted_once_per_report`. QA `test_qa_a_key_that_was_not_sent_makes_an_observation`; xfail `test_qa_an_observation_counts_each_report_once_in_any_order` |
| FR-10.58 time is flagged in Why this mix; the mix stays tactical | unit | PASS | `test_the_suggested_mix_stays_tactical_and_flags_time` |
| FR-10.59 Learn X drill at −200, curated, search sites, Settings → Coach | unit + e2e | PASS | `test_the_drill_is_200_below_your_band_and_a_valid_preset`, `test_settings_choose_the_search_sites`, `test_search_sites_follow_settings` |
| FR-10.60 notes: preview, scope, URLs stripped, own reports only | integration + e2e + smoke | PASS (B2) | `test_another_players_report_gets_coaching_without_their_name` (no notes for others). QA `test_qa_notes_need_a_report_with_games` |
| FR-8.16 game text only as listed | QA integration | PASS (B2) | see the Advanced row. Note: a note you type is sent as written, names included (see "For Adam") |
| FR-11.15 Retry: Explain only after you try | e2e + QA | PASS | `test_retry_offers_explain_after_you_try`. QA `test_qa_retry_explain_is_never_there_before_each_attempt` (screenshot) |
| FR-3.13 Update / Manage presets / Replace on a Coach clash | e2e + QA | PASS | three builder tests in `test_v011_ui.py`. QA `test_qa_overwriting_another_preset_keeps_your_filters_and_the_loaded_one` (overwrite another preset, rename the loaded one: filters unchanged, the menu follows the new name) |
| Migration 0009 (backfill, keys, observations) | integration | PASS | `test_migration_0009.py` (3 tests) |
| Docs: User Guide sections, privacy, CHANGELOG, ARCHITECTURE §7 | review + run | PASS (B6, B8) | see Docs findings |

---

## Bugs

### v0.11-B1 (major): URLs written by the LLM are shown
- **Requirement:** Done when "a URL written by the LLM is never shown"; FR-10.59 ("any link the app didn't build itself is dropped"); CLAUDE.md (LLM output is untrusted).
- **Steps:** have the AI answer a preset named `Forks: see https://evil.example/x`, or (puzzle-history report) a summary `Visit https://evil.example/x` with a weakness explanation `see www.evil.com`.
- **Expected:** the address is removed, as it is in the diagnosis's title, explanation, advice and summary.
- **Actual:** `validate_coach_preset` (`core/preset_suggestion.py:150`) keeps the name as written, and it's shown in the AI preset box and saved as a preset name. `core/coach_llm.validate` (the keyed format, still used for puzzle-history reports) strips nothing.
- **Evidence:** QA xfails `test_qa_a_url_in_an_ai_preset_name_is_never_kept`, `test_qa_a_url_in_puzzle_history_coaching_is_never_kept` (`tests/unit/test_qa_v011_core.py`).

### v0.11-B2 (major): `strip_urls` misses common web addresses and eats real words
- **Requirement:** FR-8.16 (no URLs to the LLM, ever), FR-10.60 (web addresses removed from notes before the preview and sending), Done when (LLM URL never shown).
- **Steps:** add a mistake-reason note `video: youtu.be/abc and bit.ly/y` on a move of a game in a report, tick **Include my notes**.
- **Expected:** both addresses replaced with `[link removed]` in the preview and the prompt.
- **Actual:** both are kept and sent. The regex in `core/coach_diagnosis.py` (`_URL`) only catches `http(s)://`, `www.` and bare `.com/.org/.net/.io` domains. Also kept: `chessable.co.uk/course/1`, `example.de/seite`, `ftp://files.example/x`. It also over-matches, because there's no word boundary after the TLD: `I played Qd1.Coming back` → `I played [link removed]ing back`, and `time.Commitment` loses a word.
- **Evidence:** QA xfails `test_qa_strip_urls_removes_every_web_address[5 cases]`, `test_qa_strip_urls_leaves_words_after_a_missing_space[2 cases]` (unit), `test_qa_short_links_in_notes_are_removed` (integration).

### v0.11-B5 (major): a double-click on Confirm sends and bills two AI runs
- **Requirement:** FR-8.11 (one Confirm, one estimated run); §9.3 spend guardrails.
- **Steps:** Coach report → **Get AI coaching** → double-click **Confirm**.
- **Expected:** one request.
- **Actual:** `CoachAiPanel.start` is called twice before the modal closes, and two `startCoachAi` calls go out (mock call log). In the backend, `start_ai` has no single-flight. Both jobs check the cache before either has stored an answer, and both send. With Advanced on (~$0.40 in the guide's example) this doubles the cost. v0.10's Coach box had the same pattern, and Explain my game probably does too (not tested).
- **Evidence:** QA xfails `test_qa_a_double_click_on_confirm_sends_one_request` (e2e: `['coachAi:1:standard:nonotes', 'coachAi:1:standard:nonotes']`), `test_qa_two_quick_starts_send_one_request` (integration: 2 requests to the fake provider).

### v0.11-B3 (minor): an observation is counted twice for the same report
- **Requirement:** FR-10.57 (noted when it recurs across runs). ARCHITECTURE §7: "`times_seen` counts reports, not runs".
- **Steps:** an observation is seen in report 1, then report 2, then report 1 is asked again (another option or model).
- **Expected:** seen in 2 reports. **Actual:** 3, because `ObservationsRepo.note` only compares with `last_report_id`.
- **Evidence:** QA xfail `test_qa_an_observation_counts_each_report_once_in_any_order`.

### v0.11-B4 (minor): mistakes per phase have no sample-size guard
- **Requirement:** Done when "the sample-size guard applies to every whole-game measure"; FR-10.53 (Phases and conversion).
- **Steps:** run the Coach on 1 game (real app: Send to Coach → Run).
- **Expected:** errors per phase marked *not enough data yet* below 5 games.
- **Actual:** "Mistakes per 10 games: opening 0, middlegame 0, endgame 30" with no badge. Conversion and saves on the same card do get it. `Measures.errors_per10_by_phase` has no `enough` flag. It never makes a weakness, so this is display only.
- **Evidence:** QA xfail `test_qa_errors_per_phase_are_guarded_below_five_games`; `tests/e2e/artifacts/qa-v011-real-notes-preview.png`.

### v0.11-B6 (minor): the diagnosis prompt drops the puzzles-vs-games table, and the privacy text doesn't match what's sent
- **Requirement:** FR-10.54 (input includes the FR-10.21 aggregates); CLAUDE.md (features that send data say exactly what).
- **Actual:**
  - `core/coach_diagnosis.build_prompt` copies v0.10's fields except `gap`, so a Games + Puzzles report no longer sends the puzzles-vs-games comparison. Puzzle-history-only reports still do.
  - The privacy section's v0.10 bullet still lists "the puzzles-vs-games table" for every report.
  - Its v0.11 bullet doesn't say that each key moment also carries its themes, Missed/Allowed kind, phase, and **your mistake-reason label** (`_moment_json`). Those are labels, not notes.
- **Evidence:** QA xfail `test_qa_the_diagnosis_still_sends_the_puzzles_vs_games_table`; `docs/USER_GUIDE.md` "Your data and privacy" → Get AI coaching.

### v0.11-B7 (minor): "1 games"
- `WholeGameMeasures.tsx:115`, `{e.games} games`. Seen in the real app: "Mixed endgames: 1 games, +0 =0 −0, 3 mistakes" (`qa-v011-real-coach-report.png`). v0.10-B6 fixed the same wording in Saved reports.

### v0.11-B8 (minor, docs): plan checklist item 8 not ticked
- `plans/v0.11.md` step 8 (lesson pointers) is `[ ]`, but `core/lessons.py`, `open_lesson` and the settings are built and tested. After a context reset the builder could redo it.

---

## Tests added (all in the working tree, uncommitted)
- `tests/unit/test_qa_v011_core.py` (36 passed, 11 xfailed): `test_qa_any_malformed_citation_is_dropped[12]`, `test_qa_duplicate_citations_count_once_for_tentative`, `test_qa_evidence_is_not_a_dict_of_weaknesses`, `test_qa_a_key_that_was_not_sent_makes_an_observation`, `test_qa_strip_urls_removes_every_web_address[5]` (xfail B2), `test_qa_strip_urls_keeps_chess_text`, `test_qa_a_url_in_an_ai_preset_name_is_never_kept` (xfail B1), `test_qa_a_url_in_puzzle_history_coaching_is_never_kept` (xfail B1), `test_qa_the_prompt_copies_only_allow_listed_report_fields`, `test_qa_a_standard_prompt_never_lists_a_whole_game`, `test_qa_conversion_with_four_games_makes_no_weakness_even_if_all_lost`, `test_qa_an_endgame_type_with_four_games_makes_no_weakness`, `test_qa_low_clock_needs_five_clocked_games`, `test_qa_low_clock_is_no_weakness_when_you_err_as_often_otherwise`, `test_qa_digest_for_black_held_and_castling`, `test_qa_every_curated_url_is_https_lichess_practice_or_learn`, `test_qa_unknown_topics_are_refused[6]`, `test_qa_search_links_stay_on_the_site_whatever_the_topic`, `test_qa_a_custom_search_site_must_be_https_with_a_host[5]`, `test_qa_errors_per_phase_are_guarded_below_five_games` (xfail B4), `test_qa_strip_urls_leaves_words_after_a_missing_space[2]` (xfail B2), `test_qa_the_diagnosis_still_sends_the_puzzles_vs_games_table` (xfail B6).
- `tests/integration/test_qa_v011_coach.py` (9 passed, 3 xfailed): `test_qa_twelve_games_all_get_a_digest_and_label`, `test_qa_no_header_name_date_url_rating_clock_or_comment_reaches_any_prompt`, `test_qa_advanced_sends_only_the_cap_and_the_most_recent_games`, `test_qa_advanced_is_blocked_by_the_cap_when_standard_still_fits`, `test_qa_an_advanced_run_leaves_no_trace_in_settings`, `test_qa_a_cited_ply_must_be_sent_for_that_game`, `test_qa_the_notes_preview_matches_what_is_sent_exactly`, `test_qa_short_links_in_notes_are_removed` (xfail B2), `test_qa_notes_need_a_report_with_games`, `test_qa_lesson_targets_are_strict`, `test_qa_an_observation_counts_each_report_once_in_any_order` (xfail B3), `test_qa_two_quick_starts_send_one_request` (xfail B5).
- `tests/e2e/test_qa_v011_ui.py` (6 passed, 1 xfailed): `test_qa_screens_for_the_visual_check`, `test_qa_an_out_of_range_cap_is_never_sent`, `test_qa_unticking_advanced_drops_the_comparison`, `test_qa_a_double_click_on_confirm_sends_one_request` (xfail B5), `test_qa_the_same_options_show_the_saved_answer`, `test_qa_overwriting_another_preset_keeps_your_filters_and_the_loaded_one`, `test_qa_retry_explain_is_never_there_before_each_attempt`.
- `tests/smoke/test_qa_v011_real_app.py` (1 passed): `test_qa_v011_whole_game_report_and_per_run_options`. Real Stockfish copied from the dev folder into a temp folder. Send to Coach → Run, measures with the guard, a digest row. Both options are ticked and the notes preview (URL removed) is shown. With no key the estimate is blocked and nothing is logged. After a relaunch both options are off and no settings row mentions them.

All xfails are `strict=True`, so each turns into a failure (XPASS) once its bug is fixed. Running them with `--runxfail` shows each fails on its own assertion, not on a setup error.

## Scope, architecture, security
- **Scope:** nothing from v0.12, v1.0 or v2.0 in the diff. The only match for checkpoint, journal or plan words is a docstring saying statuses come in v1.0. There's no `weaknesses` table, no checkpoint and no opening trainer.
- **Layers:**
  - The new `core/` modules (`digest`, `game_measures`, `coach_diagnosis`, `lessons`) do no I/O and no time or randomness calls.
  - Concrete repos are wired only in `app.py`. `webbrowser` is used only in `adapters/desktop.py`. No HTTP in the diff.
  - `keyring` is imported only in `secret_store`.
  - No `localStorage`, `sessionStorage`, IndexedDB, cookies or `innerHTML` in `web/src`.
  - `0009_whole_game.sql` is new, and no applied migration was edited.
  - New bridge methods use `@bridge_call`, and the allowlist test is updated and passing.
- **Dependencies:** none added. The `pyproject.toml`, `package.json` and lockfile diffs are the version bump only.
- **Secrets and fixtures:** no token or key patterns in the diff (only `…FAKE…` placeholders). Test and mock data use `player_a` / `opponent_b` / `example.org` / `evil.example`. The CDP port is set only by `tests/smoke/conftest.py`, and `app.py` refuses it without `--dev` (SR-16). The real-app runs used temp data folders (NFR-2).
- **Privacy:** checked on 12 fully-headed PGNs. No player name, date, Site URL, game ID, Elo, TimeControl, clock or comment reaches any prompt (standard, Advanced or notes). G labels map back to games only inside `coach_ai_runs.result_json` on the PC. URLs: B1, B2.

## Docs findings
- `check_docs.py --strict`: 0 errors, 0 warnings.
- **CHANGELOG `[Unreleased]`:** a line for each user-visible Done-when item: measures and guard, whole-game weaknesses, the diagnosis with evidence and tentative, Advanced, notes, kept answers, lessons, Retry Explain, preset management. There's also a *Changed* line on the larger estimate.
- **User Guide, followed against the mock (QA e2e) and the real app (QA smoke):**
  - *Whole-game measures*, *AI coaching*, *Advanced analysis*, *Include my notes*, *Lesson pointers*, *Presets* (Update, Manage) and *Retry* (Explain after you try): labels, defaults and step order match.
  - The screenshots `coach-measures`, `coach-ai-diagnosis`, `coach-ai-advanced` and `coach-notes-preview` match the screens.
  - Two wording points: the guide says **Learn <topic>:**, and the UI shows "Learn Fork:", which is consistent. The guide also names **Search my site**, and the Settings checkbox is "My own site", which is fine.
- **Privacy section:** standard, Advanced, notes and lesson-link searches are each described. Gaps: B6.
- **ARCHITECTURE §2 and §7:** the four new modules are listed. There are entries for the 0009 schema, the diagnosis and options, lessons and `open_lesson`, and the mid-build requests.
- **README:** status says v0.11 is being built (to update at the rc).
- **Plan:** B8.

## Visual check
Screenshots in `tests/e2e/artifacts/`:
- From the mock: `qa-v011-measures`, `qa-v011-advanced-confirm`, `qa-v011-diagnosis`, `qa-v011-notes-preview`, `qa-v011-ai-box-narrow` (900 px), `qa-v011-settings-coach`, `qa-v011-preset-manager`, `qa-v011-retry-explain`.
- From the real app: `qa-v011-real-notes-preview`, `qa-v011-real-coach-report`.

No clipped text or broken layout. The badges wrap cleanly at 900 px. The real-app full-page shot caught the notes modal mid-fade, which is a capture artifact. Only issue: "1 games" (B7).

## Observations (not bugs; for the builder or Adam to decide)
- **chess.com opening families fragment.** chess.com openings come from the ECOUrl slug, which has no `:` (e.g. `Italian Game Two Knights Defense`). So the FR-10.53 family rule gives the full variation, and chess.com openings will rarely reach 5 games.
- **A pasted PGN's `[Opening]` header** is sent as the digest's opening name and used as a search term, unfiltered and unlimited in length. Lichess and chess.com imports are fine.
- **Notes are sent as written**, so an opponent's name you typed in a note goes to the AI. The preview shows it, and v0.12 (FR-10.71) adds a warning.
- **`habit:castledLate`** can come from a single late-castling game once 5 games reach move 12. The king group is guarded, the late subgroup isn't.
- **Trades while ahead or behind** count a recapture on the next ply only. The plan said "within 2 plies".
- **"Send to Coach" reports:** Advanced's "most recent games" follows the order of the selection, not the dates.
- **The first diagnosis run after a v0.10 (keyed) answer** marks every finding *New in this run*, because keyed answers aren't compared.

## For Adam's manual test
- **Lesson links:** open a few curated Lichess Practice pages and the YouTube and chess.com searches (no network here, so their liveness is unchecked). Also check a custom site.
- **Real LLM runs:** standard, then Advanced on 30 games. Compare the cost with the estimate and the "N×" ratio. Check that the citations open the right moves, and that the minutes estimate is plausible with your model.
- **Include my notes** on your real notes: check the preview, especially any short links (B2).
- **Double-click Confirm** only after B5 is fixed.

---

# Round 2 (2026-11-05): re-verification of B1–B8

Branch `v0.11` at `f860532`. I changed no product code, migrations, config or docs. I added tests under `tests/` only, and committed nothing. `-m live` was not run.

## Verdict: **FAIL** (1 major, 1 minor; both new, both in `core/urls.strip_urls`)

B3–B8 are fixed and held up when I tried to break them. B1 is fixed for every text field the AI writes. **B2 is only partly fixed.** The new `strip_urls` matches bare domains against a fixed list of about 50 top-level domains, so:
- **B9 (major):** any address on a TLD outside the list is still kept, even with a path (`chess.academy/course`, `mychess.blog/post`, `chess.club/join`, `example.live/x`, `example.kr/x`, `192.168.0.1/admin`). These addresses are sent from **Include my notes** and shown from AI text.
- **B10 (minor):** a missing space before a two-letter word that is also a TLD turns ordinary text into `[link removed]`. For example, `Nf3.To be safe` becomes `[link removed] be safe`.

Every automated suite is green.

## Re-verification

| Bug | Result | Evidence |
|---|---|---|
| B1 URL in AI preset names / keyed coaching | **Fixed** | builder regressions pass. QA r2 `test_qa_r2_a_url_in_every_shown_diagnosis_field_is_removed` (title, explanation, advice, summary), `test_qa_r2_a_url_only_preset_name_still_has_a_name` (a name that is only a URL becomes `[link removed]` and is never empty) |
| B2 strip_urls misses / over-matches | **Partly fixed: B9, B10** | All round-1 shapes are caught (`youtu.be`, `bit.ly`, `.co.uk`, `.de`, `ftp://`), and so are `hxxp://`, upper case, `t.me`, `discord.gg`, `amzn.to`, punycode, and sub-domains with `?` and `#` (`test_qa_r2_strip_urls_catches_other_shapes[12]`). Well-spaced chess text is left alone, including full SAN lines, `O-O-O.`, `e.g.`/`i.e.`, `Q.E.D.` and `23.Rxe5` (`test_qa_r2_strip_urls_keeps_well_spaced_chess_text[11]`). Misses: B9. Over-match: B10 |
| B3 observation counted twice (A, B, A) | **Fixed** | `test_qa_an_observation_counts_each_report_once_in_any_order`. QA r2 `test_qa_r2_migration_0010_backfills_every_shape`: on a real v9 DB (migrations 0001–0009), rows with no report, first = last, and first ≠ last in either order backfill to `[]`, `[4]`, `[1,2]`, `[2,1]`; `schema_version` is 10; later `note()` calls count distinct reports; re-running `migrate` is a no-op |
| B4 mistakes per phase unguarded | **Fixed** | QA r2 `test_qa_r2_errors_per_phase_guard_boundary` (4 games: False, 5 games: True). Real app (QA smoke, extended): one game gives `phases_enough: false`, and the Phases card shows its *not enough data yet* badge (3 badges on the card: phases, conversion, saves) |
| B5 double Confirm bills twice | **Fixed** | Backend (QA r2, with a provider held open so the first run is still going): `…starts_from_many_threads_send_one_request` (8 threads: 1 job, 1 request); `…same_options_written_differently_join_the_run` (`None`, `{advanced: false, …}` and an explicit default cap: same job); `…other_options_while_one_is_going_are_their_own_run` (standard + notes: 2 runs, as designed); `…after_a_run_ends_the_same_options_reuse_it_or_retry` (after a failed run a retry is sent; after a done run the saved answer is used and nothing is sent). UI (e2e r2): `test_qa_r2_after_a_run_the_next_one_can_start_and_a_double_click_still_sends_one`: the guard is released once the job ends, and a second double-clicked run (Advanced) sends exactly one more request (2 in total) |
| B6 gap table dropped; privacy text | **Fixed** | builder regression passes. QA r2 `test_qa_r2_the_gap_table_sends_only_its_columns_and_at_most_ten_rows` (14 rows with extra `puzzle_ids`, `games` and `url` fields, plus non-dict rows: only the 5 columns go, at most 10 rows). The User Guide privacy bullet now lists Missed/Allowed, themes, the reason label and the gap table |
| B7 "1 games" | **Fixed** | QA smoke (real app): the measures read "From 1 game," and never "1 games" |
| B8 plan tick | **Fixed** | `plans/v0.11.md` item 8 is `[x]` |

## New bugs

### v0.11-B9 (major): `strip_urls` keeps any address whose top-level domain isn't on its list
- **Requirement:** FR-8.16 (no URLs to the LLM), FR-10.60 (web addresses removed from notes before the preview and before sending), the Done-when item "a URL written by the LLM is never shown", and the User Guide ("Web addresses in your notes … are removed").
- **Steps:** add a mistake-reason note `course: chess.academy/rook-endings` on one of your moves in a report's game, tick **Include my notes**, then Confirm. Or have the AI write advice `Study the course at chess.academy/endgames`.
- **Expected:** `[link removed]` in the preview, in the prompt and on screen.
- **Actual:** the address is sent, and it's shown. `core/urls.py` only matches a bare domain if its TLD is in `TLDS`. Also kept: `.blog`, `.club`, `.live`, `.academy`, `.kr`, `.nz`, `.example`, and IPv4 hosts with a path. A rule that treats any `host.tld/…` (a dotted host followed by `/`) as an address, whatever the TLD, would catch all of these. The TLD list would still be needed for bare domains without a path.
- **Evidence:** strict xfails `test_qa_r2_strip_urls_removes_any_host_with_a_path[8]`, `test_qa_r2_an_llm_url_on_another_tld_is_never_shown` (unit), and `test_qa_r2_a_note_with_an_address_on_another_tld_is_not_sent` (integration: the address appears in the fake provider's request). Each fails on its own assertion with `--runxfail`.

### v0.11-B10 (minor): a missing space before a two-letter word is removed as a link
- **Requirement:** FR-10.60 (the notes are sent as written, minus web addresses). `core/urls.py`'s docstring claims "missing spaces … are left alone".
- **Steps:** add the note `Blundered.No time left` (or `Nf3.To be safe`, `Castled O-O.It was late`, `Played e4.At move 3`, `Kh1.Am I safe`, `Lost.Be careful`), then tick **Include my notes**.
- **Expected:** the note unchanged. **Actual:** `[link removed] time left`, `[link removed] be safe`, and so on. `no`, `to`, `it`, `at`, `am`, `be`, `me`, `us` and `in` are all in `TLDS`. The preview shows the damage, so nothing is hidden; the AI just loses the words. AI text with normal spacing isn't affected.
- **Evidence:** strict xfail `test_qa_r2_strip_urls_leaves_two_letter_words_after_a_missing_space[6]`.

## Evidence: commands run (Git Bash; `npm.cmd` as written)

| Command | Result |
|---|---|
| `uv run pytest` | **1914 passed, 1 skipped, 16 xfailed** (326 s), rc 0. The 16 xfails are the round-2 B9 and B10 tests |
| `uv run pytest -m e2e` | **312 passed** (733 s), rc 0, including the QA r2 e2e test |
| `npm.cmd --prefix web run build`, then `uv run pytest -m smoke` | build rc 0. **35 passed, 1 skipped, 1 failed**: the failure was my own new assertion (I expected 1 badge on the Phases card, and it has 3: phases, conversion, saves). After I corrected the test, `test_qa_v011_real_app.py` passed on its own (20 s). No product failure |
| `uv run pytest -m engine` | **19 passed** (71 s) |
| `uv run pytest -m fulldb` | dev `puzzles.db` imported: **73 passed, 3 xfailed** (557 s) |
| `uv run ruff check .` / `uv run ruff format --check .` | All checks passed / 394 files already formatted |
| `uv run mypy src` | Success: no issues found in 124 source files |
| `npm.cmd --prefix web run typecheck` / `npm.cmd --prefix web run lint` | rc 0 / rc 0 |
| `uv run pre-commit run --all-files` | Detect hardcoded secrets Passed; keyring only in secret_store.py Passed |
| `python scripts/check_docs.py` / `--strict` | `check_docs: 0 error(s), 0 warning(s) [version v0.11]`, both rc 0 |
| `uv run python scripts/gen_types.py` | `web/src` unchanged (the `phases_enough` field in `types.ts` matches `dto.py`) |
| `uv run python scripts/make_icon.py --check` | icon is up to date |
| Other Developer Guide rows | unchanged since round 1 (no command, path or workflow changed in `f860532`). Not re-run: setup, the fetch scripts, and the live and credential rows (same reasons as round 1) |

## Regression check (Done-when list)
The builder's v0.11 tests and the round-1 QA tests all pass:
- digests, the measures and their guard
- the standard prompt has no move lists
- Advanced: SAN only, the cap, the newest games, blocked by the cap and the budget
- notes go only when ticked, and the preview matches what's sent
- invented labels and plies are dropped, and fewer than 3 games is tentative
- curated links are on the allowlist, and links are built by the backend
- nothing is remembered between runs
- Retry offers Explain only after you try
- preset management

Because of B9, the item "a URL written by the LLM is never shown" is still **not met**.

## Scope, architecture, security (fix commit)
- Only one new migration (`0010_observation_reports.sql`); no applied migration was edited. No dependency or lockfile changes.
- `core/urls.py` is pure (regex only). `services/coach.py` adds a `threading.Lock` around job bookkeeping only; no SQLite connection is shared. No `datetime.now`, `time.time` or `random`.
- No `localStorage`, `sessionStorage`, IndexedDB, cookies or `innerHTML` in `web/src`.
- New QA fixtures use only `evil.example`, `example.*`, `QaPzl01` and `123456789` placeholders. No token patterns.

## Observations (not bugs)
- **The 0010 backfill can lower `times_seen`:** a v9 row with `times_seen = 3` keeps only `[first, last]`, so the next `note()` for the last report returns 2 (scratch run). Only DBs that ran a dev build with 0009 have such rows, because 0009 and 0010 both ship in v0.11. In practice that means Adam's dev `user.db`.
- **The single-flight key** includes `game_cap` even when Advanced is off, so two standard starts with different caps would both send. The UI can't do this (the button is disabled while a run is going), and the builder may decide it isn't worth changing.
- **The same double-click pattern outside v0.11 (code reading, not executed):** `GameAiPanel` (Explain my game's Confirm, Explain this move) and `ExplainPanel` have no click guard, and those backends have no single-flight. These are v0.7/v0.9 features, so it isn't a v0.11 regression. Adam can decide whether to carry the B5 fix over.

## Tests added in round 2 (uncommitted)
- `tests/unit/test_qa_v011_core.py`: `test_qa_r2_strip_urls_catches_other_shapes[12]`, `test_qa_r2_strip_urls_keeps_well_spaced_chess_text[11]`, `test_qa_r2_strip_urls_removes_any_host_with_a_path[8]` (xfail B9), `test_qa_r2_an_llm_url_on_another_tld_is_never_shown` (xfail B9), `test_qa_r2_strip_urls_leaves_two_letter_words_after_a_missing_space[6]` (xfail B10), `test_qa_r2_a_url_only_preset_name_still_has_a_name`, `test_qa_r2_a_url_in_every_shown_diagnosis_field_is_removed`, `test_qa_r2_errors_per_phase_guard_boundary[2]`, `test_qa_r2_the_gap_table_sends_only_its_columns_and_at_most_ten_rows`.
- `tests/integration/test_qa_v011_coach.py`: `test_qa_r2_starts_from_many_threads_send_one_request`, `test_qa_r2_the_same_options_written_differently_join_the_run`, `test_qa_r2_other_options_while_one_is_going_are_their_own_run`, `test_qa_r2_after_a_run_ends_the_same_options_reuse_it_or_retry`, `test_qa_r2_migration_0010_backfills_every_shape`, `test_qa_r2_a_note_with_an_address_on_another_tld_is_not_sent` (xfail B9).
- `tests/e2e/test_qa_v011_ui.py`: `test_qa_r2_after_a_run_the_next_one_can_start_and_a_double_click_still_sends_one`.
- `tests/smoke/test_qa_v011_real_app.py`: extended with the B4 badge and B7 wording checks in the real window.

## For Adam's manual test (in addition to round 1)
- Once B9 is fixed: put a note with a short link on an unusual TLD (for example `.blog` or `.club`) and check the notes preview.
- Double-click **Confirm** with a real key and a low cap: check that only one `llm_usage` row is added.

# Round 3 (2026-11-05): re-verification of B9 and B10

Branch `v0.11` at `b47c240`. I changed no product code, migrations, config or docs. I added tests under `tests/` only and committed nothing. I didn't run `-m live`.

## Verdict: **PASS WITH ISSUES** (4 new minor bugs, all in `core/urls.strip_urls`; no blocker or major)

B9 and B10 are fixed as specified, and every automated suite is green. My attempts to break the new patterns found four minor problems:
- **B11:** a capitalized ending outside `WORDS`, such as `Today`, `Live`, `Page`, `Net`, `Club`, `Online` or `Link`, still turns a missing space into a link.
- **B12:** the new "host with a path" rule turns a missing space followed by `?`, `/` or `#` into a link. It removes a SAN move along with the word: `Played Nf3.Why?` becomes `Played [link removed]`.
- **B13:** hosts with non-ASCII letters or an underscore, and `host:port` with no path, are kept.
- **B14:** the regex is quadratic on long runs of dotted labels.

Chess text with normal spacing is never affected.

## Re-verification

| Bug | Result | Evidence |
|---|---|---|
| B9 any host with a path / IPv4 | **Fixed** | Round-2 regressions pass with no markers: `test_qa_r2_strip_urls_removes_any_host_with_a_path[8]`, `test_qa_r2_an_llm_url_on_another_tld_is_never_shown`, integration `test_qa_r2_a_note_with_an_address_on_another_tld_is_not_sent`. Also caught in round 3: `?query`, `#frag`, `:8080/x`, `10.0.0.1:8080/x`, bare `192.168.0.1`, deep sub-domains, trailing `/`, `EVIL.CO.UK`, `LICHESS.ORG`, `//host/x`, punycode with a path, and `HTTPS://X.Y`. Test: `test_qa_r3_strip_urls_catches_more_shapes[13]` |
| B10 missing space before a two-letter word | **Fixed** for the 16 `WORDS` | `test_qa_r2_strip_urls_leaves_two_letter_words_after_a_missing_space[6]` passes. Also kept: `bad.It is`, `Nf3.To be safe`. Still broken: other capitalized endings (B11) |

Chess text that survives (`test_qa_r3_strip_urls_keeps_chess_text[19]`): `1.e4 e5 2.Nf3`, `12.Rd1/Rd2`, `1.d4/1.c4`, `1.30`, `+1.5`, `O-O-O.`, `O-O.`, `e8=Q+.`, `23.Qxh7#`, `2.Nf3?! … 3.Bc4#`, `Rd1.Be2`, `e4.Bc4?`, `e4.Na3/Nc3?`, `Rxd8+.Kxd8 Qd1/`, `1.5/2`, `2026.11.05`, `v1.2.3`. `e.g.` and `i.e.` were already covered in round 2. SAN after a dot survives because a piece move ends in a digit, and the path rule needs letters right before `/?#`.

## New bugs

### v0.11-B11 (minor): a capitalized TLD that is an ordinary word still breaks a missing-space sentence
- **Requirement:** FR-10.60 (notes are sent as written, minus web addresses). This is the B10 class: the fix lowered the case only for the 16 entries in `WORDS`.
- **Steps:** add the note `This was a blunder.Today I learned`, tick **Include my notes**, and look at the preview.
- **Expected:** the note unchanged. **Actual:** `This was a [link removed] I learned`. These do the same: `time.Live`, `Endgame.Page`, `exchange.Net`, `club.Club`, `Then.Online`, `Rook.Link`. Also `Site`, `App`, `Info`, `Tech`, `Shop`, `Ai` and `Dev` (probe). In lower case the 16 `WORDS` still match, as designed (`blundered.it was bad` gives `[link removed] was bad`). Adam may want to reconsider that too.
- **Evidence:** strict xfail `test_qa_r3_strip_urls_leaves_capitalized_tld_words_after_a_missing_space[7]`.

### v0.11-B12 (minor): a missing space followed by `?`, `/` or `#` is removed as a link, move included
- **Requirement:** FR-10.60. ARCHITECTURE.md §7 (round-2 entry) says a missing space "isn't taken for a link".
- **Cause:** the B9 rule `(?:label\.)+[a-z]{2,24}[/?#]\S*` accepts any word as a TLD, in any case.
- **Steps:** add the note `Played Nf3.Why?`, then tick **Include my notes**.
- **Expected:** unchanged. **Actual:** `Played [link removed]`. Other examples:
  - `I castled.Why?` gives `I [link removed]`
  - `Ng5.Black/White to move` gives `[link removed] to move`
  - `Good trade.Knight/bishop` gives `Good [link removed] imbalance`
  - `Bad move.Really?!`
  - `e8=Q.Why?` gives `e8=[link removed]`
- **Note:** this affects the AI's text as well (its missing spaces), but well-spaced text is unaffected.
- **Evidence:** strict xfail `test_qa_r3_strip_urls_leaves_a_missing_space_before_a_question_or_slash[6]`.

### v0.11-B13 (minor): an address on an internationalized or underscore host, or `host:port` without a path, is kept
- **Requirement:** FR-8.16, FR-10.59 ("never a URL"), FR-10.60.
- **Cause:** labels are ASCII `[a-z0-9-]` and must start at `\b`.
  - In `café.example/menu`, `é` is a word character, so no match can start inside the host.
  - In `my_site.example/x`, `_` blocks the label.
  - `evil.example:8080` has no path, and `.example` isn't on the TLD list.
  - `localhost:8080/x` is also kept (no dot).
- **Steps:** add the note `see café.example/menu`, then tick **Include my notes**.
- **Expected:** `[link removed]`. **Actual:** sent unchanged. Also kept: `lichéss.org/x`, `пример.рф/x`, `my_site.example/x`, `evil.example:8080`. These are rare shapes, so I rate this minor rather than major like B9. AI text is rendered escaped and never as a link.
- **Evidence:** strict xfail `test_qa_r3_strip_urls_removes_idn_underscore_and_port_hosts[5]`.

### v0.11-B14 (minor): `strip_urls` is quadratic on a long run of dotted labels
- **Requirement:** NFR responsiveness. LLM output is untrusted (CLAUDE.md).
- **Cause:** `(?:label\.)+` is retried from every label start when no ending follows.
- **Where it applies:** `core/coach_diagnosis._text` and `core/coach_llm._text` filter each AI field **whole, before** clipping it, and Coach output can reach 5000 tokens, or ×4 at High reasoning. Notes are capped at 200 characters, so they aren't affected.
- **Steps:** `strip_urls("a." * N + "1")`.
- **Measured:**

  | Input | Time |
  |---|---|
  | `"a."` repeated, 1 KB | 0.08 s |
  | `"a."` repeated, 2 KB | 0.32 s |
  | `"a."` repeated, 4 KB | 1.3 s |
  | `"a."` repeated, 20 KB | 31.7 s |
  | `"Nf3."` repeated, 20 KB | 10.2 s |
- **Expected:** linear time (a few ms).
- **Evidence:** strict xfail `test_qa_r3_strip_urls_is_fast_on_a_long_run_of_dotted_labels` (4 KB must take under 0.25 s; it takes about 5 s while the suite is running).

## Evidence: commands run (Git Bash; `npm.cmd` as written)

| Command | Result |
|---|---|
| `uv run pytest` | **1962 passed, 1 skipped, 18 xfailed** (363 s), rc 0. The 18 xfails are B11–B13; B14's test was added after this run started |
| `uv run pytest tests/unit/test_qa_v011_core.py tests/integration/test_qa_v011_coach.py` | 140 passed, 19 xfailed (B11–B14). With `--runxfail -k r3`, each of the 19 fails on its own assertion |
| `uv run pytest -m e2e` | **312 passed** (778 s), rc 0 |
| `npm.cmd --prefix web run build`, then `uv run pytest -m smoke` | build rc 0. **36 passed, 1 skipped** (512 s), rc 0 |
| `uv run ruff check .` / `uv run ruff format --check .` | All checks passed / 394 files already formatted |
| `uv run mypy src` | Success: no issues found in 124 source files |
| `npm.cmd --prefix web run typecheck` / `npm.cmd --prefix web run lint` | rc 0 / rc 0 |
| `uv run pre-commit run --all-files` | Detect hardcoded secrets Passed; keyring only in secret_store.py Passed |
| `python scripts/check_docs.py` / `--strict` | `check_docs: 0 error(s), 0 warning(s) [version v0.11]`, both rc 0 |
| `uv run python scripts/gen_types.py` | no drift |
| Not re-run | `-m engine`, `-m fulldb`: the fix commit only changes `core/urls.py`, which neither suite touches (both green in round 2). Setup, fetch, live and credential rows: same reasons as round 1 |

## Regression check
- `b47c240` changes only `src/weaksquare/core/urls.py` in product code. The test edits only remove the xfail markers; no assertion was weakened.
- The other edits are an ARCHITECTURE.md §7 note, a `plans/v0.11.md` note, and two regenerated screenshots. I viewed `coach-report.png`: the layout is correct, nothing is clipped, and it is the same as round 2.
- All builder and QA round 1/2 tests for the v0.11 Done-when items pass in the runs above.
- **Done-when status:** the item "a URL written by the LLM is never shown" now holds for every common shape. B13's rare shapes are the remaining gap.

## Scope, architecture, security (fix commit)
- No migration, dependency or lockfile change.
- `core/urls.py` is still pure (regex only).
- New fixtures use only `evil.example`, `example`, private IPs and made-up words. No token patterns. pre-commit's secret scan passes.

## Docs
- The User Guide (line 874) lists the address shapes as examples only, so it's still accurate.
- The `core/urls.py` docstring and the ARCHITECTURE.md round-2 note claim more than the code does: a missing space before a capitalized word that is also a TLD (B11) or before `?`/`/` (B12) is still taken for a link. Update them when B11/B12 are fixed.

## Tests added in round 3 (uncommitted)
- `tests/unit/test_qa_v011_core.py`:
  - `test_qa_r3_strip_urls_catches_more_shapes[13]`
  - `test_qa_r3_strip_urls_keeps_chess_text[19]`
  - `test_qa_r3_strip_urls_leaves_capitalized_tld_words_after_a_missing_space[7]` (xfail B11)
  - `test_qa_r3_strip_urls_leaves_a_missing_space_before_a_question_or_slash[6]` (xfail B12)
  - `test_qa_r3_strip_urls_removes_idn_underscore_and_port_hosts[5]` (xfail B13)
  - `test_qa_r3_strip_urls_is_fast_on_a_long_run_of_dotted_labels` (xfail B14)

## For Adam's manual test (in addition to rounds 1 and 2)
- Put a note `course: mychess.blog/rook-endings` on one of your moves and tick **Include my notes**: the preview should show `[link removed]` (B9).
- Put a note `Blundered.No time` and check that it's unchanged (B10). Then try `Played Nf3.Why?` to see B12 for yourself, and decide whether B11–B14 must be fixed before `v0.11-rc1`.
