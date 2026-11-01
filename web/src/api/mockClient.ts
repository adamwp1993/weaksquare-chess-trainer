// Mock client with fixed data, for UI development (`npm.cmd --prefix web run dev -- --mode mock`)
// and for Playwright. Deterministic: no clock-dependent data and no randomness, so screenshots are stable.
//
// Scenarios via the page URL: `?scenario=empty` starts with no puzzle database imported, and
// `?scenario=upgrade` with a v0.1 database that needs the local upgrade.
import { Chess } from "chess.js";
import type { ApiClient, BackendEvent } from "./ApiClient";
import { ApiCallError } from "./ApiClient";
import { MOCK_PUZZLES, type MockPuzzle } from "./mockPuzzles";
import type {
  AppInfo,
  FilterSpec,
  HelpResponse,
  Job,
  MoveFeedback,
  OpeningFamily,
  Preset,
  PuzzleDbStatus,
  PuzzleView,
  SessionInfo,
  SessionStats,
  ThemeGroup,
  UiSettings,
} from "./types";

const INSTALLED: PuzzleDbStatus = {
  installed: true,
  puzzle_count: 6157341,
  export_date: "2026-10-02",
  imported_at: "2026-11-01T09:00:00+00:00",
  rating_min: 339,
  rating_max: 3297,
  import_job_id: null,
  needs_upgrade: false,
};

const EMPTY: PuzzleDbStatus = {
  installed: false,
  puzzle_count: null,
  export_date: null,
  imported_at: null,
  rating_min: null,
  rating_max: null,
  import_job_id: null,
  needs_upgrade: false,
};

const IMPORT_STEPS: [number, string][] = [
  [0.05, "Checking the published checksum…"],
  [0.2, "Downloading the puzzle database… 120 MB"],
  [0.4, "Verifying the download…"],
  [0.7, "Importing puzzles… 3,100,000"],
  [0.9, "Building indexes (this takes a minute)…"],
];

// A slice of the real catalog: [group, [key, name, count]].
const CATALOG: [string, [string, string, number][]][] = [
  ["Motifs", [["advancedPawn", "Advanced pawn", 312500], ["discoveredAttack", "Discovered attack", 318000],
    ["fork", "Fork", 905000], ["hangingPiece", "Hanging piece", 352000], ["pin", "Pin", 402000],
    ["kingsideAttack", "Kingside attack", 371000], ["skewer", "Skewer", 152000]]],
  ["Advanced", [["deflection", "Deflection", 251000], ["quietMove", "Quiet move", 188000]]],
  ["Mates", [["mateIn1", "Mate in 1", 551000], ["mateIn2", "Mate in 2", 674000]]],
  ["Phases", [["middlegame", "Middlegame", 3180000], ["endgame", "Endgame", 2240000]]],
  ["Special moves", [["enPassant", "En passant", 5100], ["promotion", "Promotion", 121000]]],
  ["Goals", [["advantage", "Advantage", 2510000], ["crushing", "Crushing", 2490000], ["mate", "Checkmate", 1420000]]],
  ["Lengths", [["oneMove", "One-move puzzle", 560000], ["short", "Short puzzle", 2850000], ["long", "Long puzzle", 1670000],
    ["veryLong", "Very long puzzle", 1070000]]],
  ["Origin", [["master", "Master games", 88000]]],
]; // prettier-ignore

const OPENINGS: OpeningFamily[] = [
  { family: { tag: "Italian_Game", name: "Italian Game", count: 61200 }, variations: [
    { tag: "Italian_Game_Evans_Gambit", name: "Evans Gambit", count: 4100 },
    { tag: "Italian_Game_Two_Knights_Defense", name: "Two Knights Defense", count: 12900 }] },
  { family: { tag: "Russian_Game", name: "Russian Game", count: 9800 }, variations: [
    { tag: "Russian_Game_Damiano_Variation", name: "Damiano Variation", count: 310 }] },
  { family: { tag: "Sicilian_Defense", name: "Sicilian Defense", count: 152000 }, variations: [
    { tag: "Sicilian_Defense_Closed", name: "Closed", count: 9100 },
    { tag: "Sicilian_Defense_Najdorf_Variation", name: "Najdorf Variation", count: 11800 }] },
]; // prettier-ignore

const NAMES = new Map(CATALOG.flatMap(([, themes]) => themes.map(([k, n]) => [k, n] as const)));
const SCALE = 61573; // each mock puzzle stands for this many real ones, so counts look realistic

