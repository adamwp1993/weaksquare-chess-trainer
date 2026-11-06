// Mock client with fixed data, for UI development (`npm.cmd --prefix web run dev -- --mode mock`)
// and for Playwright. Deterministic: no clock-dependent data and no randomness, so screenshots are stable.
//
// Scenarios via the page URL: `?scenario=empty` starts with no puzzle database imported, and
// `?scenario=upgrade` with a v0.1 database that needs the local upgrade, and `?scenario=update`
// with a newer puzzle export to offer (FR-2.5).
// Lichess (v0.3): `?account=signed_out|offline|expired` (default: signed in as "your_name"),
// `?signin=fail` makes Sign in fail, `?revoke=offline` makes Sign out unable to reach Lichess, and
// `?sync=slow` holds every solve at "Syncing…" until the test calls `window.__mockSyncNow()`, and
// `?played=1` puts the second mock puzzle in your Lichess history (the "already played" badge).
// Stockfish (v0.4): `?engine=missing` starts with no engine installed (the Install banner),
// `?engine=custom` with your own engine set, `?engine=custom_missing` with that engine's file gone,
// and `?engine=slow` makes every analysis take 1.5 s.
// Training modes (v0.5): `?srs=none` starts with nothing due for Spaced repetition (default: two
// puzzles due), `?dev=1` behaves like a --dev run (Settings → Debug → fast-forward time), and
// `?mode=commit_line|name_idea|danger_spotting|spaced_repetition` starts on that mode.
// v0.6: Danger spotting alternates safe and blunder candidates (the first is safe); `?reasons=off`
// starts with the mistake-reason question turned off.
// v0.7: the AI settings and Explain live in mockLlm.ts (`?ai=on|warn|over|failed|nomodel`).
// v0.8: the game library, Review and puzzle files live in mockGames.ts (`?games=empty`, `?chesscom=…`,
// `?file=none`, `?mine=1` starts with one imported puzzle of your own).
// v0.10: the Coach lives in mockCoach.ts (`?coach=report` starts with one report, `?coach=banner` also with a
// suggestion waiting behind the banner); `?showbest=1` starts with Show best moves on.
import { Chess } from "chess.js";
import type {
  AnalysisPurpose,
  ApiClient,
  BackendEvent,
  EngineSettingsChange,
  GamesSettingsChange,
  LibraryFilters,
  LlmPriceChange,
  LlmProvider,
  LlmSettingsChange,
  ReasonKey,
  ReasonSource,
  SettingValues,
  TrainingMode,
  JournalEntryInput,
  JournalFilters,
  PlanParams,
} from "./ApiClient";
import { ApiCallError, type CoachAiOptions, type CoachParams } from "./ApiClient";
import { mockAnalysis } from "./mockEngine";
import { MockCoach } from "./mockCoach";
import { MockOpenings } from "./mockOpenings";
import { MockPlan } from "./mockPlan";
import { defaultFilters } from "../state/filters";
import { gameNarrative, moveExplanation } from "./mockGameAi";
import { MockGames } from "./mockGames";
import { type ExplainTarget, MockLlm } from "./mockLlm";
import { MOCK_PUZZLES, type MockPuzzle } from "./mockPuzzles";
import type {
  AccountStatus,
  Analysis,
  AppInfo,
  AttemptRating,
  BucketCounts,
  CoachJournalLine,
  CommitFeedback,
  DangerFeedback,
  DangerReveal,
  EngineSettings,
  EngineStatus,
  Explanation,
  FilterSpec,
  GameNarrative,
  GameReview,
  HelpResponse,
  IdeaResult,
  Job,
  LadderInfo,
  LadderPreview,
  LlmSettings,
  MoveFeedback,
  OpeningFamily,
  PlyGrade,
  Preset,
  PuzzleDbStatus,
  PuzzleView,
  RatingHistory,
  ReasonPrompt,
  ReasonStats,
  Refutation,
  ReviewMove,
  SessionInfo,
  SessionStats,
  SrsStatus,
  StatRow,
  StatsReport,
  SyncStatus,
  ThemeGroup,
  UiSettings,
  UpdateOffer,
  OpeningScope,
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
  const fail = (message: string) => {
    throw new ApiCallError({ code: "invalid_argument", message, retryable: false });
  };
  if (spec.order === "depth_ladder" && spec.ratios.length > 0) fail("The depth ladder can't be combined with ratios: pick themes instead.");
  if (spec.ratios.length === 0) return;
  if (spec.themes.length > 0) fail("With ratios, the themes come from each ratio: clear the theme list.");
  if (spec.ratios.length < 2) fail("Ratios need between 2 and 10 groups.");
  if (spec.ratios.some((b) => b.themes.length === 0)) fail("Each ratio needs at least one valid theme.");
  const total = spec.ratios.reduce((a, b) => a + b.weight, 0);
  if (total !== 100) fail(`The ratios must add up to 100% (they add up to ${total}%).`);
}

function bucketSpec(spec: FilterSpec, i: number): FilterSpec {
  return { ...spec, themes: spec.ratios[i].themes, match: "any", ratios: [] };
}

// The mock's Lichess rating history (FR-9.4): fixed points, so the Stats chart is stable.
const RATING_POINTS: [string, number, number][] = [
  ["2026-10-20T19:05:00", 1772, 1], ["2026-10-20T19:31:00", 1788, 1], ["2026-10-22T20:10:00", 1781, 2],
  ["2026-10-22T20:40:00", 1799, 2], ["2026-10-25T18:15:00", 1806, 3], ["2026-10-25T18:52:00", 1795, 3],
  ["2026-10-28T21:00:00", 1813, 4], ["2026-10-28T21:33:00", 1826, 4], ["2026-10-31T17:20:00", 1834, 5],
]; // prettier-ignore
const MOCK_USER = "your_name";
const LEVELS = [2, 3, 4];
const LEVEL_NAMES: Record<number, string> = { 2: "Short", 3: "Long", 4: "Very long" };

// Depth ladder (FR-4.5): the same key as core/ladder.py, so a theme set keeps its level.
function ladderKey(spec: FilterSpec): string {
  const themes = [...spec.themes].sort();
  const match = themes.length > 1 ? spec.match : "any";
  return JSON.stringify({ exclude: [...spec.exclude_themes].sort(), match, themes });
}

function atLevel(spec: FilterSpec, level: number): FilterSpec {
  return { ...spec, lengths: [level], order: "random" };
}

// Commit the line (FR-4.2): the same grading as core/modes/commit_line.py.
function gradeLine(start: string, solution: string[], line: string[]): { grades: PlyGrade[]; extra: string[]; firstWrong: [string, string] | null } {
  const grades: PlyGrade[] = [];
  const board = new Chess(start);
  let same = true;
  let end = solution.length;
  let firstWrong: [string, string] | null = null;
  for (let i = 0; i < solution.length; i++) {
    const expected = solution[i];
    const mine = i < line.length ? line[i] : null;
    const player = i % 2 === 0;
    let correct = mine === expected;
    if (player && !correct && mine !== null && same) {
      const probe = new Chess(board.fen());
      const exp = new Chess(board.fen());
      probe.move(uciToMove(mine));
      exp.move(uciToMove(expected));
      correct = exp.isCheckmate() && probe.isCheckmate();
      if (!correct) firstWrong ??= [board.fen(), mine];
    }
    grades.push({ played: mine, expected, player, correct });
    if (same && mine !== null && correct && mine !== expected) {
      end = i + 1;
      break;
    }
    if (same && mine === expected) board.move(uciToMove(expected));
    else same = false;
  }
  return { grades, extra: line.slice(end), firstWrong };
}
// The motif themes Name the idea grades against (core/themes.py motif_themes), for the mock's puzzles.
const MOCK_MOTIFS = new Set([
  "fork", "hangingPiece", "discoveredAttack", "kingsideAttack", "advancedPawn", "quietMove", "promotion",
  "enPassant", "pin", "skewer", "deflection", "attraction", "sacrifice",
]);
const REASON_OPTIONS: ReasonPrompt["reasons"] = [
  { key: "didntLook", label: "Didn't look for it", gap: "process" },
  { key: "missedResource", label: "Missed their reply / defense / threat", gap: "process" },
  { key: "miscalculated", label: "Saw the idea, calculated it wrong", gap: "calculation" },
  { key: "unknownPattern", label: "Didn't know this pattern", gap: "knowledge" },
  { key: "rushed", label: "Rushed / time pressure", gap: "time" },
  { key: "misclick", label: "Misclick", gap: "noise" },
];
const MANAGED_PATH = "C:\\Users\\you\\AppData\\Local\\WeakSquare\\engines\\sf_19\\stockfish.exe";
const CUSTOM_PATH = "C:\\Engines\\my-stockfish.exe";

