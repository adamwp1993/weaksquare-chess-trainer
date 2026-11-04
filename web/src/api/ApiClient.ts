// The only way the UI talks to the backend (ARCHITECTURE §3 decision 8).
// Two implementations: pywebviewClient (the real app) and mockClient (UI development, Playwright).
import type {
  AccountStatus,
  Analysis,
  ExplainQuote,
  Explanation,
  LlmPrice,
  LlmSettings,
  LlmSpend,
  EngineSettings,
  EngineStatus,
  Refutation,
  AttemptRating,
  BucketCounts,
  CommitFeedback,
  DangerFeedback,
  ReasonPrompt,
  ReasonStats,
  LadderPreview,
  SrsStatus,
  ApiError,
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
  SoundSettings,
  StatsReport,
  SyncEvent,
  SyncStatus,
  UpdateOffer,
  ThemeGroup,
  UiSettings,
} from "./types";

export class ApiCallError extends Error {
  readonly code: string;
  readonly retryable: boolean;

  constructor(error: ApiError) {
    super(error.message);
    this.name = "ApiCallError";
    this.code = error.code;
    this.retryable = error.retryable;
  }
}

/** v0.7: the AI settings saved together (FR-1.2–1.4, 8.12, 8.13, 8.15). `model` is for `provider`. */
export interface LlmSettingsChange {
  provider: "none" | "anthropic" | "openai";
  model: string;
  reasoning: "low" | "medium" | "high";
  run_cap_usd: number;
  monthly_budget_usd: number;
}

export type LlmProvider = "anthropic" | "openai";

/** A row of the editable price table (FR-8.9); the long-context tier is all three or none. */
export interface LlmPriceChange {
  provider: LlmProvider;
  model: string;
  input_per_m: number;
  output_per_m: number;
  long_ctx_threshold?: number | null;
  long_input_per_m?: number | null;
  long_output_per_m?: number | null;
  as_of?: string | null;
}

export type BackendEvent =
  | { name: "job"; payload: Job }
  | { name: "account"; payload: AccountStatus }
  | { name: "sync"; payload: SyncEvent };

/** The settings the UI may write, and the value each one takes (validated again in Python). */
export interface SettingValues {
  "mixer.filters": FilterSpec;
  "ui.coordinates": boolean;
  "ui.color_scheme": "light" | "dark" | "auto";
  "ui.sounds": SoundSettings;
  "puzzle_db.auto_check": boolean;
  // v0.5
  "trainer.mode": TrainingMode;
  "commit.show_length": boolean;
  "ladder.threshold": number;
  "ladder.window": number;
  "srs.intervals": number[];
  "ui.filters_collapsed": boolean;
  // v0.6
  "reasons.ask": "always" | "off";
  "reasons.rushed_s": number;
}

/** Why you missed it (§7.3, FR-5.6). */
export type ReasonKey = ReasonPrompt["reasons"][number]["key"];

/** The Modes control (§6). Later modes join when they ship. */
export type TrainingMode = SessionInfo["mode"];

/** Which view asked: a newer request for the same purpose supersedes an older one. */
export type AnalysisPurpose = "start" | "panel" | "board";

export interface EngineSettingsChange {
  think_s?: number;
  threads?: number;
  hash_mb?: number;
}