function matches(p: MockPuzzle, spec: FilterSpec): boolean {
  const length = Math.floor(p.moves.length / 2);
  const playerColor = p.fen.split(" ")[1] === "w" ? "black" : "white";
  if (spec.rating_min !== null && p.rating < spec.rating_min) return false;
  if (spec.rating_max !== null && p.rating > spec.rating_max) return false;
  if (spec.lengths.length > 0 && spec.lengths.length < 4 && !spec.lengths.includes(Math.min(length, 4))) return false;
  if (spec.side !== "either" && spec.side !== playerColor) return false;
  if (spec.themes.length > 0) {
    const has = (t: string) => p.themes.includes(t);
    if (spec.match === "all" ? !spec.themes.every(has) : !spec.themes.some(has)) return false;
  }
  if (spec.exclude_themes.some((t) => p.themes.includes(t))) return false;
  if (spec.min_popularity !== null && (p.popularity ?? 90) < spec.min_popularity) return false;
  if (spec.min_plays !== null && (p.plays ?? 1000) < spec.min_plays) return false;
  if (spec.openings.length > 0 && !spec.openings.some((o) => (p.openings ?? []).includes(o))) return false;
  return true;
}

function validate(spec: FilterSpec) {
  if (spec.ratios.length === 0) return;
  const fail = (message: string) => {
    throw new ApiCallError({ code: "invalid_argument", message, retryable: false });
  };
  if (spec.themes.length > 0) fail("With ratios, the themes come from each ratio: clear the theme list.");
  if (spec.ratios.length < 2) fail("Ratios need between 2 and 10 groups.");
  if (spec.ratios.some((b) => b.themes.length === 0)) fail("Each ratio needs at least one valid theme.");
  const total = spec.ratios.reduce((a, b) => a + b.weight, 0);
  if (total !== 100) fail(`The ratios must add up to 100% (they add up to ${total}%).`);
}

function bucketSpec(spec: FilterSpec, i: number): FilterSpec {
  return { ...spec, themes: spec.ratios[i].themes, match: "any", ratios: [] };
}

interface MockSession {
  spec: FilterSpec;
  queue: MockPuzzle[];
  served: number;
  current: {
    puzzle: MockPuzzle;
    chess: Chess;
    start: string;
    next: number;
    decided: boolean;
    failed: boolean;
    hinted: boolean;
    finished: boolean;
  } | null;
  solved: number;
  failed: number;
}

export class MockClient implements ApiClient {
  private readonly listeners = new Set<(event: BackendEvent) => void>();
  private status: PuzzleDbStatus;
  private jobs = new Map<string, Job>();
  private nextJob = 1;
  private sessions = new Map<number, MockSession>();
  private nextSession = 1;
  private settings: UiSettings = { last_filters: null };
  private allTime = { solved: 41, failed: 17 };
  private presets = new Map<string, Preset>();
  private history = new Map<string, boolean[]>(); // puzzle id -> results here, oldest first
  readonly calls: string[] = [];

  constructor(search: string = typeof window !== "undefined" ? window.location.search : "") {
    const scenario = new URLSearchParams(search).get("scenario");
    this.status =
      scenario === "empty" ? { ...EMPTY } : scenario === "upgrade" ? { ...INSTALLED, needs_upgrade: true } : { ...INSTALLED };
    this.presets.set("Endgame drill", {
      name: "Endgame drill",
      spec: null,
      error: "This preset can't be used in this version: This version doesn't support the filter(s): source.",
      updated_at: "2026-10-30T18:00:00",
    });
  }

  private matchesHistory(p: MockPuzzle, spec: FilterSpec) {
    const h = this.history.get(p.id) ?? [];
    if (spec.only_my_misses) return h.length > 0 && !h[h.length - 1];
    if (spec.exclude_solved_here) return !h.includes(true);
    return true;
  }

  private pool(spec: FilterSpec) {
    return MOCK_PUZZLES.filter((p) => matches(p, spec) && this.matchesHistory(p, spec));
  }

  private record(p: MockPuzzle, win: boolean) {
    this.history.set(p.id, [...(this.history.get(p.id) ?? []), win]);
  }

  private emit(job: Job) {
    this.jobs.set(job.id, job);
    this.listeners.forEach((l) => l({ name: "job", payload: job }));
  }