interface MockSession {
  spec: FilterSpec;
  rated: boolean;
  mode: TrainingMode;
  showLength: boolean;
  ladder: { base: FilterSpec; key: string } | null;
  attempts: number[];
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
    firstWrong: [string, string] | null; // (FEN before, UCI): what Show answer refutes (§7.2)
    practice?: boolean; // Try again (FR-5.12): `decided` from the start, so nothing is recorded
    submitted?: boolean; // Commit the line: the line was graded
    tags?: { setup: string[]; payoff: string[] } | null; // Name the idea: null until tagged
    danger?: { candidate: string; safe: boolean; phase: "call" | "refute" | "done"; call: "safe" | "unsafe" | null };
    lostAttempt?: number; // the recorded loss, for the reason chips
    suggested?: ReasonKey | null;
    idea?: IdeaResult | null;
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
  private settings: UiSettings = {
    last_filters: null,
    coordinates: true,
    color_scheme: "light",
    sounds: { on: true, volume: 70, set: "sfx" },
    auto_check: true,
    mode: "standard",
    show_length: false,
    ladder_threshold: 80,
    ladder_window: 20,
    srs_intervals: [1, 3, 7, 14, 30],
    filters_collapsed: false,
    time_offset_days: null,
    reasons_ask: "always",
    rushed_s: 3,
    show_best: false,
    lesson_sites: ["youtube", "chesscom"],
    lesson_custom_url: "",
  };
  private reasons = new Map<number, ReasonKey>(); // attempt id -> its latest reason (§7.3)
  private attemptSession = new Map<number, { session: number; win: boolean; mode: TrainingMode }>();
  // Spaced repetition: what's due now, and misses waiting for tomorrow (moved in by fast-forward).
  private srsDue: MockPuzzle[] = [MOCK_PUZZLES[2], MOCK_PUZZLES[3]];
  private srsLater: MockPuzzle[] = [];
  private srsBoxes = 3; // scheduled but not due, beyond the lists above
  private ladders = new Map<string, { level: number; recent: boolean[] }>();
  private allTime = { solved: 41, failed: 17 };
  private presets = new Map<string, Preset>();
  private offer: UpdateOffer | null = null;
  private history = new Map<string, boolean[]>(); // puzzle id -> results here, oldest first
  private account: AccountStatus = { state: "signed_in", username: MOCK_USER, rating: 1834, provisional: false };
  private lichessHistory = new Set<string>(); // puzzles "played on Lichess"
  private ratings = new Map<number, AttemptRating>();
  private attemptPuzzle = new Map<number, { id: string; win: boolean; rated: boolean }>();
  private queuedPuzzles = new Set<string>(); // sent or waiting: Lichess will have seen these
  private nextAttempt = 1;
  private points: [string, number, number][] = [...RATING_POINTS];
  private slowSync = false;
  private engine: EngineStatus = {
    state: "ready",
    source: "managed",
    name: "Stockfish 19",
    path: MANAGED_PATH,
    tag: "sf_19",
    install_job_id: null,
    message: null,
  };
  private engineSettings: EngineSettings = { think_s: 1, threads: 7, hash_mb: 256, custom_path: null, max_threads: 8 };
  private engineDelay = 250;
  private latest = new Map<string, number>(); // latest-wins per purpose, like the backend
  private signInFails = false;
  private revokeOffline = false;
  readonly calls: string[] = [];
  private readonly llm: MockLlm;
  private readonly games: MockGames;
  private readonly coach: MockCoach;
  private readonly plan: MockPlan;
  private readonly openings = new MockOpenings();

  constructor(search: string = typeof window !== "undefined" ? window.location.search : "") {
    const params = new URLSearchParams(search);
    this.llm = new MockLlm(params, (job) => this.emit(job), () => `job-${this.nextJob++}`);
    this.games = new MockGames(params, (job) => this.emit(job), () => `job-${this.nextJob++}`,
      () => (this.account.state === "signed_in" ? this.account.username : null)); // prettier-ignore
    this.coach = new MockCoach(params, {
      emit: (job) => this.emit(job),
      jobId: () => `job-${this.nextJob++}`,
      calls: this.calls,
      filters: () => this.settings.last_filters,
      setFilters: (spec, mode) => {
        this.settings = { ...this.settings, last_filters: spec, mode: mode as TrainingMode };
      },
      quote: (kind, what) => this.llm.gameQuote(kind, what),
      startAi: (kind, what, make) => this.llm.startGame(kind, what, make),
      aiPlan: () => this.plan.aiPlan(),
    });
    this.plan = new MockPlan(params, {
      calls: this.calls,
      hasReport: () => this.coach.list().some((r) => r.is_me),
      startSession: (spec, rated, mode) =>
        this.startSession({ ...defaultFilters(), ...spec } as FilterSpec, rated, mode as TrainingMode, false),
    });
    if (typeof window !== "undefined") {
      (window as unknown as { __mockPlanProgress: (id: number, n: number) => void }).__mockPlanProgress = (id, n) => this.plan.progress(id, n);
    }
    if (params.get("showbest") === "1") this.settings.show_best = true;
    const scenario = params.get("scenario");
    // ?scheme=dark|auto starts the mock in that saved scheme; ?sounds=off with sounds off.
    const scheme = params.get("scheme");
    if (scheme === "dark" || scheme === "auto") this.settings.color_scheme = scheme;
    if (params.get("sounds") === "off") this.settings.sounds = { ...this.settings.sounds, on: false };
    if (params.get("srs") === "none") this.srsDue = [];
    if (params.get("dev") === "1") this.settings.time_offset_days = 0;
    const mode = params.get("mode");
    if (mode === "commit_line" || mode === "spaced_repetition" || mode === "name_idea" || mode === "danger_spotting") {
      this.settings.mode = mode;
    }
    if (params.get("reasons") === "off") this.settings.reasons_ask = "off";
    const account = params.get("account");
    if (account === "signed_out") this.account = { state: "signed_out", username: null, rating: null, provisional: false };
    if (account === "offline") this.account = { state: "offline", username: MOCK_USER, rating: null, provisional: false };
    if (account === "expired") this.account = { state: "expired", username: MOCK_USER, rating: null, provisional: false };
    if (params.get("played") === "1") this.lichessHistory.add(MOCK_PUZZLES[1].id);
    this.slowSync = params.get("sync") === "slow";
    this.signInFails = params.get("signin") === "fail";
    this.revokeOffline = params.get("revoke") === "offline";
    const engine = params.get("engine");
    if (engine === "missing") {
      this.engine = { ...this.engine, state: "not_installed", source: null, name: null, path: null, message: "Stockfish isn't installed." };
    }
    if (engine === "custom") {
      this.engine = { ...this.engine, source: "custom", name: "Stockfish 18", path: CUSTOM_PATH };
      this.engineSettings = { ...this.engineSettings, custom_path: CUSTOM_PATH };
    }
    if (engine === "slow") this.engineDelay = 1500;
    if (engine === "custom_missing") {
      const message = "Your custom engine can't be found. Choose it again, or switch back to the managed Stockfish.";
      this.engine = { ...this.engine, state: "custom_invalid", source: "custom", name: "Stockfish 18", path: CUSTOM_PATH, message };
      this.engineSettings = { ...this.engineSettings, custom_path: CUSTOM_PATH };
    }
    if (typeof window !== "undefined") {
      (window as unknown as { __mockSyncNow: () => void }).__mockSyncNow = () => this.drain();
    }
    this.status =
      scenario === "empty" ? { ...EMPTY } : scenario === "upgrade" ? { ...INSTALLED, needs_upgrade: true } : { ...INSTALLED };
    if (scenario === "update") {
      this.offer = {
        export_date: "2026-11-01",
        current_export_date: "2026-10-02",
        size: 309_751_173,
        approx_count: 6_193_530,
        approx_new: 36_189,
      };
    }
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
    if (spec.exclude_played_on_lichess && this.lichessHistory.has(p.id)) return false;
    if (spec.exclude_solved_here) return !h.includes(true);
    return true;
  }

  // ---- Lichess (v0.3) -----------------------------------------------------------------------
  private pushAccount() {
    const payload = { ...this.account };
    this.listeners.forEach((l) => l({ name: "account", payload }));
  }

  private syncStatusNow(): SyncStatus {
    const pending = [...this.ratings.values()].filter((r) => r.status === "syncing" || r.status === "offline").length;
    const state = this.account.state === "signed_in" ? "idle" : this.account.state === "offline" ? "offline" : "signed_out";
    return { state, pending, history_count: this.account.state === "signed_out" ? 0 : this.lichessHistory.size + 1244 };
  }

  private pushSync(attempts: AttemptRating[]) {
    const payload = { status: this.syncStatusNow(), attempts };
    this.listeners.forEach((l) => l({ name: "sync", payload }));
  }

  /** Queue one attempt (FR-6.16) and say what the result panel shows right away. */
  private queue(p: MockPuzzle, win: boolean, rated: boolean, s: MockSession): { id: number; info: AttemptRating } {
    const id = this.nextAttempt++;
    s.attempts.push(id);
    const played = this.lichessHistory.has(p.id) || this.queuedPuzzles.has(p.id);
    const online = this.account.state === "signed_in";
    const status: AttemptRating["status"] = !rated ? "unrated" : played ? "already_played" : online ? "syncing" : "offline";
    const info: AttemptRating = { attempt_id: id, status, diff: null };
    this.ratings.set(id, info);
    this.attemptPuzzle.set(id, { id: p.id, win, rated: rated && !played });
    this.queuedPuzzles.add(p.id);
    if (online && !this.slowSync) setTimeout(() => this.drain(), 400);
    return { id, info };
  }

  /** The mock's sync: Lichess "returns" +8 for a win and -12 for a loss (rated, first attempts only). */
  private drain() {
    if (this.account.state !== "signed_in") return;
    const changed: AttemptRating[] = [];
    for (const [id, r] of this.ratings) {
      if (r.status !== "syncing" && r.status !== "offline") continue;
      const a = this.attemptPuzzle.get(id)!;
      const diff = a.rated ? (a.win ? 8 : -12) : 0;
      const next: AttemptRating = diff ? { attempt_id: id, status: "done", diff } : { attempt_id: id, status: "not_rated", diff: null };
      this.ratings.set(id, next);
      this.lichessHistory.add(a.id); // like the app: a synced solve counts as played on Lichess
      changed.push(next);
      if (diff && this.account.rating !== null) {
        const rating = this.account.rating + diff;
        this.account = { ...this.account, rating };
        this.points.push([`2026-11-01T12:${String(10 + this.points.length).padStart(2, "0")}:00`, rating, 6]);
      }
    }
    if (changed.length) {
      this.pushSync(changed);
      this.pushAccount();
    }
  }

  async getAccountStatus() {
    return { ...this.account };
  }

  async startSignIn() {
    const id = `job-${this.nextJob++}`;
    this.calls.push("signIn");
    this.emit({ id, kind: "lichess_sign_in", state: "running", progress: null, message: "Waiting for you to approve in your browser…", error_code: null });
    setTimeout(() => {
      if (this.jobs.get(id)?.state !== "running") return;
      if (this.signInFails) {
        this.emit({ id, kind: "lichess_sign_in", state: "failed", progress: null, message: "Sign-in failed: Lichess refused the request. Try again.", error_code: "sign_in_failed" });
        return;
      }
      this.account = { state: "signed_in", username: MOCK_USER, rating: 1834, provisional: false };
      this.pushAccount();
      this.emit({ id, kind: "lichess_sign_in", state: "done", progress: 1, message: `Signed in as ${MOCK_USER}`, error_code: null });
      this.drain();
    }, 600);
    return id;
  }

  async cancelSignIn() {
    const running = [...this.jobs.values()].find((j) => j.kind === "lichess_sign_in" && j.state === "running");
    if (running) this.emit({ ...running, state: "cancelled", message: "Cancelled" });
  }

