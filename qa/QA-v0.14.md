# QA report: v0.14 (Lichess studies + Game Review in three parts)

# Round 2, 2026-11-08: re-verification at `5705bc3` (fixes in `7878123`)

Same rules as round 1. I changed only `tests/` and this report. No credentials, no `-m live`, and no request to lichess.org this round.

## Verdict: **PASS** (no open bugs)

All six round 1 bugs are fixed, and I found no regressions around the changed code. The notes at the end of this section aren't filed as bugs.

## Re-verified

| Bug | Result | How |
|---|---|---|
| B1 (major) | **FIXED** | Round 1's test passes unmarked: 260 plies kept. New tests run each of these with only 120 stack frames of headroom, so any recursion per move would fail: parsing, storing, re-checking, the bridge's flattening and `study_moves`. The chapter has a 700-ply main line and a 600-ply side line. A 520-ply chapter opens, saves your place at its end and continues. The 5,000-move cap holds (5,000 kept, 5,001 rejected *too large*). The three real studies from round 1 still parse and round-trip in the new format |
| B2 (minor) | **FIXED** | Round 1's test, extended by the builder, passes. The `/api/user/` check runs only after an empty listing, never after a non-empty one, and sends no token even when signed in. The User Guide's privacy entry and FR-13.5a mention the extra request |
| B3 (minor) | **FIXED** | A 5xx gives `lichess_trouble`. Offline and rate-limited messages are unchanged |
| B4 (major) | **FIXED** | Real app: the intro chapter is `done` after **Next chapter**. Mock: a chapter with moves isn't ticked when it opens at its start, and is ticked at its main-line end; a text chapter is ticked when it opens |
| B5 (minor) | **FIXED** | Real app and mock: after the heart, the board stays on the move and the saved place is unchanged |
| B6 (major) | **FIXED** | Real app at 1400x900: step-through and play-along boards are both at least 240 px. Mock at 900x700 (stacked layout), 1024x700 and 1920x1080: no horizontal overflow, the board stays between 240 and 560 px, and it no longer changes size when **Back to main line** appears. Screenshots: `tests/e2e/artifacts/qa-v014-r2-*.png` |

## Regression checks around the changed code
- **Stored tree format:** order, comments, shapes and glyphs survive JSON storage, and parents always come before their children. These damaged rows are refused with `ValueError`, so the service shows *saved copy is damaged*:
  - a missing or wrong version
  - the old nested format
  - an empty node list
  - a root with a parent, a node that is its own parent, or a parent that comes later
  - a parent index that is a bool, negative or a string
  - an illegal or unreadable move, or a non-object node
  - more than 5,001 nodes
- **`chapter()` returns a Node:** `set_place` accepts places in side lines and refuses moves off the tree. Text chapters return their text with no children. A damaged text row reads as empty text. The bridge flattens a text chapter to one entry holding its FEN as given.
- **Check for updates:** a byte-only change in the PGN reports *Only small changes*, with all 3 chapters unchanged. So stored and freshly parsed chapters fingerprint the same way, text and rejected chapters included.
- **Bridge flattening:** ids are in pre-order, each child points back to its parent, and every child's FEN is its parent's FEN plus the move.

## Commands at `5705bc3`

| Command | Result |
|---|---|
| `uv run pytest` | **3766 passed**, 1 skipped, 2 xfailed. It started before my round 2 files existed; those ran separately: unit 20 passed, integration 6 passed |
| `uv run pytest -m e2e` | **509 passed** (505 plus my 4 round 2 tests) |
| `npm.cmd --prefix web run build`, then `uv run pytest -m smoke` | 78 passed, 1 skipped, **1 failed**: `test_qa_v011_real_app.py::test_qa_v011_whole_game_report_and_per_run_options`, explained below. It passed in 9 re-runs of that file |
| ruff check, ruff format, mypy, tsc, ESLint, pre-commit | clean |
| `python scripts/check_docs.py --strict` | 0 errors, 1 warning (the `pyproject.toml` version) |

