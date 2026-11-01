// Mock client with fixed data, for UI development (`npm.cmd --prefix web run dev -- --mode mock`)
// and for Playwright. Deterministic: no clock-dependent data and no randomness, so screenshots are stable.
//
// Scenario via the page URL: `?scenario=empty` starts with no puzzle database imported.
import { Chess } from "chess.js";
import type { ApiClient, BackendEvent } from "./ApiClient";
import { ApiCallError } from "./ApiClient";
import { MOCK_PUZZLES, type MockPuzzle } from "./mockPuzzles";
import type {
  AppInfo,
  FilterSpec,
  Job,
  MoveFeedback,
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
};

const EMPTY: PuzzleDbStatus = {
  installed: false,
  puzzle_count: null,
  export_date: null,
  imported_at: null,
  rating_min: null,
  rating_max: null,
  import_job_id: null,
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
  return !spec.exclude_themes.some((t) => p.themes.includes(t));
}

interface MockSession {
  spec: FilterSpec;
  queue: MockPuzzle[];
  served: number;
  current: { puzzle: MockPuzzle; chess: Chess; next: number; decided: boolean; failed: boolean } | null;
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
  readonly calls: string[] = [];

  constructor(search: string = typeof window !== "undefined" ? window.location.search : "") {
    const scenario = new URLSearchParams(search).get("scenario");
    this.status = scenario === "empty" ? { ...EMPTY } : { ...INSTALLED };
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
    return MOCK_PUZZLES.filter((p) => matches(p, spec)).length * SCALE;
  }

  async startSession(spec: FilterSpec): Promise<SessionInfo> {
    const queue = MOCK_PUZZLES.filter((p) => matches(p, spec));
    if (queue.length === 0) {
      throw new ApiCallError({
        code: "invalid_argument",
        message: "No puzzles match these filters. Widen them and try again.",
        retryable: false,
      });
    }
    const id = this.nextSession++;
    this.sessions.set(id, { spec, queue, served: 0, current: null, solved: 0, failed: 0 });
    return { session_id: id, match_count: queue.length * SCALE, queue_size: spec.queue_size };
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
    }
    s.current = null;
    const limit = s.spec.queue_size ?? Infinity;
    if (s.served >= limit || s.served >= s.queue.length) return null;
    const puzzle = s.queue[s.served++];
    const chess = new Chess(puzzle.fen);
    chess.move(uciToMove(puzzle.moves[0]));
    s.current = { puzzle, chess, next: 1, decided: false, failed: false };
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
      return { kind: "wrong", reply: null, finished: false, outcome: this.outcome(c.puzzle, false) };
    }
    c.chess.move(uciToMove(uci));
    c.next++;
    if (c.next >= c.puzzle.moves.length || c.chess.isCheckmate()) {
      const outcome = c.decided ? null : this.outcome(c.puzzle, true);
      if (!c.decided) {
        c.decided = true;
        s.solved++;
        this.allTime.solved++;
      }
      return { kind: "solved", reply: null, finished: true, outcome };
    }
    const reply = c.puzzle.moves[c.next++];
    c.chess.move(uciToMove(reply));
    return { kind: "correct", reply, finished: false, outcome: null };
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

function uciToMove(uci: string) {
  return { from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci.length > 4 ? uci[4] : undefined };
}