  async signOut(forceLocal: boolean) {
    this.calls.push(`signOut:${forceLocal}`);
    if (this.revokeOffline && !forceLocal) {
      throw new ApiCallError({ code: "revoke_failed", message: "Lichess couldn't be reached, so the sign-in wasn't revoked there.", retryable: true });
    }
    this.account = { state: "signed_out", username: null, rating: null, provisional: false };
    this.pushAccount();
    this.pushSync([]);
  }

  async getSyncStatus() {
    return this.syncStatusNow();
  }

  async getAttemptRatings(attemptIds: number[]) {
    return attemptIds.flatMap((id) => {
      const r = this.ratings.get(id);
      return r ? [{ ...r }] : [];
    });
  }

  async getRatingHistory(): Promise<RatingHistory> {
    if (this.account.state === "signed_out" && this.points.length === RATING_POINTS.length) {
      return { points: [], sessions: [] };
    }
    const points = this.points.map(([at, rating, session_id]) => ({ at, rating, session_id }));
    const sessions = [1, 2, 3, 4, 5, 6].flatMap((sid) => {
      const mine = points.filter((p) => p.session_id === sid);
      if (mine.length === 0) return [];
      const before = points[points.indexOf(mine[0]) - 1]?.rating ?? 1764;
      return [{ session_id: sid, started_at: mine[0].at, change: mine[mine.length - 1].rating - before, solves: mine.length * 4 }];
    });
    return { points, sessions };
  }

  private pool(spec: FilterSpec) {
    return MOCK_PUZZLES.filter((p) => matches(p, spec) && this.matchesHistory(p, spec));
  }

  private record(p: MockPuzzle, win: boolean, s?: MockSession): LadderInfo | null {
    this.history.set(p.id, [...(this.history.get(p.id) ?? []), win]);
    if (!win && !this.srsLater.some((q) => q.id === p.id)) this.srsLater.push(p); // due tomorrow (FR-4.6)
    if (s?.mode === "spaced_repetition") {
      this.srsDue = this.srsDue.filter((q) => q.id !== p.id); // reviewed: due again later, or moved up a box
      if (win) this.srsBoxes++;
    }
    if (!s?.ladder) return null;
    const st = this.ladderState(s.ladder.key);
    st.recent.push(win);
    const window = this.settings.ladder_window;
    const recent = st.recent.slice(-window);
    const wins = recent.filter(Boolean).length;
    if (st.level < 4 && recent.length >= window && wins * 100 >= this.settings.ladder_threshold * window) {
      st.level++;
      st.recent = [];
      s.spec = atLevel(s.ladder.base, st.level);
      s.queue = s.queue.slice(0, s.served).concat(this.pool(s.spec).filter((q) => !s.queue.slice(0, s.served).includes(q)));
      return this.ladderInfo(s.ladder.key);
    }
    return null;
  }

  private ladderState(key: string) {
    let st = this.ladders.get(key);
    if (!st) {
      st = { level: 2, recent: [] };
      this.ladders.set(key, st);
    }
    return st;
  }

  private ladderInfo(key: string): LadderInfo {
    const st = this.ladderState(key);
    const window = this.settings.ladder_window;
    const recent = st.recent.slice(-window);
    return {
      level: st.level,
      label: LEVEL_NAMES[st.level],
      step: LEVELS.indexOf(st.level) + 1,
      steps: LEVELS.length,
      played: recent.length,
      wins: recent.filter(Boolean).length,
      window,
      threshold: this.settings.ladder_threshold,
      top: st.level === 4,
    };
  }

  async getLadderStatus(spec: FilterSpec): Promise<LadderPreview> {
    const ladder = this.ladderInfo(ladderKey(spec));
    return { ladder, match_count: this.pool(atLevel(spec, ladder.level)).length * SCALE };
  }

  async getSrsStatus(): Promise<SrsStatus> {
    return {
      due: this.srsDue.length,
      next_due: this.srsLater.length > 0 ? "2026-11-03" : "2026-11-05",
      scheduled: this.srsDue.length + this.srsLater.length + this.srsBoxes,
    };
  }

  async setTimeOffset(days: number) {
    if (this.settings.time_offset_days === null) {
      throw new ApiCallError({ code: "conflict", message: "Fast-forward time is only available in --dev runs.", retryable: false });
    }
    this.calls.push(`timeOffset:${days}`);
    if (days > (this.settings.time_offset_days ?? 0)) {
      this.srsDue.push(...this.srsLater);
      this.srsLater = [];
    }
    this.settings = { ...this.settings, time_offset_days: days };
  }

  private emit(job: Job) {
    this.jobs.set(job.id, job);
    this.listeners.forEach((l) => l({ name: "job", payload: job }));
  }

  // ---- Stockfish (v0.4) -----------------------------------------------------------------------
  async getEngineStatus() {
    return { ...this.engine };
  }

  async startEngineInstall(force: boolean) {
    if (this.engine.install_job_id) {
      throw new ApiCallError({ code: "conflict", message: "Stockfish is already being installed.", retryable: true });
    }
    const id = `job-${this.nextJob++}`;
    this.calls.push(`engineInstall:${force}`);
    this.engine = { ...this.engine, install_job_id: id };
    const kind = "stockfish_install";
    const steps: [number, string][] = [
      [0.2, "Downloading Stockfish… 16 MB"],
      [0.6, "Downloading Stockfish… 48 MB"],
      [0.88, "Verifying the download…"],
      [0.95, "Testing Stockfish…"],
    ];
    this.emit({ id, kind, state: "running", progress: 0, message: "Downloading Stockfish…", error_code: null });
    steps.forEach(([progress, message], i) => {
      setTimeout(() => {
        if (this.jobs.get(id)?.state !== "running") return;
        this.emit({ id, kind, state: "running", progress, message, error_code: null });
      }, 150 * (i + 1));
    });
    setTimeout(
      () => {
        if (this.jobs.get(id)?.state !== "running") return;
        this.engine = {
          ...this.engine,
          state: "ready",
          source: "managed",
          name: "Stockfish 19",
          path: MANAGED_PATH,
          install_job_id: null,
          message: null,
        };
        this.emit({ id, kind, state: "done", progress: 1, message: "Stockfish is installed.", error_code: null });
      },
      150 * (steps.length + 1),
    );
    return id;
  }

  async getEngineSettings() {
    return { ...this.engineSettings };
  }

  async setEngineSettings(change: EngineSettingsChange) {
    const bad = (message: string) => new ApiCallError({ code: "invalid_argument", message, retryable: false });
    const { think_s, threads, hash_mb } = change;
    if (think_s !== undefined && !(think_s >= 0.2 && think_s <= 10)) throw bad("Think time must be between 0.2 and 10 seconds.");
    const max = this.engineSettings.max_threads;
    if (threads !== undefined && !(Number.isInteger(threads) && threads >= 1 && threads <= max)) {
      throw bad(`Threads must be a whole number from 1 to ${max}.`);
    }
    if (hash_mb !== undefined && !(Number.isInteger(hash_mb) && hash_mb >= 16 && hash_mb <= 2048)) {
      throw bad("Hash must be a whole number of MB from 16 to 2048.");
    }
    this.engineSettings = { ...this.engineSettings, ...change };
    this.calls.push(`engineSettings:${JSON.stringify(change)}`);
    return { ...this.engineSettings };
  }

  async chooseEngineFile() {
    return CUSTOM_PATH;
  }

  async startCustomEngineCheck(path: string) {
    const id = `job-${this.nextJob++}`;
    const kind = "engine_check";
    this.emit({ id, kind, state: "running", progress: null, message: "Testing the engine…", error_code: null });
    setTimeout(() => {
      if (path.toLowerCase().includes("broken")) {
        const message = "That engine didn't pass the test, so it wasn't saved. (no uciok)";
        this.emit({ id, kind, state: "failed", progress: null, message, error_code: "smoke_test_failed" });
        return;
      }
      this.engine = { ...this.engine, state: "ready", source: "custom", name: "Stockfish 18", path, message: null };
      this.engineSettings = { ...this.engineSettings, custom_path: path };
      this.emit({ id, kind, state: "done", progress: 1, message: "Using Stockfish 18.", error_code: null });
    }, 300);
    return id;
  }

  async clearCustomEngine() {
    this.engineSettings = { ...this.engineSettings, custom_path: null };
    this.engine = { ...this.engine, state: "ready", source: "managed", name: "Stockfish 19", path: MANAGED_PATH, message: null };
  }

  /** FR-7.3: the mock refuses engine output during a puzzle, exactly like the backend. */
  private finishedPuzzle(sessionId: number) {
    const c = this.session(sessionId).current;
    if (!c) throw new ApiCallError({ code: "invalid_argument", message: "There's no puzzle in progress.", retryable: false });
    if (!c.finished) {
      throw new ApiCallError({ code: "conflict", message: "The engine is available once the puzzle is over.", retryable: true });
    }
    if (this.engine.state !== "ready") {
      throw new ApiCallError({ code: "engine_not_installed", message: "Stockfish isn't installed.", retryable: false });
    }
    return c;
  }

  private think() {
    return new Promise((resolve) => setTimeout(resolve, this.engineDelay));
  }

  async getRefutation(sessionId: number): Promise<Refutation> {
    const c = this.finishedPuzzle(sessionId);
    if (!c.firstWrong) {
      throw new ApiCallError({ code: "not_found", message: "There's no wrong move to refute in this puzzle.", retryable: false });
    }
    const [fenBefore, wrong] = c.firstWrong;
    const player = new Chess(c.start).turn() === "w" ? "white" : "black";
    const after = new Chess(fenBefore);
    after.move(uciToMove(wrong));
    this.calls.push("refutation");
    await this.think();
    const a = mockAnalysis(after.fen(), player, 1);
    const first = a.lines[0];
    return {
      fen_before: fenBefore,
      wrong_move: wrong,
      line: first ? first.pv.slice(0, 5) : [],
      score: first?.score ?? null,
      game_over: a.game_over,
    };
  }

  async analyzePosition(sessionId: number, fen: string, purpose: AnalysisPurpose): Promise<Analysis> {
    const c = this.finishedPuzzle(sessionId);
    const player = new Chess(c.start).turn() === "w" ? "white" : "black";
    const gen = (this.latest.get(purpose) ?? 0) + 1;
    this.latest.set(purpose, gen);
    this.calls.push(`analyze:${purpose}`);
    await this.think();
    if (this.latest.get(purpose) !== gen) return { fen, lines: [], game_over: null, superseded: true };
    return mockAnalysis(fen, player);
  }

