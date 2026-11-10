// The only way the UI talks to the backend (ARCHITECTURE §3 decision 8).
// Two implementations: pywebviewClient (the real app) and mockClient (UI development, Playwright).
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
  SoundSettings,
  SrsStatus,
  StatsReport,
  SuggestionView,
  SyncEvent,
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
  StudyWindowEvent,
  StudyRepertoirePreview,
  CheckpointSettings,
  ProgressView,
  StatusNotice,
} from "./types";

/** v0.10: one Coach run's settings (FR-10.2–10.5). `player` null means you. */
export interface CoachParams {
  source: "puzzles" | "games" | "both";
  player: string | null;
  platform: "lichess" | "chesscom";
  platforms: ("lichess" | "chesscom")[];
  count: 25 | 50 | 100 | 200;
  rated_only: boolean;
  time_classes: string[];
  color: "both" | "white" | "black";
  detail: "summary" | "detailed";
  game_ids: number[];
}

/** v0.8: the My games filters (FR-11.26); empty or missing fields don't filter. Dates are YYYY-MM-DD. */
export interface LibraryFilters {
  platforms?: ("lichess" | "chesscom" | "paste" | "file")[];
  time_classes?: string[];
  rated?: boolean | null;
  results?: ("win" | "loss" | "draw")[];
  colors?: ("white" | "black")[];
  opponent?: string;
  opening?: string;
  date_from?: string | null;
  date_to?: string | null;
  statuses?: ("none" | "analyzed")[];
  player?: string; // v0.10: "me" (default) or another player's subject, "lichess:<name>"
  limit?: number;
  offset?: number;
}

/** v0.8: the Games settings saved together (any field may be left out). */
export interface GamesSettingsChange {
  sync_on_open?: boolean;
  first_sync_days?: number;
  first_sync_max?: number;
  think_s?: number;
  thresholds?: { inaccuracy: number; mistake: number; blunder: number; decided?: number };
  tolerance_cp?: number;
  key_moments?: number;
  puzzle_level?: "blunders" | "mistakes" | "inaccuracies"; // v0.10, FR-10.40
  puzzle_think_s?: number;
}

export type ReasonSource = "puzzles" | "games" | "all";

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
  | { name: "sync"; payload: SyncEvent }
  | { name: "study_window"; payload: StudyWindowEvent };

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
  "reasons.ask": "always" | "game_review" | "off";
  "reasons.rushed_s": number;
  // v0.10
  "review.show_best": boolean;
  // v0.11 (FR-10.59)
  "coach.lesson_sites": ("youtube" | "chesscom" | "custom")[];
  "coach.lesson_custom_url": string;
  // v0.12 (FR-10.61, 10.64)
  "plan.params": PlanParams;
  "plan.carry_over": boolean;
}

/** One AI coaching run's options (FR-10.56, 10.60): chosen each time, off by default, never saved. */
export interface CoachAiOptions {
  advanced: boolean;
  game_cap: number;
  include_notes: boolean;
  include_journal: boolean; // v0.12, FR-10.71
}

/** v0.12: the settings of a training plan (FR-10.61). `weekdays`: Monday = 0. */
export interface PlanParams {
  weeks: number;
  weekdays: number[];
  minutes: number;
}

/** v0.12: a new journal entry (FR-10.67, 10.69). With a game it's a reflection. */
export interface JournalEntryInput {
  text: string;
  entry_date?: string;
  weakness_key?: string | null;
  game_id?: number | null;
  ply?: number | null;
  plan_day_id?: number | null;
  plan_task_id?: number | null;
}

