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
import { Chess } from "chess.js";
import type { ApiClient, BackendEvent, SettingValues } from "./ApiClient";
import { ApiCallError } from "./ApiClient";
import { MOCK_PUZZLES, type MockPuzzle } from "./mockPuzzles";
import type {
  AccountStatus,
  AttemptRating,
  BucketCounts,
  AppInfo,
  FilterSpec,
  HelpResponse,
  Job,
  MoveFeedback,
  OpeningFamily,
  Preset,
  PuzzleDbStatus,
  PuzzleView,
  RatingHistory,
  SessionInfo,
  SessionStats,
  StatRow,
  StatsReport,
  SyncStatus,
  UpdateOffer,
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

// The mock's Lichess rating history (FR-9.4): fixed points, so the Stats chart is stable.
const RATING_POINTS: [string, number, number][] = [
  ["2026-10-20T19:05:00", 1772, 1], ["2026-10-20T19:31:00", 1788, 1], ["2026-10-22T20:10:00", 1781, 2],
  ["2026-10-22T20:40:00", 1799, 2], ["2026-10-25T18:15:00", 1806, 3], ["2026-10-25T18:52:00", 1795, 3],
  ["2026-10-28T21:00:00", 1813, 4], ["2026-10-28T21:33:00", 1826, 4], ["2026-10-31T17:20:00", 1834, 5],
]; // prettier-ignore
const MOCK_USER = "your_name";

interface MockSession {
  spec: FilterSpec;
  rated: boolean;
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
  };
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
  private signInFails = false;
  private revokeOffline = false;
  readonly calls: string[] = [];

  constructor(search: string = typeof window !== "undefined" ? window.location.search : "") {
    const params = new URLSearchParams(search);
    const scenario = params.get("scenario");
    // ?scheme=dark|auto starts the mock in that saved scheme; ?sounds=off with sounds off.
    const scheme = params.get("scheme");
    if (scheme === "dark" || scheme === "auto") this.settings.color_scheme = scheme;
    if (params.get("sounds") === "off") this.settings.sounds = { ...this.settings.sounds, on: false };
    const account = params.get("account");
    if (account === "signed_out") this.account = { state: "signed_out", username: null, rating: null, provisional: false };
    if (account === "offline") this.account = { state: "offline", username: MOCK_USER, rating: null, provisional: false };
    if (account === "expired") this.account = { state: "expired", username: MOCK_USER, rating: null, provisional: false };
    if (params.get("played") === "1") this.lichessHistory.add(MOCK_PUZZLES[1].id);
    this.slowSync = params.get("sync") === "slow";
    this.signInFails = params.get("signin") === "fail";
    this.revokeOffline = params.get("revoke") === "offline";
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

  private record(p: MockPuzzle, win: boolean) {
    this.history.set(p.id, [...(this.history.get(p.id) ?? []), win]);
  }

  private emit(job: Job) {
    this.jobs.set(job.id, job);
    this.listeners.forEach((l) => l({ name: "job", payload: job }));
  }

  async getAppInfo(): Promise<AppInfo> {
    return {
      version: "0.3.0",
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
    if (key === "mixer.filters") this.settings = { ...this.settings, last_filters: value as FilterSpec };
    if (key === "ui.coordinates") this.settings = { ...this.settings, coordinates: value as boolean };
    if (key === "ui.color_scheme") this.settings = { ...this.settings, color_scheme: value as UiSettings["color_scheme"] };
    if (key === "ui.sounds") this.settings = { ...this.settings, sounds: value as UiSettings["sounds"] };
    if (key === "puzzle_db.auto_check") this.settings = { ...this.settings, auto_check: value as boolean };
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

  async startSession(spec: FilterSpec, rated: boolean = true): Promise<SessionInfo> {
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
    this.sessions.set(id, { spec, rated, attempts: [], queue, served: 0, current: null, solved: 0, failed: 0 });
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
      this.queue(s.current.puzzle, false, s.rated, s);
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
      opponent_sound: soundOf(puzzle.fen, puzzle.moves[0]),
      already_played: this.lichessHistory.has(puzzle.id),
    };
  }

  async submitMove(sessionId: number, uci: string): Promise<MoveFeedback> {
    const s = this.session(sessionId);
    const c = s.current;
    if (!c) throw new ApiCallError({ code: "invalid_argument", message: "There's no puzzle in progress.", retryable: false });
    const none = { move_sound: null, reply_sound: null };
    if (c.finished) return { kind: "illegal", reply: null, finished: true, outcome: null, ...none };
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
      if (c.decided) return { kind: "wrong", reply: null, finished: false, outcome: null, move_sound: moveSound, reply_sound: null };
      c.decided = c.failed = true;
      s.failed++;
      this.allTime.failed++;
      this.record(c.puzzle, false);
      const outcome = this.outcome(c.puzzle, false, s);
      return { kind: "wrong", reply: null, finished: false, outcome, move_sound: moveSound, reply_sound: null };
    }
    c.chess.move(uciToMove(uci));
    c.next++;
    if (c.next >= c.puzzle.moves.length || c.chess.isCheckmate()) {
      c.finished = true;
      const outcome = c.decided ? null : this.outcome(c.puzzle, true, s);
      if (!c.decided) {
        c.decided = true;
        s.solved++;
        this.allTime.solved++;
        this.record(c.puzzle, true);
      }
      return { kind: "solved", reply: null, finished: true, outcome, move_sound: moveSound, reply_sound: null };
    }
    const reply = c.puzzle.moves[c.next++];
    const replySound = soundOf(c.chess.fen(), reply);
    c.chess.move(uciToMove(reply));
    return { kind: "correct", reply, finished: false, outcome: null, move_sound: moveSound, reply_sound: replySound };
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
      return this.outcome(c.puzzle, false, s);
    };
    if (kind === "hint") {
      if (c.finished) throw conflict("The puzzle is over: there's nothing left to hint.");
      const outcome = decide();
      c.hinted = true;
      const square = c.puzzle.moves[c.next].slice(0, 2);
      return { kind, hint_square: square, answer_fen: null, answer_moves: [], outcome, answer_sounds: [] };
    }
    if (c.finished) {
      const line = c.puzzle.moves.slice(1);
      return { kind, hint_square: null, answer_fen: c.start, answer_moves: line, outcome: null, answer_sounds: lineSounds(c.start, line) };
    }
    if (!c.decided && !c.hinted) throw conflict("Try a Hint first: Show answer unlocks after it.");
    const outcome = decide();
    c.finished = true;
    const rest = c.puzzle.moves.slice(c.next);
    const fen = c.chess.fen();
    return { kind, hint_square: null, answer_fen: fen, answer_moves: rest, outcome, answer_sounds: lineSounds(fen, rest) };
  }

  private outcome(p: MockPuzzle, win: boolean, s: MockSession) {
    const { id, info } = this.queue(p, win, s.rated, s);
    return {
      win,
      puzzle_id: p.id,
      rating: p.rating,
      themes: p.themes.map((key) => ({ key, name: NAMES.get(key) ?? key })),
      solution: p.moves.slice(1),
      puzzle_url: `https://lichess.org/training/${p.id}`,
      attempt_id: id,
      lichess: { ...info },
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
      rating_change: this.sessionChange(s),
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
