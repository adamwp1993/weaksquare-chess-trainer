// v0.10: the Coach in the mock client (§10). Fixed, deterministic data for UI work, Playwright and the
// user-guide screenshots: one report per run, built from the mock library's analyzed game (id 1).
import { ApiCallError, type CoachAiOptions, type CoachParams } from "./ApiClient";
import { defaultFilters } from "../state/filters";
import type { GameKind } from "./mockLlm";
import type {
  CoachAiQuote,
  CoachAiRun,
  CoachAiRunSummary,
  CoachDefaults,
  CoachComparison,
  CoachEvidence,
  CoachFinding,
  CoachLesson,
  CoachJournalLine,
  CoachMeasureChange,
  CoachMeasures,
  CoachNote,
  CoachPresetView,
  CoachReport,
  CoachReportSummary,
  CoachWeakness,
  CoachWeaknessChange,
  FilterSpec,
  GameAiQuote,
  Job,
  PlanPreview,
  SuggestionView,
} from "./types";

const bad = (message: string) => new ApiCallError({ code: "invalid_argument", message, retryable: false });

export const DEFAULT_PARAMS: CoachParams = {
  source: "games", player: null, platform: "lichess", platforms: [], count: 50, rated_only: true,
  time_classes: ["rapid", "classical"], color: "both", detail: "summary", game_ids: [],
}; // prettier-ignore

function changeOf(trend: number | null): CoachWeakness["change"] {
  if (trend === null) return null;
  return trend < 0 ? "better" : trend > 0 ? "worse" : "same";
}

function w(
  key: string, label: string, count: number, per10: number, severity: number, themes: string[],
  reasons: Record<string, number>, mode: string | null = null, trend: number | null = null,
): CoachWeakness {
  const [kind, name] = key.split(":") as [CoachWeakness["kind"], string];
  return {
    change: changeOf(trend),
    key, kind, name, label, count, per10, severity, score: Math.round((per10 * severity) / 10) / 10, themes, mode,
    reasons, examples: [{ game_id: 1, ply: 6, cp_loss: 640 }, { game_id: 1, ply: 8, cp_loss: 410 }],
    puzzle_accuracy: kind === "allowed" && name === "fork" ? 0.86 : null, trend,
  }; // prettier-ignore
}

/** FR-10.53 for the mock report: a few groups with enough games, some without (not enough data yet). */
function measures(games: number): CoachMeasures {
  const n = games;
  return {
    games: n, min_games: 5,
    openings: [
      { family: "Italian Game", games: 12, score: 37.5, avg_eval_end: -85, errors_first15: 7, enough: true },
      { family: "Sicilian Defense", games: 9, score: 61.1, avg_eval_end: 20, errors_first15: 2, enough: true },
      { family: "French Defense", games: 3, score: 33.3, avg_eval_end: -140, errors_first15: 2, enough: false },
    ],
    errors_per10_by_phase: { opening: 4.3, middlegame: 9.7, endgame: 6 },
    conversion: { games: 11, hits: 6, rate: 54.5, enough: true },
    saves: { games: 8, hits: 2, rate: 25, enough: true },
    endgames: [
      { type: "rook", label: "Rook endgames", games: 7, wins: 2, draws: 2, losses: 3, errors: 6, enough: true },
      { type: "pawn", label: "King and pawn endgames", games: 3, wins: 1, draws: 0, losses: 2, errors: 2, enough: false },
    ],
    time: { games: 14, low_moves: 160, low_errors: 20, low_blunders: 11, low_error_rate: 12.5, other_moves: 980, other_errors: 25, other_blunders: 9, other_error_rate: 2.55, enough: true },
    king: { games: 28, late: 6, late_score: 25, on_time_score: 55.8, enough: true },
    phases_enough: true,
  }; // prettier-ignore
}

interface Hooks {
  emit: (job: Job) => void;
  jobId: () => string;
  calls: string[];
  filters: () => FilterSpec | null;
  setFilters: (spec: FilterSpec, mode: string) => void;
  quote: (kind: GameKind, what: string) => GameAiQuote;
  startAi: (kind: GameKind, what: string, make: (provider: string, model: string, costUsd: number) => CoachAiRun) => string;
  aiPlan: () => PlanPreview;
}

