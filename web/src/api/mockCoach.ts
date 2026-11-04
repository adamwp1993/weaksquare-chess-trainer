// v0.10: the Coach in the mock client (§10). Fixed, deterministic data for UI work, Playwright and the
// user-guide screenshots: one report per run, built from the mock library's analyzed game (id 1).
import { ApiCallError, type CoachParams } from "./ApiClient";
import type { GameKind } from "./mockLlm";
import type {
  CoachAi,
  CoachDefaults,
  CoachPresetView,
  CoachReport,
  CoachReportSummary,
  CoachWeakness,
  FilterSpec,
  GameAiQuote,
  Job,
  SuggestionView,
} from "./types";

const bad = (message: string) => new ApiCallError({ code: "invalid_argument", message, retryable: false });

export const DEFAULT_PARAMS: CoachParams = {
  source: "games", player: null, platform: "lichess", platforms: [], count: 50, rated_only: true,
  time_classes: ["rapid", "classical"], color: "both", detail: "summary", game_ids: [],
}; // prettier-ignore

function w(
  key: string, label: string, count: number, per10: number, severity: number, themes: string[],
  reasons: Record<string, number>, mode: string | null = null, trend: number | null = null,
): CoachWeakness {
  const [kind, name] = key.split(":") as [CoachWeakness["kind"], string];
  return {
    key, kind, name, label, count, per10, severity, score: Math.round((per10 * severity) / 10) / 10, themes, mode,
    reasons, examples: [{ game_id: 1, ply: 6, cp_loss: 640 }, { game_id: 1, ply: 8, cp_loss: 410 }],
    puzzle_accuracy: kind === "allowed" && name === "fork" ? 0.86 : null, trend,
  }; // prettier-ignore
}

interface Hooks {
  emit: (job: Job) => void;
  jobId: () => string;
  calls: string[];
  filters: () => FilterSpec | null;
  setFilters: (spec: FilterSpec, mode: string) => void;
  quote: (kind: GameKind, what: string) => GameAiQuote;
  startAi: (kind: GameKind, what: string, make: (provider: string, model: string, costUsd: number) => CoachAi) => string;
  aiResult: (what: string) => CoachAi | null;
}

export class MockCoach {
  private reports: CoachReport[] = [];
  private results = new Map<string, number>();
  private last: CoachParams = { ...DEFAULT_PARAMS };
  private suggestion: Omit<SuggestionView, "active"> | null = null;
  private applied: string | null = null;
  private players: { subject: string; label: string; games: number }[] = [];
  private running: string | null = null;

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
    this.h.calls.push(`coach:${p.source}:${p.player ?? "me"}:${p.game_ids.length || p.count}`);
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
    const games = p.source === "puzzles" ? 0 : p.game_ids.length || 3;
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
    }; // prettier-ignore
    this.reports.push(report);
    return report;
  }

  private preset(): CoachPresetView {
    return {
      name: "The report's mix",
      spec: {
        ...(this.h.filters() ?? {}),
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

  // ---- AI coaching -------------------------------------------------------------------------------
  private kind(id: number): GameKind {
    return this.get(id).params.detail === "detailed" ? "coach_detailed" : "coach_summary";
  }

  aiQuote(id: number): GameAiQuote {
    return this.h.quote(this.kind(id), `coach:${id}`);
  }

  startAi(id: number): string {
    const r = this.get(id);
    return this.h.startAi(this.kind(id), `coach:${id}`, (provider, model, cost) => ({
      summary: "Most of your losses come from forks you allow, about 13 per 10 games, usually because you didn't check your opponent's replies (E1). Fix that first; your pins come next.",
      weaknesses: [
        { key: "allowed:fork", label: "Allowed: Fork", explanation: "You allowed a knight fork 4 times; in 3 you said you didn't look.", drill: "Danger spotting with fork puzzles: name the threat before you move." },
        { key: "missed:pin", label: "Missed: Pin", explanation: "You had a pin 3 times and played something else (E2).", drill: "Pin puzzles at 1450–1750." },
        { key: "habit:hungPiece", label: "Hung a piece", explanation: "Twice a piece was left with no defender.", drill: "Before every move, check what it leaves undefended." },
      ],
      presets: [
        { name: "Forks you allow", spec: { ...(r.preset?.spec ?? {}), ratios: [], themes: ["fork"] }, mode: "danger_spotting", why: [] },
      ],
      fallback_preset: false, discarded: 1, provider, model, cost_usd: cost,
    })); // prettier-ignore
  }

  ai(id: number): CoachAi | null {
    return this.h.aiResult(`coach:${id}`);
  }
}
