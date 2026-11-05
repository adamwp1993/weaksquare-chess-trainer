# Vendored code

## `lichess_puzzler/` (AGPL-3.0)
Lichess's puzzle tagger, from https://github.com/ornicar/lichess-puzzler at commit
`8e24b6d5e2b9618e41581a327926e4ac67c610a2` (2026-10-23): `tagger/cook.py`, `tagger/util.py` and
`tagger/model.py`, plus the repository's `LICENSE`. It isn't on PyPI, so it's copied here (REQUIREMENTS §15).
The app calls it only through `weaksquare.core.tagging`.

Changes from upstream (`cook.py` only):
- the imports of `model` and `util` are relative (`from .model …`, `from . import util`)
- removed `import logging`, the module-level `logging.basicConfig(...)` and the `log()` helper,
  which configured the root logger on import and built lichess.org URLs; nothing else used them

The files must import only python-chess, the standard library and each other
(`tests/contract/test_vendored_tagger.py`). To update, follow docs/DEVELOPER_GUIDE.md.