  async getAppInfo(): Promise<AppInfo> {
    return {
      version: "0.1.0",
      data_dir: "C:\\Users\\you\\AppData\\Local\\WeakSquare",
      logs_dir: "C:\\Users\\you\\AppData\\Local\\WeakSquare\\logs",
      dev_mode: false,
      license: "AGPL-3.0-or-later",
      source_url: "https://github.com/adamwp1993/weaksquare-chess-trainer",
      puzzle_db_export_date: this.status.export_date,
      puzzle_count: this.status.puzzle_count,
    };
  }

  async openFolder(kind: "data" | "logs") {
    this.calls.push(`openFolder:${kind}`);
  }

  async logFrontendError(message: string) {
    this.calls.push(`error:${message}`);
  }

  async getPuzzleDbStatus() {
    return { ...this.status };
  }

  async choosePuzzleFile() {
    return "C:\\Users\\you\\Downloads\\lichess_db_puzzle.csv.zst";
  }

  async startPuzzleImport(localPath: string | null) {
    if (this.status.import_job_id) {
      throw new ApiCallError({ code: "conflict", message: "A puzzle import is already running.", retryable: true });
    }
    const id = `job-${this.nextJob++}`;
    this.calls.push(`import:${localPath ?? "download"}`);
    this.status.import_job_id = id;
    this.emit({ id, kind: "puzzle_import", state: "running", progress: 0, message: "Starting…", error_code: null });
    IMPORT_STEPS.forEach(([progress, message], i) => {
      setTimeout(() => {
        if (this.jobs.get(id)?.state !== "running") return;
        this.emit({ id, kind: "puzzle_import", state: "running", progress, message, error_code: null });
      }, 150 * (i + 1));
    });
    setTimeout(
      () => {
        if (this.jobs.get(id)?.state !== "running") return;
        this.status = { ...INSTALLED };
        this.emit({ id, kind: "puzzle_import", state: "done", progress: 1, message: "Done", error_code: null });
      },
      150 * (IMPORT_STEPS.length + 1),
    );
    return id;
  }

  async startPuzzleDbUpgrade() {
    const id = `job-${this.nextJob++}`;
    this.calls.push("upgrade");
    this.status.import_job_id = id;
    this.emit({ id, kind: "puzzle_import", state: "running", progress: 0.3, message: "Importing puzzles… 1,900,000", error_code: null });
    setTimeout(() => {
      if (this.jobs.get(id)?.state !== "running") return;
      this.status = { ...INSTALLED };
      this.emit({ id, kind: "puzzle_import", state: "done", progress: 1, message: "Upgraded: 6,157,341 puzzles, ready for the new filters.", error_code: null });
    }, 600);
    return id;
  }

  async getJob(jobId: string) {
    const job = this.jobs.get(jobId);
    if (!job) throw new ApiCallError({ code: "not_found", message: "No such job.", retryable: false });
    return job;
  }

  async cancelJob(jobId: string) {
    const job = this.jobs.get(jobId);
    if (!job || job.state !== "running") return false;
    this.status.import_job_id = null;
    this.emit({ ...job, state: "cancelled", message: "Cancelled" });
    return true;
  }

  async getSettings() {
    return { ...this.settings };
  }

  async setSetting(_key: "mixer.filters", value: FilterSpec) {
    this.settings = { last_filters: value };
  }

  async getThemeCatalog(): Promise<ThemeGroup[]> {
    return CATALOG.map(([name, themes]) => ({
      name,
      themes: themes.map(([key, label, count]) => ({ key, name: label, count })),
    }));
  }

  async countMatches(spec: FilterSpec) {
    validate(spec);
    if (spec.ratios.length > 0) {
      const ids = new Set(spec.ratios.flatMap((_, i) => this.pool(bucketSpec(spec, i)).map((p) => p.id)));
      return ids.size * SCALE;
    }
    return this.pool(spec).length * SCALE;
  }

  async countBuckets(spec: FilterSpec) {
    return spec.ratios.map((_, i) => this.pool(bucketSpec(spec, i)).length * SCALE);
  }

  async getOpeningCatalog() {
    return OPENINGS;
  }

  async listPresets() {
    return [...this.presets.values()].sort((a, b) => a.name.localeCompare(b.name));
  }

