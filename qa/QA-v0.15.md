# QA report: v0.15 (Analysis board tab)

# Round 2, 2026-11-08: re-verification at `b067918` (fixes for B1-B5)

Same rules as round 1: I changed only `tests/` and this report. No credentials, no `-m live`, no request to lichess.org.

## Verdict: **PASS WITH ISSUES** (1 new minor, doc only; no blocker or major)

All five round 1 bugs are fixed. B2 is also fixed in the real WebView2 window with real mouse drags. I found no
regressions. One new minor: the B1 fix changes v0.14 studies, and the CHANGELOG has no **Fixed** line for that (B6).

## Re-verified

| Bug | Result | How |
|---|---|---|
| B1 (minor) | **FIXED** | Round 1's four tests pass unmarked (unit x2, integration, real app: the PGN is refused with *has a null move (--)*). New tests: a null move is refused on the main line out of check, in a side line, in a nested side line, and spelled `Z0`. In a 3-game file, only the game with `--` is skipped, with its reason. `--` inside a comment isn't a null move. Studies use the same check (`has_null_move` in `parse_chapter`; the builder's `test_qa_b1_a_study_chapter_with_a_null_move_is_rejected_and_the_rest_kept`) |
| B2 (major) | **FIXED** | Round 1's mock test passes unmarked at 1280x900 with no board press first. New mock tests: the first drag, then a drag from the other row, at 1280x900 (white and flipped), 1920x1080, 1024x768 and 900x700 (stacked layout, palette scrolled into view), and after the window is resized while setting up. **Real app (WebView2, `page.mouse`):** after **Clear board**, which is a button and not a board press, dragging the white king to d4, the black king to f6 and a queen to a1 gives `8/8/5k2/8/3K4/8/8/Q7`, and **Done** accepts it |
| B3 (minor) | **FIXED** | Round 1's test passes: a solved committed line brings the opponent's move and your line. New: a *failed* committed line (`h7h6`) brings its moves too, and **Back** steps through them |
| B4 (minor) | **FIXED** | Below 1200 px the title is left out; from 1200 px the full name shows. New test at 900, 1000, 1199, 1200, 1280 and 1440 px: the header doesn't overflow, the title is either whole (not truncated, and not overlapping the nav) or absent, and every nav button is inside the header and the window. Round 1's B4 test now passes trivially because the title is hidden, so the new test is the one that counts |
| B5 (minor) | **FIXED** | Round 1's test passes: the count is main-line half-moves. New: a game from a set position with Black to move and a side line counts 2. The builder changed its own tests to 4 and 3, which matches |

## New bug

| ID | Severity | Steps | Expected | Actual | Evidence |
|---|---|---|---|---|---|
| **v0.15-B6** | minor | Read CHANGELOG `[Unreleased]` | A **Fixed** line for the change to signed-off v0.14 behaviour (CHANGELOG rules: "Fixed is for bugs in a version Adam already signed off") | None. The B1 fix also changes Lichess studies: a chapter with a null move is now listed as **Can't be used** when the study is added or updated. In v0.14 it was accepted, stored, and then read back as damaged, because `node_from_json` refuses `0000` as *illegal stored move* (checked at `b067918`: `convert_game` → `node_to_json` → `node_from_json` raises `ValueError`). The User Guide's Studies section (*Every move of every chapter is checked…*) doesn't mention null moves either, though its wording already covers them loosely | `CHANGELOG.md`, `docs/USER_GUIDE.md` line 1168; doc-only, so no test |

## Notes
- Two mock drags started within the same frame lose the second piece. With 300 ms between them (still faster than a person can manage) both land, and the real app with 300 ms pauses is correct. Not filed.
- The mock's `checkBoardPosition` doesn't count pieces, so a mock test can place a 17th white piece that the real app refuses (*White has more than 16 pieces*). That's how I noticed my own first real-app drag test was wrong. Not a product bug.

## Tests added this round
- `tests/unit/test_qa_v015_round2.py`: null move refused in 4 forms, only the bad game skipped, `--` in a comment, half-move count from a set position.
- `tests/e2e/test_qa_v015_round2_ui.py`: B2 at 5 sizes and orientations, plus after a resize; B3 on a failed line; B4 at 6 widths.
- `tests/smoke/test_qa_real_app_v015.py::test_qa_r2_b2_a_palette_drag_lands_on_its_square_in_the_real_window`.

## Commands at `b067918`

| Command | Result |
|---|---|
| `uv run pytest` | **3892 passed**, 1 skipped, 2 xfailed (24:47), round 1 QA files included. My round 2 unit file ran separately: **7 passed** |
| `uv run pytest -m e2e` | **555 passed** (17:37), my round 1 and round 2 files included |
| `uv run pytest -m smoke` (`web/dist` built by the builder) | 82 passed, 1 skipped, **1 failed**: `test_qa_v04_real_app.py::test_engine_flow_in_the_real_app`, a 20 s `wait_for_function` timeout. Re-run alone: **passed**. It runs no v0.15 code path, so I count it as a timing flake. My 3 v0.15 smoke tests pass |
| `uv run ruff check .` / `uv run ruff format --check .` | clean / 513 files formatted |
| `uv run mypy src` | no issues in 155 source files |
| `npm.cmd --prefix web run typecheck` / `npm.cmd --prefix web run lint` | clean / clean |
| `uv run pre-commit run --all-files` | all hooks passed |
| `python scripts/check_docs.py --strict` | 0 errors, 1 warning (the version bump, as in round 1) |

---

# Round 1, 2026-11-08, at `476ea51` (branch `v0.15`)

I changed only `tests/` and this report. No credentials, no `-m live`, no request to lichess.org. I didn't run
`uv run pytest -m docs_screenshots` (it rewrites `docs/img/`), `scripts/setup.py` (it installs shortcuts) or
`fetch_puzzle_db.py` (network); none of them changed in v0.15.

## Verdict: **FAIL** (1 major, 4 minor; no blocker)

Every *Done when* item has passing evidence. The verdict is FAIL only because the checkpoint gate allows minor issues
alone: dragging a piece from the set-up palette drops it one rank too low (B2, major), and that's the first step of
Adam's manual test. The other four bugs are minor.

## Traceability

| Item / requirement | Method | Result | Evidence |
|---|---|---|---|
| FR-14.1 tab opens at the start, no puzzle or game needed | e2e, real app | PASS | `test_the_tab_opens_at_the_start_and_keeps_two_lines_from_one_position`; smoke `test_the_analysis_tab_in_the_real_app` |
| FR-14.1 lines kept across tab switches, never saved | e2e, code | PASS | `test_lines_survive_switching_tabs`; tree is `App` state only, no bridge call writes it, no migration |
| FR-14.1 replacing a board with moves asks; Keep leaves it | e2e (new) | PASS | `test_qa_new_board_asks_and_keep_or_escape_keeps_your_lines` (New board: no question when empty, Keep, Escape = Keep, Replace); `test_a_pgn_with_several_games_lets_you_pick_and_asks_before_replacing`; `test_open_in_analysis_tab_asks_before_replacing_your_lines`; `test_qa_keep_my_board_on_open_in_tab_is_not_asked_again`; `test_qa_replace_on_open_in_tab_takes_the_game_position` |
| FR-14.2 / Done when: illegal or impossible position gets a clear message, never reaches Stockfish | unit, integration, e2e, real app | PASS | `test_each_problem_has_its_own_sentence_and_no_fen` (all 14 standard `status()` flags); `test_qa_every_problem_sentence_is_unique_and_ends_with_a_full_stop` (every standard flag mapped); `test_an_illegal_position_never_reaches_stockfish` (spy on the fake engine); `test_an_impossible_position_gets_a_message_and_never_reaches_the_engine`; smoke via the real bridge |
| FR-14.2 Chess960 / Shredder / variant FENs, en passant | unit (new), real engine (new) | PASS | `test_qa_a_shredder_fen_of_a_standard_position_is_accepted_as_kqkq`, `test_qa_chess960_castling_is_refused_with_the_castling_sentence`, `test_qa_variant_and_malformed_fens_get_the_isnt_a_fen_message`, `test_qa_an_en_passant_square_is_kept_only_when_the_capture_is_legal`; `tests/engine/test_qa_v015_real.py` (7 awkward legal positions on real Stockfish 19, engine alive after each) |
| FR-14.2 set-up editor: click palette, bin, castling boxes, Cancel, Done | e2e | PASS | `test_set_up_a_position_by_picking_pieces_and_clicking_squares`, `test_castling_boxes_follow_the_pieces`, `test_cancel_leaves_the_board_as_it_was`, `test_qa_done_with_moves_replaces_the_board_as_the_panel_says` |
| FR-14.2 drag from the palette, drag off to remove | e2e (new) | **FAIL (B2)** | `test_qa_b2_set_up_by_dragging_from_the_palette_and_off_the_board` (xfail). Drag-off works |
| FR-14.2 paste a FEN | e2e, real app | PASS | `test_paste_a_fen_or_be_told_why_not`; smoke |
| FR-14.3 / Done when: bad PGN gets a message, board unchanged | unit, integration, e2e, real app (new) | PASS | `test_a_pgn_with_nothing_usable_raises_one_clear_message`, `test_qa_unusable_pgns_get_one_clear_message` (Chess960 with and without a Variant tag, Crazyhouse, Atomic, bad FEN tag, impossible start, illegal move in a side line, >5,000 moves, comment only); `test_a_bad_pgn_says_why_and_changes_nothing`; `test_qa_pgn_edge_cases_in_the_real_app` |
| FR-14.3 side lines, glyphs, comments as escaped text | unit (new), real app (new) | PASS | `test_qa_nested_side_lines_and_glyphs_are_kept`; real app shows `<b>bold</b>` as text, no `<b>` element, `e4!`, two side lines |
| FR-14.3 several games, pick one, >200 games, BOM/CRLF | unit (new), e2e | PASS | `test_qa_five_hundred_games_list_the_first_two_hundred_and_say_so`, `test_qa_a_bom_and_crlf_line_ends_are_read`, `test_a_pgn_with_several_games_lets_you_pick_and_asks_before_replacing` |
| FR-14.3 every move checked | unit, integration, real app (new) | **FAIL (B1)** | null move in check: `test_qa_b1_*` (xfail) in unit, integration and smoke |
| FR-14.3 not added to the library | real app | PASS | smoke: `games` row count unchanged |
| Done when: PGN comments, headers, clocks never reach the engine or an LLM | integration | PASS | `test_a_pgns_headers_comments_and_clocks_never_reach_the_engine`, `test_headers_and_clocks_are_nowhere_in_the_tree`, `test_the_analysis_tab_has_no_llm_and_no_repository` (import graph) |
| FR-14.4 either side, branches, Back/Forward/main line, keys | e2e | PASS | `test_the_tab_opens_at_the_start_and_keeps_two_lines_from_one_position`; `test_qa_arrow_keys_do_nothing_while_typing_a_fen_or_pgn` |
| FR-14.4 engine eval, top 3, arrow, White's side | integration, e2e, unit (new) | PASS | `test_a_legal_position_is_analyzed_on_the_interactive_engine` (interactive engine only); `test_the_engine_and_its_arrow_follow_the_board`; `test_qa_the_engine_wording_is_from_whites_side_on_this_tab`; `test_qa_the_engine_panel_never_says_for_you_on_this_tab` |
| "both" viewpoint leaves puzzles, Review, openings unchanged | unit (new), full suites | PASS | `test_qa_colour_viewpoints_keep_the_for_you_wording`; the existing wording tests in the full backend and e2e suites pass |
| Done when: popular replies skipped cleanly signed out / offline | integration, e2e, real app | PASS | `test_popular_replies_are_skipped_cleanly_when_signed_out`, `..._offline`; new: `test_qa_rate_limited_popular_replies_are_unavailable_and_pause_further_requests` (no request during the pause), `test_qa_an_expired_sign_in_is_unavailable_not_an_error`, `test_qa_a_cached_answer_is_used_when_offline`; e2e `test_popular_replies_say_sign_in_when_signed_out`, `test_qa_popular_replies_unavailable_is_quiet_and_the_board_still_works`; smoke shows *Sign in* |
| FR-14.5 / Done when: nothing written to puzzles, stats, games, Coach | integration | PASS | `test_trying_lines_changes_no_puzzle_stat_game_or_coach_data` (every table in both DBs hashed, except `explorer_cache`); service holds no repository |
| FR-14.5 nothing to an LLM | integration, code | PASS | import-graph test; no `explain`/LLM import in the tab's modules or `AnalysisView` |
| FR-14.6 / Done when: same position from puzzles | e2e | PASS | `test_open_in_analysis_tab_from_a_finished_puzzle`; new: `test_qa_open_in_tab_after_show_answer_stepped_into_the_answer`, `test_qa_open_in_tab_after_try_again` (4 moves: the practice run, not doubled), `test_qa_open_in_tab_carries_your_own_moves_and_the_cursor`, `test_qa_open_in_tab_from_danger_spotting_after_the_punishment` |
| FR-14.6 / Done when: same position from Game Review | e2e | PASS | `test_open_in_analysis_tab_from_game_review_with_its_moves`, `test_qa_replace_on_open_in_tab_takes_the_game_position` |
| FR-14.6 moves that led there, Commit the line | e2e (new) | **FAIL (B3)** | `test_qa_b3_open_in_tab_from_commit_the_line` (xfail): right position, 0 moves |
| FR-10.72 tooltips | e2e | PASS | `test_analysis_options_have_tooltips` |
| StudyReader after `MoveTree` moved out | e2e | PASS | v0.14 study e2e and QA tests in the full e2e run |
| Docs: User Guide chapter | followed against the mock | PASS (with B2) | see Docs findings |

## Bugs

| ID | Severity | Steps | Expected | Actual | Evidence |
|---|---|---|---|---|---|
| **v0.15-B1** | minor | Import PGN `1. e4 e5 2. Qh5 Nc6 3. Qxf7+ -- 4. Qxe8 *` and step to the end | Refused, or at least no node is an impossible position (FR-14.3, plan: "every move checked by python-chess") | Accepted with 7 moves. After `--` White is to move with Black in check, and `4. Qxe8` captures the king: the real app's board shows `r1bqQbnr/pppp2pp/2n5/4p3/4P3/8/PPPP1PPP/RNB1KBNR b KQ - 0 4` (no black king). Stockfish is still protected (`check_fen` refuses those FENs), but chess.js lets you play on, including capturing the king yourself after `--`. Cause: `core.study_pgn.convert_game` accepts python-chess's null move without checking it, so v0.14 studies have the same gap. Suggest refusing any null move, or one made in check | `tests/unit/test_qa_v015_position_pgn.py::test_qa_b1_a_null_move_that_leaves_a_king_in_check_is_refused`, `::test_qa_b1_no_position_in_an_imported_tree_is_illegal`, `tests/integration/test_qa_v015_analysis_tab.py::test_qa_b1_a_null_move_in_check_never_reaches_the_board`, `tests/smoke/test_qa_real_app_v015.py::test_qa_b1_a_null_move_in_check_never_puts_an_impossible_position_on_the_board` (all xfail) |
| **v0.15-B2** | **major** | Analysis tab → **Set up position** → drag the white queen from the palette onto d4 (don't click the board first) → **Done** | The queen is on d4 | It lands on **d3**. Entering set-up adds the palette row above the board and moves it down 58 px (board top 155 → 213 at 1280x900). Chessground keeps the old position, and `Board` clears it only on a press *on the board* (the capture-phase `remeasure`), not on a press on the palette, so `dragNewPiece` uses stale bounds. After any press on the board, drags land correctly, which is why click-to-place passes. Dragging from the palette is the first step of Adam's manual test and the first method the User Guide gives | `tests/e2e/test_qa_v015_ui.py::test_qa_b2_set_up_by_dragging_from_the_palette_and_off_the_board` (xfail); a probe with one board click first put it on d4 |
| **v0.15-B3** | minor | **Commit the line** mode → enter the line → **Submit** → **Analyze** → **Open in Analysis tab** | The position with the puzzle's moves from its start (FR-14.6, Adam's planning decision) | Right position, **no moves**. `TrainerView` records `played` for normal moves, the answer and Danger spotting, but `onCommitMove` / `submitLine` never add the entered line, so no history reaches the board and `lineForAnalysisTab` falls back to the board alone | `tests/e2e/test_qa_v015_ui.py::test_qa_b3_open_in_tab_from_commit_the_line` (xfail) |
| **v0.15-B4** | minor | Any page in a 900 px wide window | The app's name readable, as the self-check fix intended ("the title shortens") | The title truncates to **"W…"**: the short "WeakSquare" doesn't fit beside the nav either. Screenshot `tests/e2e/artifacts/qa-v015-narrow.png` | `tests/e2e/test_qa_v015_ui.py::test_qa_b4_the_app_name_is_readable_in_a_900_px_window` (xfail) |
| **v0.15-B5** | minor | Import a PGN with several games where one has side lines, e.g. `1. e4 e5 (1... c5 2. Nf3 Nc6 3. Bb5) 2. Nf3` | The pick list's "· N moves" counts the game's moves | `move_count` is every node in the tree, side lines included: that game shows "7 moves" for a 3-ply main line. It also counts half-moves ("5 moves" for `1. e4 e5 2. Nf3 Nc6 3. Bb5`). The mock counts main-line plies only, so the e2e tests can't see it, and `test_a_pasted_pgn_lists_its_games_and_sends_one_tree` pins the current count (4 for a game with a 1-ply side line) | `tests/unit/test_qa_v015_position_pgn.py::test_qa_b5_the_pick_lists_move_count_is_the_main_line_only` (xfail) |

Notes, not filed:
- python-chess calls a double check by two knights valid (`4k3/8/8/8/8/3n1n2/8/4K3 w`), so it isn't refused. It can't happen in a game, but Stockfish analyzes it without trouble.
- A FEN pasted as the board part only (`rnbqkbnr/.../RNBQKBNR`) is accepted as White to move with **no** castling rights, without a word.
- **Keep my board** after picking a game in Import PGN also throws away the pasted text, so you paste it again to change your mind.
- `get_analysis_pgn_game(pgn, True)` returns game 1 (`True == 1`). Harmless; the UI always sends a number.
- **Done** in set-up replaces a board with moves without asking. FR-14.1 lists only New board, Import and Open in Analysis tab, and the panel and User Guide both warn, so this is as specified.

## Tests added
- `tests/unit/test_qa_v015_position_pgn.py`: Shredder / Chess960 / variant / malformed FENs, en passant, stalemate and mate, every status flag mapped; nested side lines with glyphs, set-up FEN with Black to move, unusable PGNs (9 cases), From Position, BOM and CRLF, markup and control characters, 500 games; B1 (2, xfail), B5 (xfail).
- `tests/integration/test_qa_v015_analysis_tab.py`: rate limit pauses requests, expired sign-in, cached answer offline, White's-side wording and mate text, unknown purpose refused, colour viewpoints unchanged; B1 (xfail).
- `tests/e2e/test_qa_v015_ui.py`: Open in Analysis tab after Show answer, Try again, your own moves (cursor), Danger spotting; New board Keep / Escape / Replace; Keep not asked again; Replace takes the game position; Done replaces as the panel says; arrow keys while typing; popular replies unavailable and erroring; no "for you" on the tab; dialog and narrow-window screenshots; B2, B3, B4 (xfail).
- `tests/smoke/test_qa_real_app_v015.py`: real python-chess PGN edges in the real window (side lines, glyphs, markup as text, bad PGN leaves the board, no page errors); B1 (xfail).
- `tests/engine/test_qa_v015_real.py`: 7 awkward legal positions on real Stockfish 19.

## Scope, architecture, security
- Nothing from v1.0 built. No dead UI. `AnalysisTabService` is stateless and built in `Api` from the engine and `OpeningSources` it already has; no concrete adapter wired outside `app.py`.
- `core/position_setup.py` and `core/analysis_pgn.py` do no I/O (an in-memory `StringIO` only).
- No new dependency: `pyproject.toml` and `web/package.json` change only the version; lockfiles committed. No migration, no edit to an applied one.
- New bridge methods use `@bridge_call` and are in the allowlist test (passes). No localStorage, sessionStorage, IndexedDB or cookies in `web/src`. No `datetime.now()`, `time.time()` or global random added to `core/` or `services/`.
- The tab's engine requests use the interactive engine (`test_a_legal_position_is_analyzed_on_the_interactive_engine`).
- Secrets: no token or key patterns in the v0.15 diff or my tests; fixtures use invented names ("Player A", "player_a"). The CDP port is set only by the test harness (`app.py` refuses it outside `--dev`). gitleaks and the keyring hook pass.

## Docs findings
- `python scripts/check_docs.py --strict`: `check_docs: 0 error(s), 1 warning(s) [version v0.15]`. The warning is "pyproject.toml changed: check whether docs/DEVELOPER_GUIDE.md needs updating", from the version bump; no guide change is needed.
- Developer Guide commands run as written: see the table below. None of them calls a `.ps1`, bare `npm`/`npx` or venv activation.
- User Guide "The Analysis tab" followed step by step against the mock: labels, order and defaults match (Set up position, Clear board, Start position, White/Black to move, castling boxes greyed out without king and rook, Or paste a FEN, Use this FEN, Enter, Cancel, Done; Import, pick list, Open; Keep my board / Replace; ← / →). Step 2 of *Setting up a position* ("Drag a piece from a row onto a square") misleads on the first drag because of B2. The privacy section's new entry says popular replies send the FEN, explorer source and rating bands to explorer.lichess.org; that matches the code (`fetch_explorer` sends `board.fen()`, source and ratings).
- CHANGELOG `[Unreleased]` has a line for each user-visible *Done when* item (tab, set up, import, popular replies, Open in Analysis tab). README's status line still says v0.14 is the latest release, which is right until sign-off.
- Screenshots `analysis-tab.png` and `analysis-setup.png` are current and match the screens.

## Visual check
Screenshots in `tests/e2e/artifacts/`: `qa-v015-pgn-pick.png`, `qa-v015-confirm.png`, `qa-v015-narrow.png`, `qa-v015-narrow-setup.png`, plus the builder's `docs/img/analysis-*.png`. No clipping or overlap apart from B4. At 900x650 the set-up panel moves under the board, so **Done** needs a scroll; that's the normal stacked layout.

## Commands

| Command | Result |
|---|---|
| `uv run pytest` | **3855 passed**, 1 skipped, 2 xfailed (26:50). Collected before my files existed; those ran separately: unit + integration **32 passed, 4 xfailed** (B1 x2, B1, B5) |
| `uv run pytest -m e2e` | **527 passed** (17:33), same; my file separately: **12 passed, 3 xfailed** (B2, B3, B4) |
| `npm.cmd --prefix web run build`, then `uv run pytest -m smoke` | **81 passed**, 1 skipped, 1 xfailed (B1, mine) (19:09); includes `test_real_app_v015.py` and my `test_qa_real_app_v015.py` |
| `uv run pytest -m fulldb` | 74 passed, 3 xfailed, 2 failed (`test_perf_v02.py::test_v02_filters_fast_and_correct`, `test_qa_v05_round3_ladder_worst_case.py::...[fork, promote 3->4]`) while the smoke suite ran beside it; both files re-run alone: **7 passed, 2 xfailed**. Timing only, no v0.15 code involved |
| `uv run pytest -m engine` | **19 passed**; my `tests/engine/test_qa_v015_real.py`: **7 passed** |
| `uv run ruff check .` / `uv run ruff format --check .` | clean / 509 files formatted (after formatting my own file) |
| `uv run mypy src` | no issues in 155 source files |
| `npm.cmd --prefix web run typecheck` / `npm.cmd --prefix web run lint` | clean / clean |
| `uv run pre-commit run --all-files` | all hooks passed (gitleaks, keyring hook included) |
| `python scripts/check_docs.py --strict` | 0 errors, 1 warning (version bump, see above) |
| `uv run python scripts/gen_types.py` | `types.ts` unchanged |
| `uv run python scripts/make_icon.py --check` | icon is up to date |

## For Adam's manual test
- **B2:** when you drag pieces in step 1, watch whether the first one lands a rank low.
- The real window with Stockfish installed and signed in: I ran the real app signed out and without Stockfish, and the engine and popular replies only against fakes, the mock and real Stockfish through the service. Check that real popular replies appear, that clicking one plays it, and that the eval reads "+0.3" / "White mates in N".
- Drag and drop with a real mouse, and dragging a board piece off the board, in WebView2.
- Open in Analysis tab from a real finished puzzle and a real reviewed game: same position, and you can step back to the start.
