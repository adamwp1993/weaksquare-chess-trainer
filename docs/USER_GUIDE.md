# WeakSquare Chess Trainer: User Guide

WeakSquare Chess Trainer is a Windows desktop app for training chess tactics on the Lichess puzzle database. You choose exactly which puzzles you get (themes, rating, length, side), solve them on a board, and over time the app helps you find and fix the gaps in your play.

This guide covers **only what the app does today**. Each section says which version added it. For what changed in each version, see [CHANGELOG.md](../CHANGELOG.md).

<!--
Planned chapters, added only when their version ships (see CLAUDE.md "Documentation"):
  Getting started: first run and the puzzle download ......... v0.1
  Choosing your puzzles (filters, queue) ...................... v0.1, v0.2
  Solving a puzzle (the trainer, the session bar) ............. v0.1
  Presets and stats ........................................... v0.2
  Signing in with Lichess, syncing solves, offline mode ....... v0.3
  Getting unstuck: hints and the engine ....................... v0.4
  Training modes .............................................. v0.5, v0.6
  Mistake reasons ............................................. v0.6
  AI explanations and what they cost .......................... v0.7
  Your game library and Game Review ........................... v0.8, v0.9
  The Coach ................................................... v0.10
  Tracking your progress ...................................... v1.0
  Installing from source and updating ......................... v0.1, v1.0
  The About screen ............................................ v0.1
  Troubleshooting ............................................. grows each version
-->

## Your data and privacy
*Added in v0.1.*

- **Where your data lives:** everything is stored on this PC under `%LOCALAPPDATA%\WeakSquare`.
  - `puzzles.db` is the imported Lichess puzzle database. It's large but rebuildable: re-importing replaces it.
  - `user.db` holds everything you create: your attempts, presets and settings, and from later versions your games and analysis. Back up this file to keep your history.
  - Before an update changes `user.db`, the app saves a copy in the `backups` folder next to it and keeps the last five.
- **Sign-ins and API keys** are never written to files. From v0.3, your Lichess sign-in, and from v0.7 any AI provider key, are stored in **Windows Credential Manager**. Signing out removes them.
- **Nothing leaves your PC** unless you use a feature that needs the internet. Those features are listed in their own sections, along with what they send.
  - **Puzzle database download** (v0.1): requests the public puzzle file and its checksum list from database.lichess.org. Nothing else is sent.
  - **Links that open your browser** (v0.1): **Open this puzzle on Lichess** (after a puzzle) and the **Source code** link on the About screen open the page in your default browser, like any link you click. The app itself sends nothing.

## Getting started: the puzzle database
*Added in v0.1.*

WeakSquare trains on the Lichess open puzzle database: about 6 million puzzles, public domain. It's stored on your PC, so after the first download everything works offline.

If setup already imported it, the app opens straight to your puzzles. Otherwise the first screen is **Get the puzzle database**:

![The first-run screen](img/first-run.png)

1. Click **Download from Lichess**. The app downloads about 300 MB, checks it against the checksum Lichess publishes, and imports it. Expect a few minutes; the progress bar shows each stage.
2. When it's finished, the app switches to your puzzles.

![The import in progress](img/first-run-importing.png)

**Already have the file?** Click **Use a file I already have…** and choose a `lichess_db_puzzle.csv.zst` (or an unpacked `.csv`) from database.lichess.org.

**Updating:** Lichess publishes a new export regularly. Choose **☰ → Update puzzle database…**. You can keep training while it runs; the new puzzles are switched in when it's finished.

**Gotchas**
- **Cancel** stops at any point and leaves your current puzzles as they were. An interrupted download picks up where it stopped next time.
- If the download doesn't match Lichess's checksum, it's deleted and nothing changes. Try again later (Lichess may be updating the file).
- Importing never touches your attempts or settings.
- **What it sends:** the download is a plain file request to database.lichess.org. Nothing about you or your training is sent.

## Choosing your puzzles
*Added in v0.1.*

The left-hand panel, **Choose your puzzles**, decides which puzzles you get. The count under the filters updates as you change them, so you always know how many puzzles match.

1. Pick **Themes**, or leave it at **All themes**.
2. Choose **ANY** (a puzzle needs at least one of your themes) or **ALL** (it needs every one).
3. Narrow it down with **Exclude themes**, **Rating**, **Number of moves** and **You play**.
4. Set how many **Puzzles** you want, or switch on **Endless**.
5. Press **Start**.

![The filter panel with Fork, ALL, rating 1100–1700 and 2-move puzzles](img/mixer.png)

