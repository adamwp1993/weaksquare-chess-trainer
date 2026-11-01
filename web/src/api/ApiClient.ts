// The only way the UI talks to the backend (ARCHITECTURE §3 decision 8).
// Two implementations: pywebviewClient (the real app) and mockClient (UI development, Playwright).
import type {
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
  SessionInfo,
  SessionStats,
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

export type BackendEvent = { name: "job"; payload: Job };

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
  getJob(jobId: string): Promise<Job>;
  cancelJob(jobId: string): Promise<boolean>;
  getSettings(): Promise<UiSettings>;
  setSetting(key: "mixer.filters", value: FilterSpec): Promise<void>;
  getThemeCatalog(): Promise<ThemeGroup[]>;
  countMatches(spec: FilterSpec): Promise<number>;
  /** The live count of each ratio group (FR-3.10). */
  countBuckets(spec: FilterSpec): Promise<number[]>;
  getOpeningCatalog(): Promise<OpeningFamily[]>;
  listPresets(): Promise<Preset[]>;
  savePreset(name: string, spec: FilterSpec, overwrite: boolean): Promise<Preset>;
  renamePreset(oldName: string, newName: string): Promise<void>;
  deletePreset(name: string): Promise<void>;
  startSession(spec: FilterSpec): Promise<SessionInfo>;
  /** The next puzzle, or null when the session is complete. */
  nextPuzzle(sessionId: number): Promise<PuzzleView | null>;
  submitMove(sessionId: number, uci: string): Promise<MoveFeedback>;
  /** Hint, then Show answer (§7.2). Before the puzzle is decided, either one makes it a loss. */
  requestHelp(sessionId: number, kind: "hint" | "answer"): Promise<HelpResponse>;
  getSessionStats(sessionId: number): Promise<SessionStats>;
  /** Subscribe to pushed events (job progress). Returns an unsubscribe function. */
  onEvent(listener: (event: BackendEvent) => void): () => void;
}
