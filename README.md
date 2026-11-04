# WeakSquare Chess Trainer

A Windows desktop app for chess tactics training on the Lichess puzzle database. Mix any combination of themes, ratings and puzzle lengths, solve on a board, sync solves to your Lichess account, get unstuck with Stockfish and optional AI explanations, and track whether the gaps in your play are actually closing.

**Status:** in development. v0.8, your games (a library synced from Lichess and chess.com, plus PGN and URL import), Game Review with Stockfish on your PC (graded moves, eval graph, key moments, refutations), Retry your mistakes, Save as puzzle and importing your own puzzle files (the My puzzles source), is released (2026-11-04). v0.9 (Game Review AI: Explain this move, Explain my game, and a model per AI feature) is being built. Built version by version per [ROADMAP.md](ROADMAP.md). See [CHANGELOG.md](CHANGELOG.md) for what each version added.

## Getting started
The app runs from source on Windows 10 or 11. You need Git, Python 3.12 and Node.js LTS. Then:

```powershell
git clone <this repository>
cd weaksquare-chess-trainer
python scripts/setup.py
```

The setup script installs everything into a virtual environment, downloads the puzzle database, and adds a Start-menu shortcut. Details: [Developer Guide](docs/DEVELOPER_GUIDE.md).

There's no packaged `.exe`, on purpose. Be wary of any download that claims to be this app as a zipped executable.

## Documentation
- [User Guide](docs/USER_GUIDE.md): how to use the app
- [Developer Guide](docs/DEVELOPER_GUIDE.md): setup, commands, testing
- [Requirements](REQUIREMENTS.md), [Architecture](ARCHITECTURE.md), [Roadmap](ROADMAP.md)

## License
[AGPL-3.0-or-later](LICENSE). It uses chessground (GPL-3.0) and, from v0.10, the lichess-puzzler tagger (AGPL-3.0). Stockfish (GPL-3.0) and the Lichess puzzle database (CC0) are downloaded by the setup script and not included in this repository. See REQUIREMENTS.md §15.