  async savePreset(name: string, spec: FilterSpec, overwrite: boolean) {
    const clean = name.trim().split(/\s+/).join(" ");
    if (!clean) throw new ApiCallError({ code: "invalid_argument", message: "Give the preset a name.", retryable: false });
    const existing = [...this.presets.keys()].find((k) => k.toLowerCase() === clean.toLowerCase());
    if (existing && !overwrite) {
      throw new ApiCallError({
        code: "conflict",
        message: `A preset called "${existing}" already exists. Replace it, or pick another name.`,
        retryable: false,
      });
    }
    validate(spec);
    if (existing) this.presets.delete(existing);
    const preset = { name: clean, spec, error: null, updated_at: "2026-11-01T12:00:00" };
    this.presets.set(clean, preset);
    return preset;
  }

  async renamePreset(oldName: string, newName: string) {
    const p = this.presets.get(oldName);
    if (!p) throw new ApiCallError({ code: "not_found", message: `There's no preset called "${oldName}".`, retryable: false });
    const clash = [...this.presets.keys()].find((k) => k.toLowerCase() === newName.trim().toLowerCase() && k !== oldName);
    if (clash) throw new ApiCallError({ code: "conflict", message: `A preset called "${clash}" already exists.`, retryable: false });
    this.presets.delete(oldName);
    this.presets.set(newName.trim(), { ...p, name: newName.trim() });
  }

  async deletePreset(name: string) {
    if (!this.presets.delete(name)) {
      throw new ApiCallError({ code: "not_found", message: `There's no preset called "${name}".`, retryable: false });
    }
  }

  async startSession(spec: FilterSpec): Promise<SessionInfo> {
    validate(spec);
    const pools = spec.ratios.length > 0 ? spec.ratios.map((_, i) => this.pool(bucketSpec(spec, i))) : [this.pool(spec)];
    const queue = interleave(pools, spec);
    if (queue.length === 0) {
      throw new ApiCallError({
        code: "invalid_argument",
        message: "No puzzles match these filters. Widen them and try again.",
        retryable: false,
      });
    }
    const id = this.nextSession++;
    this.sessions.set(id, { spec, queue, served: 0, current: null, solved: 0, failed: 0 });
    const empty = spec.ratios.length > 0 ? pools.flatMap((p, i) => (p.length === 0 ? [i] : [])) : [];
    return { session_id: id, match_count: queue.length * SCALE, queue_size: spec.queue_size, empty_buckets: empty };
  }

  private session(id: number): MockSession {
    const s = this.sessions.get(id);
    if (!s) throw new ApiCallError({ code: "not_found", message: "That session has ended.", retryable: false });
    return s;
  }

  async nextPuzzle(sessionId: number): Promise<PuzzleView | null> {
    const s = this.session(sessionId);
    if (s.current && !s.current.decided) {
      s.failed++;
      this.allTime.failed++;
      this.record(s.current.puzzle, false);
    }
    s.current = null;
    const limit = s.spec.queue_size ?? Infinity;
    if (s.served >= limit || s.served >= s.queue.length) return null;
    const puzzle = s.queue[s.served++];
    const chess = new Chess(puzzle.fen);
    chess.move(uciToMove(puzzle.moves[0]));
    s.current = { puzzle, chess, start: chess.fen(), next: 1, decided: false, failed: false, hinted: false, finished: false };
    return {
      number: s.served,
      puzzle_id: puzzle.id,
      fen: puzzle.fen,
      opponent_move: puzzle.moves[0],
      player_color: chess.turn() === "w" ? "white" : "black",
      rating: puzzle.rating,
    };
  }

  async submitMove(sessionId: number, uci: string): Promise<MoveFeedback> {
    const s = this.session(sessionId);
    const c = s.current;
    if (!c) throw new ApiCallError({ code: "invalid_argument", message: "There's no puzzle in progress.", retryable: false });
    if (c.finished) return { kind: "illegal", reply: null, finished: true, outcome: null };
    const expected = c.puzzle.moves[c.next];
    let ok = uci === expected;
    if (!ok) {
      const probe = new Chess(c.chess.fen());
      const exp = new Chess(c.chess.fen());
      try {
        probe.move(uciToMove(uci));
        exp.move(uciToMove(expected));
        ok = exp.isCheckmate() && probe.isCheckmate();
      } catch {
        return { kind: "illegal", reply: null, finished: false, outcome: null };
      }
    }
    if (!ok) {
      if (c.decided) return { kind: "wrong", reply: null, finished: false, outcome: null };
      c.decided = c.failed = true;
      s.failed++;
      this.allTime.failed++;
      this.record(c.puzzle, false);
      return { kind: "wrong", reply: null, finished: false, outcome: this.outcome(c.puzzle, false) };
    }
    c.chess.move(uciToMove(uci));
    c.next++;
    if (c.next >= c.puzzle.moves.length || c.chess.isCheckmate()) {
      c.finished = true;
      const outcome = c.decided ? null : this.outcome(c.puzzle, true);
      if (!c.decided) {
        c.decided = true;
        s.solved++;
        this.allTime.solved++;
        this.record(c.puzzle, true);
      }
      return { kind: "solved", reply: null, finished: true, outcome };
    }
    const reply = c.puzzle.moves[c.next++];
    c.chess.move(uciToMove(reply));
    return { kind: "correct", reply, finished: false, outcome: null };
  }