export class MockCoach {
  private reports: CoachReport[] = [];
  private results = new Map<string, number>();
  private last: CoachParams = { ...DEFAULT_PARAMS };
  private suggestion: Omit<SuggestionView, "active"> | null = null;
  private applied: string | null = null;
  private players: { subject: string; label: string; games: number }[] = [];
  private running: string | null = null;
  private runs = new Map<number, CoachAiRun[]>(); // like coach_ai_runs: every answer, whatever model is chosen now
  private runCount = 0;
  private cachedRun = new Map<string, number>();
  private jobRuns = new Map<string, number>();

  constructor(
    params: URLSearchParams,
    private readonly h: Hooks,
  ) {
    if (params.get("coach") === "report") this.makeReport(this.last, "2026-11-04T09:00:00");
    if (params.get("coach") === "banner") {
      this.makeReport(this.last, "2026-11-04T09:00:00");
      this.suggest(this.reports[0], true);
    }
  }

  defaults(): CoachDefaults {
    return { params: { ...this.last }, usernames: ["player_a"], players: [...this.players], running_job: this.running };
  }

  start(p: CoachParams): string {
    if (![25, 50, 100, 200].includes(p.count)) throw bad("The number of games must be 25, 50, 100 or 200.");
    if (p.player !== null && !p.player.trim()) throw bad("Enter a username or a profile link.");
    if (p.source === "puzzles" && p.player) throw bad("The puzzle history is yours only: choose Games for another player.");
    this.last = { ...p, game_ids: [] };
    const id = this.h.jobId();
    this.running = id;
    this.h.calls.push(`coach:${p.source}:${p.player ?? "me"}:${p.game_ids.length || p.count}`, `coachPlatforms:${p.platforms.join(",")}`);
    const steps = ["Syncing your games…", "Analyzing 3 games on your PC: about 2 min left", "Writing the report…"];
    steps.forEach((message, i) =>
      setTimeout(() => this.h.emit({ id, kind: "coach_run", state: "running", progress: i / 3, message, error_code: null }), i * 200),
    );
    setTimeout(() => {
      const r = this.makeReport(p, "2026-11-04T10:30:00");
      this.results.set(id, r.id);
      if (r.is_me && r.source !== "puzzles") this.suggest(r, false);
      this.running = null;
      this.h.emit({ id, kind: "coach_run", state: "done", progress: 1, message: `Report ready: ${r.games} games`, error_code: null });
    }, 800);
    return id;
  }

  result(jobId: string): number | null {
    return this.results.get(jobId) ?? null;
  }

  list(): CoachReportSummary[] {
    return [...this.reports].reverse().map((r) => ({
      id: r.id, created_at: r.created_at, subject_label: r.subject_label, is_me: r.is_me, source: r.source, games: r.games,
      top: [...r.allowed, ...r.missed, ...r.habits].sort((a, b) => b.score - a.score).slice(0, 3).map((x) => x.label),
    })); // prettier-ignore
  }

  get(id: number): CoachReport {
    const r = this.reports.find((x) => x.id === id);
    if (!r) throw new ApiCallError({ code: "not_found", message: "That report isn't saved.", retryable: false });
    return r;
  }

