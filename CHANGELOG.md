# Changelog

Notable changes to WeakSquare Chess Trainer, newest first. The format follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/). Version numbers are the ROADMAP.md checkpoints (v0.1 … v1.0), not semantic versioning.

## How entries are written
- **Same commit as the change.** When a commit changes what the app does, the builder adds a line under `[Unreleased]` in that commit.
- **Written for the person using the app:** what you can now do, or what behaves differently. Don't describe the code. Put requirement IDs at the end in brackets, e.g. `[FR-3.2]`.
- **Groups:** Added, Changed, Deprecated, Removed, Fixed, Security. Leave out empty groups.
- **Fixed** is for bugs in a version Adam already signed off. Bugs found and fixed inside the version being built live in `qa/` reports, not here.
- **Handoff (step 6):** add a `Candidates:` line under `[Unreleased]` listing the rc tag and date. Add each new rc to that line.
- **Sign-off (step 9):** rename `[Unreleased]` to `[v0.x] - YYYY-MM-DD`, keep the Candidates line, and start a new empty `[Unreleased]` above it.
- `python scripts/check_docs.py` checks this structure and that every requirement ID cited here exists.

## [Unreleased]

### Changed
- **Why you missed it:** Settings → Training → **Ask why you missed** has a new choice, **Game Review only**, which asks about your mistakes in Game Review but not after puzzles. [FR-5.8]

## [v0.7] - 2026-11-03
Candidates: v0.7-rc1 (2026-11-03)