  // ---- v0.7: AI settings and Explain (mockLlm.ts) -------------------------------------------------
  async getLlmSettings() {
    return this.llm.settings();
  }

  async setLlmSettings(change: LlmSettingsChange) {
    return this.llm.update(change);
  }

  async setLlmKey(provider: LlmProvider, key: string) {
    return this.llm.setKey(provider, key);
  }

  async deleteLlmKey(provider: LlmProvider) {
    return this.llm.deleteKey(provider);
  }

  async startLlmKeyTest(provider: LlmProvider, model: string) {
    return this.llm.startKeyTest(provider, model);
  }

  async listLlmPrices() {
    return this.llm.listPrices();
  }

  async saveLlmPrice(row: LlmPriceChange) {
    return this.llm.savePrice(row);
  }

  async deleteLlmPrice(provider: LlmProvider, model: string) {
    return this.llm.deletePrice(provider, model);
  }

  async getLlmSpend() {
    return this.llm.getSpend();
  }

  private explainTarget(sessionId: number): ExplainTarget {
    const c = this.session(sessionId).current;
    if (!c) throw new ApiCallError({ code: "invalid_argument", message: "There's no puzzle in progress.", retryable: false });
    const p = c.puzzle;
    const start = new Chess(p.fen);
    if (p.moves[0]) start.move(uciToMove(p.moves[0]));
    const s = this.session(sessionId);
    const path = [s.mode, c.danger ? `call:${c.danger.call ?? "none"}` : "", c.firstWrong ? `wrong:${c.firstWrong[1]}` : ""].join("|");
    return {
      puzzleId: p.id,
      path,
      startFen: start.fen(),
      solution: p.moves.slice(1),
      finished: c.finished,
      engineReady: this.engine.state === "ready",
    };
  }

  async getExplainQuote(sessionId: number) {
    return this.llm.quote(this.explainTarget(sessionId));
  }

  async startExplain(sessionId: number) {
    return this.llm.start(sessionId, this.explainTarget(sessionId));
  }

  async getExplanation(sessionId: number) {
    return this.llm.result(sessionId, this.session(sessionId).current?.puzzle.id ?? null);
  }

  // ---- v0.9: a model per AI feature and Game Review AI ------------------------------------------
  async setLlmFeature(feature: "game_review" | "coach" | "openings", choice: "same" | LlmProvider, model: string, reasoning: LlmSettings["reasoning"]) {
    return this.llm.setFeature(feature, choice, model, reasoning);
  }

  /** The analyzed move you may ask about (your own), as the backend checks it. */
  private aiMove(gameId: number, ply: number): { review: GameReview; move: ReviewMove } {
    const review = this.games.review(gameId);
    const bad = (message: string) => new ApiCallError({ code: "invalid_argument", message, retryable: false });
    if (!review.analyzed) throw bad("Analyze this game first: the AI explains Stockfish's analysis.");
    if (!review.game.user_color) throw bad("Choose which side you played first.");
    const move = review.moves[ply];
    if (!move) throw bad("There's no such move in this game.");
    if (review.game.user_color !== "both" && review.game.user_color !== move.mover) throw bad("Explain this move works on your own moves.");
    if (!move.best_move) throw bad("The analysis has no best line for this move.");
    return { review, move };
  }

  async getGameMoveQuote(gameId: number, ply: number) {
    this.aiMove(gameId, ply);
    return this.llm.gameQuote("game_move", `move:${gameId}:${ply}`);
  }

  async startGameMoveExplain(gameId: number, ply: number) {
    const { move } = this.aiMove(gameId, ply);
    return this.llm.startGame("game_move", `move:${gameId}:${ply}`, (provider, model, costUsd) => moveExplanation(move, provider, model, costUsd));
  }

  async getGameMoveExplanation(gameId: number, ply: number) {
    this.aiMove(gameId, ply);
    return this.llm.gameResult(`move:${gameId}:${ply}`) as Explanation | null;
  }

  private aiGame(gameId: number, n: number | null) {
    const review = this.games.review(gameId);
    if (!review.analyzed) throw new ApiCallError({ code: "invalid_argument", message: "Analyze this game first: the AI explains Stockfish's analysis.", retryable: false }); // prettier-ignore
    const m = this.games.aiMoments(gameId, n);
    return { review, ...m, what: `narrative:${gameId}:${m.n}:${m.plies.join(",")}` };
  }

  async getGameNarrativeQuote(gameId: number, n: number | null) {
    return this.llm.gameQuote("game_narrative", this.aiGame(gameId, n).what);
  }

  async startGameNarrative(gameId: number, n: number | null) {
    const g = this.aiGame(gameId, n);
    return this.llm.startGame(
      "game_narrative",
      g.what,
      (provider, model, costUsd) => gameNarrative(g.review, g.n, g.plies, provider, model, costUsd),
      () => this.games.markAiReviewed(gameId),
    );
  }

  async getGameNarrative(gameId: number, n: number | null) {
    return this.llm.gameResult(this.aiGame(gameId, n).what) as GameNarrative | null;
  }

  // ---- v0.8: the game library, Game Review and your own puzzles (mockGames.ts) ----------------
  async getGamesSettings() {
    return this.games.getSettings();
  }

  async setGamesSettings(change: GamesSettingsChange) {
    return this.games.setSettings(change);
  }

  async verifyChesscom(username: string) {
    return this.games.verifyChesscom(username);
  }

  async setChesscomUsername(username: string | null) {
    return this.games.setChesscom(username);
  }

  async startGamesSync() {
    return this.games.startSync();
  }

  async listGames(filters: LibraryFilters) {
    return this.games.list(filters);
  }

  async importGamePgn(text: string) {
    return this.games.importPgn(text);
  }

  async chooseGameFile() {
    return this.games.chooseFile();
  }

  async pickImportedGame(token: string, index: number) {
    return this.games.pick(token, index);
  }

  async startGameUrlImport(url: string, chesscomUsername: string | null) {
    return this.games.startUrl(url, chesscomUsername);
  }

  async getGameUrlImport(jobId: string) {
    return this.games.urlResult(jobId);
  }

  async setGameColor(gameId: number, color: "white" | "black" | "both") {
    this.games.setColor(gameId, color);
  }

  async openGameOnline(gameId: number) {
    this.calls.push(`open:${this.games.onlineUrl(gameId)}`);
  }

  async analyzeGames(gameIds: number[], force: boolean) {
    return this.games.analyze(gameIds, force);
  }

  async getAnalysisQueue() {
    return this.games.queue();
  }

  async getReview(gameId: number) {
    return this.games.review(gameId);
  }

  async retryMove(gameId: number, ply: number, uci: string) {
    return this.games.retry(gameId, ply, uci);
  }

  async saveGamePuzzle(gameId: number, ply: number) {
    return this.games.savePuzzle(gameId, ply);
  }

  async setGameReason(gameId: number, ply: number, reason: ReasonKey) {
    this.games.setGameReason(gameId, ply, reason);
  }

  async setRetryReason(retryId: number, reason: ReasonKey) {
    this.games.setRetryReason(retryId, reason);
  }

  async getGameStats() {
    return this.games.stats({ attempts: this.allTime.solved + this.allTime.failed, wins: this.allTime.solved });
  }

  async chooseAndImportPuzzles(label: string) {
    return this.games.importPuzzles(label);
  }

  async getPuzzleImportReport(jobId: string) {
    return this.games.importReport(jobId);
  }

  async listPuzzleSets() {
    return this.games.puzzleSets();
  }

  // ---- v0.10: Game Review additions, your puzzles, the Coach (mockCoach.ts) ------------------------
  async analyzeGamePosition(gameId: number, fen: string, purpose: "panel" | "board"): Promise<Analysis> {
    if (this.engine.state !== "ready") {
      throw new ApiCallError({ code: "engine_not_installed", message: "Install Stockfish to analyze positions.", retryable: false });
    }
    this.games.review(gameId);
    const key = `review:${purpose}`;
    const gen = (this.latest.get(key) ?? 0) + 1;
    this.latest.set(key, gen);
    this.calls.push(`analyzeGame:${gameId}:${purpose}`);
    await this.think();
    if (this.latest.get(key) !== gen) return { fen, lines: [], game_over: null, superseded: true };
    return mockAnalysis(fen, new Chess(fen).turn() === "w" ? "white" : "black");
  }

  async archiveMyPuzzle(puzzleId: number) {
    this.calls.push(`archivePuzzle:${puzzleId}`);
    this.games.archive(String(puzzleId));
  }

  async getCoachDefaults() {
    return this.coach.defaults();
  }

  async startCoachRun(params: CoachParams) {
    return this.coach.start(params);
  }

  async getCoachRunResult(jobId: string) {
    return this.coach.result(jobId);
  }

  async listCoachReports() {
    return this.coach.list();
  }

  async getCoachReport(reportId: number) {
    return this.coach.get(reportId);
  }

  async getCoachAiQuote(reportId: number, options: CoachAiOptions) {
    return this.coach.aiQuote(reportId, options);
  }

  async startCoachAi(reportId: number, options: CoachAiOptions) {
    return this.coach.startAi(reportId, options);
  }

  async getCoachAiJobRun(jobId: string) {
    return this.coach.jobRun(jobId);
  }

  async listCoachAiRuns(reportId: number) {
    return this.coach.listRuns(reportId);
  }

  async getCoachAiRun(reportId: number, runId: number) {
    return this.coach.getRun(reportId, runId);
  }

  async getCoachNotesPreview(reportId: number) {
    return this.coach.notesPreview(reportId);
  }

  async openLesson(reportId: number, topic: string, target: string) {
    this.coach.openLesson(reportId, topic, target);
  }

  // ---- v0.12: the training plan and journal -------------------------------------------------------
  async getCoachJournalPreview(reportId: number): Promise<CoachJournalLine[]> {
    return this.coach.journalPreview(reportId);
  }

  async getPlanSettings() {
    return this.plan.getSettings();
  }

  async previewPlan(params: PlanParams | null) {
    return this.plan.preview(params);
  }

  async createPlan(params: PlanParams, confirmed: boolean) {
    return this.plan.create(params, confirmed);
  }