  private makeReport(p: CoachParams, created: string): CoachReport {
    const me = !p.player;
    const name = p.player?.replace(/^.*(lichess\.org\/@\/|chess\.com\/member\/)/, "").replace(/\/.*$/, "") ?? "";
    if (!me && !this.players.some((x) => x.subject.endsWith(`:${name.toLowerCase()}`))) {
      this.players.push({ subject: `${p.platform}:${name.toLowerCase()}`, label: `${name} (${p.platform === "lichess" ? "Lichess" : "chess.com"})`, games: 3 });
    }
    const second = this.reports.filter((x) => x.is_me).length > 0 && me;
    const games = p.source === "puzzles" ? 0 : p.game_ids.length || 30;
    const id = this.reports.length + 1;
    const report: CoachReport = {
      id, created_at: created, subject_label: me ? "You (player_a)" : `${name} (${p.platform === "lichess" ? "Lichess" : "chess.com"})`,
      is_me: me, source: p.source, params: { ...p }, games, first_played: games ? "2026-10-27T09:40:00+00:00" : null,
      last_played: games ? "2026-10-30T18:20:00+00:00" : null,
      per10: games ? { blunders: 13.3, mistakes: 6.7, inaccuracies: 10 } : {}, results: games ? { loss: 2, draw: 1 } : {},
      missed: games ? [
        w("missed:pin", "Missed: Pin", 3, 10, 260, ["pin"], { didntLook: 2 }, null, second ? -3.3 : null),
        w("missed:mateIn2", "Missed: Mate in 2", 2, 6.7, 1000, ["mateIn2"], {}, null, second ? 0 : null),
      ] : [],
      allowed: games ? [
        w("allowed:fork", "Allowed: Fork", 4, 13.3, 410, ["fork"], { didntLook: 3, miscalculated: 1 }, "danger_spotting", second ? 3.3 : null),
      ] : [],
      habits: games ? [w("habit:hungPiece", "Hung a piece", 2, 6.7, 380, ["hangingPiece", "fork"], { rushed: 1 }, "danger_spotting")] : [],
      puzzles: p.source !== "games" && me ? [
        { ...w("puzzle:mateIn2", "Puzzles: Mate in 2", 9, 0, 0, ["mateIn2"], {}), puzzle_accuracy: 0.55, examples: [] },
      ] : [],
      gap: p.source === "both" ? [
        { theme: "fork", label: "Fork", puzzle_accuracy: 0.86, puzzle_attempts: 64, missed_per10: 0, allowed_per10: 13.3 },
        { theme: "pin", label: "Pin", puzzle_accuracy: 0.71, puzzle_attempts: 21, missed_per10: 10, allowed_per10: 0 },
      ] : [],
      reasons: games ? { didntLook: 5, miscalculated: 1, rushed: 1 } : {}, low_clock_errors: games ? 1 : 0,
      preset: games ? this.preset() : null, notes: [],
      whole_game: games ? [
        w("time:low_clock", "Mistakes under 10% of your clock", 4, 13.3, 450, [], {}),
        w("endgame:rook", "Rook endgames", 2, 6.7, 300, ["rookEndgame"], {}),
        ...(new URLSearchParams(window.location.search).get("coachopening") ? [w("opening:Italian Game", "Italian Game: you score 30%", 5, 16.7, 120, [], {}), w("opening:Rare Line", "Rare Line: you score 20%", 5, 16.7, 120, [], {})] : []),
      ] : [],
      measures: games >= 24 ? measures(games) : null, // the mock's measures assume a full run
      comparison: second && games ? this.comparison() : null,
    }; // prettier-ignore
    this.reports.push(report);
    return report;
  }

  /** FR-10.73 for the mock's second report of yours: rates, New and Gone, and a measure with too few games. */
  private comparison(): CoachComparison {
    const m = (key: string, label: string, unit: "per10" | "pct", then: number, now: number, verdict: CoachMeasureChange["verdict"]): CoachMeasureChange => ({
      key, label, unit, then, now, delta: Math.round((now - then) * 100) / 100, verdict,
    }); // prettier-ignore
    const row = (key: string, label: string, then: number | null, now: number, flag: "new" | "gone" | null, verdict: CoachWeaknessChange["verdict"], series: (number | null)[]): CoachWeaknessChange => ({
      key, label, then, now, delta: then === null ? null : Math.round((now - then) * 100) / 100, flag, verdict, series,
      puzzle: key === "allowed:fork" ? { then: 71, now: 86, then_attempts: 40, now_attempts: 24, verdict: "better" } : null,
    }); // prettier-ignore
    return {
      earlier_id: 1, earlier_created_at: "2026-11-04T09:00:00", days_between: 12, new_games: 22, shared_games: 8, enough_new_games: true,
      settings: "same", puzzle_history: false, reports: 2,
      weaknesses: [
        row("allowed:fork", "Allowed: Fork", 10, 13.3, null, "worse", [10, 13.3]),
        row("missed:pin", "Missed: Pin", 13.3, 10, null, "better", [13.3, 10]),
        row("missed:mateIn2", "Missed: Mate in 2", 6.7, 6.7, null, "same", [6.7, 6.7]),
        row("habit:hungPiece", "Hung a piece", null, 6.7, "new", "not_enough", [null, 6.7]),
        row("missed:skewer", "Missed: Skewer", 3.3, 0, "gone", "better", [3.3, 0]),
      ],
      health: [m("health:blunders", "Blunders", "per10", 15, 13.3, "better"), m("health:mistakes", "Mistakes", "per10", 6.7, 6.7, "same"), m("health:inaccuracies", "Inaccuracies", "per10", 8, 10, "worse")],
      measures: [m("conversion", "Winning positions converted", "pct", 45, 54.5, "better"), m("opening_score:French Defense", "Score in the French Defense", "pct", 50, 33.3, "not_enough")],
    }; // prettier-ignore
  }