### Added
- **AI explanations:** once a puzzle is over, **Explain** asks Claude (Anthropic) or GPT (OpenAI) to explain it in plain words: the idea, each move, and why your move failed. It's grounded in the solution, Stockfish's lines and the board's attack and defence facts, and every move and square it mentions is checked against the position before it's shown. **Show me** steps through the solution with its arrows and circles drawn on the board. It needs Stockfish and your own API key, and works in every mode, Danger spotting included. [FR-8.1] [FR-8.2] [FR-8.3] [FR-8.4] [FR-8.5] [FR-8.7] [FR-8.8]
- **AI settings:** choose a provider and model (nothing is pre-selected; the list shows each model's cost per Explain), save your API key to Windows Credential Manager, and check it with **Test key**, which is free. On the startup page, a saved key is checked quietly at launch. [FR-1.2] [FR-1.3] [FR-1.4] [FR-1.6] [FR-1.8]
- **Spending limits:** an editable price table, a monthly budget (default $5, warns at 80%, stops at 100%), a per-run cap (default $0.50), a hard limit on every request's length, a reasoning setting (Low by default), and a spend indicator in the top bar. Explanations are saved, so showing one again is free. [FR-1.10] [FR-8.6] [FR-8.9] [FR-8.10] [FR-8.11] [FR-8.12] [FR-8.13] [FR-8.14] [FR-8.15]

## [v0.6] - 2026-11-03
Candidates: v0.6-rc1 (2026-11-03)

### Added
- **Name the idea first:** a new training mode. Before your first move you tag the idea (setup and payoff motifs), then solve as usual; afterwards you see which ideas you found, which you missed and which tags were extra. [FR-4.3]
- **Danger spotting:** a new training mode that shows the position just before a blunder with one move highlighted. Call it **Safe** or **Unsafe**; if it's the blunder, punish it with the right reply. About half the highlighted moves are safe ones that Stockfish has checked, so "Unsafe" isn't always the answer. It needs Stockfish, and the results stay on this PC (they don't sync, and they don't affect Spaced repetition or the history filters). [FR-4.4]
- **Why you missed it:** after a failed puzzle, six chips (keys **1–6**) ask why: didn't look, missed their reply, miscalculated, didn't know the pattern, rushed, or misclick. The app highlights a likely reason; you can add a short note, skip, or change your answer until you move on. Turn the question off, or change what counts as rushed, in Settings → Training. [FR-5.6] [FR-5.7] [FR-5.8] [FR-5.9]
- **Misclicks don't count against you here:** a miss you tag Misclick is left out of your accuracy (the session bar, Stats and the depth ladder) and counted on its own. It still counts as a loss on Lichess. [FR-5.10]
- **Stats:** a **Why you missed** breakdown (filter by theme and mode, with a weekly trend), and each mode's own measure: Commit's calculation accuracy, Name the idea's ideas found and tags right, and Danger-spotting accuracy on safe moves and on blunders. [FR-9.3] [FR-9.7]

### Fixed
- Clicking a square on the board works anywhere in the square again. After something above the board appeared or changed height, a move only registered when you clicked near the middle of the square.

## [v0.5] - 2026-11-03
Candidates: v0.5-rc1 (2026-11-03)

### Added
- **Training modes:** a **Modes** control at the top of the filters panel picks how you train: **Standard** (as before), **Commit the line** or **Spaced repetition**. The app remembers your choice; changing it starts a new session. [FR-4.2] [FR-4.6]
- **Commit the line:** enter the whole line, your moves and the replies you expect, with no feedback, then press **Submit**. Every one of your moves must match the solution to win; the replies you predicted are scored separately as calculation accuracy. The solution's length is hidden unless you turn on **Show move count** (solves then count for less on Lichess, because you knew the length). [FR-4.2]
- **Spaced repetition:** puzzles you miss come back on a schedule (1, 3, 7, 14 and 30 days by default, editable in Settings). A miss in any mode, including your misses from earlier versions, starts a puzzle at the first box; solving it in Spaced repetition moves it up, and solving it from the last box retires it. [FR-4.6]
- **Depth ladder:** a new **Order** option serves 2-move puzzles, then 3-move, then 4+ once you're accurate enough (80% over your last 20 at that level by default; both adjustable in Settings). Your level is kept for each set of themes and never drops. [FR-4.5] [FR-3.11]
- **Stats by mode:** the Stats page has accuracy per training mode. [FR-9.1]
- **Hide the filters while you play:** **«** at the top of the filters panel (or **F**) folds it into a slim bar with your mode and a summary; the board gets bigger. **Show filters** brings it back unchanged, and the app remembers your choice. [FR-1.14]
- **Settings → Training:** the depth ladder's threshold and window, and the Spaced-repetition review boxes. [FR-4.5] [FR-4.6]

### Fixed
- The **Already played: rating unaffected** badge (it said "on Lichess") is no longer cut off in the side column. [FR-6.11b]
- **Cancel** right after **Sign in with Lichess** now always cancels; very early, it could be missed and the sign-in kept waiting. [FR-6.1a]

## [v0.4] - 2026-11-02
Candidates: v0.4-rc1 (2026-11-02), v0.4-rc2 (2026-11-02)

### Added
- **Why your move fails:** after a wrong move, **Show answer** shows the solution with *Why your move fails* and Stockfish's evaluation above it; its **Show me** steps through your move and Stockfish's best reply (up to 5 moves). [FR-7.2]
- **Stockfish after each puzzle:** once a puzzle is over, a panel shows the evaluation of the starting position and the top 3 lines for whatever is on the board, following you through the answer. Evaluations read from your side, e.g. "+3.2 for you". Nothing from the engine is ever shown while you're solving. [FR-7.2] [FR-7.3] [FR-7.7]
- **Show me:** each of Stockfish's lines has a **Show me** button that puts the line on the board for you to step through with Back / Forward; **Done** returns. [FR-7.7]
- **Try again (not scored):** once a puzzle is over, solve it again from the start for practice. Nothing is recorded or sent to Lichess; the puzzle keeps your first result. [FR-5.12]
- **Show answer** stays clickable after a puzzle: click it again to go back to the start of the answer, for example after exploring on the analysis board, whose **Close** now reads **Back to the answer**. [FR-5.4]
- **Analysis board:** **Analyze on the board** lets you move pieces for either side after a puzzle, with Stockfish's evaluation, top lines and a best-move arrow after each move. Nothing there is scored. [FR-7.7]
- **Install Stockfish from the app:** where the engine would appear and it isn't installed, *Stockfish isn't installed* offers **Install Stockfish**, with progress. [FR-7.5]
- **Settings → Engine:** think time, threads and hash, **Use my own engine…** (any UCI engine that passes a self-test) and **Reinstall**. About shows the engine in use and where it is. [FR-7.4] [FR-7.5] [NFR-7]
- **Stockfish 19 installs with setup:** `scripts/setup.py` now downloads the official Stockfish 19 build from GitHub (about 80 MB), checks it against a pinned SHA-256 before unpacking it, tests it and installs it into your data folder. `scripts/fetch_stockfish.py` installs or repairs it on its own, and running it again does nothing when the engine is already fine (`--force` reinstalls). [FR-7.1] [FR-7.5]

## [v0.3] - 2026-11-02
Candidates: v0.3-rc1 (2026-11-02)

### Added
- **Sign in with Lichess** from the new startup page or the gear settings. Lichess opens in your own browser, so your password manager and two-factor sign-in work. The sign-in is kept in Windows Credential Manager, never in a file. With a sign-in Lichess accepts, the startup page is a single **Continue as *your name*** button. [FR-1.1] [FR-1.5] [FR-1.6] [FR-6.1] [FR-6.1a] [FR-6.5]
- **Solves sync to Lichess** as you play, with an honest angle (`mix` only when themes and move count are All). Offline or signed out, they wait and sync later, and the top bar says how many are waiting. [FR-1.7] [FR-6.8] [FR-6.13] [FR-6.14] [FR-6.16]
- **Your Lichess puzzle rating** in the top bar, the **+/−** change on each puzzle's result (or why there isn't one), and the session's total in the session bar. All of them come straight from Lichess. [FR-6.11a] [FR-6.11b] [FR-6.11c]
- **Rated** switch for the session: off sends your solves as unrated. [FR-1.9] [FR-6.15]
- **Exclude played on Lichess** (on by default): your Lichess puzzle history is read when you sign in, and those puzzles are left out. A puzzle you've already played there shows *Already played on Lichess: rating unaffected*. [FR-3.9] [FR-6.17]
- **Sign out** cancels your sign-in on Lichess as well as removing it from this PC. If Lichess can't be reached, the app asks first. [FR-6.6]
- A **gear** icon opens Settings, now with your Lichess account at the top. [FR-1.8]
- **Rating trend** on Stats: a chart of your Lichess puzzle rating over time and the change in each session, from what Lichess returned. [FR-9.4] [FR-6.11d]