  async useAiPlan(runId: number, confirmed: boolean) {
    return this.plan.useAi(runId, confirmed);
  }

  async getCurrentPlan() {
    return this.plan.current();
  }

  async getTodayPlan() {
    return this.plan.today();
  }

  async listPlans() {
    return this.plan.history();
  }

  async setPlanTaskTick(taskId: number, done: boolean) {
    this.plan.tick(taskId, done);
  }

  async skipPlanTask(taskId: number, skipped: boolean) {
    this.plan.skip(taskId, skipped);
  }

  async swapPlanTask(taskId: number) {
    return this.plan.swap(taskId);
  }

  async startPlanTask(taskId: number, rated: boolean) {
    return this.plan.start(taskId, rated);
  }

  async startPlanLessonDrill(taskId: number, rated: boolean) {
    this.plan.openLesson(taskId, "curated:0");
    const session = await this.startSession({ ...defaultFilters(), queue_size: 20 }, rated, "standard", false);
    return { kind: "session" as const, task_id: taskId, session, remaining: 20, mode: "standard", game_id: null, lesson: null, prompt: null, weakness_key: null, plan_day_id: null };
  }

  async openPlanLesson(taskId: number, target: string) {
    this.plan.openLesson(taskId, target);
  }

  async markReviewPly(gameId: number, ply: number) {
    return this.plan.markPly(gameId, ply);
  }

  // ---- v0.13: the opening trainer (REQUIREMENTS §18) ----
  async getOpeningBookStatus() {
    return this.openings.status();
  }

  async startOpeningBookImport() {
    const id = `job-${this.nextJob++}`;
    this.calls.push("openingBookImport");
    const kind = "opening_book_import";
    this.emit({ id, kind, state: "running", progress: 0, message: "Reading the opening book…", error_code: null });
    setTimeout(() => {
      this.openings.importBook();
      this.emit({ id, kind, state: "done", progress: 1, message: "Imported the opening book.", error_code: null });
    }, 100);
    return id;
  }

  async getOpeningFamilies(query: string) {
    return this.openings.families(query);
  }

  async getOpeningSettings() {
    return this.openings.settings();
  }

  async setOpeningSources(useWikibooks: boolean, source: "lichess" | "masters", ratings: number[]) {
    this.calls.push(`openingSources:${useWikibooks}:${source}:${ratings.join(",")}`);
    return this.openings.setSources(useWikibooks, source, ratings);
  }

  async getOpeningPage(sans: string[]) {
    this.calls.push(`openingPage:${sans.join(" ")}`);
    return this.openings.page(sans);
  }

  async setOpeningSettings(preset: OpeningScope["preset"], subLines: number | null, maxMoves: number | null, extend: boolean | null) {
    this.calls.push(`openingSettings:${preset}:${extend}`);
    return this.openings.setSettings(preset, subLines, maxMoves, extend);
  }

  async getOpeningLines(family: string) {
    return this.openings.lines(family, this.engine.state === "ready");
  }

  async getOpeningNote(positionKey: string, moveUci: string, kind: "overview" | "move") {
    return this.openings.note(positionKey, moveUci, kind);
  }

  async getOpeningNoteQuote(family: string, lineIndex: number, ply: number | null, regenerate: boolean) {
    return this.openings.noteQuote(family, lineIndex, ply, regenerate, this.openingAi());
  }

  async startOpeningNote(family: string, lineIndex: number, ply: number | null, regenerate: boolean) {
    const quote = this.openings.noteQuote(family, lineIndex, ply, regenerate, this.openingAi());
    if (quote.state === "cached") return null;
    if (quote.state !== "ok") throw new ApiCallError({ code: quote.state, message: quote.message ?? "", retryable: false });
    const id = `job-${this.nextJob++}`;
    this.calls.push(`openingNote:${ply}:${regenerate}`);
    const kind = "opening_note";
    this.emit({ id, kind, state: "running", progress: null, message: "Asking the AI…", error_code: null });
    setTimeout(() => {
      this.openings.saveNote(family, lineIndex, ply);
      this.emit({ id, kind, state: "done", progress: 1, message: "Saved.", error_code: null });
    }, 100);
    return id;
  }

  async getOpeningOverviewKey(family: string) {
    return this.openings.overviewKey(family);
  }

  private openingAi(): boolean {
    return this.llm.settings().features.some((f) => f.feature === "explain" && f.model !== "");
  }

  async getOpeningPrefetchPlan(family: string, preset: OpeningScope["preset"], subLines: number | null, maxMoves: number | null, extend: boolean) {
    return this.openings.prefetchPlan(family, preset, subLines, maxMoves, extend, this.openingAi());
  }

  async startOpeningPrefetch(family: string, preset: OpeningScope["preset"], subLines: number | null, maxMoves: number | null, extend: boolean) {
    const id = `job-${this.nextJob++}`;
    this.calls.push(`openingPrefetch:${preset}:${extend}`);
    const kind = "opening_prefetch";
    this.emit({ id, kind, state: "running", progress: 0.2, message: "Asking the AI (1 of 5)…", error_code: null });
    setTimeout(() => {
      if (this.jobs.get(id)?.state !== "running") return;
      const saved = this.openings.savePrefetch(family, preset, subLines, maxMoves, extend);
      this.emit({ id, kind, state: "done", progress: 1, message: `Saved ${saved} notes for $0.0312.`, error_code: null });
    }, new URLSearchParams(window.location.search).get("prefetch") === "slow" ? 5000 : 300);
    return id;
  }

  async exportOpeningNotes(family: string) {
    this.calls.push(`openingExport:${family}`);
    return this.openings.hasNotes() ? `C:\\mock\\exports\\${family.replace(/ /g, "-")}-notes.md` : null;
  }

  async deleteOpeningNotes(family: string) {
    this.calls.push(`openingDelete:${family}`);
    return this.openings.deleteNotes();
  }

  async startOpeningExtend(family: string) {
    if (this.engine.state !== "ready") {
      throw new ApiCallError({ code: "engine_not_installed", message: "Install Stockfish to continue lines past the book.", retryable: false });
    }
    if (this.openings.lines(family, true).pending === 0) return null;
    const id = `job-${this.nextJob++}`;
    this.calls.push(`openingExtend:${family}`);
    const kind = "opening_extend";
    this.emit({ id, kind, state: "running", progress: null, message: "Stockfish has looked at 2 positions…", error_code: null });
    setTimeout(() => {
      this.openings.extendLines(family);
      this.emit({ id, kind, state: "done", progress: 1, message: "Stockfish continued the lines.", error_code: null });
    }, 100);
    return id;
  }

  async analyzeOpeningPosition(fen: string, purpose: "start" | "panel" | "board", player: "white" | "black"): Promise<Analysis> {
    if (this.engine.state !== "ready") {
      throw new ApiCallError({ code: "engine_not_installed", message: "Install Stockfish to analyze positions.", retryable: false });
    }
    this.calls.push(`analyzeOpening:${purpose}`);
    await this.think();
    return mockAnalysis(fen, player);
  }

  async getRepertoire(color: "white" | "black") {
    return this.openings.repertoire(color);
  }

  async addRepertoireLines(color: "white" | "black", family: string, lineIndices: number[]) {
    this.calls.push(`repertoireAdd:${color}:${family}:${lineIndices.join(",")}`);
    return this.openings.addLines(color, family, lineIndices);
  }

  async previewRepertoireRemoval(color: "white" | "black", positionKey: string, moveUci: string) {
    return this.openings.previewRemoval(color, positionKey, moveUci);
  }

  async removeRepertoireMove(color: "white" | "black", positionKey: string, moveUci: string) {
    return this.openings.remove(color, positionKey, moveUci);
  }

  async setRepertoireMain(color: "white" | "black", positionKey: string, moveUci: string) {
    return this.openings.setMain(color, positionKey, moveUci);
  }

  async moveRepertoireMove(color: "white" | "black", positionKey: string, moveUci: string, direction: "up" | "down") {
    return this.openings.move(color, positionKey, moveUci, direction);
  }

  async getJournal(filters: JournalFilters) {
    return this.plan.timeline(filters);
  }

  async addJournalEntry(entry: JournalEntryInput) {
    return this.plan.add(entry);
  }

  async editJournalEntry(entryId: number, text: string, weaknessKey: string | null) {
    return this.plan.edit(entryId, text, weaknessKey);
  }

  async deleteJournalEntry(entryId: number) {
    this.plan.remove(entryId);
  }

  async getGameNotes(gameId: number) {
    return this.plan.gameNotes(gameId);
  }

  async getSuggestion() {
    return this.coach.getSuggestion();
  }

  async applySuggestion() {
    return this.coach.apply();
  }

  async dismissSuggestion() {
    return this.coach.dismiss();
  }

