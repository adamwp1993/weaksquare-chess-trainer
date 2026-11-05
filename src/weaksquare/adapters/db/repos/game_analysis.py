"""user.db repository for `game_analysis` (v0.8, FR-11.9): one row per analyzed move."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence

from weaksquare.adapters.db.connection import Database
from weaksquare.core.engine import EngineLine
from weaksquare.core.game_review import MoveRow, Score


def _lines_json(lines: Sequence[EngineLine]) -> str:
    return json.dumps([{"cp": ln.cp, "mate": ln.mate, "pv": list(ln.pv)} for ln in lines])


def _lines(text: str) -> tuple[EngineLine, ...]:
    out = []
    for d in json.loads(text or "[]"):
        if isinstance(d, dict):
            out.append(EngineLine(d.get("cp"), d.get("mate"), tuple(str(m) for m in d.get("pv") or ())))
    return tuple(out)


def _tags_json(tags: Sequence[str]) -> str | None:
    return json.dumps(list(tags)) if tags else None


def _tags(text: str | None) -> tuple[str, ...]:
    try:
        data = json.loads(text) if text else []
    except ValueError:
        return ()
    return tuple(str(t) for t in data) if isinstance(data, list) else ()


class GameAnalysisRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def replace(
        self, game_id: int, rows: Sequence[MoveRow], status: str, think_s: float, engine: str,
        analyzed_at: str | None = None,
    ) -> None:  # fmt: skip
        """Store a game's analysis and mark the game analyzed, in one transaction: a cancelled or failed
        run leaves the previous analysis (or none) untouched."""
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM game_analysis WHERE game_id = ?", (game_id,))
            conn.executemany(
                "INSERT INTO game_analysis (game_id, ply, fen_before, move_uci, move_san, mover, eval_before,"
                " eval_after, best_move, multipv_json, refutation_uci, cp_loss, classification, kind, phase,"
                " low_clock, clock_s, themes, habits) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        game_id, r.ply, r.fen_before, r.move_uci, r.move_san, r.mover,
                        json.dumps(r.eval_before.to_json()), json.dumps(r.eval_after.to_json()), r.best_move,
                        _lines_json(r.lines), " ".join(r.refutation), r.cp_loss, r.classification, r.kind, r.phase,
                        None if r.low_clock is None else int(r.low_clock), r.clock_s,
                        _tags_json(r.themes), _tags_json(r.habits),
                    )
                    for r in rows
                ],
            )  # fmt: skip
            conn.execute(
                "UPDATE games SET analysis_status = ?, analysis_think_s = ?, analysis_engine = ?,"
                " analyzed_at = COALESCE(?, analyzed_at) WHERE id = ?",
                (status, think_s, engine, analyzed_at, game_id),
            )

    def rows(self, game_id: int) -> list[MoveRow]:
        with self._db.session() as conn:
            found = conn.execute(
                "SELECT ply, fen_before, move_uci, move_san, mover, eval_before, eval_after, best_move, multipv_json,"
                " refutation_uci, cp_loss, classification, kind, phase, low_clock, clock_s, themes, habits"
                " FROM game_analysis WHERE game_id = ? ORDER BY ply",
                (game_id,),
            ).fetchall()
        return [
            MoveRow(
                ply=r[0],
                fen_before=r[1],
                move_uci=r[2],
                move_san=r[3],
                mover=r[4],
                eval_before=Score.from_json(json.loads(r[5])),
                eval_after=Score.from_json(json.loads(r[6])),
                best_move=r[7],
                lines=_lines(r[8]),
                refutation=tuple((r[9] or "").split()),
                cp_loss=r[10],
                classification=r[11],
                kind=r[12],
                phase=r[13],
                low_clock=None if r[14] is None else bool(r[14]),
                clock_s=r[15],
                themes=_tags(r[16]),
                habits=_tags(r[17]),
            )
            for r in found
        ]

    def regrade(self, fn: Callable[[MoveRow], MoveRow]) -> int:
        """Apply `fn` to every stored move and save what changed (v0.8-B1). Returns the moves changed."""
        with self._db.session() as conn:
            games = [int(r[0]) for r in conn.execute("SELECT DISTINCT game_id FROM game_analysis")]
        changed = 0
        for gid in games:
            updates = []
            for r in self.rows(gid):
                n = fn(r)
                if (n.cp_loss, n.classification, n.kind) != (r.cp_loss, r.classification, r.kind):
                    updates.append((n.cp_loss, n.classification, n.kind, gid, r.ply))
            if updates:
                with self._db.transaction() as conn:
                    conn.executemany(
                        "UPDATE game_analysis SET cp_loss = ?, classification = ?, kind = ? WHERE game_id = ? AND ply = ?",
                        updates,
                    )
                changed += len(updates)
        return changed

    def set_tags(self, game_id: int, tags: Sequence[tuple[int, Sequence[str], Sequence[str]]]) -> None:
        """Store (ply, themes, habits) for a game's moves (v0.10 tagging and its backfill)."""
        with self._db.transaction() as conn:
            conn.executemany(
                "UPDATE game_analysis SET themes = ?, habits = ? WHERE game_id = ? AND ply = ?",
                [(_tags_json(t), _tags_json(h), game_id, ply) for ply, t, h in tags],
            )

    def analyzed_games(self) -> list[int]:
        with self._db.session() as conn:
            return [int(r[0]) for r in conn.execute("SELECT DISTINCT game_id FROM game_analysis ORDER BY game_id")]

    def row(self, game_id: int, ply: int) -> MoveRow | None:
        rows = [r for r in self.rows(game_id) if r.ply == ply]
        return rows[0] if rows else None