  private preset(): CoachPresetView {
    return {
      name: "The report's mix",
      spec: {
        ...(this.h.filters() ?? defaultFilters()),
        themes: [], match: "any", source: "lichess", my_origins: [], my_share: null, order: "random",
        ratios: [{ themes: ["fork"], weight: 46 }, { themes: ["pin"], weight: 26 }, { themes: ["hangingPiece", "fork"], weight: 14 }, { themes: ["long", "veryLong"], weight: 14 }],
        rating_min: 1450, rating_max: 1750,
      } as unknown as Record<string, unknown>,
      mode: "danger_spotting",
      why: [
        "Allowed: Fork: 13.3 per 10 games, your #1 leak (46% of the mix).",
        "Missed: Pin: 10 per 10 games, #2 (26% of the mix).",
        "Hung a piece: 6.7 per 10 games, #3 (14% of the mix).",
        "Long and very long combinations get 14%, including a 10% exploration share.",
        "Mode: Danger spotting, because you mostly didn't look for it.",
        "Rating 1450–1750, aiming for about 75% first-try accuracy.",
      ],
    }; // prettier-ignore
  }

  private suggest(r: CoachReport, forceBanner: boolean) {
    const p = r.preset;
    if (!p) return;
    const current = this.h.filters();
    const untouched = !forceBanner && (current === null || JSON.stringify(current) === this.applied);
    const number = this.reports.filter((x) => x.is_me).length;
    this.suggestion = {
      report_id: r.id, number, created_at: r.created_at, label: `Suggested — from Coach run #${number}, ${r.created_at.slice(0, 10)}`,
      spec: p.spec, mode: p.mode, why: p.why, pending: !untouched,
      previous: current ? ({ ...current } as unknown as Record<string, unknown>) : null,
    }; // prettier-ignore
    if (untouched) this.apply();
  }

  getSuggestion(): SuggestionView | null {
    if (!this.suggestion) return null;
    return { ...this.suggestion, active: JSON.stringify(this.h.filters()) === this.applied };
  }

  apply(): SuggestionView {
    if (!this.suggestion) throw new ApiCallError({ code: "not_found", message: "There's no suggested mix yet. Run the Coach first.", retryable: false });
    this.applied = JSON.stringify(this.suggestion.spec);
    this.h.setFilters(this.suggestion.spec as unknown as FilterSpec, this.suggestion.mode);
    this.suggestion = { ...this.suggestion, pending: false };
    this.h.calls.push("suggestion:apply");
    return this.getSuggestion()!;
  }

  dismiss(): SuggestionView | null {
    if (!this.suggestion) return null;
    this.suggestion = { ...this.suggestion, pending: false };
    this.h.calls.push("suggestion:dismiss");
    return this.getSuggestion();
  }

  // ---- AI coaching (v0.11: the whole-game diagnosis, kept per run) ---------------------------------
  private kind(id: number): GameKind {
    return this.get(id).params.detail === "detailed" ? "coach_detailed" : "coach_summary";
  }

  private what(id: number, o: CoachAiOptions): string {
    return `coach:${id}:${o.advanced ? `adv${o.game_cap}` : "std"}:${o.include_notes ? "notes" : "nonotes"}:${o.include_journal ? "journal" : "nojournal"}`;
  }

  private check(o: CoachAiOptions) {
    if (!Number.isInteger(o.game_cap) || o.game_cap < 10 || o.game_cap > 50) throw bad("The game cap must be 10–50.");
  }