/** v0.12: the Journal tab's filters (FR-10.70). */
export interface JournalFilters {
  kinds?: ("note" | "reflection" | "log")[];
  game_id?: number;
  weakness_key?: string;
  date_from?: string;
  date_to?: string;
  query?: string;
  before?: string;
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
  getReasonStats(theme: string | null, mode: TrainingMode | null, source?: ReasonSource): Promise<ReasonStats>;
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
  // ---- v0.9: a model per AI feature (FR-1.15) and Game Review AI (§11.4) -----------------------
  /** Game Review's own provider and model, or "same" to follow Explain's; and its reasoning level. */
  setLlmFeature(feature: "game_review" | "coach" | "openings", choice: "same" | LlmProvider, model: string, reasoning: LlmSettings["reasoning"]): Promise<LlmSettings>;
  /** Can Explain this move run for one of your analyzed moves, and about what would it cost? */
  getGameMoveQuote(gameId: number, ply: number): Promise<GameAiQuote>;
  /** Explain this move (FR-11.17), as a job. Then call getGameMoveExplanation. */
  startGameMoveExplain(gameId: number, ply: number): Promise<string>;
  /** This move's explanation under the current Game Review model (fresh or saved), or null. Plain text. */
  getGameMoveExplanation(gameId: number, ply: number): Promise<Explanation | null>;
  /** The estimate shown before Explain my game (FR-8.11). `n` null: the Key moments setting. */
  getGameNarrativeQuote(gameId: number, n: number | null): Promise<GameAiQuote>;
  /** Explain my game (FR-11.18), as a job; only after you confirm the estimate. */
  startGameNarrative(gameId: number, n: number | null): Promise<string>;
  getGameNarrative(gameId: number, n: number | null): Promise<GameNarrative | null>;
  // ---- Game library, Game Review and your own puzzles (v0.8) ----------------------------------
  getGamesSettings(): Promise<GamesSettings>;
  setGamesSettings(change: GamesSettingsChange): Promise<GamesSettings>;
  /** FR-11.24 Verify: the public profile (not_found: no such player). */
  verifyChesscom(username: string): Promise<ChesscomProfile>;
  /** Link (or unlink with null) a chess.com username. */
  setChesscomUsername(username: string | null): Promise<GamesSettings>;
  /** FR-11.27: sync both linked accounts as a job; null when no account is linked. */
  startGamesSync(): Promise<string | null>;
  listGames(filters: LibraryFilters): Promise<GamePage>;
  importGamePgn(text: string): Promise<GameImport>;
  /** Native Open dialog for a .pgn; null if cancelled. Several games come back as choices. */
  chooseGameFile(): Promise<GameImport | null>;
  pickImportedGame(token: string, index: number): Promise<GameImport>;
  /** A Lichess or chess.com game URL, as a job; then getGameUrlImport. */
  startGameUrlImport(url: string, chesscomUsername: string | null): Promise<string>;
  getGameUrlImport(jobId: string): Promise<GameImport | null>;
  setGameColor(gameId: number, color: "white" | "black" | "both"): Promise<void>;
  openGameOnline(gameId: number): Promise<void>;
  /** Queue games for the background engine (FR-11.31); null when there's nothing to do. */
  analyzeGames(gameIds: number[], force: boolean): Promise<string | null>;
  getAnalysisQueue(): Promise<AnalysisQueue>;
  getReview(gameId: number): Promise<GameReview>;
  /** Retry mode (FR-11.15): the answer comes back only with the result. */
  retryMove(gameId: number, ply: number, uci: string, thinkMs: number | null): Promise<RetryResult>;
  saveGamePuzzle(gameId: number, ply: number): Promise<SavedPuzzle>;
  setGameReason(gameId: number, ply: number, reason: ReasonKey, note: string | null): Promise<void>;
  setRetryReason(retryId: number, reason: ReasonKey, note: string | null): Promise<void>;
  getGameStats(): Promise<GameStats>;
  /** FR-10.46: Open dialog, then the import job; null if cancelled. */
  chooseAndImportPuzzles(label: string): Promise<string | null>;
  getPuzzleImportReport(jobId: string): Promise<PuzzleImportReport | null>;
  listPuzzleSets(): Promise<PuzzleSet[]>;
  // ---- v0.10: Game Review additions, your puzzles, the Coach -----------------------------------
  /** Analyze from here (FR-11.34): the interactive engine on any position of the free board. */
  analyzeGamePosition(gameId: number, fen: string, purpose: "panel" | "board"): Promise<Analysis>;
  /** FR-10.44: archive one of your puzzles you don't want (kept, never served). */
  archiveMyPuzzle(puzzleId: number): Promise<void>;
  getCoachDefaults(): Promise<CoachDefaults>;
  /** A Coach run (sync, analyze, tag, puzzles, report) as a job; then getCoachRunResult. */
  startCoachRun(params: CoachParams): Promise<string>;
  getCoachRunResult(jobId: string): Promise<number | null>;
  listCoachReports(): Promise<CoachReportSummary[]>;
  getCoachReport(reportId: number): Promise<CoachReport>;
  // ---- v0.11: whole-game coaching (§10.11) ------------------------------------------------------
  /** The estimate for this run's options; with Advanced, how it compares with a standard run (FR-10.56). */
  getCoachAiQuote(reportId: number, options: CoachAiOptions): Promise<CoachAiQuote>;
  /** Get AI coaching (FR-10.21–10.25, 10.54), only after you confirm the estimate. Options are never saved. */
  startCoachAi(reportId: number, options: CoachAiOptions): Promise<string>;
  /** The AI run a finished Get AI coaching job made (or showed again). */
  getCoachAiJobRun(jobId: string): Promise<number | null>;
  /** Every AI answer kept for this report, oldest first (v0.11 planning). */
  listCoachAiRuns(reportId: number): Promise<CoachAiRunSummary[]>;
  getCoachAiRun(reportId: number, runId: number): Promise<CoachAiRun | null>;
  /** FR-10.60: exactly the notes Include my notes would send. */
  getCoachNotesPreview(reportId: number): Promise<CoachNote[]>;
  /** FR-10.59: open a lesson pointer in your browser. Only the topic and target go; the backend builds the URL. */
  openLesson(reportId: number, topic: string, target: string): Promise<void>;
  // ---- v0.12: the training plan and journal (§10.12) --------------------------------------------
  /** FR-10.71: exactly the entries Include my journal would send. */
  getCoachJournalPreview(reportId: number): Promise<CoachJournalLine[]>;
  getPlanSettings(): Promise<PlanSettings>;
  /** The plan these settings would make from your latest report. Nothing is saved. */
  previewPlan(params: PlanParams | null): Promise<PlanPreview>;
  /** Start the deterministic plan. It replaces the current one only when `confirmed` (FR-10.65). */
  createPlan(params: PlanParams, confirmed: boolean): Promise<TrainingPlan>;
  /** Use this plan (FR-10.66). */
  useAiPlan(runId: number, confirmed: boolean): Promise<TrainingPlan>;
  getCurrentPlan(): Promise<TrainingPlan | null>;
  getTodayPlan(): Promise<TodayPlan | null>;
  listPlans(): Promise<TrainingPlan[]>;
  /** Your hand tick or untick, which always wins over what the app saw (FR-10.64). */
  setPlanTaskTick(taskId: number, done: boolean): Promise<void>;
  skipPlanTask(taskId: number, skipped: boolean): Promise<void>;
  swapPlanTask(taskId: number): Promise<number>;
  /** Start (FR-10.63): a puzzle task's session uses its own filters; your Mixer stays as it was. */
  startPlanTask(taskId: number, rated: boolean): Promise<PlanTaskAction>;
  startPlanLessonDrill(taskId: number, rated: boolean): Promise<PlanTaskAction>;
  /** Open one of a lesson task's links, which ticks it. The backend builds the URL (FR-10.59). */
  openPlanLesson(taskId: number, target: string): Promise<void>;
  /** You looked at this move in Game Review (FR-10.64, 10.68). */
  markReviewPly(gameId: number, ply: number): Promise<boolean>;
  // ---- v0.13: the opening trainer (REQUIREMENTS §18) ----
  getOpeningBookStatus(): Promise<OpeningBookStatus>;
  startOpeningBookImport(): Promise<string>;
  getOpeningFamilies(query: string): Promise<BookFamily[]>;
  getOpeningSettings(): Promise<OpeningSettings>;
  setOpeningSources(useWikibooks: boolean, source: "lichess" | "masters", ratings: number[]): Promise<OpeningSettings>;
  /** FR-12.15: the Wikibooks page for a line's moves so far. Only when you open the panel. */
  getOpeningPage(sans: string[]): Promise<OpeningPage>;
  setOpeningSettings(preset: OpeningScope["preset"], subLines: number | null, maxMoves: number | null, extend: boolean | null): Promise<OpeningSettings>;
  /** FR-12.13: lines grow past the book only from stored results; this never runs the engine. */
  getOpeningLines(family: string): Promise<OpeningLines>;
  getOpeningNote(positionKey: string, moveUci: string, kind: "overview" | "move"): Promise<OpeningNote | null>;
  /** `ply` null is the opening's overview. A saved note is free unless you're regenerating it. */
  getOpeningNoteQuote(family: string, lineIndex: number, ply: number | null, regenerate: boolean): Promise<OpeningNoteQuote>;
  startOpeningNote(family: string, lineIndex: number, ply: number | null, regenerate: boolean): Promise<string | null>;
  /** FR-12.8: Explain the last move of a line outside the book. */
  getOpeningMovesNoteQuote(moves: string[], regenerate: boolean): Promise<OpeningNoteQuote>;
  startOpeningMovesNote(moves: string[], regenerate: boolean): Promise<string | null>;
  getOpeningOverviewKey(family: string): Promise<string>;
  getOpeningPrefetchPlan(family: string, preset: OpeningScope["preset"], subLines: number | null, maxMoves: number | null, extend: boolean): Promise<OpeningPrefetchPlan>;
  /** Only after you Confirm the estimate (FR-8.11, 12.7b). */
  startOpeningPrefetch(family: string, preset: OpeningScope["preset"], subLines: number | null, maxMoves: number | null, extend: boolean): Promise<string>;
  exportOpeningNotes(family: string): Promise<string | null>;
  /** What Delete notes would remove, so you can be asked first. */
  getOpeningNotesDeletion(family: string): Promise<OpeningNotesDeletion>;
  deleteOpeningNotes(family: string): Promise<number>;
  /** Continue the lines with Stockfish in the background; null when there's nothing to do. */
  startOpeningExtend(family: string): Promise<string | null>;
  analyzeOpeningPosition(fen: string, purpose: "start" | "panel" | "board", player: "white" | "black"): Promise<Analysis>;
  getOpeningDeviation(color: "white" | "black", moves: string[], theirMove: string): Promise<OpeningDeviation>;
  addOpeningDeviation(color: "white" | "black", moves: string[], theirMove: string, reply: string): Promise<RepertoireAdded>;
  /** FR-12.14: the job's message is the proposal's id. Nothing is saved until saveRepertoireProposal. */
  startRepertoireBuild(color: "white" | "black", family: string, limits: { max_moves: number; min_share: number; max_replies: number; max_positions: number }): Promise<string>;
  getRepertoireProposal(proposalId: string): Promise<RepertoireProposal>;
  saveRepertoireProposal(proposalId: string): Promise<RepertoireAdded>;
  discardRepertoireProposal(proposalId: string): Promise<void>;
  getPracticeSummary(color: "white" | "black"): Promise<PracticeSummary>;
  getPracticeTolerance(): Promise<boolean>;
  setPracticeTolerance(on: boolean): Promise<boolean>;
  /** FR-12.10: what a session can be limited to. */
  getPracticeBranches(color: "white" | "black", openingId: number | null): Promise<PracticeBranch[]>;
  startPractice(color: "white" | "black", mode: "due" | "new" | "all", openingId: number | null, branch: string | null): Promise<PracticeState>;
  playPracticeMove(sessionId: string, uci: string): Promise<PracticeState>;
  showPracticeAnswer(sessionId: string): Promise<PracticeState>;
  continuePractice(sessionId: string): Promise<PracticeState>;
  endPractice(sessionId: string): Promise<void>;
  setPracticeReason(attemptId: number, reason: ReasonKey, note: string | null): Promise<void>;
  getOpeningStats(color: "white" | "black"): Promise<OpeningStat[]>;
  matchOpeningFamily(name: string): Promise<string | null>;
  getRepertoire(color: "white" | "black"): Promise<Repertoire>;
  addRepertoireLines(color: "white" | "black", family: string, lineIndices: number[]): Promise<RepertoireAdded>;
  previewRepertoireRemoval(color: "white" | "black", positionKey: string, moveUci: string): Promise<string[]>;
  removeRepertoireMove(color: "white" | "black", positionKey: string, moveUci: string): Promise<Repertoire>;
  setRepertoireMain(color: "white" | "black", positionKey: string, moveUci: string): Promise<Repertoire>;
  moveRepertoireMove(color: "white" | "black", positionKey: string, moveUci: string, direction: "up" | "down"): Promise<Repertoire>;