  async getAppInfo(): Promise<AppInfo> {
    return {
      version: "0.6.0",
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
        const message = this.offer ? "6,193,530 puzzles: 44,112 new, 7,923 removed." : "6,157,341 puzzles imported.";
        this.offer = null;
        this.emit({ id, kind: "puzzle_import", state: "done", progress: 1, message, error_code: null });
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

  async checkForDbUpdate(force: boolean) {
    const id = `job-${this.nextJob++}`;
    this.calls.push(`check:${force}`);
    const message = this.offer ? "A newer puzzle database is available (exported 2026-11-01)." : "Your puzzle database is up to date.";
    this.emit({ id, kind: "puzzle_db_update_check", state: "done", progress: 1, message, error_code: null });
    return id;
  }

  async getUpdateOffer() {
    return this.offer;
  }

  async dismissUpdate(kind: "not_now" | "skip") {
    this.calls.push(`dismiss:${kind}`);
    this.offer = null;
  }

  async getJob(jobId: string) {
    const job = this.jobs.get(jobId);
    if (!job) throw new ApiCallError({ code: "not_found", message: "No such job.", retryable: false });
    return job;
  }

  async cancelJob(jobId: string) {
    if (this.games.cancel(jobId)) return true;
    const job = this.jobs.get(jobId);
    if (!job || job.state !== "running") return false;
    this.status.import_job_id = null;
    this.emit({ ...job, state: "cancelled", message: "Cancelled" });
    return true;
  }

  async getSettings() {
    return { ...this.settings };
  }

  async setSetting<K extends keyof SettingValues>(key: K, value: SettingValues[K]) {
    this.calls.push(`setting:${key}=${JSON.stringify(value)}`);
    this.plan.setSetting(key, value);
    if (key === "mixer.filters") this.settings = { ...this.settings, last_filters: value as FilterSpec };
    if (key === "ui.coordinates") this.settings = { ...this.settings, coordinates: value as boolean };
    if (key === "ui.color_scheme") this.settings = { ...this.settings, color_scheme: value as UiSettings["color_scheme"] };
    if (key === "ui.sounds") this.settings = { ...this.settings, sounds: value as UiSettings["sounds"] };
    if (key === "puzzle_db.auto_check") this.settings = { ...this.settings, auto_check: value as boolean };
    if (key === "trainer.mode") this.settings = { ...this.settings, mode: value as TrainingMode };
    if (key === "commit.show_length") this.settings = { ...this.settings, show_length: value as boolean };
    if (key === "ladder.threshold") this.settings = { ...this.settings, ladder_threshold: value as number };
    if (key === "ladder.window") this.settings = { ...this.settings, ladder_window: value as number };
    if (key === "srs.intervals") this.settings = { ...this.settings, srs_intervals: value as number[] };
    if (key === "ui.filters_collapsed") this.settings = { ...this.settings, filters_collapsed: value as boolean };
    if (key === "reasons.ask") {
      if (value !== "always" && value !== "off") {
        throw new ApiCallError({ code: "invalid_argument", message: "reasons.ask must be 'always' or 'off'", retryable: false });
      }
      this.settings = { ...this.settings, reasons_ask: value as "always" | "off" };
    }
    if (key === "review.show_best") this.settings = { ...this.settings, show_best: value as boolean };
    if (key === "coach.lesson_sites") this.settings = { ...this.settings, lesson_sites: value as UiSettings["lesson_sites"] };
    if (key === "coach.lesson_custom_url") {
      const t = (value as string).trim();
      if (t && (!t.startsWith("https://") || t.split("{q}").length !== 2 || /\s/.test(t))) {
        throw new ApiCallError({ code: "invalid_argument", message: "Put {q} once in the search address, where the search words go.", retryable: false });
      }
      this.settings = { ...this.settings, lesson_custom_url: t };
    }
    if (key === "reasons.rushed_s") {
      const n = value as number;
      if (!Number.isInteger(n) || n < 1 || n > 30) {
        throw new ApiCallError({ code: "invalid_argument", message: "The rushed threshold must be a whole number of seconds from 1 to 30.", retryable: false });
      }
      this.settings = { ...this.settings, rushed_s: n };
    }
  }

  async getThemeCatalog(): Promise<ThemeGroup[]> {
    return CATALOG.map(([name, themes]) => ({
      name,
      themes: themes.map(([key, label, count]) => ({ key, name: label, count })),
    }));
  }

  async countMatches(spec: FilterSpec) {
    validate(spec);
    if (spec.source === "my") return this.games.myPool(spec).length;
    if (spec.source === "both") return this.pool(spec).length * SCALE + this.games.myPool(spec).length;
    if (spec.order === "depth_ladder") return (await this.getLadderStatus(spec)).match_count;
    if (spec.ratios.length > 0) {
      const ids = new Set(spec.ratios.flatMap((_, i) => this.pool(bucketSpec(spec, i)).map((p) => p.id)));
      return ids.size * SCALE;
    }
    return this.pool(spec).length * SCALE;
  }

  async countBuckets(spec: FilterSpec): Promise<BucketCounts> {
    return {
      total: await this.countMatches(spec),
      buckets: spec.ratios.map((_, i) => this.pool(bucketSpec(spec, i)).length * SCALE),
    };
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

  async startSession(
    spec: FilterSpec, rated: boolean = true, mode: TrainingMode = "standard", showLength: boolean = false,
  ): Promise<SessionInfo> {
    validate(spec);
    this.calls.push(`start:${mode}`);
    if (mode === "spaced_repetition") {
      if (this.srsDue.length === 0) {
        throw new ApiCallError({ code: "invalid_argument", message: "Nothing is due for review. Missed puzzles come back here on their review day.", retryable: false });
      }
      const id = this.nextSession++;
      const queue = [...this.srsDue]; // still due until reviewed, like the backend
      this.sessions.set(id, { spec: { ...spec, ratios: [], themes: [] }, rated, mode, showLength: false, ladder: null, attempts: [], queue, served: 0, current: null, solved: 0, failed: 0 });
      return { session_id: id, match_count: queue.length, queue_size: spec.queue_size, empty_buckets: [], mode };
    }
    if (spec.order === "depth_ladder" && mode !== "standard" && mode !== "commit_line") {
      throw new ApiCallError({ code: "invalid_argument", message: "The depth ladder works in Standard and Commit the line. Choose another order.", retryable: false });
    }
    if (mode === "danger_spotting") {
      if (this.engine.state !== "ready") {
        throw new ApiCallError({ code: "engine_not_installed", message: "Danger spotting needs Stockfish to check the safe moves. Install it in Settings → Engine.", retryable: false });
      }
      rated = false; // FR-4.4: never synced
    }
    const ladder = spec.order === "depth_ladder" ? { base: spec, key: ladderKey(spec) } : null;
    if (ladder) spec = atLevel(spec, this.ladderState(ladder.key).level);
    if (spec.source !== "lichess" && (mode === "name_idea" || mode === "danger_spotting")) {
      throw new ApiCallError({ code: "invalid_argument", message: "My puzzles works in Standard, Commit the line and Spaced repetition. Choose Lichess DB for this mode.", retryable: false });
    }
    const mine = spec.source === "lichess" ? [] : this.games.myPool(spec);
    const pools = spec.source === "my" ? [mine] : spec.source === "both" ? [[...mine, ...this.pool(spec)]]
      : spec.ratios.length > 0 ? spec.ratios.map((_, i) => this.pool(bucketSpec(spec, i))) : [this.pool(spec)]; // prettier-ignore
    const queue = interleave(pools, spec);
    if (queue.length === 0) {
      throw new ApiCallError({
        code: "invalid_argument",
        message: "No puzzles match these filters. Widen them and try again.",
        retryable: false,
      });
    }
    const id = this.nextSession++;
    this.sessions.set(id, { spec, rated, mode, showLength: showLength && mode === "commit_line", ladder, attempts: [], queue, served: 0, current: null, solved: 0, failed: 0 });
    const empty = spec.ratios.length > 0 ? pools.flatMap((p, i) => (p.length === 0 ? [i] : [])) : [];
    return { session_id: id, match_count: queue.length * SCALE, queue_size: spec.queue_size, empty_buckets: empty, mode };
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
      this.record(s.current.puzzle, false, s);
      this.queue(s.current.puzzle, false, s.rated, s);
    }
    s.current = null;
    const limit = s.spec.queue_size ?? Infinity;
    if (s.served >= limit || s.served >= s.queue.length) return null;
    const puzzle = s.queue[s.served++];
    if (s.mode === "danger_spotting") return this.nextDanger(s, puzzle);
    const chess = new Chess(puzzle.fen);
    if (puzzle.moves[0]) chess.move(uciToMove(puzzle.moves[0]));
    s.current = {
      puzzle, chess, start: chess.fen(), next: 1, decided: false, failed: false, hinted: false, finished: false,
      firstWrong: null, tags: s.mode === "name_idea" ? null : undefined,
    };
    return {
      number: s.served,
      puzzle_id: puzzle.id,
      fen: puzzle.fen,
      opponent_move: puzzle.moves[0],
      player_color: chess.turn() === "w" ? "white" : "black",
      rating: puzzle.rating,
      opponent_sound: puzzle.moves[0] ? soundOf(puzzle.fen, puzzle.moves[0]) : null,
      already_played: puzzle.source !== "my" && this.lichessHistory.has(puzzle.id),
      mode: s.mode,
      solution_plies: s.mode === "commit_line" && s.showLength ? puzzle.moves.length - 1 : null,
      max_plies: s.mode === "commit_line" ? (s.showLength ? puzzle.moves.length - 1 : 60) : null,
      candidate: null,
      source: puzzle.source === "my" ? "my" : "lichess",
      strict_without_engine: puzzle.source === "my" && puzzle.origin !== "import" && this.engine.state !== "ready",
      solve_as_opponent: puzzle.solve_as === "opponent",
      game_id: puzzle.game_id ?? null,
      game_ply: puzzle.ply ?? null,
    };
  }

  /** Danger spotting (FR-4.4): odd puzzles get a "safe" move, even ones the real blunder. */
  private nextDanger(s: MockSession, puzzle: MockPuzzle): PuzzleView {
    const chess = new Chess(puzzle.fen);
    const blunder = puzzle.moves[0];
    const safe = s.served % 2 === 1;
    const others = chess.moves({ verbose: true }).map((m) => m.from + m.to + (m.promotion ?? "")).filter((m) => m !== blunder).sort();
    const candidate = safe && others.length ? others[0] : blunder;
    s.current = {
      puzzle, chess, start: chess.fen(), next: 1, decided: false, failed: false, hinted: false, finished: false,
      firstWrong: null, danger: { candidate, safe: candidate !== blunder, phase: "call", call: null },
    };
    return {
      number: s.served, puzzle_id: puzzle.id, fen: puzzle.fen, opponent_move: "",
      player_color: chess.turn() === "w" ? "white" : "black", rating: puzzle.rating, opponent_sound: null,
      already_played: false, mode: s.mode, solution_plies: null, max_plies: null, candidate, source: "lichess", strict_without_engine: false,
      solve_as_opponent: false, game_id: null, game_ply: null,
    };
  }

  private reveal(c: NonNullable<MockSession["current"]>): DangerReveal | null {
    const d = c.danger;
    if (!d) return null;
    if (d.safe) return { candidate: d.candidate, is_safe: true, call: d.call, best_score: "+0.4 for you", candidate_score: "+0.3 for you", line: [] };
    return { candidate: d.candidate, is_safe: false, call: d.call, best_score: null, candidate_score: null, line: c.puzzle.moves.slice(1) };
  }

  private decideDanger(s: MockSession, c: NonNullable<MockSession["current"]>, win: boolean) {
    if (c.decided) return null;
    c.decided = true;
    if (win) s.solved++;
    else s.failed++;
    const outcome = { ...this.outcome(c.puzzle, win, s), danger: this.reveal(c) };
    if (!win) {
      c.lostAttempt = outcome.attempt_id;
      c.suggested = c.danger && !c.danger.safe && c.danger.call === "safe" ? "missedResource" : null;
    }
    return outcome;
  }

  async callDanger(sessionId: number, call: "safe" | "unsafe"): Promise<DangerFeedback> {
    const s = this.session(sessionId);
    const c = s.current;
    if (!c) throw new ApiCallError({ code: "invalid_argument", message: "There's no puzzle in progress.", retryable: false });
    if (!c.danger) throw new ApiCallError({ code: "conflict", message: "Safe / Unsafe is for Danger spotting.", retryable: false });
    if (c.danger.phase !== "call") throw new ApiCallError({ code: "conflict", message: "You've already made your call for this puzzle.", retryable: false });
    this.calls.push(`danger:${call}`);
    c.danger.call = call;
    const correct = (call === "safe") === c.danger.safe;
    if (call === "unsafe" && !c.danger.safe) {
      const sound = soundOf(c.chess.fen(), c.danger.candidate);
      c.chess.move(uciToMove(c.danger.candidate));
      c.danger.phase = "refute";
      return { call, correct: true, refute: true, fen: c.chess.fen(), blunder_sound: sound, outcome: null };
    }
    c.danger.phase = "done";
    c.finished = true;
    const outcome = this.decideDanger(s, c, correct);
    return { call, correct, refute: false, fen: c.chess.fen(), blunder_sound: null, outcome };
  }

  async setIdeaTags(sessionId: number, setup: string[], payoff: string[]) {
    const s = this.session(sessionId);
    const c = s.current;
    if (!c) throw new ApiCallError({ code: "invalid_argument", message: "There's no puzzle in progress.", retryable: false });
    if (s.mode !== "name_idea") throw new ApiCallError({ code: "conflict", message: "Tagging the idea is for Name the idea first.", retryable: false });
    if (c.tags) throw new ApiCallError({ code: "conflict", message: "You've already named the idea for this puzzle.", retryable: false });
    if (setup.length + payoff.length === 0) {
      throw new ApiCallError({ code: "invalid_argument", message: "Name at least one idea before you start solving.", retryable: false });
    }
    if (setup.length > 3 || payoff.length > 3) throw new ApiCallError({ code: "invalid_argument", message: "Pick at most 3 tags per slot.", retryable: false });
    this.calls.push(`tags:${[...setup, ...payoff].join(",")}`);
    c.tags = { setup, payoff };
  }

  private ideaResult(c: NonNullable<MockSession["current"]>): IdeaResult | null {
    if (!c.tags || c.practice) return null;
    const motifs = c.puzzle.themes.filter((t) => MOCK_MOTIFS.has(t));
    const named = [...new Set([...c.tags.setup, ...c.tags.payoff])];
    const label = (key: string) => ({ key, name: NAMES.get(key) ?? key });
    const correct = named.filter((t) => motifs.includes(t));
    return {
      found: correct.length, total: motifs.length, extra: named.length - correct.length,
      correct: correct.map(label), wrong: named.filter((t) => !motifs.includes(t)).map(label),
      missed: motifs.filter((t) => !named.includes(t)).map(label),
    };
  }

  async getReasonPrompt(sessionId: number): Promise<ReasonPrompt | null> {
    if (this.settings.reasons_ask === "off") return null;
    const c = this.session(sessionId).current;
    if (!c || !c.finished || c.lostAttempt === undefined) return null;
    this.calls.push("reasonPrompt");
    return { attempt_id: c.lostAttempt, source: c.danger ? "danger" : "puzzle", suggested: c.suggested ?? null, reasons: REASON_OPTIONS };
  }

  async setMistakeReason(attemptId: number, reason: ReasonKey, note: string | null) {
    const a = this.attemptSession.get(attemptId);
    if (!a) throw new ApiCallError({ code: "not_found", message: "That attempt doesn't exist.", retryable: false });
    if (a.win) throw new ApiCallError({ code: "conflict", message: "You solved that one: there's no miss to explain.", retryable: false });
    if (!REASON_OPTIONS.some((r) => r.key === reason)) throw new ApiCallError({ code: "invalid_argument", message: "Unknown mistake reason.", retryable: false });
    if (note && note.trim().length > 200) throw new ApiCallError({ code: "invalid_argument", message: "Keep the note under 200 characters.", retryable: false });
    this.calls.push(`reason:${attemptId}=${reason}${note ? `:${note.trim()}` : ""}`);
    this.reasons.set(attemptId, reason);
  }

  async getReasonStats(theme: string | null, mode: TrainingMode | null, source: ReasonSource = "puzzles"): Promise<ReasonStats> {
    if (source === "games") return this.games.reasonStats();
    this.calls.push(`reasonStats:${theme ?? "all"}:${mode ?? "all"}`);
    // Fixed history plus whatever you tagged in this mock session, filtered like the backend.
    const base: [ReasonKey, number][] = [["didntLook", 7], ["missedResource", 5], ["miscalculated", 4], ["unknownPattern", 3], ["rushed", 2]];
    const scale = theme || mode ? 0.5 : 1;
    const counts = new Map(base.map(([k, n]) => [k, Math.round(n * scale)]));
    let misclicks = 1;
    for (const [id, r] of this.reasons) {
      const a = this.attemptSession.get(id);
      if (mode && a?.mode !== mode) continue;
      if (r === "misclick") misclicks++;
      else counts.set(r, (counts.get(r) ?? 0) + 1);
    }
    const tagged = [...counts.values()].reduce((x, y) => x + y, 0);
    const reasons = REASON_OPTIONS.filter((o) => o.key !== "misclick").map((o) => ({
      ...o, count: counts.get(o.key) ?? 0, share: tagged ? (counts.get(o.key) ?? 0) / tagged : null,
    }));
    const trend = [
      { week: "2026-10-12", counts: [2, 1, 1, 0, 1].map((n) => Math.round(n * scale)) },
      { week: "2026-10-19", counts: [3, 2, 1, 1, 0].map((n) => Math.round(n * scale)) },
      { week: "2026-10-26", counts: [2, 2, 2, 2, 1].map((n) => Math.round(n * scale)) },
    ];
    return { reasons, tagged, untagged: 4, misclicks, misclick_warning: misclicks * 4 >= tagged + misclicks && tagged + misclicks >= 8, trend };
  }

  async submitLine(sessionId: number, moves: string[]): Promise<CommitFeedback> {
    const s = this.session(sessionId);
    const c = s.current;
    const fail = (code: string, message: string) => new ApiCallError({ code, message, retryable: false });
    if (!c) throw fail("invalid_argument", "There's no puzzle in progress.");
    if (s.mode !== "commit_line") throw fail("conflict", "Submit is for Commit the line: in this mode, play your moves on the board.");
    if (c.finished) throw fail("conflict", "This puzzle is over: there's nothing to submit.");
    if (moves.length === 0) throw fail("invalid_argument", "Enter at least one move before you submit.");
    const probe = new Chess(c.start);
    try {
      moves.forEach((m) => probe.move(uciToMove(m)));
    } catch {
      throw fail("invalid_argument", "The line contains an illegal move.");
    }
    this.calls.push(`submitLine:${moves.join(" ")}`);
    const { grades, extra, firstWrong } = gradeLine(c.start, c.puzzle.moves.slice(1), moves);
    const win = grades.filter((g) => g.player).every((g) => g.correct);
    const replies = grades.filter((g) => !g.player);
    c.finished = true;
    c.submitted = true;
    c.firstWrong = firstWrong;
    let outcome = null;
    if (!c.decided) {
      c.decided = true;
      if (win) {
        s.solved++;
        this.allTime.solved++;
      } else {
        s.failed++;
        this.allTime.failed++;
      }
      const levelUp = this.record(c.puzzle, win, s);
      outcome = { ...this.outcome(c.puzzle, win, s), level_up: levelUp };
    }
    return {
      grades, extra, replies_correct: replies.filter((g) => g.correct).length, replies_total: replies.length,
      win: win && outcome !== null, outcome, line_sounds: lineSounds(c.start, moves),
    };
  }

  async submitMove(sessionId: number, uci: string): Promise<MoveFeedback> {
    const s = this.session(sessionId);
    const c = s.current;
    if (!c) throw new ApiCallError({ code: "invalid_argument", message: "There's no puzzle in progress.", retryable: false });
    const none = { move_sound: null, reply_sound: null };
    if (s.mode === "commit_line") {
      throw new ApiCallError({ code: "conflict", message: "In Commit the line, enter the whole line and press Submit.", retryable: false });
    }
    if (c.finished) return { kind: "illegal", reply: null, finished: true, outcome: null, ...none };
    if (c.tags === null) {
      throw new ApiCallError({ code: "conflict", message: "Name the idea first, then press Start solving.", retryable: false });
    }
    if (c.danger) return this.refuteMove(s, c, uci);
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
        return { kind: "illegal", reply: null, finished: false, outcome: null, ...none };
      }
    }
    const moveSound = soundOf(c.chess.fen(), uci);
    if (!ok) {
      c.firstWrong ??= [c.chess.fen(), uci];
      if (c.decided) return { kind: "wrong", reply: null, finished: false, outcome: null, move_sound: moveSound, reply_sound: null };
      c.decided = c.failed = true;
      s.failed++;
      this.allTime.failed++;
      const levelUp = this.record(c.puzzle, false, s);
      const outcome = { ...this.outcome(c.puzzle, false, s), level_up: levelUp };
      return { kind: "wrong", reply: null, finished: false, outcome, move_sound: moveSound, reply_sound: null };
    }
    c.chess.move(uciToMove(uci));
    c.next++;
    if (c.next >= c.puzzle.moves.length || c.chess.isCheckmate()) {
      c.finished = true;
      let outcome = null;
      if (!c.decided) {
        c.decided = true;
        s.solved++;
        this.allTime.solved++;
        const levelUp = this.record(c.puzzle, true, s);
        outcome = { ...this.outcome(c.puzzle, true, s), level_up: levelUp };
      }
      return { kind: "solved", reply: null, finished: true, outcome, move_sound: moveSound, reply_sound: null };
    }
    const reply = c.puzzle.moves[c.next++];
    const replySound = soundOf(c.chess.fen(), reply);
    c.chess.move(uciToMove(reply));
    return { kind: "correct", reply, finished: false, outcome: null, move_sound: moveSound, reply_sound: replySound };
  }