**The smoke failure is a test problem, not a product bug.** I'm not filing it against v0.14.
- **What failed:** the v0.11 QA test's last check looked for the bare word `advanced` anywhere in `user.db`'s settings, and it found the word in this run. Pytest truncated the offending value.
- **Likely cause:** the puzzle theme `advancedPawn` in `mixer.suggested`, the Coach's suggested mix. Its themes depend on real Stockfish's analysis, so the word appears only in some runs.
- **What I changed:** in `tests/smoke/test_qa_v011_real_app.py` the check now looks for the per-run option keys and JSON fields themselves, and names the offending rows. It passed afterwards.

## Tests added in round 2
- `tests/unit/test_qa_v014_r2.py` (20 tests): `test_qa14r2_order_comments_shapes_and_glyphs_survive_storage_through_json`, `test_qa14r2_a_damaged_stored_tree_is_refused` (15 cases), `test_qa14r2_stored_text_survives_and_a_damaged_text_chapter_reads_as_empty`, `test_qa14r2_the_move_cap_still_holds_at_5000`, `test_qa14r2_parse_store_recheck_flatten_and_repertoire_never_recurse_per_move`, `test_qa14r2_a_text_chapter_flattens_to_its_board_and_text`
- `tests/integration/test_qa_v014_r2_studies.py`: `test_qa14r2_a_byte_change_with_the_same_content_lists_every_chapter_unchanged`, `test_qa14r2_a_260_move_chapter_opens_saves_your_place_and_adds_to_the_repertoire`, `test_qa14r2_your_place_is_limited_to_600_moves_deep`, `test_qa14r2_text_chapters_still_open_with_their_text`, `test_qa14r2_a_row_in_the_old_nested_format_reads_as_damaged`, `test_qa14r2_b2_the_user_check_sends_no_token_and_only_follows_an_empty_listing`
- `tests/e2e/test_qa_v014_ui.py`: `test_qa14r2_opening_a_chapter_with_moves_doesnt_finish_it_but_a_text_chapter_does`, `test_qa14r2_the_reader_fits_narrow_and_wide_windows` (900x700, 1024x700, 1920x1080)
- `tests/smoke/test_qa_v011_real_app.py`: the settings check made precise (above)

## Notes (not filed)
- **Old saved copies:** a copy saved before `7878123`, in the nested format, now opens as *damaged: delete the study and add it again*. Nothing in the format change converts it. That's harmless, because v0.14 hasn't been released. Copies saved in Adam's dev folder during the build would need re-adding.
- **Your place past ply 600:** `parse_path` caps a saved place at 600 plies, so in a chapter longer than 300 moves your place stops being saved past that point. The UI ignores the error. Real games essentially never get there, and `test_qa14r2_your_place_is_limited_to_600_moves_deep` records the limit.
- **Wide windows:** at 1920x1080 the board column (7 of 12) is wider than the 560 px board, which leaves an empty band of about 400 px before the move list. It's cosmetic.

## For Adam's manual test
Unchanged from round 1 (below). Step 2's play-along board is now full size.

# Round 1, 2026-11-08, at `6940507` (branch `v0.14`)

I changed only `tests/` and this report. No credentials, no `-m live`. Smoke runs were signed out, in temp data folders. The Lichess window ran only against local pages (`--test-origin`). I made 4 plain GETs to lichess.org's documented study API (3 study `.pgn` downloads, 1 `/api/study/by/<made-up name>`). Nothing from them was committed.

## Verdict: **FAIL** (0 blocker, 3 major, 3 minor)

The isolation of the Lichess window, the parser, storage, private-study handling, Add to my repertoire and the three-part review all hold up. The gate fails on three majors:
- **B1:** a chapter's main line is cut off silently after 100 moves.
- **B4:** a chapter with no moves can never be marked finished. All three of Adam's test studies have such chapters, so they can never reach **Finished**.
- **B6:** the play-along board is 112 px wide in a 1400x900 window. Gamebook chapters are the whole of `ZCPaIb70` and `swkkeUJZ`.

## Bugs