  aiQuote(id: number, o: CoachAiOptions): CoachAiQuote {
    this.check(o);
    const r = this.get(id);
    const quote = this.h.quote(this.kind(id), this.what(id, o));
    const cached = quote.state === "cached" ? (this.cachedRun.get(this.what(id, o)) ?? null) : null;
    let compare = null;
    if (o.advanced && quote.state !== "cached" && quote.typical_usd !== null) {
      const ratio = 3.8;
      compare = {
        games_with_moves: Math.min(o.game_cap, r.games), token_ratio: ratio,
        standard_usd: Math.round((quote.typical_usd / ratio) * 1e6) / 1e6,
        budget_share: quote.budget_usd ? Math.round((quote.typical_usd / quote.budget_usd) * 1000) / 1000 : null,
        minutes: 2,
      }; // prettier-ignore
      // An Advanced prompt is about 4× a standard one in the mock.
      const scaled = (x: number | null) => (x === null ? null : Math.round(x * ratio * 1e6) / 1e6);
      return {
        quote: { ...quote, input_tokens: quote.input_tokens && Math.round(quote.input_tokens * ratio),
                 typical_usd: scaled(quote.typical_usd), worst_usd: scaled(quote.worst_usd) },
        compare: { ...compare, budget_share: quote.budget_usd ? Math.round(((scaled(quote.typical_usd) ?? 0) / quote.budget_usd) * 1000) / 1000 : null },
        cached_run: null,
      }; // prettier-ignore
    }
    return { quote, compare, cached_run: cached };
  }

  startAi(id: number, o: CoachAiOptions): string {
    this.check(o);
    const r = this.get(id);
    const what = this.what(id, o);
    this.h.calls.push(`coachAi:${id}:${o.advanced ? `advanced:${o.game_cap}` : "standard"}:${o.include_notes ? "notes" : "nonotes"}${o.include_journal ? ":journal" : ""}`);
    const runs = this.runs.get(id) ?? [];
    let job = "";
    job = this.h.startAi(this.kind(id), what, (provider, model, cost) => {
      const run = this.diagnosis(r, runs.length + this.runCount, o, provider, model, cost, runs.length > 0);
      this.runCount += 1;
      runs.push(run);
      this.runs.set(id, runs);
      this.cachedRun.set(what, run.id);
      this.jobRuns.set(job, run.id);
      return run;
    });
    const cached = this.cachedRun.get(what);
    if (cached !== undefined) this.jobRuns.set(job, cached);
    return job;
  }

  jobRun(job: string): number | null {
    return this.jobRuns.get(job) ?? null;
  }

  listRuns(id: number): CoachAiRunSummary[] {
    return (this.runs.get(id) ?? []).map((x) => ({
      id: x.id, created_at: x.created_at, format: x.format, advanced: x.advanced, include_notes: x.include_notes,
      game_cap: x.game_cap, provider: x.provider, model: x.model, cost_usd: x.cost_usd, findings: x.findings.length,
      new: x.findings.filter((f) => f.new).length, include_journal: x.include_journal,
    })); // prettier-ignore
  }

  getRun(id: number, runId: number): CoachAiRun | null {
    return (this.runs.get(id) ?? []).find((x) => x.id === runId) ?? null;
  }

  notesPreview(id: number): CoachNote[] {
    if (!this.get(id).is_me) return [];
    return [
      { game: "G1", ply: 7, move: "4. Nxe5", reason: "didntLook", text: "I only looked at my own attack, see [link removed]", source: "game" },
      { game: "G2", ply: 9, move: "5. Bd3", reason: "miscalculated", text: "thought the bishop was protected", source: "game" },
      { game: null, ply: null, move: null, reason: "unknownPattern", text: "never seen this back-rank trick", source: "puzzle" },
    ]; // prettier-ignore
  }

  journalPreview(id: number): CoachJournalLine[] {
    if (!this.get(id).is_me) return [];
    return [
      { text: "The knight on e5 was the whole game. I saw it one move too late.", kind: "reflection", game: "G1", ply: 7, move: "4. Nxe5", weakness: "allowed:fork" },
      { text: "I keep missing forks when I'm short of time.", kind: "note", game: null, ply: null, move: null, weakness: "allowed:fork" },
    ]; // prettier-ignore
  }

  openLesson(id: number, topic: string, target: string) {
    this.get(id);
    if (!/^(curated:\d+|youtube|chesscom|custom)$/.test(target)) throw bad("Unknown lesson link.");
    this.h.calls.push(`openLesson:${id}:${topic}:${target}`);
  }

  private lesson(topic: string, label: string, drill: string[] | null, curated: string[]): CoachLesson {
    return {
      topic, label, curated, sites: ["youtube", "chesscom"],
      drill: drill ? { name: `Learn: ${label}`, spec: { ...defaultFilters(), themes: drill, rating_min: 1150, rating_max: 1450, queue_size: 20 } as unknown as Record<string, unknown>, mode: "standard", why: [] } : null,
    }; // prettier-ignore
  }