  /** Danger spotting: one move, the refutation's first (any mate counts). */
  private refuteMove(s: MockSession, c: NonNullable<MockSession["current"]>, uci: string): MoveFeedback {
    const d = c.danger!;
    if (d.phase !== "refute") throw new ApiCallError({ code: "conflict", message: "Make your call first: Safe or Unsafe.", retryable: false });
    const expected = c.puzzle.moves[1];
    const probe = new Chess(c.chess.fen());
    try {
      probe.move(uciToMove(uci));
    } catch {
      return { kind: "illegal", reply: null, finished: false, outcome: null, move_sound: null, reply_sound: null };
    }
    const exp = new Chess(c.chess.fen());
    exp.move(uciToMove(expected));
    const ok = uci === expected || (exp.isCheckmate() && probe.isCheckmate());
    const sound = soundOf(c.chess.fen(), uci);
    if (ok) c.chess.move(uciToMove(uci));
    else c.firstWrong = [c.chess.fen(), uci];
    d.phase = "done";
    c.finished = true;
    const outcome = this.decideDanger(s, c, ok);
    return { kind: ok ? "solved" : "wrong", reply: null, finished: true, outcome, move_sound: sound, reply_sound: null };
  }

  async requestHelp(sessionId: number, kind: "hint" | "answer"): Promise<HelpResponse> {
    const s = this.session(sessionId);
    const c = s.current;
    const conflict = (message: string) => new ApiCallError({ code: "conflict", message, retryable: false });
    if (!c) throw new ApiCallError({ code: "invalid_argument", message: "There's no puzzle in progress.", retryable: false });
    if (c.danger) {
      const d = c.danger;
      if (kind === "hint") {
        if (d.phase !== "refute") throw conflict("Hint is only offered while you look for the refutation.");
        const outcome = this.decideDanger(s, c, false);
        c.hinted = true;
        return { kind, hint_square: c.puzzle.moves[1].slice(0, 2), answer_fen: null, answer_moves: [], outcome, answer_sounds: [], refute: false };
      }
      if (d.phase === "refute" && !c.decided && !c.hinted) throw conflict("Try a Hint first: Show answer unlocks after it.");
      const outcome = this.decideDanger(s, c, false);
      d.phase = "done";
      c.finished = true;
      const line = d.safe ? [d.candidate] : c.puzzle.moves;
      return { kind, hint_square: null, answer_fen: c.puzzle.fen, answer_moves: line, outcome, answer_sounds: lineSounds(c.puzzle.fen, line), refute: c.firstWrong !== null };
    }
    const decide = () => {
      if (c.decided) return null;
      c.decided = c.failed = true;
      s.failed++;
      this.allTime.failed++;
      const levelUp = this.record(c.puzzle, false, s);
      return { ...this.outcome(c.puzzle, false, s), level_up: levelUp };
    };
    if (kind === "hint") {
      if (c.finished) throw conflict("The puzzle is over: there's nothing left to hint.");
      const outcome = decide();
      c.hinted = true;
      const square = c.puzzle.moves[s.mode === "commit_line" ? 1 : c.next].slice(0, 2);
      return { kind, hint_square: square, answer_fen: null, answer_moves: [], outcome, answer_sounds: [], refute: false };
    }
    if (c.finished) {
      const line = c.puzzle.moves.slice(1);
      const sounds = lineSounds(c.start, line);
      return { kind, hint_square: null, answer_fen: c.start, answer_moves: line, outcome: null, answer_sounds: sounds, refute: c.firstWrong !== null };
    }
    if (!c.decided && !c.hinted) throw conflict("Try a Hint first: Show answer unlocks after it.");
    const outcome = decide();
    c.finished = true;
    const commit = s.mode === "commit_line";
    const rest = c.puzzle.moves.slice(commit ? 1 : c.next);
    const fen = commit ? c.start : c.chess.fen();
    return { kind, hint_square: null, answer_fen: fen, answer_moves: rest, outcome, answer_sounds: lineSounds(fen, rest), refute: c.firstWrong !== null };
  }