export interface ApiClient {
  getAppInfo(): Promise<AppInfo>;
  openFolder(kind: "data" | "logs"): Promise<void>;
  logFrontendError(message: string, source: string): Promise<void>;
  getPuzzleDbStatus(): Promise<PuzzleDbStatus>;
  /** Native file picker; null if cancelled. */
  choosePuzzleFile(): Promise<string | null>;
  /** Starts the import job (download when localPath is null). Returns the job ID. */
  startPuzzleImport(localPath: string | null): Promise<string>;
  /** Rebuilds an older-schema puzzle database from its own rows (no download). Returns the job ID. */
  startPuzzleDbUpgrade(): Promise<string>;
  /** FR-2.5: start the update check (force: the "Check for updates" button). Returns the job ID. */
  checkForDbUpdate(force: boolean): Promise<string>;
  getUpdateOffer(): Promise<UpdateOffer | null>;
  dismissUpdate(kind: "not_now" | "skip"): Promise<void>;
  getJob(jobId: string): Promise<Job>;
  cancelJob(jobId: string): Promise<boolean>;
  getSettings(): Promise<UiSettings>;
  setSetting<K extends keyof SettingValues>(key: K, value: SettingValues[K]): Promise<void>;
  getThemeCatalog(): Promise<ThemeGroup[]>;
  countMatches(spec: FilterSpec): Promise<number>;
  /** A ratio mix's live counts (FR-3.10): all groups together, and each group, in one call. */
  countBuckets(spec: FilterSpec): Promise<BucketCounts>;
  getOpeningCatalog(): Promise<OpeningFamily[]>;
  listPresets(): Promise<Preset[]>;
  savePreset(name: string, spec: FilterSpec, overwrite: boolean): Promise<Preset>;
  renamePreset(oldName: string, newName: string): Promise<void>;
  deletePreset(name: string): Promise<void>;
  /** rated: the session's Rated toggle (FR-1.9); off syncs every solve as rated: false.
   *  mode (§6); showLength: Commit the line's Show move count (FR-4.2). */
  startSession(spec: FilterSpec, rated: boolean, mode: TrainingMode, showLength: boolean): Promise<SessionInfo>;
  /** Commit the line (FR-4.2): grade the whole line you entered (UCI, both sides). */
  submitLine(sessionId: number, moves: string[]): Promise<CommitFeedback>;
  /** Spaced repetition (FR-4.6): what's due. */
  getSrsStatus(): Promise<SrsStatus>;
  /** Depth ladder (FR-4.5): the level these filters would start at, and its pool size. */
  getLadderStatus(spec: FilterSpec): Promise<LadderPreview>;
  /** FR-4.6 fast-forward time: --dev runs only. */
  setTimeOffset(days: number): Promise<void>;
  /** The next puzzle, or null when the session is complete. */
  nextPuzzle(sessionId: number): Promise<PuzzleView | null>;
  submitMove(sessionId: number, uci: string): Promise<MoveFeedback>;
  /** Name the idea first (FR-4.3): your tags, before your first move. */
  setIdeaTags(sessionId: number, setup: string[], payoff: string[]): Promise<void>;
  /** Danger spotting (FR-4.4): is the highlighted move safe? */
  callDanger(sessionId: number, call: "safe" | "unsafe"): Promise<DangerFeedback>;
  /** §7.3: after a lost puzzle, once it's over, the reason chips (null: don't ask). */
  getReasonPrompt(sessionId: number): Promise<ReasonPrompt | null>;
  /** FR-5.6: save why you missed it; choosing again replaces it. */
  setMistakeReason(attemptId: number, reason: ReasonKey, note: string | null): Promise<void>;
  /** FR-9.7: the mistake-reason breakdown, optionally for one theme and/or mode. */
  getReasonStats(theme: string | null, mode: TrainingMode | null): Promise<ReasonStats>;
  /** Hint, then Show answer (§7.2). Before the puzzle is decided, either one makes it a loss. */
  requestHelp(sessionId: number, kind: "hint" | "answer"): Promise<HelpResponse>;
  /** FR-5.12 Try again (not scored): replay the finished puzzle from its start; nothing is recorded. */
  retryPuzzle(sessionId: number): Promise<void>;
  getSessionStats(sessionId: number): Promise<SessionStats>;
  /** The Stats page (FR-9.1, 9.2): every attempt you've made here. */
  getStats(): Promise<StatsReport>;
  /** Your Lichess account (FR-1.1, 1.6). Never includes a token. */
  getAccountStatus(): Promise<AccountStatus>;
  /** Opens Lichess in your default browser; resolves with the sign-in job's ID. */
  startSignIn(): Promise<string>;
  cancelSignIn(): Promise<void>;
  /** Revokes on Lichess, then removes it here (FR-6.6). forceLocal: remove it even if Lichess can't be reached. */
  signOut(forceLocal: boolean): Promise<void>;
  getSyncStatus(): Promise<SyncStatus>;
  /** FR-6.11b: the rating change (or why there isn't one) for these attempts. */
  getAttemptRatings(attemptIds: number[]): Promise<AttemptRating[]>;
  /** FR-9.4: your Lichess puzzle rating over time, from sync responses. */
  getRatingHistory(): Promise<RatingHistory>;
  // ---- Stockfish (v0.4) -----------------------------------------------------------------------
  /** Installed? Which engine, where (About, NFR-7)? An install in progress? */
  getEngineStatus(): Promise<EngineStatus>;
  /** FR-7.5: install the pinned Stockfish as a background job (force: reinstall). Returns the job ID. */
  startEngineInstall(force: boolean): Promise<string>;
  getEngineSettings(): Promise<EngineSettings>;
  /** FR-7.4: change any of think time, threads and hash (validated again in Python). */
  setEngineSettings(change: EngineSettingsChange): Promise<EngineSettings>;
  /** Native picker for your own engine's .exe; null if cancelled. */
  chooseEngineFile(): Promise<string | null>;
  /** Test your own engine and use it if it passes (FR-7.5 advanced). Returns the job ID. */
  startCustomEngineCheck(path: string): Promise<string>;
  clearCustomEngine(): Promise<void>;
  /** §7.2 step 2: the engine's answer to the move that lost the puzzle. Only once the puzzle is over. */
  getRefutation(sessionId: number): Promise<Refutation>;
  /** FR-7.2, 7.7: eval and top lines, only once the puzzle is over (the backend refuses earlier, FR-7.3). */
  analyzePosition(sessionId: number, fen: string, purpose: AnalysisPurpose): Promise<Analysis>;
  // ---- LLM settings, the cost guardrails and Explain (v0.7) -------------------------------------
  /** The AI settings, the price table's models with their cost per Explain, and this month's spend. Never a key. */
  getLlmSettings(): Promise<LlmSettings>;
  setLlmSettings(change: LlmSettingsChange): Promise<LlmSettings>;
  /** Saves the key in Windows Credential Manager (SR-1). It never comes back. */
  setLlmKey(provider: LlmProvider, key: string): Promise<LlmSettings>;
  deleteLlmKey(provider: LlmProvider): Promise<LlmSettings>;
  /** Test key (FR-1.4): the provider's free model lookup, as a job. Resolves with the job ID. */
  startLlmKeyTest(provider: LlmProvider, model: string): Promise<string>;
  listLlmPrices(): Promise<LlmPrice[]>;
  saveLlmPrice(row: LlmPriceChange): Promise<LlmPrice[]>;
  deleteLlmPrice(provider: LlmProvider, model: string): Promise<LlmPrice[]>;
  /** FR-1.10: this month's spend against the budget. */
  getLlmSpend(): Promise<LlmSpend>;
  /** Can Explain run for the puzzle that just ended, and about what would it cost (FR-8.11)? */
  getExplainQuote(sessionId: number): Promise<ExplainQuote>;
  /** Explain the puzzle that just ended (§7.2 step 3), as a job. Then call getExplanation. */
  startExplain(sessionId: number): Promise<string>;
  /** The explanation for the puzzle on the board, or null. Its text is plain: render it escaped (FR-8.7). */
  getExplanation(sessionId: number): Promise<Explanation | null>;
  /** Subscribe to pushed events (job progress, account, sync). Returns an unsubscribe function. */
  onEvent(listener: (event: BackendEvent) => void): () => void;
}