| Control | What it does |
|---|---|
| **Themes** | Opens a list of every theme in the database, grouped (Motifs, Advanced, Mates, Mate patterns, Phases, Special moves, Goals, Lengths, Origin) with how many puzzles have each. Type in **Search themes** to find one. **Select all** ticks every theme shown by the search; **Clear** unticks everything. Leaving it empty means all themes. |
| **Match: ANY / ALL** | ANY: puzzles with *at least one* chosen theme. ALL: puzzles with *every* chosen theme, e.g. Fork + Long finds long puzzles that involve a fork. |
| **Exclude themes** | Puzzles with *any* of these themes are left out, whatever else they match. |
| **Rating** | Drag either end of the slider, or type exact numbers in the boxes. A typed number applies when you press **Enter** or click elsewhere. If the maximum you type is below the minimum, the minimum moves down to match. The range runs from the easiest to the hardest puzzle in the database. |
| **Number of moves** | How many moves *you* make: 1, 2, 3 or 4 and more. Tick any combination, or **All**. This is counted from the solution itself, not from the One-move/Short/Long/Very long theme tags. |
| **You play** | White, Black or Either. |
| **Puzzles** / **Endless** | A session of a fixed number of puzzles (1 to 500), or an endless one. |

Puzzles come in random order, and no puzzle repeats within a session. Your filters are remembered the next time you open the app.

![The theme list with search and Select all / Clear](img/theme-picker.png)

**Gotchas**
- If the count says **0 puzzles match**, Start is disabled. Widen a filter. A common cause is ALL with two themes that never appear together, such as One-move and Very long.
- Themes are hidden while you solve (see below), so choosing a single theme tells you the idea in advance. Mix several themes for a real test.

## Solving a puzzle
*Added in v0.1.*

1. The board turns to your side and the opponent's move plays first. Then it's your turn: find the best move.
2. Drag a piece, or click it and then its destination. When a pawn promotes, choose the piece.
3. If your move is right, the opponent's reply plays automatically. Keep going until the line is complete.
4. When the puzzle ends, the result panel shows whether you **Solved** or **Failed** it, and reveals its **themes**. **Open this puzzle on Lichess** shows it on the Lichess website.
5. Press **Next puzzle**.

![The trainer, waiting for your move](img/trainer.png)

**How it's scored**
- **Solved** means you played every move of the solution with no wrong move.
- A **wrong move fails the puzzle at once**. The move is taken back and you can keep trying to finish the line, with nothing more to lose.
- When the solution is a checkmate, **any** checkmating move counts.
- Pressing **Skip (counts as failed)** before you've finished also records a failed attempt.

**The session bar** at the top shows this session's **Solved**, **Failed**, **Accuracy** and **Played**. On the right, **All time** counts every attempt you've ever made; your attempts are saved as you go, so they survive closing the app. When a fixed-length session ends, you get a summary and a **New session** button.

![A solved puzzle with its themes revealed](img/solved.png)

## Installing from source
*Added in v0.1.*

WeakSquare runs from its source code; there's no installer to download. You need Windows 10 or 11 with **Git**, **Python 3.12 or newer** and **Node.js LTS** installed.

1. Open PowerShell (or a Command Prompt) in the folder where you want the app, and run:
   ```powershell
   git clone https://github.com/adamwp1993/weaksquare-chess-trainer
   cd weaksquare-chess-trainer
   python scripts/setup.py
   ```
2. Setup takes a few minutes. It installs everything into the project folder, builds the app, downloads and imports the puzzle database (see *Getting started*), and adds **WeakSquare Chess Trainer** to your Start menu. To skip the puzzle download, add `--skip-puzzle-db`; the app then offers it on first run.
3. Start the app from the Start menu.

**Updating:** in the same folder, run `git pull`, then `python scripts/setup.py` again. Setup skips anything that's already up to date, and your data isn't touched.

**Gotchas**
- If setup says uv isn't on your PATH, that's fine: setup carries on without it.
- Only one copy of the app runs at a time. Starting it again brings the open window to the front.

## The About screen
*Added in v0.1.*

Open the menu (**☰**, top right) and choose **About** to see:

![The About screen](img/about.png)


| Item | What it shows |
|---|---|
| **Version** | The app version you're running. |
| **Data folder** | Where your puzzles, attempts and settings live. **Open** shows it in File Explorer. |
| **Logs folder** | Log files that help diagnose problems. **Open** shows it in File Explorer. Sign-in tokens and keys are removed before anything is written. |
| **Puzzle database** | How many puzzles are imported, and the date of the Lichess export they came from. |
| **License** and **Source code** | The app is open source under AGPL-3.0-or-later. The link opens the code in your browser. |
