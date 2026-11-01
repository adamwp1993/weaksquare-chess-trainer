"""puzzles.db schema v2 (v0.2): opening ids, the local upgrade of a v1 database, and the exact
new/removed counts after an import (FR-2.5)."""

from __future__ import annotations

import csv
import shutil
import sqlite3
from pathlib import Path

import pytest

from tests.helpers import FIXTURE_CSV, fixture_rows
from tests.integration.test_puzzle_import import make, run_import
from weaksquare.adapters.db.migrate import migrate, read_version
from weaksquare.adapters.db.repos.puzzle_import import opening_tags
from weaksquare.config import MIGRATIONS_DIR, Paths
from weaksquare.core.clock import FixedClock
from weaksquare.jobs.runner import JobRunner

V1_INDEXES = """
CREATE UNIQUE INDEX puzzles_id ON puzzles (id);
CREATE INDEX puzzles_filter ON puzzles (rating, length, player_color, t0, t1, t2);
"""


@pytest.fixture
def runner() -> JobRunner:
    return JobRunner()


def write_csv(path: Path, rows: list[dict[str, str]]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return path


def make_v1_db(path: Path, clock: FixedClock, tmp: Path) -> None:
    """A puzzles.db exactly as v0.1 built it: migration 0001 only, the v0.1 indexes, no opening ids."""
    only_v1 = tmp / "v1-migrations"
    only_v1.mkdir()
    shutil.copy(MIGRATIONS_DIR / "puzzles" / "0001_init.sql", only_v1)
    migrate(path, only_v1, clock)
    conn = sqlite3.connect(path)
    rows = fixture_rows()
    for r in rows:
        moves = r["Moves"].split()
        conn.execute(
            "INSERT INTO puzzles (id, fen, moves, rating, rating_dev, popularity, nb_plays, themes, game_url,"
            " opening_tags, length, player_color, t0, t1, t2) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0,0,0)",
            (r["PuzzleId"], r["FEN"], r["Moves"], int(r["Rating"]), int(r["RatingDeviation"]), int(r["Popularity"]),
             int(r["NbPlays"]), r["Themes"], r["GameUrl"], r["OpeningTags"], len(moves) // 2,
             0 if " b " in r["FEN"] else 1),
        )  # fmt: skip
    conn.executescript(V1_INDEXES)
    conn.executemany(
        "INSERT INTO meta (key, value) VALUES (?, ?)",
        [("row_count", str(len(rows))), ("export_date", "2026-10-02"), ("sha256", "ab" * 32),
         ("source", "https://database.lichess.org/lichess_db_puzzle.csv.zst"), ("rating_min", "400"),
         ("rating_max", "3000"), ("imported_at", "2026-10-03T10:00:00")],
    )  # fmt: skip
    conn.commit()
    conn.close()


def test_opening_tags_split() -> None:
    assert opening_tags("") == (None, None)
    assert opening_tags("Italian_Game") == ("Italian_Game", None)
    assert opening_tags("Sicilian_Defense Sicilian_Defense_Closed") == ("Sicilian_Defense", "Sicilian_Defense_Closed")


def test_import_builds_opening_ids(paths: Paths, clock: FixedClock, runner: JobRunner) -> None:
    s = make(paths, clock, runner)
    assert run_import(s, runner, FIXTURE_CSV) == "done"
    tagged = [r for r in fixture_rows() if r["OpeningTags"].strip()]
    assert tagged, "the fixture needs puzzles with opening tags"
    with s.db.session() as conn:
        for r in tagged:
            family, variation = opening_tags(r["OpeningTags"])
            row = conn.execute(
                "SELECT f.tag AS family, v.tag AS variation, v.family_id = f.id AS linked FROM pz.puzzles p"
                " JOIN pz.openings f ON f.id = p.opening_family LEFT JOIN pz.openings v ON v.id = p.opening_variation"
                " WHERE p.id = ?",
                (r["PuzzleId"],),
            ).fetchone()
            assert row["family"] == family and row["variation"] == variation
            if variation:
                assert row["linked"] == 1
        untagged = conn.execute(
            "SELECT COUNT(*) FROM pz.puzzles WHERE opening_tags = '' AND opening_family IS NOT NULL"
        ).fetchone()[0]
        assert untagged == 0
        counted = conn.execute("SELECT SUM(count) FROM pz.openings WHERE family_id IS NULL").fetchone()[0]
        assert counted == len(tagged)
    s.close()


def test_upgrade_v1_db_without_download(paths: Paths, clock: FixedClock, runner: JobRunner, tmp_path: Path) -> None:
    make_v1_db(paths.puzzles_db, clock, tmp_path)
    assert read_version(paths.puzzles_db) == 1
    s = make(paths, clock, runner)  # no http: the upgrade must not need one
    status = s.puzzle_db.status()
    assert status.installed and status.needs_upgrade

    job = s.puzzle_db.start_upgrade()
    done = runner.wait(job, 60)
    assert done is not None and done.state == "done", done
    assert done.message.startswith(f"Upgraded: {len(fixture_rows()):,} puzzles")

    after = s.puzzle_db.status()
    assert not after.needs_upgrade and after.puzzle_count == len(fixture_rows())
    assert after.export_date == "2026-10-02"  # the export it came from is kept
    assert read_version(paths.puzzles_db) >= 2
    with s.db.session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM pz.openings").fetchone()[0] > 0
        masks = conn.execute("SELECT COUNT(*) FROM pz.puzzles WHERE t0 != 0 OR t1 != 0 OR t2 != 0").fetchone()[0]
        assert masks == len(fixture_rows())  # theme bits rebuilt from the themes text
    assert not paths.puzzles_new_db.exists()
    s.close()


def test_upgrade_refused_when_current(paths: Paths, clock: FixedClock, runner: JobRunner) -> None:
    s = make(paths, clock, runner)
    assert run_import(s, runner, FIXTURE_CSV) == "done"
    assert not s.puzzle_db.status().needs_upgrade
    from weaksquare.core.errors import ConflictError

    with pytest.raises(ConflictError):
        s.puzzle_db.start_upgrade()
    s.close()


def test_new_removed_counts(paths: Paths, clock: FixedClock, runner: JobRunner, tmp_path: Path) -> None:
    """Database B = A minus 3 puzzles plus 5 new ones: the finish message has the exact numbers."""
    rows = fixture_rows()
    a, extra = rows[:-5], rows[-5:]
    b = a[3:] + extra
    s = make(paths, clock, runner)
    assert run_import(s, runner, write_csv(tmp_path / "a.csv", a)) == "done"
    job = s.puzzle_db.start_import(str(write_csv(tmp_path / "b.csv", b)))
    done = runner.wait(job, 60)
    assert done is not None and done.state == "done"
    assert done.message == f"{len(b):,} puzzles: 5 new, 3 removed."
    s.close()


def test_first_import_has_nothing_to_compare(paths: Paths, clock: FixedClock, runner: JobRunner) -> None:
    s = make(paths, clock, runner)
    job = s.puzzle_db.start_import(str(FIXTURE_CSV))
    done = runner.wait(job, 60)
    assert done is not None and done.message == f"{len(fixture_rows()):,} puzzles imported."
    s.close()
