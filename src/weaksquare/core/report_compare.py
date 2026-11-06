"""Since last report (v0.12, FR-10.73): how a report compares with your earlier ones. Pure.

**The guards.** A change is called better or worse only when both reports have at least 5 games in that group
(FR-10.53's guard) and at least 5 of the newer report's games weren't in the older one. Otherwise it says *not enough
new games yet*. Puzzle-history reports have no games: a theme there already needs 10 attempts to be listed.

**What it never does.** It describes change, it doesn't set a weakness's status (statuses are v1.0, §10.8). Its AI
part (`prompt_json`) holds weakness keys and rates per report with days between them: no games, dates or text. An AI
statement about a trend must name a key that was sent and agree with `verdict`, or `validate_trend` drops it, so the
AI can't call a change better than the numbers do.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from weaksquare.core.stats import AttemptRow
from weaksquare.core.urls import strip_urls

MIN_GROUP_GAMES = 5  # FR-10.53's guard
MIN_NEW_GAMES = 5
MIN_PUZZLE_ATTEMPTS = 10  # the same bar a puzzle theme needs to be listed (core/coach.py)
MAX_HISTORY = 5  # this report and up to 4 before it
TOP_GROUPS = ("weaknesses", "whole_game")
RATE_GROUPS = ("missed", "allowed", "habits", "whole_game")
SAME_RATE = 0.05  # per 10 games: smaller than the rounding of the stored rates
SAME_PCT = 0.5
BETTER, WORSE, SAME, NOT_ENOUGH = "better", "worse", "same", "not_enough"
MAX_TREND_NOTES = 8
MAX_TREND_COMMENT = 300
TREND_CHANGES = {"improved": BETTER, "worse": WORSE, "same": SAME}


@dataclass(frozen=True)
class Side:
    """One saved report, as the comparison reads it."""

    id: int
    created_at: str
    data: Mapping[str, Any]
    game_ids: frozenset[int]

    @property
    def games(self) -> int:
        return int(self.data.get("games") or 0)

    @property
    def source(self) -> str:
        return str(self.data.get("source") or "games")

    @property
    def settings(self) -> Any:
        return self.data.get("analysis_settings")

    def rates(self) -> dict[str, Mapping[str, Any]]:
        out: dict[str, Mapping[str, Any]] = {}
        for group in RATE_GROUPS:
            for w in self.data.get(group) or ():
                if isinstance(w, Mapping) and isinstance(w.get("key"), str):
                    out[w["key"]] = w
        return out

    def top(self) -> dict[str, Mapping[str, Any]]:
        out: dict[str, Mapping[str, Any]] = {}
        for group in TOP_GROUPS:
            for w in self.data.get(group) or ():
                if isinstance(w, Mapping) and isinstance(w.get("key"), str):
                    out[w["key"]] = w
        return out

    def puzzle_rows(self) -> dict[str, Mapping[str, Any]]:
        return {
            w["key"]: w
            for w in self.data.get("puzzles") or ()
            if isinstance(w, Mapping) and isinstance(w.get("key"), str)
        }


@dataclass(frozen=True)
class PuzzleChange:
    """First-try accuracy on a weakness's themes: up to the older report, then between the two."""

    then_attempts: int
    then_first_try: int
    now_attempts: int
    now_first_try: int
    verdict: str

    @property
    def then(self) -> float | None:
        return round(100 * self.then_first_try / self.then_attempts, 1) if self.then_attempts else None

    @property
    def now(self) -> float | None:
        return round(100 * self.now_first_try / self.now_attempts, 1) if self.now_attempts else None


@dataclass(frozen=True)
class WeaknessChange:
    key: str
    label: str
    then: float | None  # per 10 games (puzzle-history: first-try accuracy, %)
    now: float | None
    delta: float | None
    flag: str | None  # new / gone
    verdict: str  # better / worse / same / not_enough; `new` weaknesses have no earlier rate to compare
    series: tuple[float | None, ...]  # oldest first, up to 5 reports, this one last
    puzzle: PuzzleChange | None = None


@dataclass(frozen=True)
class MeasureChange:
    key: str
    label: str
    unit: str  # per10 / pct
    then: float | None
    now: float | None
    delta: float | None
    verdict: str


@dataclass(frozen=True)
class Comparison:
    earlier_id: int
    earlier_created_at: str
    days_between: int
    new_games: int
    shared_games: int
    enough_new_games: bool
    settings: str  # same / different / unknown
    puzzle_history: bool
    history: tuple[tuple[int, str], ...]  # (report id, when), oldest first, this one last
    weaknesses: tuple[WeaknessChange, ...]
    health: tuple[MeasureChange, ...]
    measures: tuple[MeasureChange, ...]


def _day(text: str) -> date:
    return datetime.fromisoformat(text).date()