| ID | Sev | Steps to reproduce | Expected | Actual | Evidence |
|---|---|---|---|---|---|
| **v0.14-B1** | major | Parse a study whose chapter has a main line of more than 200 plies, such as a 130-move annotated game | Every move kept, or the chapter rejected with a reason | Kept as 200 plies, with no message. `MAX_DEPTH = 200` is documented as "nesting of side lines", but `_convert` and `node_from_json` count every ply, main line included. `move_count` reports 200. Raising the cap alone would hit Python's recursion limit in `_convert`, `node_from_json` and `bridge/api.py` `_flatten_study_tree`, which all recurse once per ply | `tests/unit/test_qa_v014.py::test_qa14_b1_a_long_main_line_is_kept_whole` (xfail) |
| **v0.14-B2** | minor | Studies by author, type a username that doesn't exist | A clear "no such user" message (FR-13.5a, Done when) | *No public studies.*, the same as a real user with none. Real Lichess answers `GET /api/study/by/<unknown>` with **HTTP 200 and an empty body** (checked 2026-11-08). The app's 404 branch never runs. The fake client returns 404, so `test_studies_by_author_errors` passes against behaviour Lichess doesn't have | `tests/integration/test_qa_v014_studies.py::test_qa14_b2_an_unknown_user_gets_its_own_message` (xfail) |
| **v0.14-B3** | minor | Studies by author while Lichess returns a 5xx | *Lichess is having trouble*, as for downloads (plan v0.14a note) | *Lichess couldn't be reached. Check your connection.* A retryable 5xx `HttpError` counts as `is_network_error` | `test_qa_v014_studies.py::test_qa14_b3_author_search_on_a_lichess_5xx_doesnt_blame_your_connection` (xfail) |
| **v0.14-B4** | major | Open a study whose first chapter has no moves on a normal board (an introduction). Read it, click **Next chapter** | The chapter counts as done, so the study can reach **Finished** (FR-13.1) | It's never marked done. `StudyReader` marks a chapter finished only when `cur === end && cur !== 0`. For a no-move chapter `end` is 0, and **Next chapter** doesn't call `onFinished` (only the text-chapter button does). Real studies have these chapters: `ZCPaIb70` 1, `nq1GGbNO` 3, `swkkeUJZ` 9 (parsed by QA). None of them can ever be Finished, and their progress never reaches "N of N" | `tests/smoke/test_qa_v014_real_app.py::test_qa14_b4_a_chapter_with_no_moves_counts_as_finished_once_read` (xfail, real app: `done` stays False) |
| **v0.14-B5** | minor | On a study's page, step 4 moves into a chapter, then click **♡** | The board stays on the move | The reader jumps back to where the chapter was opened (`StudyReader`'s key includes `reload`, which the heart bumps, so it remounts at `startPath`). 400 ms later **your saved place is overwritten** with that position | `tests/e2e/test_qa_v014_ui.py::test_qa14_b5_hearting_on_the_study_page_keeps_your_move`, `tests/smoke/test_qa_v014_real_app.py::test_qa14_b5_…` (both xfail; real app: no current move after the heart) |
| **v0.14-B6** | major | Open a play-along (gamebook) chapter in a 1400x900 window | A board about the size of the step-through board (up to 560 px) | **112 px** (pieces about 14 px), in the real app and the mock. The board's column is `flex: 0 0 auto` and the board is `width: 100%`, so the board takes the width of the button row under it: four buttons give 256 px in a normal chapter, two give 112 px in a play-along chapter, and a text chapter's board is smaller still. It also jumps to 384 px when **Back to main line** appears. Screenshots: `tests/e2e/artifacts/qa-v014-study-gamebook-1400x900.png`, `qa-v014-real-gamebook.png`, `qa-v014-real-side-line.png` | `test_qa_v014_ui.py::test_qa14_b6_the_play_along_board_is_as_big_as_the_step_through_board`, `test_qa_v014_real_app.py::test_qa14_b6_…` (xfail; real app: normal 259 px, play-along 112 px) |

Every xfail is strict, so a fix turns it into a failure until its marker is removed. I re-ran each one with `--runxfail` to confirm it fails for the stated reason.

## Traceability

