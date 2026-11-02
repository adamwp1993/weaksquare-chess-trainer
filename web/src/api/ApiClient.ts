// The only way the UI talks to the backend (ARCHITECTURE §3 decision 8).
// Two implementations: pywebviewClient (the real app) and mockClient (UI development, Playwright).
import type {
  AccountStatus,
  AttemptRating,
  BucketCounts,
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
  /** rated: the session's Rated toggle (FR-1.9); off syncs every solve as rated: false. */
  startSession(spec: FilterSpec, rated: boolean): Promise<SessionInfo>;
  /** The next puzzle, or null when the session is complete. */
  nextPuzzle(sessionId: number): Promise<PuzzleView | null>;
  submitMove(sessionId: number, uci: string): Promise<MoveFeedback>;
  /** Hint, then Show answer (§7.2). Before the puzzle is decided, either one makes it a loss. */
  requestHelp(sessionId: number, kind: "hint" | "answer"): Promise<HelpResponse>;
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
  /** Subscribe to pushed events (job progress, account, sync). Returns an unsubscribe function. */
  onEvent(listener: (event: BackendEvent) => void): () => void;
}
