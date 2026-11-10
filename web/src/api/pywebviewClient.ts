// Real client: calls the Python `Api` through pywebview's js_api bridge.
import {
  ApiCallError,
  type AnalysisPurpose,
  type ApiClient,
  type BackendEvent,
  type CoachAiOptions,
  type CoachParams,
  type EngineSettingsChange,
  type LlmPriceChange,
  type LlmProvider,
  type LlmSettingsChange,
  type GamesSettingsChange,
  type LibraryFilters,
  type ReasonKey,
  type ReasonSource,
  type SettingValues,
  type TrainingMode,
  JournalEntryInput,
  JournalFilters,
  PlanParams,
} from "./ApiClient";
import type {
  AccountStatus,
  BackupInfo,
  BackupStatus,
  RestoreNotice,
  Analysis,
  AnalysisQueue,
  ApiError,
  AppInfo,
  AttemptRating,
  BucketCounts,
  ChesscomProfile,
  CoachAiQuote,
  CoachAiRun,
  CoachAiRunSummary,
  CoachDefaults,
  CoachJournalLine,
  CoachNote,
  CoachReport,
  CoachReportSummary,
  CommitFeedback,
  DangerFeedback,
  EngineSettings,
  EngineStatus,
  ExplainQuote,
  Explanation,
  FilterSpec,
  GameAiQuote,
  GameImport,
  GameNarrative,
  GamePage,
  GameReview,
  GameStats,
  GamesSettings,
  HelpResponse,
  Job,
  JournalEntry,
  JournalTimeline,
  BookFamily,
  OpeningBookStatus,
  OpeningLines,
  OpeningNote,
  OpeningNoteQuote,
  OpeningNotesDeletion,
  OpeningDeviation,
  OpeningPrefetchPlan,
  OpeningStat,
  PracticeBranch,
  PracticeState,
  PracticeSummary,
  RepertoireProposal,
  OpeningPage,
  OpeningScope,
  OpeningSettings,
  Repertoire,
  RepertoireAdded,
  LadderPreview,
  LlmPrice,
  LlmSettings,
  LlmSpend,
  MoveFeedback,
  OpeningFamily,
  PlanPreview,
  PlanSettings,
  PlanTaskAction,
  Preset,
  PuzzleDbStatus,
  PuzzleImportReport,
  PuzzleSet,
  PuzzleView,
  RatingHistory,
  ReasonPrompt,
  ReasonStats,
  Refutation,
  RetryResult,
  SavedPuzzle,
  SessionInfo,
  SessionStats,
  SrsStatus,
  StatsReport,
  SuggestionView,
  SyncStatus,
  ThemeGroup,
  TodayPlan,
  TrainingPlan,
  UiSettings,
  UpdateOffer,
  AuthorStudy,
  StarterStudy,
  StudyAddResult,
  StudyChapter,
  PositionCheck,
  AnalysisPgnImport,
  AnalysisPgnGame,
  PopularReplies,
  StudyDetail,
  StudyPlace,
  StudySummary,
  StudyUpdate,
  StudyRepertoirePreview,
  CheckpointSettings,
  ProgressView,
  StatusNotice,
  SetupState,
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
  // ---- v0.9: a model per AI feature and Game Review AI -------------------------------------------
  setLlmFeature(feature: "game_review" | "coach", choice: "same" | LlmProvider, model: string, reasoning: LlmSettings["reasoning"]) {
    return this.call<LlmSettings>("set_llm_feature", feature, choice, model, reasoning);
  }

  getGameMoveQuote(gameId: number, ply: number) {
    return this.call<GameAiQuote>("get_game_move_quote", gameId, ply);
  }

  startGameMoveExplain(gameId: number, ply: number) {
    return this.call<string>("start_game_move_explain", gameId, ply);
  }

  getGameMoveExplanation(gameId: number, ply: number) {
    return this.call<Explanation | null>("get_game_move_explanation", gameId, ply);
  }

  getGameNarrativeQuote(gameId: number, n: number | null) {
    return this.call<GameAiQuote>("get_game_narrative_quote", gameId, n);
  }

  startGameNarrative(gameId: number, n: number | null) {
    return this.call<string>("start_game_narrative", gameId, n);
  }

  getGameNarrative(gameId: number, n: number | null) {
    return this.call<GameNarrative | null>("get_game_narrative", gameId, n);
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

  getReasonStats(theme: string | null, mode: TrainingMode | null, source: ReasonSource = "puzzles") {
    return this.call<ReasonStats>("get_reason_stats", theme, mode, source);
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

  getGamesSettings() {
    return this.call<GamesSettings>("get_games_settings");
  }

  setGamesSettings(c: GamesSettingsChange) {
    return this.call<GamesSettings>(
      "set_games_settings",
      c.sync_on_open ?? null,
      c.first_sync_days ?? null,
      c.first_sync_max ?? null,
      c.think_s ?? null,
      c.thresholds ?? null,
      c.tolerance_cp ?? null,
      c.key_moments ?? null,
    );
  }

  verifyChesscom(username: string) {
    return this.call<ChesscomProfile>("verify_chesscom", username);
  }

  setChesscomUsername(username: string | null) {
    return this.call<GamesSettings>("set_chesscom_username", username);
  }

  startGamesSync() {
    return this.call<string | null>("start_games_sync");
  }

  listGames(filters: LibraryFilters) {
    return this.call<GamePage>("list_games", filters);
  }

  importGamePgn(text: string) {
    return this.call<GameImport>("import_game_pgn", text);
  }

  chooseGameFile() {
    return this.call<GameImport | null>("choose_game_file");
  }

  pickImportedGame(token: string, index: number) {
    return this.call<GameImport>("pick_imported_game", token, index);
  }

  startGameUrlImport(url: string, chesscomUsername: string | null) {
    return this.call<string>("start_game_url_import", url, chesscomUsername);
  }

  getGameUrlImport(jobId: string) {
    return this.call<GameImport | null>("get_game_url_import", jobId);
  }

  setGameColor(gameId: number, color: "white" | "black" | "both") {
    return this.call<void>("set_game_color", gameId, color);
  }

  openGameOnline(gameId: number) {
    return this.call<void>("open_game_online", gameId);
  }

  analyzeGames(gameIds: number[], force: boolean) {
    return this.call<string | null>("analyze_games", gameIds, force);
  }

  getAnalysisQueue() {
    return this.call<AnalysisQueue>("get_analysis_queue");
  }

  getReview(gameId: number) {
    return this.call<GameReview>("get_review", gameId);
  }

  retryMove(gameId: number, ply: number, uci: string, thinkMs: number | null) {
    return this.call<RetryResult>("retry_move", gameId, ply, uci, thinkMs);
  }

  saveGamePuzzle(gameId: number, ply: number) {
    return this.call<SavedPuzzle>("save_game_puzzle", gameId, ply);
  }

  setGameReason(gameId: number, ply: number, reason: ReasonKey, note: string | null) {
    return this.call<void>("set_game_reason", gameId, ply, reason, note);
  }

  setRetryReason(retryId: number, reason: ReasonKey, note: string | null) {
    return this.call<void>("set_retry_reason", retryId, reason, note);
  }

  getGameStats() {
    return this.call<GameStats>("get_game_stats");
  }

  chooseAndImportPuzzles(label: string) {
    return this.call<string | null>("choose_and_import_puzzles", label);
  }

  getPuzzleImportReport(jobId: string) {
    return this.call<PuzzleImportReport | null>("get_puzzle_import_report", jobId);
  }

  listPuzzleSets() {
    return this.call<PuzzleSet[]>("list_puzzle_sets");
  }

  // ---- v0.13: the opening trainer (REQUIREMENTS §18) ----
  getOpeningBookStatus() {
    return this.call<OpeningBookStatus>("get_opening_book_status");
  }

  startOpeningBookImport() {
    return this.call<string>("start_opening_book_import");
  }

  getOpeningFamilies(query: string) {
    return this.call<BookFamily[]>("get_opening_families", query);
  }

  getOpeningSettings() {
    return this.call<OpeningSettings>("get_opening_settings");
  }

  setOpeningSources(useWikibooks: boolean, source: "lichess" | "masters", ratings: number[]) {
    return this.call<OpeningSettings>("set_opening_sources", useWikibooks, source, ratings);
  }

  getOpeningPage(sans: string[]) {
    return this.call<OpeningPage>("get_opening_page", sans);
  }

  setOpeningSettings(preset: OpeningScope["preset"], subLines: number | null, maxMoves: number | null, extend: boolean | null) {
    return this.call<OpeningSettings>("set_opening_settings", preset, subLines, maxMoves, extend);
  }

  getOpeningLines(family: string) {
    return this.call<OpeningLines>("get_opening_lines", family);
  }

  getOpeningNote(positionKey: string, moveUci: string, kind: "overview" | "move") {
    return this.call<OpeningNote | null>("get_opening_note", positionKey, moveUci, kind);
  }

  getOpeningNoteQuote(family: string, lineIndex: number, ply: number | null, regenerate: boolean) {
    return this.call<OpeningNoteQuote>("get_opening_note_quote", family, lineIndex, ply, regenerate);
  }

  startOpeningNote(family: string, lineIndex: number, ply: number | null, regenerate: boolean) {
    return this.call<string | null>("start_opening_note", family, lineIndex, ply, regenerate);
  }

  getOpeningMovesNoteQuote(moves: string[], regenerate: boolean) {
    return this.call<OpeningNoteQuote>("get_opening_moves_note_quote", moves, regenerate);
  }

  startOpeningMovesNote(moves: string[], regenerate: boolean) {
    return this.call<string | null>("start_opening_moves_note", moves, regenerate);
  }

  getOpeningOverviewKey(family: string) {
    return this.call<string>("get_opening_overview_key", family);
  }

  getOpeningPrefetchPlan(family: string, preset: OpeningScope["preset"], subLines: number | null, maxMoves: number | null, extend: boolean) {
    return this.call<OpeningPrefetchPlan>("get_opening_prefetch_plan", family, preset, subLines, maxMoves, extend);
  }

  startOpeningPrefetch(family: string, preset: OpeningScope["preset"], subLines: number | null, maxMoves: number | null, extend: boolean) {
    return this.call<string>("start_opening_prefetch", family, preset, subLines, maxMoves, extend);
  }

  exportOpeningNotes(family: string) {
    return this.call<string | null>("export_opening_notes", family);
  }

  getOpeningNotesDeletion(family: string) {
    return this.call<OpeningNotesDeletion>("get_opening_notes_deletion", family);
  }

  deleteOpeningNotes(family: string) {
    return this.call<number>("delete_opening_notes", family);
  }

  startOpeningExtend(family: string) {
    return this.call<string | null>("start_opening_extend", family);
  }

  analyzeOpeningPosition(fen: string, purpose: "start" | "panel" | "board", player: "white" | "black") {
    return this.call<Analysis>("analyze_opening_position", fen, purpose, player);
  }

  getOpeningDeviation(color: "white" | "black", moves: string[], theirMove: string) {
    return this.call<OpeningDeviation>("get_opening_deviation", color, moves, theirMove);
  }

  addOpeningDeviation(color: "white" | "black", moves: string[], theirMove: string, reply: string) {
    return this.call<RepertoireAdded>("add_opening_deviation", color, moves, theirMove, reply);
  }

  startRepertoireBuild(color: "white" | "black", family: string, limits: { max_moves: number; min_share: number; max_replies: number; max_positions: number }) {
    return this.call<string>("start_repertoire_build", color, family, limits);
  }

  getRepertoireProposal(proposalId: string) {
    return this.call<RepertoireProposal>("get_repertoire_proposal", proposalId);
  }

  saveRepertoireProposal(proposalId: string) {
    return this.call<RepertoireAdded>("save_repertoire_proposal", proposalId);
  }

  discardRepertoireProposal(proposalId: string) {
    return this.call<void>("discard_repertoire_proposal", proposalId);
  }

  getPracticeSummary(color: "white" | "black") {
    return this.call<PracticeSummary>("get_practice_summary", color);
  }

  getPracticeTolerance() {
    return this.call<boolean>("get_practice_tolerance");
  }

  setPracticeTolerance(on: boolean) {
    return this.call<boolean>("set_practice_tolerance", on);
  }

  getPracticeBranches(color: "white" | "black", openingId: number | null) {
    return this.call<PracticeBranch[]>("get_practice_branches", color, openingId);
  }

  startPractice(color: "white" | "black", mode: "due" | "new" | "all", openingId: number | null, branch: string | null) {
    return this.call<PracticeState>("start_practice", color, mode, openingId, branch);
  }

  playPracticeMove(sessionId: string, uci: string) {
    return this.call<PracticeState>("play_practice_move", sessionId, uci);
  }

  showPracticeAnswer(sessionId: string) {
    return this.call<PracticeState>("show_practice_answer", sessionId);
  }

  continuePractice(sessionId: string) {
    return this.call<PracticeState>("continue_practice", sessionId);
  }

  endPractice(sessionId: string) {
    return this.call<void>("end_practice", sessionId);
  }

  setPracticeReason(attemptId: number, reason: ReasonKey, note: string | null) {
    return this.call<void>("set_practice_reason", attemptId, reason, note);
  }

  getOpeningStats(color: "white" | "black") {
    return this.call<OpeningStat[]>("get_opening_stats", color);
  }

  matchOpeningFamily(name: string) {
    return this.call<string | null>("match_opening_family", name);
  }

  getRepertoire(color: "white" | "black") {
    return this.call<Repertoire>("get_repertoire", color);
  }

  addRepertoireLines(color: "white" | "black", family: string, lineIndices: number[]) {
    return this.call<RepertoireAdded>("add_repertoire_lines", color, family, lineIndices);
  }

  previewRepertoireRemoval(color: "white" | "black", positionKey: string, moveUci: string) {
    return this.call<string[]>("preview_repertoire_removal", color, positionKey, moveUci);
  }

  removeRepertoireMove(color: "white" | "black", positionKey: string, moveUci: string) {
    return this.call<Repertoire>("remove_repertoire_move", color, positionKey, moveUci);
  }

  setRepertoireMain(color: "white" | "black", positionKey: string, moveUci: string) {
    return this.call<Repertoire>("set_repertoire_main", color, positionKey, moveUci);
  }

  moveRepertoireMove(color: "white" | "black", positionKey: string, moveUci: string, direction: "up" | "down") {
    return this.call<Repertoire>("move_repertoire_move", color, positionKey, moveUci, direction);
  }

  // ---- v0.10 ---------------------------------------------------------------------------------------
  analyzeGamePosition(gameId: number, fen: string, purpose: "panel" | "board") {
    return this.call<Analysis>("analyze_game_position", gameId, fen, purpose);
  }

  archiveMyPuzzle(puzzleId: number) {
    return this.call<void>("archive_my_puzzle", puzzleId);
  }

  getCoachDefaults() {
    return this.call<CoachDefaults>("get_coach_defaults");
  }

  startCoachRun(params: CoachParams) {
    return this.call<string>("start_coach_run", params);
  }

  getCoachRunResult(jobId: string) {
    return this.call<number | null>("get_coach_run_result", jobId);
  }

  listCoachReports() {
    return this.call<CoachReportSummary[]>("list_coach_reports");
  }

  getCoachReport(reportId: number) {
    return this.call<CoachReport>("get_coach_report", reportId);
  }

  getCoachAiQuote(reportId: number, options: CoachAiOptions) {
    return this.call<CoachAiQuote>("get_coach_ai_quote", reportId, options);
  }

  startCoachAi(reportId: number, options: CoachAiOptions) {
    return this.call<string>("start_coach_ai", reportId, options);
  }

  getCoachAiJobRun(jobId: string) {
    return this.call<number | null>("get_coach_ai_job_run", jobId);
  }

  listCoachAiRuns(reportId: number) {
    return this.call<CoachAiRunSummary[]>("list_coach_ai_runs", reportId);
  }

  getCoachAiRun(reportId: number, runId: number) {
    return this.call<CoachAiRun | null>("get_coach_ai_run", reportId, runId);
  }

  getCoachNotesPreview(reportId: number) {
    return this.call<CoachNote[]>("get_coach_notes_preview", reportId);
  }

  openLesson(reportId: number, topic: string, target: string) {
    return this.call<void>("open_lesson", reportId, topic, target);
  }

  getCoachJournalPreview(reportId: number) {
    return this.call<CoachJournalLine[]>("get_coach_journal_preview", reportId);
  }

  getPlanSettings() {
    return this.call<PlanSettings>("get_plan_settings");
  }

  previewPlan(params: PlanParams | null) {
    return this.call<PlanPreview>("preview_plan", params);
  }

  createPlan(params: PlanParams, confirmed: boolean) {
    return this.call<TrainingPlan>("create_plan", params, confirmed);
  }

  useAiPlan(runId: number, confirmed: boolean) {
    return this.call<TrainingPlan>("use_ai_plan", runId, confirmed);
  }

  getCurrentPlan() {
    return this.call<TrainingPlan | null>("get_current_plan");
  }

  getTodayPlan() {
    return this.call<TodayPlan | null>("get_today_plan");
  }

  listPlans() {
    return this.call<TrainingPlan[]>("list_plans");
  }

  setPlanTaskTick(taskId: number, done: boolean) {
    return this.call<void>("set_plan_task_tick", taskId, done);
  }

  skipPlanTask(taskId: number, skipped: boolean) {
    return this.call<void>("skip_plan_task", taskId, skipped);
  }

  swapPlanTask(taskId: number) {
    return this.call<number>("swap_plan_task", taskId);
  }

  startPlanTask(taskId: number, rated: boolean) {
    return this.call<PlanTaskAction>("start_plan_task", taskId, rated);
  }

  startPlanLessonDrill(taskId: number, rated: boolean) {
    return this.call<PlanTaskAction>("start_plan_lesson_drill", taskId, rated);
  }

  openPlanLesson(taskId: number, target: string) {
    return this.call<void>("open_plan_lesson", taskId, target);
  }

  markReviewPly(gameId: number, ply: number) {
    return this.call<boolean>("mark_review_ply", gameId, ply);
  }

  getJournal(filters: JournalFilters) {
    return this.call<JournalTimeline>("get_journal", filters);
  }

  addJournalEntry(entry: JournalEntryInput) {
    return this.call<JournalEntry>("add_journal_entry", entry);
  }

  editJournalEntry(entryId: number, text: string, weaknessKey: string | null) {
    return this.call<JournalEntry>("edit_journal_entry", entryId, text, weaknessKey);
  }

  deleteJournalEntry(entryId: number) {
    return this.call<void>("delete_journal_entry", entryId);
  }

  getGameNotes(gameId: number) {
    return this.call<JournalEntry[]>("get_game_notes", gameId);
  }

  getSuggestion() {
    return this.call<SuggestionView | null>("get_suggestion");
  }

  applySuggestion() {
    return this.call<SuggestionView>("apply_suggestion");
  }

  dismissSuggestion() {
    return this.call<SuggestionView | null>("dismiss_suggestion");
  }

  // v0.14: Lichess studies
  addStudy(text: string) {
    return this.call<string>("add_study", text);
  }

  addStudyById(studyId: string, chapterId: string | null) {
    return this.call<string>("add_study_by_id", studyId, chapterId);
  }

  getStudyAddResult(jobId: string) {
    return this.call<StudyAddResult | null>("get_study_add_result", jobId);
  }

  findAuthorStudies(username: string) {
    return this.call<AuthorStudy[]>("find_author_studies", username);
  }

  getStudyStarterList() {
    return this.call<StarterStudy[]>("get_study_starter_list");
  }

  listStudies(which: "all" | "favorites" | "in_progress" | "finished") {
    return this.call<StudySummary[]>("list_studies", which);
  }

  getStudy(studyId: string) {
    return this.call<StudyDetail>("get_study", studyId);
  }

  checkBoardPosition(fen: string) {
    return this.call<PositionCheck>("check_board_position", fen);
  }

  importAnalysisPgn(pgn: string) {
    return this.call<AnalysisPgnImport>("import_analysis_pgn", pgn);
  }

  getAnalysisPgnGame(pgn: string, index: number) {
    return this.call<AnalysisPgnGame>("get_analysis_pgn_game", pgn, index);
  }

  analyzeBoardPosition(fen: string, purpose: "start" | "panel" | "board") {
    return this.call<Analysis>("analyze_board_position", fen, purpose);
  }

  getPopularReplies(fen: string) {
    return this.call<PopularReplies>("get_popular_replies", fen);
  }

  getStudyChapter(studyId: string, chapterKey: string) {
    return this.call<StudyChapter>("get_study_chapter", studyId, chapterKey);
  }

  setStudyPlace(studyId: string, chapterKey: string, path: string[]) {
    return this.call<void>("set_study_place", studyId, chapterKey, path);
  }

  getStudyContinue(studyId: string) {
    return this.call<StudyPlace>("get_study_continue", studyId);
  }

  setStudyChapterDone(studyId: string, chapterKey: string, done: boolean) {
    return this.call<void>("set_study_chapter_done", studyId, chapterKey, done);
  }

  restartStudy(studyId: string) {
    return this.call<void>("restart_study", studyId);
  }

  heartStudy(studyId: string, hearted: boolean) {
    return this.call<void>("heart_study", studyId, hearted);
  }

  deleteStudy(studyId: string) {
    return this.call<void>("delete_study", studyId);
  }

  previewStudyRepertoire(studyId: string, chapterKey: string | null, color: "white" | "black", sideLines: boolean) {
    return this.call<StudyRepertoirePreview>("preview_study_repertoire", studyId, chapterKey, color, sideLines);
  }

  saveStudyRepertoire(previewId: string, choices: Record<string, "mine" | "study">) {
    return this.call<RepertoireAdded>("save_study_repertoire", previewId, choices);
  }

  discardStudyRepertoire() {
    return this.call<void>("discard_study_repertoire");
  }

  checkStudyUpdates(studyId: string) {
    return this.call<string>("check_study_updates", studyId);
  }

  getStudyUpdate(studyId: string) {
    return this.call<StudyUpdate | null>("get_study_update", studyId);
  }

  applyStudyUpdate(studyId: string) {
    return this.call<void>("apply_study_update", studyId);
  }

  discardStudyUpdate(studyId: string) {
    return this.call<void>("discard_study_update", studyId);
  }

  openStudyOnLichess(studyId: string, chapterKey: string | null) {
    return this.call<void>("open_study_on_lichess", studyId, chapterKey);
  }

  openLichessStudiesInBrowser() {
    return this.call<void>("open_lichess_studies_in_browser");
  }

  openLichessWindow() {
    return this.call<boolean>("open_lichess_window");
  }

  closeLichessWindow() {
    return this.call<void>("close_lichess_window");
  }

  isLichessWindowOpen() {
    return this.call<boolean>("is_lichess_window_open");
  }

  getBackupStatus() {
    return this.call<BackupStatus>("get_backup_status");
  }

  setBackupSettings(enabled: boolean, folder: string | null, intervalDays: number, keep: number) {
    return this.call<BackupStatus>("set_backup_settings", enabled, folder, intervalDays, keep);
  }

  chooseBackupFolder() {
    return this.call<string | null>("choose_backup_folder");
  }

  backupNow() {
    return this.call<string | null>("backup_now");
  }

  chooseBackupToRestore() {
    return this.call<BackupInfo | null>("choose_backup_to_restore");
  }

  restoreBackup(token: string) {
    return this.call<string>("restore_backup", token);
  }

  takeRestoreNotice() {
    return this.call<RestoreNotice | null>("take_restore_notice");
  }

  getProgress() {
    return this.call<ProgressView>("get_progress");
  }

  getCheckpointSettings() {
    return this.call<CheckpointSettings>("get_checkpoint_settings");
  }

  setCheckpointSettings(settings: CheckpointSettings) {
    return this.call<CheckpointSettings>("set_checkpoint_settings", settings);
  }

  runCheckpointNow() {
    return this.call<string>("run_checkpoint_now");
  }

  takeStatusNotices() {
    return this.call<StatusNotice[]>("take_status_notices");
  }

  getSetupState() {
    return this.call<SetupState>("get_setup_state");
  }

  chooseSetup(choice: "fresh") {
    return this.call<SetupState>("choose_setup", choice);
  }

  skipSetupStep(step: "engine" | "lichess") {
    return this.call<SetupState>("skip_setup_step", step);
  }

  finishSetup() {
    return this.call<SetupState>("finish_setup");
  }

  onEvent(listener: (event: BackendEvent) => void) {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }
}