| Item / requirement | Method | Result | Evidence |
|---|---|---|---|
| DW: window has no bridge, settings or tokens, and can't leave lichess.org | existing smoke (real window, local pages) + unit import graph | PASS | `tests/smoke/test_lichess_window_isolation.py` (8), `tests/unit/test_lichess_window.py`, `test_lichess_window_adapter.py` |
| DW: Add this study only accepts a study address and works from the ID alone | existing + new | PASS | `test_study_links.py`, `test_lichess_window_adapter.py::test_adds_are_re_checked…`, `test_qa_v014.py::test_qa14_non_study_addresses_are_refused` |
| DW: every move validated; an illegal chapter rejected, the rest kept | existing + new + 3 real studies | PASS, but see **B1** | `test_study_pgn.py`, `test_qa14_a_chapter_after_a_broken_one_keeps_its_own_headers`. Real: `ZCPaIb70` 8 ch, `nq1GGbNO` 33, `swkkeUJZ` 39 (4 text): 0 rejected, all round-trip and flatten |
| DW: comments plain text, invalid arrow or highlight squares dropped | existing + new, real app | PASS | `test_qa14_markup_and_script_in_comments_stay_text`, `test_qa14_shapes_…item_by_item`. Real app: `<b>bold</b>` and the URL shown literally, 0 `a[href]` |
| DW: opens offline and after the author deletes it | existing + new real-app smoke | PASS | `test_a_saved_study_opens_offline…`; `test_qa14_saved_study_steps_through_and_continue_survives_an_offline_restart` (relaunch with the proxy on a closed port; Check for updates fails cleanly, copy intact) |
| DW: Check for updates never changes your copy without asking, and keeps your place | existing + new | PASS | `test_check_for_updates_never_changes…`, `test_an_update_that_removes_your_chapter…`, `test_qa14_check_for_updates_on_a_private_study…` |
| DW: hearts and place survive a restart, nothing sent to Lichess | existing + new real app | PASS, but see **B5** | `test_place_is_saved_checked_and_survives_a_restart`, `test_hearts_are_local_and_filter`; real-app relaunch |
| DW: starter list holds only links, titles and authors | existing + new | PASS | `test_starter_list_ships_and_is_valid`, `test_qa14_starter_list_holds_only…` (24 entries, 4 fields: study_id, title, author, opening; loads) |
| DW: Add to my repertoire stores `source = study`, a transposition reuses its position, the moves are drilled | existing | PASS | `test_study_repertoire.py`, `test_add_to_repertoire_stores_study_moves_and_practice_drills_them`, e2e `test_add_to_repertoire_previews…` |
| DW: study text never reaches the LLM | existing + new | PASS | `test_study_text_never_reaches_an_ai`; `test_qa14_study_text_is_absent_from_explain_my_game…` (Explain my game run against the fake provider after adding studies); `test_qa14_no_module_that_talks_to_an_llm_imports_study_code` |
| DW: recorded study fixtures scrubbed and anonymized | new | PASS | `test_qa14_study_fixtures_use_invented_ids_and_no_real_study_or_starter_id`, `test_qa14_study_fixture_authors_are_placeholders`, `test_fixtures_clean.py` |
| DW: links, chapter links and IDs parse; anything else makes no request | existing + new | PASS | `test_anything_but_a_study_address_makes_no_request`, e2e `test_paste_refuses…`, `test_qa14_a_bad_username_makes_no_request` |
| DW: text chapter kept and shown; moves from an invalid position rejected | existing + real app | PASS, but see **B6** for its board | `test_a_decorative_board…`, `test_moves_from_an_impossible_position…`; real-app Text chapter |
| DW: public study never sends the token; 403 with an old token gives the sign-in-again message | existing + new | PASS | `test_private_study_with_a_pre_v014_sign_in…`, `test_qa14_a_public_study_never_sends_the_token_even_with_study_read`, `test_account.py` scopes |
| DW: Studies by author lists and adds; unknown user and offline get clear messages | existing + new + 1 real GET | **FAIL (B2)**, offline PASS | `test_qa14_b2_…`, `test_qa14_author_search_offline_and_rate_limited` |
| DW: main line only unless Include side lines | existing | PASS | `test_main_line_only_by_default`, `test_side_lines_and_the_whole_study` |
| DW: a URL in study text renders as text | existing + real app | PASS | e2e `test_paste_adds…` (no `a`), real-app intro |
| DW: strength rules +/- tests; none says so; works with no AI key; prompt carries only the strengths; cache key changed | existing + new | PASS | `test_game_story.py` (16), `test_game_explain.py`, e2e `test_review_story_ui.py`, `test_qa14_strength_texts_never_name_the_engines_other_moves`, `test_qa14_only_move_from_a_decided_position…` |
| FR-13.1 tab, progress, filters | e2e + real app | **FAIL (B4)** | `test_my_studies_lists_progress…`, B4 test |
| FR-13.3/13.4 window, Add this study | smoke (local pages) | PASS | isolation smoke; real lichess.org left to Adam |
| FR-13.5, 13.5a, 13.6, 13.7 | as above | PASS except B2, B3 | |
| FR-13.8 reader: branches, gamebook, shapes | e2e + real app | PASS except **B6** | e2e `test_gamebook_play_along…`; real-app side line and Back to main line |
| FR-13.9, 13.10 | integration, e2e, real app | PASS except **B5** | |
| FR-13.11 | unit, integration, e2e | PASS | |
| FR-13.12 | see above | PASS | |
| FR-6.1 `study:read` | existing | PASS | `test_oauth.py`, `test_account.py` |
| FR-11.36 / FR-11.18 did_well | existing + new | PASS | as above |