### Changed
- Puzzles you played before this version stay on this PC and aren't sent to Lichess.

## [v0.2] - 2026-11-01
Candidates: v0.2-rc1 (2026-11-01)

### Added
- **Mix by ratio:** give theme groups a share of the session, e.g. 50% forks, 30% pins or skewers, 20% one-movers. Each group shows its own count, and the mix holds to within one puzzle. [FR-3.10]
- **Opening filter:** choose opening families or individual variations, with search. [FR-3.7]
- **Quality filter:** minimum popularity and minimum plays, on by default at 50 and 100 (adjustable, or off). [FR-3.8]
- **Your history:** leave out puzzles you've solved here (on by default), or train only your misses. [FR-3.9]
- **Order:** random, easy → hard, or grouped by theme. [FR-3.11]
- **Presets:** save your filters under a name, then load, rename or delete them. [FR-3.13]
- **Hint** circles the piece that moves next, and **Show answer** (unlocked by a Hint) steps through the rest of the solution with Back and Forward. Either one before the end fails the puzzle; after it, Show answer is free. [FR-5.2] [FR-5.4]
- **Stats** (☰ → Stats): accuracy by theme, length and rating band, plus the "first move right, line wrong" rate. [FR-9.1] [FR-9.2]
- **Keyboard shortcuts:** N or Enter for the next puzzle, H for Hint, A for Show answer, arrows to step through it, C for coordinates, ? for the list.
- Show or hide the board coordinates (C, the ☰ menu, or Settings); your choice is saved.
- **Dark mode:** Light, Dark or Match system in ☰ → Settings…, applied at once and remembered; the app opens in your saved scheme. [FR-1.12]
- **Move sounds:** moves, captures, checks, mates, and solved or failed puzzles, with an on/off switch, volume and four sound sets (sfx, piano, 8-bit, futuristic). In the default sfx set, a solved puzzle plays a short, soft chime. [FR-1.13]
- **Update check:** once a day, a banner tells you when Lichess has a newer puzzle export (with its date, download size and an approximate count), with Update now, Not now and Skip this export. **Check for updates** in the update dialog checks at once, and Settings can turn the daily check off. It's silent offline and sends nothing about you. [FR-2.5]
- **App icon and desktop shortcut:** setup also puts a shortcut on your desktop (`--no-desktop-shortcut` to skip), and the shortcuts, window and taskbar show the WeakSquare icon. [NFR-8a]
- After a puzzle-database update, the finish message gives the exact numbers, e.g. "6,201,004 puzzles: 44,112 new, 450 removed." [FR-2.5]

