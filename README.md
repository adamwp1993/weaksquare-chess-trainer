# WeakSquare Chess Trainer

A Windows desktop app for chess tactics training on the Lichess puzzle database. Mix any combination of themes, ratings and puzzle lengths, solve on a board, sync solves to your Lichess account, get unstuck with Stockfish and optional AI explanations, and track whether the gaps in your play are actually closing.

**Status:** in development. v0.4, Stockfish (a pinned, hash-checked Stockfish 19 install; why your wrong move fails; evals and top lines after each puzzle; an analysis board; Show me for any engine line; Try again, not scored), is released (2026-11-02). v0.5 (training modes I) is next. Built version by version per [ROADMAP.md](ROADMAP.md). See [CHANGELOG.md](CHANGELOG.md) for what each version added.

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