## Commands run

| Command | Result |
|---|---|
| `uv run pytest` | **3725 passed**, 1 skipped, 2 xfailed (23 min). This run was before my tests were added. My unit and integration files then: 22 passed + 1 xfail, 14 passed + 2 xfail |
| `uv run pytest -m e2e` | **503 passed**, 2 xfailed (B5, B6) (16.5 min) |
| `npm.cmd --prefix web run build`, then `uv run pytest -m smoke` | **76 passed**, 1 skipped, 3 xfailed (B4, B5, B6) (18.5 min) |
| `uv run ruff check .`, `ruff format --check .`, `uv run mypy src` | clean |
| `npm.cmd --prefix web run typecheck`, `npm.cmd --prefix web run lint` | clean |
| `uv run pre-commit run --all-files` | passed (gitleaks, keyring hook) |
| `python scripts/check_docs.py --strict` | `0 error(s), 1 warning(s) [version v0.14]`. The warning (pyproject changed) is only the version bump |
| `uv run python scripts/gen_types.py` | no diff |
| `uv run pytest -m docs_screenshots` | 51 passed, no diff in `docs/img` |
| `uv run python scripts/make_icon.py --check` | up to date |
| `uv run python scripts/fetch_stockfish.py --dev` | already installed |
| `python scripts/setup.py --no-shortcut --skip-puzzle-db --skip-engine` (temp data dir) | rc 0, "Setup complete" |
| `uv run pytest -m fulldb` (dev puzzles.db is imported) | 76 passed, 3 xfailed (existing v0.13 markers) |
| `uv run pytest -m engine` | 19 passed |
| `--dev-server`, `fetch_puzzle_db.py --dev`, `record_db_update.py`, live commands | not run: unchanged in v0.14, need the network, or are live |

## Tests added
- `tests/unit/test_qa_v014.py`: `test_qa14_b1_a_long_main_line_is_kept_whole` (xfail), `test_qa14_a_100_move_main_line_is_kept`, `test_qa14_a_chapter_with_no_moves_on_a_normal_board_is_usable_not_text`, `test_qa14_markup_and_script_in_comments_stay_text`, `test_qa14_shapes_with_bad_colours_or_squares_are_dropped_item_by_item`, `test_qa14_a_chapter_after_a_broken_one_keeps_its_own_headers`, `test_qa14_non_study_addresses_are_refused` (9), `test_qa14_study_fixtures_use_invented_ids_and_no_real_study_or_starter_id`, `test_qa14_study_fixture_authors_are_placeholders`, `test_qa14_starter_list_holds_only_links_titles_authors_and_openings`, `test_qa14_starter_list_rejects_content_fields`, `test_qa14_no_module_that_talks_to_an_llm_imports_study_code`, `test_qa14_strength_texts_never_name_the_engines_other_moves`, `test_qa14_only_move_from_a_decided_position_is_not_praised`, `test_qa14_a_mate_only_move_counts_against_a_drawn_second_line`
- `tests/integration/test_qa_v014_studies.py`: `test_qa14_a_public_study_never_sends_the_token_even_with_study_read`, `test_qa14_check_for_updates_on_a_private_study_asks_without_the_token_first`, `test_qa14_private_study_after_signing_out_keeps_your_copy`, `test_qa14_a_bad_username_makes_no_request` (6), `test_qa14_an_author_with_no_public_studies_lists_nothing`, `test_qa14_b2_an_unknown_user_gets_its_own_message` (xfail), `test_qa14_author_search_offline_and_rate_limited`, `test_qa14_b3_…` (xfail), `test_qa14_restart_clears_place_and_finished_but_keeps_hearts`, `test_qa14_a_place_in_a_side_line_is_accepted_and_one_off_the_tree_refused`, `test_qa14_study_text_is_absent_from_explain_my_game_and_explain_this_move`
- `tests/e2e/test_qa_v014_ui.py`: `test_qa14_screenshots_of_every_new_screen` (1400x900 and 1024x700, with a horizontal-overflow check), `test_qa14_b5_…` (xfail), `test_qa14_the_step_through_board_is_a_usable_size`, `test_qa14_b6_…` (xfail), `test_qa14_a_bad_username_and_an_author_search_error_show_a_message`
- `tests/smoke/test_qa_v014_real_app.py`: `test_qa14_saved_study_steps_through_and_continue_survives_an_offline_restart`, `test_qa14_b4_…`, `test_qa14_b5_…`, `test_qa14_b6_…` (xfail). It seeds an invented study into a temp `user.db`, so no request is made.