  getJournal(filters: JournalFilters): Promise<JournalTimeline>;
  addJournalEntry(entry: JournalEntryInput): Promise<JournalEntry>;
  editJournalEntry(entryId: number, text: string, weaknessKey: string | null): Promise<JournalEntry>;
  deleteJournalEntry(entryId: number): Promise<void>;
  /** FR-10.69: a game's notes, in order of the move they're on. */
  getGameNotes(gameId: number): Promise<JournalEntry[]>;
  getSuggestion(): Promise<SuggestionView | null>;
  applySuggestion(): Promise<SuggestionView>;
  dismissSuggestion(): Promise<SuggestionView | null>;
  // v0.14: Lichess studies (REQUIREMENTS §19). Study text never goes to an LLM (FR-13.12).
  /** FR-13.5: a pasted link, chapter link or ID; anything else is refused before any request. Returns a job. */
  addStudy(text: string): Promise<string>;
  /** FR-13.5a, 13.6: from Studies by author or the starter list. Returns a job. */
  addStudyById(studyId: string, chapterId: string | null): Promise<string>;
  getStudyAddResult(jobId: string): Promise<StudyAddResult | null>;
  findAuthorStudies(username: string): Promise<AuthorStudy[]>;
  getStudyStarterList(): Promise<StarterStudy[]>;
  listStudies(which: "all" | "favorites" | "in_progress" | "finished"): Promise<StudySummary[]>;
  getStudy(studyId: string): Promise<StudyDetail>;
  getStudyChapter(studyId: string, chapterKey: string): Promise<StudyChapter>;
  // ---- v0.15: the Analysis tab (REQUIREMENTS §20). Nothing here is scored or saved (FR-14.5) ----
  /** FR-14.2: a set-up position or pasted FEN, with a sentence per problem. */
  checkBoardPosition(fen: string): Promise<PositionCheck>;
  /** FR-14.3: the games in a pasted PGN, to pick from. Not added to your library. */
  importAnalysisPgn(pgn: string): Promise<AnalysisPgnImport>;
  getAnalysisPgnGame(pgn: string, index: number): Promise<AnalysisPgnGame>;
  /** FR-14.4: eval and top 3 lines on the interactive engine. */
  analyzeBoardPosition(fen: string, purpose: "start" | "panel" | "board"): Promise<Analysis>;
  /** FR-14.4: the Lichess explorer's most played moves; signed out or offline is a state, not an error. */
  getPopularReplies(fen: string): Promise<PopularReplies>;
  /** FR-13.10: local only. */
  setStudyPlace(studyId: string, chapterKey: string, path: string[]): Promise<void>;
  getStudyContinue(studyId: string): Promise<StudyPlace>;
  setStudyChapterDone(studyId: string, chapterKey: string, done: boolean): Promise<void>;
  restartStudy(studyId: string): Promise<void>;
  /** FR-13.9: stored only in the app. */
  heartStudy(studyId: string, hearted: boolean): Promise<void>;
  deleteStudy(studyId: string): Promise<void>;
  /** FR-13.11: nothing is saved until saveStudyRepertoire. A null chapter means the whole study. */
  previewStudyRepertoire(studyId: string, chapterKey: string | null, color: "white" | "black", sideLines: boolean): Promise<StudyRepertoirePreview>;
  /** Each conflict keeps your move unless its position maps to "study". */
  saveStudyRepertoire(previewId: string, choices: Record<string, "mine" | "study">): Promise<RepertoireAdded>;
  discardStudyRepertoire(): Promise<void>;
  /** FR-13.7: a job; your copy changes only through applyStudyUpdate. */
  checkStudyUpdates(studyId: string): Promise<string>;
  getStudyUpdate(studyId: string): Promise<StudyUpdate | null>;
  applyStudyUpdate(studyId: string): Promise<void>;
  discardStudyUpdate(studyId: string): Promise<void>;
  openStudyOnLichess(studyId: string, chapterKey: string | null): Promise<void>;
  openLichessStudiesInBrowser(): Promise<void>;
  /** FR-13.3: the isolated Lichess window. True if a new window opened. */
  openLichessWindow(): Promise<boolean>;
  closeLichessWindow(): Promise<void>;
  isLichessWindowOpen(): Promise<boolean>;
  // ---- v0.16: backup and restore (REQUIREMENTS §21). File paths never cross the bridge from here. ----
  getBackupStatus(): Promise<BackupStatus>;
  /** FR-15.3: automatic backups. `folder` comes from chooseBackupFolder. */
  setBackupSettings(enabled: boolean, folder: string | null, intervalDays: number, keep: number): Promise<BackupStatus>;
  chooseBackupFolder(): Promise<string | null>;
  /** FR-15.1: the Save dialog, then a backup job. The job ID, or null if you cancel. */
  backupNow(): Promise<string | null>;
  /** FR-15.4: the Open dialog, then what's in the file (or an error saying why it can't be restored). */
  chooseBackupToRestore(): Promise<BackupInfo | null>;
  /** Replace my data: a job that checks and stages the backup, then the app restarts. */
  restoreBackup(token: string): Promise<string>;
  /** After a restart: what the restore did, once. */
  takeRestoreNotice(): Promise<RestoreNotice | null>;
  // ---- v1.0: checkpoints and fix tracking (REQUIREMENTS §10.8) ----
  /** FR-10.38: the Coach's Progress tab. */
  getProgress(): Promise<ProgressView>;
  getCheckpointSettings(): Promise<CheckpointSettings>;
  /** FR-10.32/10.35/10.37/10.38. Refused (invalid_argument) when a value is out of range. */
  setCheckpointSettings(settings: CheckpointSettings): Promise<CheckpointSettings>;
  /** FR-10.32 Run checkpoint now: a `checkpoint` job. */
  runCheckpointNow(): Promise<string>;
  /** FR-10.38: status changes not seen yet, once. */
  takeStatusNotices(): Promise<StatusNotice[]>;
  /** Subscribe to pushed events (job progress, account, sync). Returns an unsubscribe function. */
  onEvent(listener: (event: BackendEvent) => void): () => void;
}