def _verdict(then: float | None, now: float | None, *, enough: bool, higher_is_better: bool, same: float) -> str:
    if not enough or then is None or now is None:
        return NOT_ENOUGH
    delta = now - then
    if abs(delta) < same:
        return SAME
    return BETTER if (delta > 0) == higher_is_better else WORSE


def _delta(then: float | None, now: float | None) -> float | None:
    return round(now - then, 2) if then is not None and now is not None else None


def _settings_state(a: Any, b: Any) -> str:
    if a is None or b is None:
        return "unknown"
    return "same" if a == b else "different"


def _group_games(data: Mapping[str, Any], key: str) -> int | None:
    """How many games a whole-game weakness's own group has in a report (FR-10.73's "in that group"). None for a
    weakness that's measured over the whole report, whose group is the report's games."""
    kind, _, name = key.partition(":")
    ms = data.get("measures")
    measures = ms if isinstance(ms, Mapping) else {}

    def named(rows_key: str, field: str) -> int:
        for row in measures.get(rows_key) or ():
            if isinstance(row, Mapping) and row.get(field) == name:
                return int(row.get("games") or 0)
        return 0

    if kind == "opening":
        return named("openings", "family")
    if kind == "endgame":
        return named("endgames", "type")
    group = {"phase:conversion": "conversion", "time:low_clock": "time", "habit:castledLate": "king"}.get(key)
    return int(_group(measures, group).get("games") or 0) if group else None


def _group_enough(cur: Side, old: Side, key: str, enough: bool) -> bool:
    """QA v0.12-B2: a weakness that only fell below its group's 5 games hasn't improved: there's no longer a
    rate to compare."""
    a, b = _group_games(old.data, key), _group_games(cur.data, key)
    if a is None or b is None:
        return enough
    return enough and a >= MIN_GROUP_GAMES and b >= MIN_GROUP_GAMES


def _weakness_rows(
    cur: Side, chain: Sequence[Side], enough: bool, puzzle: Mapping[str, PuzzleChange]
) -> list[WeaknessChange]:
    old = chain[-1]
    now_rates, old_rates = cur.rates(), old.rates()
    now_top, old_top = cur.top(), old.top()
    series_sides = [*chain[-(MAX_HISTORY - 1) :], cur]
    out: list[WeaknessChange] = []
    for key in sorted(set(now_top) | set(old_top)):
        w = now_top.get(key) or old_top.get(key) or {}
        in_now = key in now_rates
        was = key in old_rates
        then = float(old_rates[key].get("per10") or 0.0) if was else None
        # A tactical weakness missing from a report really didn't happen: every one found is stored. A whole-game one
        # can be missing and still happen, below its gate or out of the capped list, so its rate is unknown
        # (QA v0.12-B16), not 0, and there's nothing to call better.
        now = (
            float(now_rates[key].get("per10") or 0.0)
            if in_now
            else (None if _group_games({}, key) is not None else 0.0)
        )
        flag = "new" if key not in old_rates else "gone" if key not in now_top else None
        verdict = _verdict(
            then, now, enough=_group_enough(cur, old, key, enough), higher_is_better=False, same=SAME_RATE
        )
        out.append(
            WeaknessChange(
                key, str(w.get("label") or key), then, now, _delta(then, now), flag, verdict,
                tuple(float(s.rates()[key].get("per10") or 0.0) if key in s.rates() else None for s in series_sides),
                puzzle.get(key),
            )
        )  # fmt: skip
    # The worst rate first; what's gone at the end.
    out.sort(key=lambda c: (c.flag == "gone", -(c.now or 0.0), c.key))
    return out


def _puzzle_history_rows(cur: Side, chain: Sequence[Side]) -> list[WeaknessChange]:
    old = chain[-1]
    now_rows, old_rows = cur.puzzle_rows(), old.puzzle_rows()
    series_sides = [*chain[-(MAX_HISTORY - 1) :], cur]

    def pct(w: Mapping[str, Any] | None) -> float | None:
        acc = w.get("puzzle_accuracy") if w else None
        return round(100 * float(acc), 1) if isinstance(acc, int | float) else None

    out: list[WeaknessChange] = []
    for key in sorted(set(now_rows) | set(old_rows)):
        then, now = pct(old_rows.get(key)), pct(now_rows.get(key))
        w = now_rows.get(key) or old_rows.get(key) or {}
        flag = "new" if key not in old_rows else "gone" if key not in now_rows else None
        out.append(
            WeaknessChange(
                key, str(w.get("label") or key), then, now, _delta(then, now), flag,
                _verdict(then, now, enough=True, higher_is_better=True, same=SAME_PCT),
                tuple(pct(s.puzzle_rows().get(key)) for s in series_sides),
            )
        )  # fmt: skip
    out.sort(key=lambda c: (c.flag == "gone", c.now if c.now is not None else 101.0, c.key))
    return out


