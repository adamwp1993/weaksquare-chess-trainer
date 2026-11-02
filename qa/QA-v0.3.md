# QA report: v0.3 (Lichess account + sync)

**Round 1, 2026-11-01.** Branch `v0.3` at `6aebdcf`. Independent QA. No product code, migrations, config or docs were changed; new tests are only under `tests/`. Not run, per the hard rules: `pytest -m live`, `scripts/set_test_token.py`, any keyring read, any real call to lichess.org (or database.lichess.org). The real app was only launched with `--dev` and a temp `WEAKSQUARE_DATA_DIR` (its own empty keyring entry, so signed out). `%LOCALAPPDATA%\WeakSquare` still doesn't exist; the dev folder's `user.db`/`puzzles.db` mtimes are unchanged (13:40/13:42, before this run).

## Verdict: **FAIL** (one major bug)

Every *Done when* item that can run offline passes with evidence, and so do the static checks, full-DB tests, real-app smoke, docs check and screenshots. One **major** bug blocks the gate: **B5**, a solve recorded during the 429 wait sends a batch at once, ignoring the minute Lichess asks for (FR-6.10). The rest are minor (B1–B4, B6, B7). The live-test item can't be verified by QA (Adam runs it).

---

## Evidence: commands run

| Command (as written in the Developer Guide unless noted) | Result |
|---|---|
| `uv run pytest` | builder: **533 passed**, 189 deselected (92 s). With QA tests: **567 passed, 3 xfailed** (B1, B3, B5) |
| `uv run pytest -m e2e` | builder: **98 passed** (219 s). With QA tests: **104 passed, 1 xfailed** (B2) (250 s) |
| `npm.cmd --prefix web run build`, then `uv run pytest -m smoke` | builder: **18 passed** (141 s). With QA test: **19 passed** (135 s) |
| `uv run pytest -m fulldb` (full DB imported: dev `puzzles.db`, 1.67 GB) | **57 passed, 1 xfailed** (v0.2-B2, known). QA file + `test_perf_v03.py` with `-s`: 4 passed; default count with 20k history + 5k solved **364 ms**, with **100k history 405 ms**, exact against an oracle; ratio count 273 ms |
| `uv run ruff check .` / `uv run ruff format --check .` | All checks passed / 178 files already formatted (after QA files) |
| `uv run mypy src` | Success: no issues found in 63 source files |
| `npm.cmd --prefix web run typecheck` / `npm.cmd --prefix web run lint` | clean / clean |
| `uv run pre-commit run --all-files` | all hooks Passed (gitleaks, keyring-only-in-secret_store) |
| `python scripts/check_docs.py --strict` and without `--strict` | `check_docs: 0 error(s), 0 warning(s) [version v0.3]` (both; also under `powershell -ExecutionPolicy AllSigned` via `uv run`) |
| `uv run python scripts/gen_types.py` | rc 0, `types.ts` unchanged (no git diff) |
| `uv run pytest -m docs_screenshots` | 11 passed; `docs/img` byte-identical (no git diff) |
| `uv run python scripts/make_icon.py --check` | icon is up to date |
| `uv lock --check` | Resolved 58 packages, lockfile up to date |
| `python scripts/setup.py --no-shortcut --skip-puzzle-db` (not bare: it writes real shortcuts and replaces the DB) | rc 0: `uv sync --locked`, `npm ci`, build, Chromium, pre-commit; ends "Setup complete. Start the app with: uv run python -m weaksquare" (v0.2-B6 wording fixed) |
| `uv run python -m weaksquare --dev` (temp `WEAKSQUARE_DATA_DIR`) | window up, closed with WM_CLOSE, exit 0; log banner "WeakSquare 0.3.0", migrations 0001–0003 applied, 0 ERROR lines, no `lichess.org/api` call |
| `npm.cmd --prefix web run dev` + `uv run python -m weaksquare --dev-server` (temp data folder) | window up, exit 0, same clean log |
| `npm.cmd --prefix web run dev -- --mode mock`, open http://127.0.0.1:5173 | HTTP 200 |
| `uv run python scripts/fetch_puzzle_db.py --dev` | not run: would replace the read-only dev DB (same as v0.2) |
| `uv run python tests/fixtures/tools/record_db_update.py` | not run: network call to database.lichess.org (hard rule: no Lichess calls); unchanged since v0.2 |
| Store the live-test token / `uv run pytest -m live` | not run (hard rule; Adam's rows) |

The Developer Guide, README and User Guide contain no `.ps1`, bare `npm`/`npx` or venv-activation commands.

---

## Traceability

### Done when (ROADMAP v0.3)

| Item | Method | Result | Evidence |
|---|---|---|---|
| Angle-rule unit tests cover all FR-6.13/6.14 cases (+ length-theme decision) | existing + QA | PASS | `unit/test_angle.py` (13 tests: mix only when all/all, other filters keep mix, one theme, ANY match, selection order within tier, motif before phase/goal, mates/special moves as motifs, phase when no motif, selected length ranks last, move count only → length theme, theme beats narrowed length, ratios in group order, no-match fallback). QA `test_qa_v03_edges.py::test_qa_non_theme_filters_keep_mix[4]` (excluded themes, rating, side, only-my-misses), `::test_qa_length_theme_for_every_length[5]` (1/2/3/4/9 moves), `::test_qa_all_mode_reports_the_motif_not_the_phase`, `::test_qa_ratio_angle_uses_bucket_themes`. Openings → mix and Rated off → `rated:false` in `test_angle.py::test_other_filters_keep_mix`, `test_sync.py::test_rated_off_sends_rated_false` |
| Sync integration tests against the fake client | existing + QA | PASS except **B5** | `integration/test_sync.py` (13: batches <100 grouped by angle, one solution per puzzle per request, skipped ids, network/5xx backoff 30 s→, 429 ≥60 s / Retry-After, 401 expires and keeps queue, 400 marks failed, per-account queue, no account no requests, solving never waits). QA: `::test_qa_exactly_99_then_1` (100 pending → 99+1), `::test_qa_offline_then_reconnect_drains_the_queue`, `::test_qa_solve_while_signed_out_syncs_after_sign_in_with_its_angle`, `::test_qa_429_is_not_retried_and_keeps_retry_after` (real `LichessHttp` + MockTransport, 1 request), `::test_qa_no_request_during_the_429_wait` (xfail, **B5**) |
| At-least-once (FR-6.16a) | existing | PASS | `test_sync.py::test_offline_backs_off_then_resends` (timeout leaves rows pending, resent); nothing marked synced without a 2xx (`_apply` only runs after `solve_batch` returns) |
| Live test syncs 3 `rated:false` solves with the test token and records the shape | **manual (Adam)** | NOT VERIFIED | Not run by rule. Offline: `unit/test_live_scrub_and_token_script.py` (scrubber anonymizes, token script never echoes). Fixtures are hand-written from the spec and labeled so in `tests/fixtures/http/lichess/README.md` (documented known limit). See **B4** |
| Rating display: +, −, offline then synced, Rated off, already played, 0/missing, session total (fake client) | existing + QA | PASS | `integration/test_rating_display.py` (8 tests); e2e `test_lichess_ui.py::test_rated_solve_shows_the_change_header_and_session_total`, `::test_rated_off_says_unrated`, `::test_offline_solve_will_sync_later`, `::test_already_played_badge`; QA `::test_qa_offline_then_reconnect_drains_the_queue` (3 offline → done, session total = sum of diffs), real app `smoke/test_qa_v03_real_app.py` ("Will sync later" when signed out) |
| Header rating only ever from Lichess responses | existing + QA | PASS | `test_rating_display.py::test_header_rating_only_from_lichess` (account value, then each glicko, unchanged with no response, Lichess recalculation wins); `test_account.py::test_rating_updates_only_from_lichess`; QA `::test_qa_sign_out_keeps_pending_and_hides_rating` (hidden when signed out) |

### Requirement IDs in scope

| ID | Method | Result | Evidence |
|---|---|---|---|
| FR-1.1 / 1.5 / 1.6 / 1.7 (startup page, fast path, offline) | e2e + real app + QA screenshots | PASS (B6, B7 cosmetic) | `test_lichess_ui.py::test_fast_path_continue_as`, `::test_signed_out_sign_in_flow`, `::test_sign_in_failure_is_shown`, `::test_offline_and_expired_startup`; `smoke/test_real_app_v03.py`; QA `smoke/test_qa_v03_real_app.py` (startup again on reload, "Not signed in"); screenshots `qa-v03/*-startup-*.png` |
| FR-1.8 (gear: account + existing settings) | e2e + screenshot | PASS | `test_lichess_ui.py::test_gear_opens_settings_with_the_account`; `qa-v03/light-settings-account.png` |
| FR-1.9 Rated (default on each launch, not saved) | e2e + QA | PASS | `test_rated_off_says_unrated`; QA `test_qa_v03_ui.py::test_qa_rated_is_on_again_after_reload`; real app row `rated=1` |
| FR-1.11 (Lichess part) | e2e | PASS | sign-in / sign-out in startup and gear (above) |
| FR-3.9 Exclude played on Lichess (default on, count, perf) | existing + QA + full DB | PASS | `test_lichess_history.py::test_exclude_played_on_lichess_count_and_sampling`, `::test_both_history_filters_together_count_each_puzzle_once`, `::test_defaults_and_saved_filters_upgrade` (v3 upgrade); `fulldb/test_perf_v03.py` (364 ms, exact); QA `fulldb/test_qa_v03_fulldb.py` (100k history: 405 ms, exact; sampler never serves a played puzzle); QA e2e `::test_qa_exclude_played_changes_the_count`; disabled when signed out with no history (real app) |
| FR-6.1 / 6.1a / 6.2 / 6.3 / SR-4 / SR-9 (PKCE, browser, loopback) | existing + QA | PASS (B3) | `unit/test_oauth.py`, `integration/test_oauth_loopback.py` (127.0.0.1 only, one callback, wrong path 404 not consumed, timeout, cancel), `test_account.py::test_sign_in_flow…`, `::test_state_mismatch…`, `::test_timeout_and_denied`, `::test_cancel_sign_in`; QA `::test_qa_sign_in_job_never_leaks_the_code_or_token`, `::test_qa_second_sign_in_while_waiting_is_refused`, e2e `::test_qa_double_click_sign_in_starts_one_wait`. Real browser round trip: manual (Adam) |
| FR-6.4 (401 → discard, "Sign in again") | existing + QA | PARTIAL (**B2**) | token discarded: `test_account.py::test_launch_check_expired_token_is_discarded`, `test_sync.py::test_401…`, QA `::test_qa_history_import_401_expires_the_account`; startup page says it. Main page doesn't: QA e2e `::test_qa_expired_sign_in_says_sign_in_again_on_the_main_page` (xfail) |
| FR-6.5 / 6.7 / SR-1 / SR-7 / SR-8 (token storage and handling) | existing + QA | PASS | `unit/test_secret_store.py` (1,000-char token, too long refused without echo, per-folder entry, tests can't open real entries); `test_rating_display.py::test_no_token_ever_crosses_the_bridge`; QA `::test_qa_token_never_in_logs_events_or_job_messages` (whole session at DEBUG incl. network/400/429/revoke failure: token absent from every log record, pushed event and bridge reply), `::test_qa_token_is_per_request_and_never_in_errors` (header per request, not a client default, not in URL or error text) |
| FR-6.6 sign-out revokes; offline confirmation | existing + QA | PASS | `test_account.py::test_sign_out_revokes_then_deletes`, `::test_sign_out_offline_needs_confirmation`, `::test_sign_out_with_an_already_revoked_token`; e2e `::test_sign_out_offline_asks_before_removing`; QA `::test_qa_sign_out_keeps_pending_and_hides_rating` |
| FR-6.8 / 6.9 / 6.10 / 6.12 | existing + QA | PASS except FR-6.10 (**B5**) | see Sync row |
| FR-6.11a–d | existing + QA | PASS | see Rating display rows; FR-6.11d `test_user_db_v3.py::test_mark_synced_rating_history_and_session_change` |
| FR-6.13–6.15 | existing + QA | PASS | see Angle row |
| FR-6.16 / decision 1 (pre-v0.3 never synced; per-account queue) | existing + QA | PASS | `test_user_db_v3.py::test_v2_attempts_become_local_and_are_never_queued` (real v2→v3 migration with backup), `::test_pending_queue_per_account`, `test_sync.py::test_solves_sync_only_to_their_account`, `::test_solving_never_waits_for_a_slow_sync` |
| FR-6.17 history import (incremental, broken stream, other account) | existing + QA | PASS | `test_lichess_history.py` (5 import tests); QA 401 case |
| FR-9.4 rating trend | e2e + screenshot | PASS | `test_lichess_ui.py::test_rating_trend_on_stats`, `::test_rating_trend_empty_when_signed_out`; `qa-v03/*-stats-rating-trend.png` |
| SR-2 bridge minimal + argument validation | existing + QA | PASS | `contract/test_bridge_allowlist.py` (7 new methods listed), `test_rating_display.py::test_attempt_ratings_validates_ids`; QA `::test_qa_bridge_rejects_bad_arguments[10]` (`rated:"false"`/`0`, `force_local:"yes"`/`1`, ids `0`/`-3`/`1.5`/string, extra args) |
| SR-5 / SR-10 log redaction | existing | PASS | `unit/test_logging_redaction.py` (incl. JSON token fields) |
| SR-12 / 12a fixtures scrubbed and anonymized | existing + grep | PASS | `contract/test_fixtures_clean.py` (extended for `lip_` and `access_token`); fixtures use `player_a`; repo grep finds no non-FAKE `li?_…`, Bearer or `sk-` values |
| SR-13 live tests opt-in | read + run | PASS (B4) | `-m live` deselected by `addopts`; token only via `weaksquare-test`; batch body asserts ≤3 and `rated:false` |
| SR-15 | n/a | PASS (B3 is related) | sign-out revokes |

---

## Bugs

### v0.3-B5 (major): a solve during the 429 wait sends a batch immediately
- **Steps:** signed in; Lichess answers a batch with 429 (state `waiting`, retry scheduled ≥60 s); solve another puzzle within the minute.
- **Expected:** no request until the scheduled retry (FR-6.10 "back off on HTTP 429"; plan §8 "at least 60 s"; Lichess's API rule is to wait a full minute after a 429; the User Guide says "the app waits and tries again").
- **Actual:** `SessionService._record` → `SyncService.recorded()` → `kick()` submits a new `lichess_sync` job at once, and `_drain` posts the whole queue again. Every solve in that minute sends another request. (The same applies during network/5xx backoff: each solve retries immediately. Harmless when offline, less so against a struggling server.) Reachable after a large backlog, e.g. a long offline session (>~200 solves/hour).
- **Evidence:** `tests/integration/test_qa_v03_edges.py::test_qa_no_request_during_the_429_wait` (xfail strict; with `--runxfail`: `assert 2 == 1`, second `BatchCall` sent while `state == "waiting"`). The builder's `test_sync.py::test_429_waits_at_least_a_minute` only checks the scheduled delay.

### v0.3-B1 (minor): an unexpected 2xx body is treated as "offline"
- **Steps:** Lichess returns 200 with a body the parser rejects (e.g. a JSON array) for `GET /api/account` or the batch POST.
- **Expected:** a non-network failure: the account check reports an error; the batch is marked `failed` (not retried forever).
- **Actual:** `LichessHttp` raises `HttpError(..., status=None)`, and `is_network_error` treats `status is None` as a network error. The account check goes `offline` and rechecks forever; the sync resends the batch with backoff forever (every 10 min). `exchange_code`'s "didn't return an access token" also shows "Lichess couldn't be reached". Matters mostly if the real response shape differs from the hand-written fixtures.
- **Evidence:** `test_qa_v03_edges.py::test_qa_unexpected_response_is_not_a_network_error` (xfail strict; `is_network_error(HttpError('Lichess returned an unexpected account response')) == True`).

### v0.3-B2 (minor): an expired sign-in isn't announced on the main page (FR-6.4)
- **Steps:** a 401 arrives mid-session (sync or history import), or launch with an expired token and click Continue.
- **Expected:** FR-6.4 "discard the token and show 'Sign in again'".
- **Actual:** the token is discarded (correct) and the header rating disappears; the main page shows nothing about it (only "Not signed in: N solves waiting to sync" once something is pending). "Sign in again" appears only on the startup page or inside the gear dialog.
- **Evidence:** `tests/e2e/test_qa_v03_ui.py::test_qa_expired_sign_in_says_sign_in_again_on_the_main_page` (xfail strict; mock `?account=expired`, no "Sign in again" text on the main page). Code: `LichessStatus.tsx` has no `expired` branch.

### v0.3-B3 (minor): a token obtained during a failed sign-in is never revoked
- **Steps:** sign in; the code exchange succeeds, then `GET /api/account` fails (network drop) or Credential Manager refuses the token.
- **Expected:** the new token is revoked (best effort), since it's never stored and nothing else can revoke it.
- **Actual:** the job fails with "Lichess couldn't be reached"; the token is dropped in memory but stays valid on Lichess for about a year (visible only at lichess.org/account/security).
- **Evidence:** `test_qa_v03_edges.py::test_qa_failed_sign_in_after_the_exchange_revokes_the_new_token` (xfail strict; `revoked == []`).

### v0.3-B4 (minor): the live test can push the same 3 solves up to 4 times (SR-13)
- **Steps:** `uv run pytest -m live` while Lichess answers the batch POST with a 5xx or times out after receiving it.
- **Expected:** at most 3 solves pushed per run (SR-13).
- **Actual:** `tests/live/test_lichess_live.py` uses `HttpClient().post_json`, which retries 5xx and transport errors 3 times by default, resending the batch.
- **Evidence:** `test_qa_v03_edges.py::test_qa_post_json_resends_on_5xx` (passes: 4 requests for one call). Fix in the live test: no retry for the POST (`request_json(..., retry=False)`).

### v0.3-B6 (minor, docs): User Guide wording differs from the app
- *Syncing and offline mode* says the top bar shows **Offline: 3 solves waiting to sync** "offline, or before you sign in". Signed out, the chip says **Not signed in: 1 solve waiting to sync** (real app screenshot `qa-v03-real/signed-out-result.png`).
- *Signing in*: **Sign in as someone else** reuses whatever account the browser is signed in to on lichess.org; the guide doesn't say to sign out of lichess.org in the browser first.
- *Syncing*: "If Lichess asks the app to slow down… the app waits and tries again" is not true while B5 is open.

### v0.3-B7 (minor, cosmetic)
- Startup page, offline: the status line and the yellow alert repeat the same message ("Lichess can't be reached…") (`qa-v03/light-startup-offline.png`).
- The mixer summary says "solved or played on Lichess left out" for a user who has never signed in, where the Lichess part does nothing (`qa-v03-real/signed-out-result.png`).
- The ⚙ glyph in the Light header is pale (light grey-violet) next to the ☰ icon (`qa-v03/light-*.png`).

---

## Tests added (all under `tests/`)
- `tests/integration/test_qa_v03_edges.py`: `test_qa_non_theme_filters_keep_mix[×4]`, `test_qa_length_theme_for_every_length[×5]`, `test_qa_all_mode_reports_the_motif_not_the_phase`, `test_qa_ratio_angle_uses_bucket_themes`, `test_qa_rating_status_edges`, `test_qa_token_is_per_request_and_never_in_errors`, `test_qa_429_is_not_retried_and_keeps_retry_after`, `test_qa_401_is_unauthorized_and_not_retried`, `test_qa_unexpected_response_is_not_a_network_error` (xfail B1), `test_qa_token_never_in_logs_events_or_job_messages`, `test_qa_sign_in_job_never_leaks_the_code_or_token`, `test_qa_sign_out_keeps_pending_and_hides_rating`, `test_qa_solve_while_signed_out_syncs_after_sign_in_with_its_angle`, `test_qa_bridge_rejects_bad_arguments[×10]`, `test_qa_second_sign_in_while_waiting_is_refused`, `test_qa_exactly_99_then_1`, `test_qa_history_import_401_expires_the_account`, `test_qa_offline_then_reconnect_drains_the_queue`, `test_qa_failed_sign_in_after_the_exchange_revokes_the_new_token` (xfail B3), `test_qa_post_json_resends_on_5xx` (B4 evidence), `test_qa_no_request_during_the_429_wait` (xfail B5)
- `tests/e2e/test_qa_v03_ui.py`: `test_qa_screenshots_of_every_v03_screen[light/dark]` (14 screens each), `test_qa_rated_is_on_again_after_reload`, `test_qa_exclude_played_changes_the_count`, `test_qa_no_header_rating_or_chip_on_the_startup_page`, `test_qa_double_click_sign_in_starts_one_wait`, `test_qa_expired_sign_in_says_sign_in_again_on_the_main_page` (xfail B2)
- `tests/smoke/test_qa_v03_real_app.py`: `test_signed_out_solve_is_queued_with_its_angle` (real window: startup on reload, history checkbox disabled, Hint → "Will sync later", chip, user.db row `(rated 1, 'mix', 'pending', NULL account, 'hint')`, no Lichess call in the log)
- `tests/fulldb/test_qa_v03_fulldb.py`: `test_qa_default_count_with_100k_history`, `test_qa_sampler_never_serves_a_played_puzzle`

Each xfail is `strict=True`: the fix commit removes the marker and keeps the test as its regression test.

---

## Scope / architecture / security
- **Scope:** nothing from v0.4+ in the diff (grep for LLM/Anthropic/OpenAI/chess.com/Stockfish/engine/spaced repetition/coach/api_key: only a redaction regex and a docstring mention "later LLM keys"). No LLM or chess.com fields in the UI.
- **Layers:** `core/` has no I/O imports; `random`/`datetime.now`/`time.time` absent from `core/` and `services/` (only `random.Random` type hints; `lichess_history.iso_from_ms` converts a timestamp, no clock read). Concrete adapters (`LichessHttp`, `KeyringSecretStore`, `TimerScheduler`, `LoopbackListener`) are constructed only in `app.py` (defaults in `build_services`; keyring only in `main()`). keyring imported only in `adapters/secret_store.py` (pre-commit hook passes). All Lichess HTTP goes through `adapters/http.py` (token per request, never a client default). Repos use `Database.session()` per call (no shared connection). `Api` dependencies are underscore attributes; allowlist test updated.
- **Browser storage:** none in `web/src` (`contract/test_no_browser_storage.py` + grep).
- **Migrations:** only `0003_lichess.sql` added; 0001/0002 untouched.
- **Data folders:** tests and QA runs used temp folders; real folder absent; dev folder unchanged.
- **Dependencies:** match the plan. Python: `keyring` (lock adds `jaraco.*`, `pywin32-ctypes`, `more-itertools`, plus platform-marked Linux backends `secretstorage`/`jeepney`/`cryptography`). npm: `@mantine/charts`, `recharts`, `react-is` (transitive: d3-*, redux toolkit, immer, etc.). `uv.lock` and `package-lock.json` committed; `uv lock --check` clean. ARCHITECTURE §7 has entries for both.
- **Security:** no non-FAKE `li?_…`, `Bearer …` or `sk-` values in the repo or `tests/e2e/artifacts`; fixtures anonymized (`player_a`); the token never reaches a DTO, log, event or error (QA tests above). CDP port: only the smoke harness sets it; `app.py` refuses it outside dev (SR-16). `KeyringSecretStore` refuses non-test services under pytest; each data folder has its own entry. The live recorder blanks every non-shape value.

## Docs
- `check_docs.py --strict`: 0 errors, 0 warnings [v0.3]. No `TODO(v0.3)` left.
- Developer Guide: every row run as written except the ones listed above (setup with flags, DB fetch, update recorder, the two live/token rows). All work; no AllSigned-incompatible commands.
- User Guide "Signing in with Lichess, syncing solves, offline mode" followed against the mock and the real app (signed-out path): labels, defaults (Rated on, Exclude played on and greyed when signed out), order of steps and screenshots match, except **B6**. Privacy section lists exactly what is sent (ID, win, rated, angle; username/rating reads; history; revoke), matching `batch_body` and the client calls.
- CHANGELOG `[Unreleased]` covers every user-visible *Done when* item (sign-in, sync, rating/change/session total, Rated, exclude played + badge, sign-out, gear, trend; pre-v0.3 attempts stay local). README status line updated.
- Screenshots: `docs_screenshots` regenerates byte-identical images; `startup.png`, `rating-change.png`, `stats.png`, `settings.png` show the v0.3 screens.

## Visual check
28 mock screenshots in `tests/e2e/artifacts/qa-v03/` (Light and Dark: startup signed in/out/offline/expired/all options/sign-in failed, result Syncing/+8 with header and session total/Will sync later with chip/Unrated, mixer with history and Rated, settings account, Stats trend, revoke-failed) and 2 real-app shots in `qa-v03-real/`. No clipping or layout breakage; Dark chart line and table readable. Cosmetic notes in B7.

## For Adam's manual test
- The real OAuth round trip in your browser (PKCE, loopback page, window back to front), and that the header rating matches lichess.org.
- `uv run python scripts/set_test_token.py`, then `uv run pytest -m live --record-lichess`: confirms `rounds[].ratingDiff`, `glicko.rating` and the activity shape, and replaces the hand-written fixtures. If the shapes differ, note that B1 decides what happens (offline loops / all solves "skipped").
- Rated `mix` solves: +/− on each result, header and session total update; Wi-Fi off → "Will sync later"; reconnect drains; solves appear on Lichess; Stats trend; sign out → no `weaksquare` entry in Credential Manager.
- Be aware: solves made while signed out (rated by default) are all sent, rated, to the first account that signs in (FR-6.16 as written). A long signed-out history means a large rated push on first sign-in.