  private diagnosis(r: CoachReport, n: number, o: CoachAiOptions, provider: string, model: string, cost: number, later: boolean): CoachAiRun {
    const ev = (label: string, ply: number, move: string): CoachEvidence => ({ label, game_id: 1, ply, move });
    const findings: CoachFinding[] = [
      {
        key: "allowed:fork", label: "Allowed: Fork", category: "tactical", title: "You walk into knight forks",
        explanation: "In 3 games your move let a knight fork your king and rook (G1 4. Nxe5, G2 5. Bd3, G3 6. Qe2). In each you said you didn't look at your opponent's checks.",
        advice: "Before every move, list your opponent's checks and captures. Danger spotting with fork puzzles trains exactly that.",
        tentative: false, observation: false, seen: 0, new: false,
        evidence: [ev("G1", 6, "4. Nxe5"), ev("G2", 8, "5. Bd3"), ev("G3", 10, "6. Qe2")],
        lesson: this.lesson("theme:fork", "Fork", ["fork"], ["Lichess Practice: The Fork"]),
      },
      {
        key: "time:low_clock", label: "Mistakes under 10% of your clock", category: "time", title: "Your clock runs out before the game does",
        explanation: "Under 10% of your time you make a mistake every 8 moves, against one every 40 moves otherwise (G2 31. Rd1).",
        advice: "Spend less time on the opening moves you know; keep at least a fifth of your time for the last 20 moves.",
        tentative: true, observation: false, seen: 0, new: false, evidence: [ev("G2", 60, "31. Rd1")],
        lesson: this.lesson("concept:timeManagement", "Time management", null, []),
      },
      {
        key: null, label: null, category: "strategic", title: "You trade pieces when you're behind",
        explanation: "Down material, you traded queens in 2 games (G1 18. Qxd8, G3 22. Qxe7), which made the endgames easy for your opponent.",
        advice: "When you're behind, keep pieces on and look for activity; trade when you're ahead.",
        tentative: true, observation: true, seen: later ? 2 : 1, new: false,
        evidence: [ev("G1", 34, "18. Qxd8"), ev("G3", 42, "22. Qxe7")],
        lesson: this.lesson("concept:trades", "When to trade pieces", null, []),
      },
    ]; // prettier-ignore
    if (o.advanced) {
      findings.push({
        key: null, label: null, category: "opening", title: "You move your queen early in the Italian",
        explanation: "With the full games, the queen comes out by move 5 in both Italian games (G1 3. Qh5, G3 4. Qf3) and is chased back.",
        advice: "Develop knights and bishops first; bring the queen out after you've castled.",
        tentative: true, observation: true, seen: 1, new: later, evidence: [ev("G1", 4, "3. Qh5"), ev("G3", 6, "4. Qf3")],
        lesson: this.lesson("concept:development", "Development in the opening", null, ["Lichess Learn: chess basics"]),
      }); // prettier-ignore
    }
    return {
      id: 100 + n, created_at: "2026-11-04T10:40:00", format: "diagnosis", advanced: o.advanced, include_notes: o.include_notes,
      game_cap: o.advanced ? o.game_cap : null,
      summary: "Most of your losses come from forks you allow, about 13 per 10 games, usually because you didn't check your opponent's replies. Your clock is the next problem: most of your late blunders come under 10% of your time.",
      findings,
      presets: [{ name: "Forks you allow", spec: { ...(r.preset?.spec ?? {}), ratios: [], themes: ["fork"] }, mode: "danger_spotting", why: [] }],
      fallback_preset: false, discarded: 1, provider, model, cost_usd: cost, include_journal: o.include_journal,
      trend: r.comparison ? [
        { key: "missed:pin", label: "Missed: Pin", change: "improved", comment: "Down from 13.3 to 10 per 10 games, and the pin drills are showing up in your games." },
        { key: "allowed:fork", label: "Allowed: Fork", change: "worse", comment: "Up from 10 to 13.3 per 10 games, even though your fork puzzles improved: the gap is in checking your opponent's replies." },
      ] : [],
      plan: r.is_me ? this.h.aiPlan() : null,
      plan_check: r.is_me ? { ai_tasks: 24, dropped: 2, filled: 2, fallback: false } : null,
    }; // prettier-ignore
  }
}
