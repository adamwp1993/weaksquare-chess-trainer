// Real client: calls the Python `Api` through pywebview's js_api bridge.
import { ApiCallError, type ApiClient, type BackendEvent, type SettingValues } from "./ApiClient";
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
  StatsReport,
  ThemeGroup,
  UiSettings,
} from "./types";

type Envelope<T> = { ok: true; data: T } | { ok: false; error: ApiError };
type PyApi = Record<string, (...args: unknown[]) => Promise<Envelope<unknown>>>;

declare global {
  interface Window {
    pywebview?: { api: PyApi };
    __ws_events?: (event: BackendEvent) => void;
  }
}

function bridgeReady(): Promise<PyApi> {
  return new Promise((resolve) => {
    if (window.pywebview?.api) {
      resolve(window.pywebview.api);
      return;
    }
    window.addEventListener("pywebviewready", () => resolve(window.pywebview!.api), { once: true });
  });
}

export class PywebviewClient implements ApiClient {
  private readonly listeners = new Set<(event: BackendEvent) => void>();

  constructor() {
    window.__ws_events = (event) => this.listeners.forEach((l) => l(event));
  }

  private async call<T>(method: string, ...args: unknown[]): Promise<T> {
    const api = await bridgeReady();
    const fn = api[method];
    if (!fn) throw new ApiCallError({ code: "internal", message: `Unknown method ${method}`, retryable: false });
    const result = (await fn(...args)) as Envelope<T>;
    if (!result.ok) throw new ApiCallError(result.error);
    return result.data;
  }

  getAppInfo() {
    return this.call<AppInfo>("get_app_info");
  }

  openFolder(kind: "data" | "logs") {
    return this.call<void>("open_folder", kind);
  }

  logFrontendError(message: string, source: string) {
    return this.call<void>("log_frontend_error", message, source);
  }

  getPuzzleDbStatus() {
    return this.call<PuzzleDbStatus>("get_puzzle_db_status");
  }

  choosePuzzleFile() {
    return this.call<string | null>("choose_puzzle_file");
  }

  startPuzzleImport(localPath: string | null) {
    return this.call<string>("start_puzzle_import", localPath);
  }

  startPuzzleDbUpgrade() {
    return this.call<string>("start_puzzle_db_upgrade");
  }

  getJob(jobId: string) {
    return this.call<Job>("get_job", jobId);
  }

  cancelJob(jobId: string) {
    return this.call<boolean>("cancel_job", jobId);
  }

  getSettings() {
    return this.call<UiSettings>("get_settings");
  }

  setSetting<K extends keyof SettingValues>(key: K, value: SettingValues[K]) {
    return this.call<void>("set_setting", key, value);
  }

  getThemeCatalog() {
    return this.call<ThemeGroup[]>("get_theme_catalog");
  }

  countMatches(spec: FilterSpec) {
    return this.call<number>("count_matches", spec);
  }

  countBuckets(spec: FilterSpec) {
    return this.call<number[]>("count_buckets", spec);
  }

  getOpeningCatalog() {
    return this.call<OpeningFamily[]>("get_opening_catalog");
  }

  listPresets() {
    return this.call<Preset[]>("list_presets");
  }

  savePreset(name: string, spec: FilterSpec, overwrite: boolean) {
    return this.call<Preset>("save_preset", name, spec, overwrite);
  }

  renamePreset(oldName: string, newName: string) {
    return this.call<void>("rename_preset", oldName, newName);
  }

  deletePreset(name: string) {
    return this.call<void>("delete_preset", name);
  }

  startSession(spec: FilterSpec) {
    return this.call<SessionInfo>("start_session", spec);
  }

  nextPuzzle(sessionId: number) {
    return this.call<PuzzleView | null>("next_puzzle", sessionId);
  }

  submitMove(sessionId: number, uci: string) {
    return this.call<MoveFeedback>("submit_move", sessionId, uci);
  }

  requestHelp(sessionId: number, kind: "hint" | "answer") {
    return this.call<HelpResponse>("request_help", sessionId, kind);
  }

  getSessionStats(sessionId: number) {
    return this.call<SessionStats>("get_session_stats", sessionId);
  }

  getStats() {
    return this.call<StatsReport>("get_stats");
  }

  onEvent(listener: (event: BackendEvent) => void) {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }
}