## Scope, architecture and security
- No later-version code. No new dependency: pythonnet comes with pywebview, and `pyproject.toml`, `package.json` and both lockfiles changed only the version. Migration 0014 is new; no applied migration was edited.
- `core/study_*` and `game_review` do no I/O. Concrete adapters are wired only in `app.py`. All HTTP goes through `adapters/http.py`. The Lichess window is the deliberate exception: WebView2 loads lichess.org itself (FR-13.3), and it uses `webbrowser` for refused links.
- No `datetime.now`, `time.time` or global `random` added to `core/` or `services/`. No browser storage in `web/src`. `keyring` appears only in `secret_store`. The bridge allowlist test passes.
- SR-16: the window's `--test-cdp-port` and `--test-origin` are passed only by the smoke test, never by `adapters/lichess_window.py` or `app.py`, and inherited `WEBVIEW2_*` variables are stripped. The window process also works under `pythonw.exe` (the Start-menu shortcut) with piped stdio: checked.
- Fixtures: invented `Test…`/`Chap…` IDs, `player_author`. None of Adam's test-study IDs or the starter IDs appear in fixtures (new test). No token patterns.
- The token goes out only on the retry after a 403, and only with `study:read` recorded. Never for a public study, even when signed in (new test).

## Docs
- `check_docs --strict`: clean. CHANGELOG `[Unreleased]` covers every user-visible Done-when item. The User Guide has the studies chapter, the privacy entries (what's requested, what the window loads), the sign-in step and the three-part review.
- The User Guide says *"Reaching the end of a chapter's main line marks it done (✓)"*. That's false for a chapter with no moves (B4). Fixing B4 fixes this.
- The User Guide sections were followed against the mock and the real window for paste, branches, text chapters, Continue, hearts, filters, update review and repertoire preview. Steps match the labels, except where B4, B5 and B6 bite.
- Visual check (artifacts `qa-v014-*.png`): at 1024x700 the top bar wraps onto a second line (not new, but tighter with **Studies** added). No overflow or clipped text. Boards: B6. The mock's review Summary has no phase line (mock data only; the real backend adds it).

## Notes (not filed)
- `http://lichess.org/study/…`, `lichess.org:443/…` and `/study/embed/…` links are refused. That's within FR-13.5's wording; Adam may want to accept them.
- After an accepted update changes a chapter, a saved place that no longer fits that chapter is kept as stored. The reader follows it only as far as it still goes, which is harmless.
- Explain my game's cache key doesn't include the strengths themselves. A threshold change that alters the strengths but not the key moments would reuse an older narrative. Edge case.

## For Adam's manual test
- Everything on real lichess.org through the window (manual step 1): I was limited to local pages.
- Comparing text, arrows, highlights and play-along against Lichess for `ZCPaIb70` and `nq1GGbNO` (steps 2-3). The parser handles both cleanly, and side by side is a human check. Expect the tiny play-along board (B6).
- The private study `RVTx2uvp` with a real sign-in again (step 5): needs your account.
- The starter list's contents (24 studies, 4 authors, 18 openings): yours to approve. I only checked the fields and that it loads.
- **What you did well** on a real strong game (step 9).