  private outcome(p: MockPuzzle, win: boolean, s: MockSession) {
    const { id, info } = this.queue(p, win, s.rated, s);
    const sid = [...this.sessions.entries()].find(([, v]) => v === s)?.[0] ?? 0;
    this.attemptSession.set(id, { session: sid, win, mode: s.mode });
    const c = s.current;
    if (c && !win && !c.danger) {
      c.lostAttempt = id;
      const idea = this.ideaResult(c);
      // The mock's FR-5.9 rules (no clock, so never Rushed): first move right then wrong; no tag a motif.
      c.suggested = c.firstWrong && c.next > 1 && c.firstWrong[0] !== c.start ? "miscalculated" : idea && idea.total > 0 && idea.found === 0 ? "unknownPattern" : null;
    }
    return {
      win,
      puzzle_id: p.id,
      rating: p.rating,
      themes: p.themes.map((key) => ({ key, name: NAMES.get(key) ?? key })),
      solution: p.moves.slice(1),
      puzzle_url: `https://lichess.org/training/${p.id}`,
      attempt_id: id,
      lichess: { ...info },
      level_up: null as LadderInfo | null,
      idea: c && !c.danger ? this.ideaResult(c) : null,
      danger: null as DangerReveal | null,
    };
  }

  async retryPuzzle(sessionId: number) {
    const s = this.session(sessionId);
    const c = s.current;
    if (!c) throw new ApiCallError({ code: "invalid_argument", message: "There's no puzzle in progress.", retryable: false });
    if (!c.finished) {
      throw new ApiCallError({ code: "conflict", message: "Finish the puzzle first: Try again is for after it's over.", retryable: true });
    }
    const chess = new Chess(c.puzzle.fen);
    if (!c.danger && c.puzzle.moves[0]) chess.move(uciToMove(c.puzzle.moves[0]));
    this.calls.push("retry");
    s.current = {
      puzzle: c.puzzle, chess, start: chess.fen(), next: 1, decided: true, failed: false, hinted: false,
      finished: false, firstWrong: null, practice: true, tags: c.tags ? { setup: [], payoff: [] } : undefined,
      danger: c.danger ? { ...c.danger, phase: "call", call: null } : undefined,
      lostAttempt: c.lostAttempt, suggested: c.suggested,
    };
  }

  async getSessionStats(sessionId: number): Promise<SessionStats> {
    const s = this.session(sessionId);
    const misclicks = [...this.reasons].filter(([id, r]) => r === "misclick" && this.attemptSession.get(id)?.session === sessionId).length;
    const failed = s.failed - misclicks;
    const played = s.solved + failed;
    const limit = Math.min(s.spec.queue_size ?? Infinity, s.queue.length);
    return {
      solved: s.solved,
      failed,
      accuracy: played ? s.solved / played : null,
      played,
      queue_size: s.spec.queue_size,
      finished: played + misclicks >= limit,
      all_time_solved: this.allTime.solved,
      all_time_failed: this.allTime.failed,
      rating_change: this.sessionChange(s),
      mode: s.mode,
      ladder: s.ladder ? this.ladderInfo(s.ladder.key) : null,
      misclicks,
    };
  }

  private sessionChange(s: MockSession): number | null {
    const diffs = s.attempts.flatMap((id) => {
      const r = this.ratings.get(id);
      return r?.status === "done" && r.diff !== null ? [r.diff] : [];
    });
    return diffs.length ? diffs.reduce((a, b) => a + b, 0) : null;
  }

  async getStats(): Promise<StatsReport> {
    const r = (key: string, label: string, attempts: number, solved: number, firstRight: number, lineWrong: number): StatRow => ({
      key,
      label,
      attempts,
      solved,
      accuracy: attempts ? solved / attempts : null,
      first_right: firstRight,
      line_wrong_rate: firstRight ? lineWrong / firstRight : null,
    });
    return {
      overall: r("all", "All puzzles", 58, 41, 49, 8),
      by_theme: [
        r("middlegame", "Middlegame", 31, 23, 27, 4), r("fork", "Fork", 22, 17, 19, 2),
        r("endgame", "Endgame", 19, 12, 15, 3), r("mateIn2", "Mate in 2", 9, 8, 9, 1),
        r("pin", "Pin", 8, 4, 6, 2), r("discoveredAttack", "Discovered attack", 5, 2, 4, 2),
      ],
      by_length: [r("1", "1 move", 14, 13, 13, 0), r("2", "2 moves", 27, 19, 23, 4), r("3", "3 moves", 12, 7, 10, 3),
        r("4", "4+ moves", 5, 2, 3, 1)],
      by_rating: [r("1000", "1000–1199", 9, 8, 9, 1), r("1200", "1200–1399", 21, 16, 18, 2),
        r("1400", "1400–1599", 19, 12, 15, 3), r("1600", "1600–1799", 9, 5, 7, 2)],
      missing: 0,
      by_mode: [r("standard", "Standard", 44, 31, 37, 6), r("commit_line", "Commit the line", 9, 6, 8, 2),
        r("name_idea", "Name the idea first", 6, 4, 5, 1), r("danger_spotting", "Danger spotting", 12, 8, 8, 0),
        r("spaced_repetition", "Spaced repetition", 5, 4, 4, 0)],
      misclicks: 1,
      misclick_warning: false,
      details: {
        replies_correct: 11, replies_total: 17, ideas_found: 5, ideas_total: 9, tags_named: 8,
        danger_safe: 6, danger_safe_right: 5, danger_blunder: 6, danger_blunder_right: 3,
      },
    }; // prettier-ignore
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

// The mock's stand-in for core/move_sounds.py (the real classification is tested in Python).
type Sound = "move" | "capture" | "check" | "checkmate" | "castle";

function soundOf(fen: string, uci: string): Sound {
  const c = new Chess(fen);
  const m = c.move(uciToMove(uci));
  if (c.isCheckmate()) return "checkmate";
  if (c.inCheck()) return "check";
  if (m.captured) return "capture";
  if (m.isKingsideCastle() || m.isQueensideCastle()) return "castle";
  return "move";
}

function lineSounds(fen: string, ucis: string[]): Sound[] {
  const c = new Chess(fen);
  return ucis.map((uci) => {
    const s = soundOf(c.fen(), uci);
    c.move(uciToMove(uci));
    return s;
  });
}

function uciToMove(uci: string) {
  return { from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci.length > 4 ? uci[4] : undefined };
}