### Changed
- The puzzle-database screen says plainly that it downloads the **entire** Lichess puzzle database: about 300 MB, about 6 million puzzles, roughly 1.5 GB once imported. [FR-2.1a]
- Phase, goal and origin themes are chosen in the theme list's own groups, alongside the other themes. [FR-3.6]
- The filter panel scrolls on its own, so the board stays in view, and the match count updates as you play.
- Dimmed text, the green messages and the teal buttons are darker (lighter in Dark), so all text meets WCAG AA contrast.
- The first time v0.2 starts, it upgrades your puzzle database for the new opening and quality filters. This rebuilds it from the copy you already have (no download, about 2 minutes, with a progress bar), and your attempts and settings aren't touched. [FR-2.3]

## [v0.1] - 2026-11-01
Candidates: v0.1-rc1 (2026-11-01)

### Added
- Project specification, architecture, roadmap, QA agent, documentation set and repo guardrails.
- Licensed AGPL-3.0-or-later.
- The app window opens from the **WeakSquare Chess Trainer** shortcut in the Start menu, which `python scripts/setup.py` creates along with everything else the app needs. Re-running setup is safe. [NFR-8]
- **About** screen (the **?** button): version, your data and logs folders with Open buttons, the license and a link to the source code. [NFR-7]
- Only one copy runs at a time: starting it again brings the open window to the front. [NFR-1]
- Before an update changes your `user.db`, a backup goes to the `backups` folder (the last five are kept). A `user.db` from a newer version of the app is refused and left untouched. [NFR-3]
- Problems are written to rotating log files in the `logs` folder, with sign-in tokens and keys removed. [NFR-4] [SR-10]
- **Puzzle database import:** on first run the app downloads the Lichess puzzle database (about 300 MB, roughly 6 million puzzles), checks it against the checksum Lichess publishes, and imports it with a progress bar. You can also import a file you already have, cancel at any time, and later update from the menu (**☰ → Update puzzle database…**). An interrupted download resumes. A cancelled or failed import leaves your current puzzles and all your data untouched. [FR-2.1] [FR-2.3] [SR-6]
- **Choose your puzzles:** pick any mix of themes from a grouped, searchable list, matching ANY or ALL of them; exclude themes; set a rating range with a slider or exact numbers; choose the number of moves (1, 2, 3, 4+) and the side you play. A live count shows how many puzzles match, and your filters are remembered. [FR-3.1] [FR-3.2] [FR-3.3] [FR-3.4] [FR-3.5]
- Sessions of a fixed number of puzzles or endless, in random order with no repeats. [FR-3.11] [FR-3.12]
- **Solve puzzles on a board:** the opponent's move plays first, your correct moves get the reply automatically, and any checkmating move counts when the solution is a mate. A wrong move fails the puzzle but you can finish the line. Themes stay hidden until the puzzle is decided. [FR-4.1] [FR-5.1] [FR-5.3] [FR-3.14]
- Every attempt is saved. A session bar shows solved, failed and accuracy for the session, plus your all-time totals. [FR-5.5]