HEALTH = (("blunders", "Blunders"), ("mistakes", "Mistakes"), ("inaccuracies", "Inaccuracies"))


def _health(cur: Side, old: Side, enough: bool) -> list[MeasureChange]:
    a, b = old.data.get("per10") or {}, cur.data.get("per10") or {}
    return [
        MeasureChange(
            f"health:{k}", label, "per10", float(a.get(k) or 0.0), float(b.get(k) or 0.0),
            _delta(float(a.get(k) or 0.0), float(b.get(k) or 0.0)),
            _verdict(float(a.get(k) or 0.0), float(b.get(k) or 0.0), enough=enough, higher_is_better=False, same=SAME_RATE),
        )
        for k, label in HEALTH
    ]  # fmt: skip


def _group(m: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    v = m.get(key)
    return v if isinstance(v, Mapping) else {}


def _rate_row(
    key: str, label: str, a: Mapping[str, Any], b: Mapping[str, Any], field: str, enough_new: bool, *,
    higher_is_better: bool, unit: str = "pct",
) -> MeasureChange | None:  # fmt: skip
    then, now = a.get(field), b.get(field)
    if not isinstance(then, int | float) or not isinstance(now, int | float):
        return None
    enough = enough_new and int(a.get("games") or 0) >= MIN_GROUP_GAMES and int(b.get("games") or 0) >= MIN_GROUP_GAMES
    return MeasureChange(
        key, label, unit, float(then), float(now), _delta(float(then), float(now)),
        _verdict(float(then), float(now), enough=enough, higher_is_better=higher_is_better, same=SAME_PCT),
    )  # fmt: skip


def _measures(cur: Side, old: Side, enough_new: bool) -> list[MeasureChange]:
    """Only the whole-game measures both reports have (FR-10.73)."""
    a, b = old.data.get("measures"), cur.data.get("measures")
    if not isinstance(a, Mapping) or not isinstance(b, Mapping):
        return []
    out: list[MeasureChange] = []
    then_open = {o.get("family"): o for o in a.get("openings") or () if isinstance(o, Mapping)}
    for o in b.get("openings") or ():
        if isinstance(o, Mapping) and o.get("family") in then_open:
            fam = str(o["family"])
            row = _rate_row(f"opening_score:{fam}", f"Score in the {fam}", then_open[fam], o, "score", enough_new, higher_is_better=True)  # fmt: skip
            if row is not None:
                out.append(row)
    for key, label, field, group, higher in (
        ("conversion", "Winning positions converted", "rate", "conversion", True),
        ("saves", "Losing positions saved", "rate", "saves", True),
        ("low_clock", "Mistakes per 100 moves under 10% of your clock", "low_error_rate", "time", False),
    ):
        row = _rate_row(key, label, _group(a, group), _group(b, group), field, enough_new, higher_is_better=higher)
        if row is not None:
            out.append(row)
    ka, kb = _group(a, "king"), _group(b, "king")
    if ka.get("games") and kb.get("games"):
        late_a = {"games": ka["games"], "late_pct": round(100 * int(ka.get("late") or 0) / int(ka["games"]), 1)}
        late_b = {"games": kb["games"], "late_pct": round(100 * int(kb.get("late") or 0) / int(kb["games"]), 1)}
        row = _rate_row("late_castling", "Games castled late or never", late_a, late_b, "late_pct", enough_new, higher_is_better=False)  # fmt: skip
        if row is not None:
            out.append(row)
    return out


def compare(cur: Side, earlier: Sequence[Side], puzzle: Mapping[str, PuzzleChange] | None = None) -> Comparison | None:
    """`earlier` is the subject's earlier reports of the same kind, oldest first. None with no earlier report."""
    if not earlier:
        return None
    chain = list(earlier)[-(MAX_HISTORY - 1) :]
    old = chain[-1]
    puzzle_history = cur.source == "puzzles"
    new = len(cur.game_ids - old.game_ids)
    shared = len(cur.game_ids & old.game_ids)
    enough_new = new >= MIN_NEW_GAMES
    enough = enough_new and cur.games >= MIN_GROUP_GAMES and old.games >= MIN_GROUP_GAMES
    weak = _puzzle_history_rows(cur, chain) if puzzle_history else _weakness_rows(cur, chain, enough, puzzle or {})
    return Comparison(
        old.id, old.created_at, (_day(cur.created_at) - _day(old.created_at)).days, new, shared, enough_new,
        "same" if puzzle_history else _settings_state(cur.settings, old.settings), puzzle_history,
        tuple((s.id, s.created_at) for s in [*chain, cur]), tuple(weak),
        () if puzzle_history else tuple(_health(cur, old, enough)),
        () if puzzle_history else tuple(_measures(cur, old, enough_new)),
    )  # fmt: skip


def puzzle_changes(
    rows: Iterable[AttemptRow], weaknesses: Mapping[str, Sequence[str]], then_end: datetime, now_end: datetime
) -> dict[str, PuzzleChange]:
    """FR-10.73: first-try accuracy on each weakness's themes, your attempts up to the older report against
    those between the two. A misclick isn't counted (FR-5.10), and an attempt counts once however many of the
    weakness's themes the puzzle has."""
    tally = {k: [0, 0, 0, 0] for k in weaknesses}
    wanted = {k: set(v) for k, v in weaknesses.items()}
    for r in rows:
        if r.finished_at is None or r.misclick or not r.themes or r.mode == "danger_spotting":
            continue
        if r.finished_at <= then_end:
            at = 0
        elif r.finished_at <= now_end:
            at = 2
        else:
            continue
        theirs = set(r.themes)
        for k, want in wanted.items():
            if want & theirs:
                tally[k][at] += 1
                tally[k][at + 1] += int(r.win)
    out: dict[str, PuzzleChange] = {}
    for k, (ta, tw, na, nw) in tally.items():
        if ta or na:
            enough = ta >= MIN_PUZZLE_ATTEMPTS and na >= MIN_PUZZLE_ATTEMPTS
            verdict = _verdict(100 * tw / ta if ta else None, 100 * nw / na if na else None, enough=enough,
                               higher_is_better=True, same=SAME_PCT)  # fmt: skip
            out[k] = PuzzleChange(ta, tw, na, nw, verdict)
    return out


# ------------------------------------------------------------ for the AI (FR-10.73)


def _report_labels(count: int) -> list[str]:
    """Labels for a series, oldest first: "4 reports ago" ... "1 report ago", "this report"."""
    return [
        "this report" if n == 0 else f"{n} report{'s' if n != 1 else ''} ago" for n in range(count - 1, -1, -1)
    ]  # fmt: skip


def prompt_json(c: Comparison, history_days: Sequence[int]) -> dict[str, Any]:
    """The comparison as aggregates only: weakness keys and their rates per report, labeled, with the days
    between them. No games, positions, dates or text from earlier reports. `history_days[i]` is how many days before
    this report the i-th entry of the history was made."""
    labels = _report_labels(len(c.history))
    unit = "first_try_pct" if c.puzzle_history else "per_10_games"
    return {
        "unit": unit,
        "reports": [{"label": lb, "days_before_this_report": d} for lb, d in zip(labels, history_days, strict=True)],
        "new_games_since_last_report": c.new_games,
        "games_shared_with_last_report": c.shared_games,
        "analysis_settings": c.settings,
        "weaknesses": [
            {
                "key": w.key,
                "rates": dict(zip(labels[-len(w.series) :], w.series, strict=True)),
                "flag": w.flag,
                "change": w.verdict,
                **(
                    {"puzzle_first_try_pct": {"before_last_report": w.puzzle.then, "since_last_report": w.puzzle.now}}
                    if w.puzzle is not None
                    else {}
                ),
            }
            for w in c.weaknesses
        ],
        "game_health": [{"key": m.key, "then": m.then, "now": m.now, "change": m.verdict} for m in c.health],
        "measures": [{"key": m.key, "then": m.then, "now": m.now, "change": m.verdict} for m in c.measures],
    }


@dataclass(frozen=True)
class TrendNote:
    key: str
    change: str  # improved / worse / same
    comment: str

    def to_json(self) -> dict[str, str]:
        return {"key": self.key, "change": self.change, "comment": self.comment}


def validate_trend(raw: Any, c: Comparison | None) -> tuple[list[TrendNote], int]:
    """(the AI's trend statements that hold up, how many were dropped). The key must be a weakness that was sent, and
    the claimed change must match the app's own guarded verdict (FR-10.55, FR-10.73)."""
    items = raw if isinstance(raw, list) else []
    if c is None:
        return [], len(items)
    verdicts = {w.key: w.verdict for w in c.weaknesses}
    out: list[TrendNote] = []
    dropped = 0
    for t in items:
        key = t.get("key") if isinstance(t, Mapping) else None
        change = t.get("change") if isinstance(t, Mapping) else None
        comment = t.get("comment") if isinstance(t, Mapping) else None
        text = " ".join(strip_urls(comment).split())[:MAX_TREND_COMMENT] if isinstance(comment, str) else ""
        held = (
            isinstance(key, str) and isinstance(change, str) and text and len(out) < MAX_TREND_NOTES
            and key in verdicts and TREND_CHANGES.get(change) == verdicts[key]
            and all(n.key != key for n in out)
        )  # fmt: skip
        if not held:
            dropped += 1
            continue
        out.append(TrendNote(str(key), str(change), text))
    return out, dropped
