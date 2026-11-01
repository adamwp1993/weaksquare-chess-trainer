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

## Installing from source
*Added in v0.1.*

WeakSquare runs from its source code; there's no installer to download. You need Windows 10 or 11 with **Git**, **Python 3.12 or newer** and **Node.js LTS** installed.

1. Open PowerShell (or a Command Prompt) in the folder where you want the app, and run:
   ```powershell
   git clone https://github.com/adamwp1993/weaksquare-chess-trainer
   cd weaksquare-chess-trainer
   python scripts/setup.py
   ```
2. Setup takes a few minutes. It installs everything into the project folder, builds the app, and adds **WeakSquare Chess Trainer** to your Start menu.
3. Start the app from the Start menu.

**Updating:** in the same folder, run `git pull`, then `python scripts/setup.py` again. Setup skips anything that's already up to date, and your data isn't touched.

**Gotchas**
- If setup says uv isn't on your PATH, that's fine: setup carries on without it.
- Only one copy of the app runs at a time. Starting it again brings the open window to the front.

## The About screen
*Added in v0.1.*

Click **?** at the top right to see:

| Item | What it shows |
|---|---|
| **Version** | The app version you're running. |
| **Data folder** | Where your puzzles, attempts and settings live. **Open** shows it in File Explorer. |
| **Logs folder** | Log files that help diagnose problems. **Open** shows it in File Explorer. Sign-in tokens and keys are removed before anything is written. |
| **Puzzle database** | How many puzzles are imported, and the date of the Lichess export they came from. |
| **License** and **Source code** | The app is open source under AGPL-3.0-or-later. The link opens the code in your browser. |