  async requestHelp(sessionId: number, kind: "hint" | "answer"): Promise<HelpResponse> {
    const s = this.session(sessionId);
    const c = s.current;
    const conflict = (message: string) => new ApiCallError({ code: "conflict", message, retryable: false });
    if (!c) throw new ApiCallError({ code: "invalid_argument", message: "There's no puzzle in progress.", retryable: false });
    const decide = () => {
      if (c.decided) return null;
      c.decided = c.failed = true;
      s.failed++;
      this.allTime.failed++;
      this.record(c.puzzle, false);
      return this.outcome(c.puzzle, false);
    };
    if (kind === "hint") {
      if (c.finished) throw conflict("The puzzle is over: there's nothing left to hint.");
      const outcome = decide();
      c.hinted = true;
      return { kind, hint_square: c.puzzle.moves[c.next].slice(0, 2), answer_fen: null, answer_moves: [], outcome };
    }
    if (c.finished) return { kind, hint_square: null, answer_fen: c.start, answer_moves: c.puzzle.moves.slice(1), outcome: null };
    if (!c.decided && !c.hinted) throw conflict("Try a Hint first: Show answer unlocks after it.");
    const outcome = decide();
    c.finished = true;
    return { kind, hint_square: null, answer_fen: c.chess.fen(), answer_moves: c.puzzle.moves.slice(c.next), outcome };
  }

  private outcome(p: MockPuzzle, win: boolean) {
    return {
      win,
      puzzle_id: p.id,
      rating: p.rating,
      themes: p.themes.map((key) => ({ key, name: NAMES.get(key) ?? key })),
      solution: p.moves.slice(1),
      puzzle_url: `https://lichess.org/training/${p.id}`,
    };
  }

  async getSessionStats(sessionId: number): Promise<SessionStats> {
    const s = this.session(sessionId);
    const played = s.solved + s.failed;
    const limit = Math.min(s.spec.queue_size ?? Infinity, s.queue.length);
    return {
      solved: s.solved,
      failed: s.failed,
      accuracy: played ? s.solved / played : null,
      played,
      queue_size: s.spec.queue_size,
      finished: played >= limit,
      all_time_solved: this.allTime.solved,
      all_time_failed: this.allTime.failed,
    };
  }

  onEvent(listener: (event: BackendEvent) => void) {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }
}

// The mock's queue: ratio groups taken in turn (no repeats), then the chosen order (FR-3.10, 3.11).
function interleave(pools: MockPuzzle[][], spec: FilterSpec): MockPuzzle[] {
  const seen = new Set<string>();
  const out: MockPuzzle[] = [];
  const idx = pools.map(() => 0);
  let added = true;
  while (added) {
    added = false;
    pools.forEach((pool, i) => {
      while (idx[i] < pool.length && seen.has(pool[idx[i]].id)) idx[i]++;
      if (idx[i] < pool.length) {
        seen.add(pool[idx[i]].id);
        out.push(pool[idx[i]++]);
        added = true;
      }
    });
  }
  if (spec.order === "easy_to_hard") out.sort((a, b) => a.rating - b.rating);
  if (spec.order === "by_theme" && spec.themes.length > 0) {
    const group = (p: MockPuzzle) => {
      const i = spec.themes.findIndex((t) => p.themes.includes(t));
      return i < 0 ? spec.themes.length : i;
    };
    out.sort((a, b) => group(a) - group(b));
  }
  return out;
}

function uciToMove(uci: string) {
  return { from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci.length > 4 ? uci[4] : undefined };
}
