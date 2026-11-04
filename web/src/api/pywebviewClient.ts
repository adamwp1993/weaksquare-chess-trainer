// Real client: calls the Python `Api` through pywebview's js_api bridge.
import {
  ApiCallError,
  type AnalysisPurpose,
  type ApiClient,
  type BackendEvent,
  type EngineSettingsChange,
  type LlmPriceChange,
  type LlmProvider,
  type LlmSettingsChange,
  type ReasonKey,
  type SettingValues,
  type TrainingMode,
} from "./ApiClient";
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
  StatsReport,
  SyncStatus,
  UpdateOffer,
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

  retryPuzzle(sessionId: number) {
    return this.call<void>("retry_puzzle", sessionId);
  }

  getEngineStatus() {
    return this.call<EngineStatus>("get_engine_status");
  }

  startEngineInstall(force: boolean) {
    return this.call<string>("start_engine_install", force);
  }

  getEngineSettings() {
    return this.call<EngineSettings>("get_engine_settings");
  }

  setEngineSettings(change: EngineSettingsChange) {
    const { think_s = null, threads = null, hash_mb = null } = change;
    return this.call<EngineSettings>("set_engine_settings", think_s, threads, hash_mb);
  }

  chooseEngineFile() {
    return this.call<string | null>("choose_engine_file");
  }

  startCustomEngineCheck(path: string) {
    return this.call<string>("start_custom_engine_check", path);
  }

  clearCustomEngine() {
    return this.call<void>("clear_custom_engine");
  }

  getRefutation(sessionId: number) {
    return this.call<Refutation>("get_refutation", sessionId);
  }

  analyzePosition(sessionId: number, fen: string, purpose: AnalysisPurpose) {
    return this.call<Analysis>("analyze_position", sessionId, fen, purpose);
  }

  // ---- v0.7: LLM settings, guardrails, Explain --------------------------------------------------
  getLlmSettings() {
    return this.call<LlmSettings>("get_llm_settings");
  }

  setLlmSettings(c: LlmSettingsChange) {
    return this.call<LlmSettings>("set_llm_settings", c.provider, c.model, c.reasoning, c.run_cap_usd, c.monthly_budget_usd);
  }

  setLlmKey(provider: LlmProvider, key: string) {
    return this.call<LlmSettings>("set_llm_key", provider, key);
  }

  deleteLlmKey(provider: LlmProvider) {
    return this.call<LlmSettings>("delete_llm_key", provider);
  }

  startLlmKeyTest(provider: LlmProvider, model: string) {
    return this.call<string>("start_llm_key_test", provider, model);
  }

  listLlmPrices() {
    return this.call<LlmPrice[]>("list_llm_prices");
  }

  saveLlmPrice(r: LlmPriceChange) {
    return this.call<LlmPrice[]>(
      "save_llm_price",
      r.provider,
      r.model,
      r.input_per_m,
      r.output_per_m,
      r.long_ctx_threshold ?? null,
      r.long_input_per_m ?? null,
      r.long_output_per_m ?? null,
      r.as_of ?? null,
    );
  }

  deleteLlmPrice(provider: LlmProvider, model: string) {
    return this.call<LlmPrice[]>("delete_llm_price", provider, model);
  }

  getLlmSpend() {
    return this.call<LlmSpend>("get_llm_spend");
  }

  getExplainQuote(sessionId: number) {
    return this.call<ExplainQuote>("get_explain_quote", sessionId);
  }

  startExplain(sessionId: number) {
    return this.call<string>("start_explain", sessionId);
  }

  getExplanation(sessionId: number) {
    return this.call<Explanation | null>("get_explanation", sessionId);
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

  checkForDbUpdate(force: boolean) {
    return this.call<string>("check_for_db_update", force);
  }

  getUpdateOffer() {
    return this.call<UpdateOffer | null>("get_update_offer");
  }

  dismissUpdate(kind: "not_now" | "skip") {
    return this.call<void>("dismiss_update", kind);
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
    return this.call<BucketCounts>("count_buckets", spec);
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

  startSession(spec: FilterSpec, rated: boolean, mode: TrainingMode, showLength: boolean) {
    return this.call<SessionInfo>("start_session", spec, rated, mode, showLength);
  }

  submitLine(sessionId: number, moves: string[]) {
    return this.call<CommitFeedback>("submit_line", sessionId, moves);
  }

  getSrsStatus() {
    return this.call<SrsStatus>("get_srs_status");
  }

  getLadderStatus(spec: FilterSpec) {
    return this.call<LadderPreview>("get_ladder_status", spec);
  }

  setTimeOffset(days: number) {
    return this.call<void>("set_time_offset", days);
  }

  nextPuzzle(sessionId: number) {
    return this.call<PuzzleView | null>("next_puzzle", sessionId);
  }

  submitMove(sessionId: number, uci: string) {
    return this.call<MoveFeedback>("submit_move", sessionId, uci);
  }

  setIdeaTags(sessionId: number, setup: string[], payoff: string[]) {
    return this.call<void>("set_idea_tags", sessionId, setup, payoff);
  }

  callDanger(sessionId: number, call: "safe" | "unsafe") {
    return this.call<DangerFeedback>("call_danger", sessionId, call);
  }

  getReasonPrompt(sessionId: number) {
    return this.call<ReasonPrompt | null>("get_reason_prompt", sessionId);
  }

  setMistakeReason(attemptId: number, reason: ReasonKey, note: string | null) {
    return this.call<void>("set_mistake_reason", attemptId, reason, note);
  }

  getReasonStats(theme: string | null, mode: TrainingMode | null) {
    return this.call<ReasonStats>("get_reason_stats", theme, mode);
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

  getAccountStatus() {
    return this.call<AccountStatus>("get_account_status");
  }

  startSignIn() {
    return this.call<string>("start_sign_in");
  }

  cancelSignIn() {
    return this.call<void>("cancel_sign_in");
  }

  signOut(forceLocal: boolean) {
    return this.call<void>("sign_out", forceLocal);
  }

  getSyncStatus() {
    return this.call<SyncStatus>("get_sync_status");
  }

  getAttemptRatings(attemptIds: number[]) {
    return this.call<AttemptRating[]>("get_attempt_ratings", attemptIds);
  }

  getRatingHistory() {
    return this.call<RatingHistory>("get_rating_history");
  }

  onEvent(listener: (event: BackendEvent) => void) {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }
}
