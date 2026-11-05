// The mock client's AI side (v0.7): settings, the price table, the guardrails and Explain, with fixed data.
// v0.9: a model per AI feature (FR-1.15) and Game Review AI (Explain this move, Explain my game).
// Scenarios via the page URL:
//   ?ai=on       Anthropic with a key and Claude Haiku 5.5 picked (default: no AI set up)
//   ?ai=warn     as on, with 85% of the monthly budget used (the yellow indicator)
//   ?ai=over     as on, with the budget used up (Explain blocked, cached results still free)
//   ?ai=failed   as on, but the launch check failed (the startup page opens the full form)
//   ?ai=nomodel  Anthropic with a key and no model picked
//   ?ai=split    as on, with Game Review on its own model (Claude Sonnet 5.5)
// The mock's explanations follow the puzzle's real solution and always include one discarded
// annotation, so the "some annotations were discarded" note can be seen and tested.
import { Chess } from "chess.js";
import type { LlmPriceChange, LlmProvider, LlmSettingsChange } from "./ApiClient";
import { ApiCallError } from "./ApiClient";
import type {
  CoachAi,
  ExplainQuote,
  Explanation,
  GameAiQuote,
  GameNarrative,
  Job,
  LlmFeature,
  LlmPrice,
  LlmSettings,
  LlmSpend,
} from "./types";

const SEED: LlmPrice[] = [
  { provider: "anthropic", model: "claude-haiku-5-5", input_per_m: 0.1, output_per_m: 0.5, long_ctx_threshold: 100000, long_input_per_m: 0.5, long_output_per_m: 2.5, as_of: "2026-10-31" },
  { provider: "anthropic", model: "claude-sonnet-5-5", input_per_m: 2, output_per_m: 10, long_ctx_threshold: null, long_input_per_m: null, long_output_per_m: null, as_of: "2026-10-31" },
  { provider: "anthropic", model: "claude-opus-5-5", input_per_m: 4, output_per_m: 20, long_ctx_threshold: null, long_input_per_m: null, long_output_per_m: null, as_of: "2026-10-31" },
  { provider: "anthropic", model: "claude-fable-5-1", input_per_m: 10, output_per_m: 50, long_ctx_threshold: null, long_input_per_m: null, long_output_per_m: null, as_of: "2026-10-31" },
  { provider: "openai", model: "gpt-5.4-nano", input_per_m: 0.2, output_per_m: 1.25, long_ctx_threshold: null, long_input_per_m: null, long_output_per_m: null, as_of: "2026-10-31" },
  { provider: "openai", model: "gpt-5.4-mini", input_per_m: 0.75, output_per_m: 4.5, long_ctx_threshold: null, long_input_per_m: null, long_output_per_m: null, as_of: "2026-10-31" },
  { provider: "openai", model: "gpt-5.4", input_per_m: 2.5, output_per_m: 15, long_ctx_threshold: null, long_input_per_m: null, long_output_per_m: null, as_of: "2026-10-31" },
  { provider: "openai", model: "gpt-5.5", input_per_m: 5, output_per_m: 30, long_ctx_threshold: null, long_input_per_m: null, long_output_per_m: null, as_of: "2026-10-31" },
];
const LABELS: Record<LlmProvider, string> = { anthropic: "Anthropic", openai: "OpenAI" };
const PREFIX: Record<LlmProvider, string> = { anthropic: "sk-ant-", openai: "sk-" };
const MULT = { low: 1, medium: 2, high: 4 } as const;
const PROMPT_TOKENS = 2234; // (6,000 + 700 characters) / 3, as the backend estimates
const ACTUAL = { input: 1834, output: 412 }; // what the mock's "provider" reports
// v0.9: per request kind, as core/llm/defaults.py has them (prompt tokens = typical characters / 3).
const KIND = {
  explain: { prompt: 2000, typical: 600, max: 1500 },
  game_move: { prompt: 2000, typical: 600, max: 1500 },
  game_narrative: { prompt: 10000, typical: 3000, max: 4000 },
  coach_summary: { prompt: 6000, typical: 1500, max: 2500 }, // v0.10
  coach_detailed: { prompt: 23333, typical: 3000, max: 5000 },
} as const;
const ACTUAL_GAME = {
  game_move: { input: 1900, output: 450 },
  game_narrative: { input: 9400, output: 2600 },
  coach_summary: { input: 5200, output: 1300 },
  coach_detailed: { input: 19800, output: 2700 },
} as const;
export type GameKind = "game_move" | "game_narrative" | "coach_summary" | "coach_detailed";
type Choice = "same" | LlmProvider;
type Feature = "explain" | "game_review" | "coach";
type Other = "game_review" | "coach";
const featureOf = (kind: GameKind): Other => (kind.startsWith("coach") ? "coach" : "game_review");

const cost = (p: LlmPrice, input: number, output: number) => {
  const long = p.long_ctx_threshold !== null && input > p.long_ctx_threshold;
  const i = long ? (p.long_input_per_m ?? p.input_per_m) : p.input_per_m;
  const o = long ? (p.long_output_per_m ?? p.output_per_m) : p.output_per_m;
  return (input * i + output * o) / 1_000_000;
};
const r6 = (x: number) => Math.round(x * 1e6) / 1e6;
const bad = (message: string) => new ApiCallError({ code: "invalid_argument", message, retryable: false });

export interface ExplainTarget {
  puzzleId: string;
  path: string; // your moves, as the backend's cache key has them
  startFen: string;
  solution: string[]; // UCI from startFen
  finished: boolean;
  engineReady: boolean;
}

export class MockLlm {
  private provider: LlmSettings["provider"] = "none";
  private models: Record<LlmProvider, string> = { anthropic: "", openai: "" };
  private keys: Record<LlmProvider, boolean> = { anthropic: false, openai: false };
  private reasoning: LlmSettings["reasoning"] = "low";
  private cap = 0.5;
  private budget = 5;
  private spent = 0;
  private prices: LlmPrice[] = SEED.map((p) => ({ ...p }));
  private keyCheck: LlmSettings["key_check"] = "none";
  private keyCheckMessage: string | null = null;
  private cache = new Map<string, Explanation>();
  private results = new Map<number, { puzzleId: string; x: Explanation }>();
  // v0.9: Game Review's own choice (FR-1.15), its spend, and its results keyed like the backend's cache.
  private fs: Record<Other, { choice: Choice; model: string; reasoning: LlmSettings["reasoning"] }> = {
    game_review: { choice: "same", model: "", reasoning: "low" },
    coach: { choice: "same", model: "", reasoning: "low" },
  };
  private spentBy: Record<Feature, number> = { explain: 0, game_review: 0, coach: 0 };
  private gameCache = new Map<string, Explanation | GameNarrative | CoachAi>();
  readonly calls: string[] = [];

  constructor(
    params: URLSearchParams,
    private readonly emit: (job: Job) => void,
    private readonly newJobId: () => string,
  ) {
    const ai = params.get("ai");
    if (ai && ai !== "off") {
      this.provider = "anthropic";
      this.keys.anthropic = true;
      this.models.anthropic = ai === "nomodel" ? "" : "claude-haiku-5-5";
      this.keyCheck = "ok";
    }
    if (ai === "split") this.fs.game_review = { choice: "anthropic", model: "claude-sonnet-5-5", reasoning: "low" };
    if (ai === "warn") this.spent = 4.25;
    if (ai === "over") this.spent = 5.0012;
    if (ai === "failed") {
      this.keyCheck = "failed";
      this.keyCheckMessage = "The API key was rejected. Check it in Settings → AI, or create a new one in the provider's console.";
    }
  }

  private configured() {
    return this.provider !== "none" && this.keys[this.provider];
  }

  private spend(): LlmSpend {
    const level = this.spent >= this.budget ? "over" : this.spent >= 0.8 * this.budget ? "warn" : "ok";
    return { month: "2026-11", spent_usd: r6(this.spent), budget_usd: this.budget, level, configured: this.configured() };
  }

  settings(): LlmSettings {
    const providers = (["anthropic", "openai"] as LlmProvider[]).map((p) => ({
      provider: p,
      label: LABELS[p],
      key_stored: this.keys[p],
      model: this.models[p],
      models: this.prices
        .filter((r) => r.provider === p)
        .sort((a, b) => a.input_per_m - b.input_per_m || a.model.localeCompare(b.model))
        .map((r) => ({ model: r.model, explain_usd: r6(cost(r, PROMPT_TOKENS, 600 * MULT[this.reasoning])) })),
    }));
    return {
      provider: this.provider,
      reasoning: this.reasoning,
      run_cap_usd: this.cap,
      monthly_budget_usd: this.budget,
      providers,
      spend: this.spend(),
      key_check: this.keyCheck,
      key_check_message: this.keyCheckMessage,
      features: [this.feature("explain"), this.feature("game_review"), this.feature("coach")],
    };
  }

  /** What a feature's requests use now: its provider, model and reasoning (FR-1.15). */
  private effective(feature: Feature) {
    const model = this.provider === "none" ? "" : this.models[this.provider];
    if (feature === "explain") return { provider: this.provider, model, reasoning: this.reasoning };
    const f = this.fs[feature];
    if (f.choice === "same") return { provider: this.provider, model, reasoning: f.reasoning };
    return { provider: f.choice as LlmSettings["provider"], model: f.model, reasoning: f.reasoning };
  }

  private feature(feature: Feature): LlmFeature {
    const e = this.effective(feature);
    const k = KIND[feature === "explain" ? "explain" : feature === "coach" ? "coach_summary" : "game_narrative"];
    const order = (p: string) => (p === "anthropic" ? 0 : 1);
    const priced = this.prices.some((p) => p.provider === e.provider && p.model === e.model);
    return {
      feature,
      label: feature === "explain" ? "Puzzle Explain" : feature === "coach" ? "Coach" : "Game Review",
      choice: feature === "explain" ? this.provider : this.fs[feature].choice,
      model: feature === "explain" ? e.model : this.fs[feature].model,
      reasoning: e.reasoning,
      provider: e.provider,
      effective_model: e.model,
      ready: e.provider !== "none" && this.keys[e.provider] && !!e.model && priced,
      spent_usd: r6(this.spentBy[feature]),
      options: [...this.prices]
        .sort((a, b) => order(a.provider) - order(b.provider) || a.input_per_m - b.input_per_m || a.model.localeCompare(b.model))
        .map((r) => ({ provider: r.provider, model: r.model, usd: r6(cost(r, k.prompt, k.typical * MULT[e.reasoning])) })),
    };
  }

  setFeature(feature: string, choice: Choice, model: string, reasoning: LlmSettings["reasoning"]): LlmSettings {
    if (feature !== "game_review" && feature !== "coach") throw bad("Unknown AI feature.");
    const m = model.trim();
    if (choice !== "same" && m && !/^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,99}$/.test(m)) {
      throw bad("That isn't a valid model ID (letters, digits and . _ : / @ - only, up to 100).");
    }
    this.fs[feature] = { choice, model: choice === "same" ? "" : m, reasoning };
    this.calls.push(`llmFeature:${feature}:${choice}:${this.fs[feature].model}:${reasoning}`);
    return this.settings();
  }

  update(c: LlmSettingsChange): LlmSettings {
    if (!(c.run_cap_usd >= 0 && c.run_cap_usd <= 1000)) throw bad("The per-run cap must be between $0 and $1,000.");
    if (!(c.monthly_budget_usd >= 0 && c.monthly_budget_usd <= 1000)) throw bad("The monthly budget must be between $0 and $1,000.");
    const model = c.model.trim();
    if (model && !/^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,99}$/.test(model)) {
      throw bad("That isn't a valid model ID (letters, digits and . _ : / @ - only, up to 100).");
    }
    this.provider = c.provider;
    if (c.provider !== "none") this.models[c.provider] = model;
    this.reasoning = c.reasoning;
    this.cap = Math.round(c.run_cap_usd * 1e4) / 1e4;
    this.budget = Math.round(c.monthly_budget_usd * 1e4) / 1e4;
    this.calls.push(`llmSettings:${c.provider}:${model}`);
    return this.settings();
  }

  setKey(provider: LlmProvider, key: string): LlmSettings {
    const k = key.trim();
    if (k.length < 20 || /\s/.test(k)) throw bad("That doesn't look like an API key (20–400 characters, no spaces).");
    if (!k.startsWith(PREFIX[provider])) {
      throw bad(`That doesn't look like an ${LABELS[provider]} key: they start with ${PREFIX[provider]}.`);
    }
    this.keys[provider] = true;
    this.keyCheck = "none";
    this.keyCheckMessage = null;
    this.calls.push(`llmKey:${provider}`); // never the key itself
    return this.settings();
  }

  deleteKey(provider: LlmProvider): LlmSettings {
    this.keys[provider] = false;
    this.keyCheck = "none";
    this.keyCheckMessage = null;
    return this.settings();
  }

  startKeyTest(provider: LlmProvider, model: string): string {
    if (!this.keys[provider]) throw bad(`Save an ${LABELS[provider]} key first.`);
    const id = this.newJobId();
    const kind = "llm_key_test";
    this.emit({ id, kind, state: "running", progress: null, message: `Testing your ${LABELS[provider]} key…`, error_code: null });
    setTimeout(() => {
      const message = model ? `The key works with ${model}.` : "The key works. Pick a model to use it.";
      this.emit({ id, kind, state: "done", progress: 1, message, error_code: null });
    }, 200);
    return id;
  }

  listPrices(): LlmPrice[] {
    return this.prices.map((p) => ({ ...p }));
  }

  savePrice(r: LlmPriceChange): LlmPrice[] {
    if (!r.model.trim()) throw bad("A price row needs a model ID.");
    if (!(r.input_per_m >= 0 && r.input_per_m <= 1000) || !(r.output_per_m >= 0 && r.output_per_m <= 1000)) {
      throw bad("Prices must be between $0 and $1,000 per 1M tokens.");
    }
    const tier = [r.long_ctx_threshold, r.long_input_per_m, r.long_output_per_m].map((v) => v ?? null);
    if (tier.some((v) => v !== null) && tier.some((v) => v === null)) {
      throw bad("A long-context tier needs its threshold and both of its prices.");
    }
    const row: LlmPrice = {
      provider: r.provider,
      model: r.model.trim(),
      input_per_m: r.input_per_m,
      output_per_m: r.output_per_m,
      long_ctx_threshold: tier[0],
      long_input_per_m: tier[1],
      long_output_per_m: tier[2],
      as_of: r.as_of ?? "2026-11-03",
    };
    this.prices = [...this.prices.filter((p) => !(p.provider === row.provider && p.model === row.model)), row];
    return this.listPrices();
  }

  deletePrice(provider: LlmProvider, model: string): LlmPrice[] {
    const before = this.prices.length;
    this.prices = this.prices.filter((p) => !(p.provider === provider && p.model === model));
    if (this.prices.length === before) {
      throw new ApiCallError({ code: "not_found", message: "There's no price row for that model.", retryable: false });
    }
    return this.listPrices();
  }

  getSpend(): LlmSpend {
    return this.spend();
  }

  // ---- Explain ----------------------------------------------------------------------------------

  private key(t: ExplainTarget) {
    return `${t.puzzleId}|${t.path}|${this.provider}|${this.provider === "none" ? "" : this.models[this.provider]}`;
  }

  private check(t: ExplainTarget) {
    if (!t.finished) throw new ApiCallError({ code: "conflict", message: "The engine is available once the puzzle is over.", retryable: true });
    if (!t.engineReady) throw new ApiCallError({ code: "engine_not_installed", message: "Explain needs Stockfish. Install it first.", retryable: false });
  }

  quote(t: ExplainTarget): ExplainQuote {
    this.check(t);
    const provider = this.provider;
    const model = provider === "none" ? "" : this.models[provider];
    const none = (state: string, message: string): ExplainQuote => ({ state, message, provider, model, typical_usd: null, worst_usd: null });
    if (!this.configured()) return none("not_configured", "Choose an AI provider and save its key in Settings → AI.");
    if (!model) return none("no_model", "Pick a model in Settings → AI.");
    if (this.cache.has(this.key(t))) return { ...none("cached", ""), message: null };
    const price = this.prices.find((p) => p.provider === provider && p.model === model);
    if (!price) {
      return none("no_price", `${model} has no row in the price table, so its cost can't be worked out. Add its prices in Settings → AI.`);
    }
    const typical = r6(cost(price, PROMPT_TOKENS, 600 * MULT[this.reasoning]));
    const worst = r6(cost(price, PROMPT_TOKENS, 1500 * MULT[this.reasoning]));
    const q = { provider, model, typical_usd: typical, worst_usd: worst };
    if (this.spent >= this.budget) {
      const message = `You've used this month's AI budget ($${this.spent.toFixed(2)} of $${this.budget.toFixed(2)}). Raise it in Settings → AI, or wait until next month.`;
      return { state: "over_budget", message, ...q };
    }
    if (worst > this.cap) {
      const message = `This request could cost up to $${worst.toFixed(4)}, more than your per-run cap of $${this.cap.toFixed(2)}. Raise the cap in Settings → AI.`;
      return { state: "over_cap", message, ...q };
    }
    return { state: "ok", message: null, ...q };
  }

  start(sessionId: number, t: ExplainTarget): string {
    const q = this.quote(t);
    if (q.state !== "ok" && q.state !== "cached") throw new ApiCallError({ code: q.state, message: q.message ?? "", retryable: false });
    const id = this.newJobId();
    const kind = "explain";
    this.calls.push(`explain:${t.puzzleId}:${q.model}`);
    this.emit({ id, kind, state: "running", progress: null, message: "Asking Stockfish…", error_code: null });
    setTimeout(() => this.emit({ id, kind, state: "running", progress: null, message: "Asking the AI…", error_code: null }), 150);
    setTimeout(() => {
      const key = this.key(t);
      let x = this.cache.get(key);
      if (x) x = { ...x, cached: true, cost_usd: 0 };
      else {
        const price = this.prices.find((p) => p.provider === q.provider && p.model === q.model)!;
        x = explanationFor(t, q.provider, q.model, r6(cost(price, ACTUAL.input, ACTUAL.output)));
        this.spent += x.cost_usd;
        this.spentBy.explain += x.cost_usd;
        this.cache.set(key, x);
      }
      this.results.set(sessionId, { puzzleId: t.puzzleId, x });
      this.emit({ id, kind, state: "done", progress: 1, message: x.cached ? "Explained (saved)." : `Explained for $${x.cost_usd.toFixed(4)}.`, error_code: null });
    }, 500);
    return id;
  }

  result(sessionId: number, puzzleId: string | null): Explanation | null {
    const r = this.results.get(sessionId);
    return r && r.puzzleId === puzzleId ? r.x : null;
  }

  // ---- Game Review AI (v0.9) ------------------------------------------------------------------------

  private gameKey(what: string, feature: Other = "game_review") {
    const e = this.effective(feature);
    return `${what}|${e.provider}|${e.model}`;
  }

  gameQuote(kind: GameKind, what: string): GameAiQuote {
    const e = this.effective(featureOf(kind));
    const base: GameAiQuote = {
      state: "ok", message: null, provider: e.provider, model: e.model, input_tokens: null, typical_output_tokens: null,
      max_output_tokens: null, typical_usd: null, worst_usd: null, run_cap_usd: this.cap, spent_usd: r6(this.spent),
      budget_usd: this.budget,
    }; // prettier-ignore
    const none = (state: string, message: string | null): GameAiQuote => ({ ...base, state, message });
    if (e.provider === "none" || !this.keys[e.provider]) return none("not_configured", "Choose an AI provider and save its key in Settings → AI.");
    if (!e.model) return none("no_model", "Pick a model in Settings → AI.");
    if (this.gameCache.has(this.gameKey(what, featureOf(kind)))) return none("cached", null);
    const price = this.prices.find((p) => p.provider === e.provider && p.model === e.model);
    if (!price) {
      return none("no_price", `${e.model} has no row in the price table, so its cost can't be worked out. Add its prices in Settings → AI.`);
    }
    const k = KIND[kind];
    const maxOut = k.max * MULT[e.reasoning];
    const typicalOut = Math.min(k.typical * MULT[e.reasoning], maxOut);
    const q: GameAiQuote = {
      ...base, input_tokens: k.prompt, typical_output_tokens: typicalOut, max_output_tokens: maxOut,
      typical_usd: r6(cost(price, k.prompt, typicalOut)), worst_usd: r6(cost(price, k.prompt, maxOut)),
    }; // prettier-ignore
    if (this.spent >= this.budget) {
      const message = `You've used this month's AI budget ($${this.spent.toFixed(2)} of $${this.budget.toFixed(2)}). Raise it in Settings → AI, or wait until next month.`;
      return { ...q, state: "over_budget", message };
    }
    if ((q.worst_usd ?? 0) > this.cap) {
      const message = `This request could cost up to $${(q.worst_usd ?? 0).toFixed(4)}, more than your per-run cap of $${this.cap.toFixed(2)}. Raise the cap in Settings → AI.`;
      return { ...q, state: "over_cap", message };
    }
    return q;
  }

  /** One Game Review request as a job: `make` builds the answer, `done` runs once it's stored. */
  startGame(kind: GameKind, what: string, make: (provider: string, model: string, costUsd: number) => Explanation | GameNarrative | CoachAi, done?: () => void): string {
    const q = this.gameQuote(kind, what);
    if (q.state !== "ok" && q.state !== "cached") throw new ApiCallError({ code: q.state, message: q.message ?? "", retryable: false });
    const id = this.newJobId();
    const job = kind === "game_move" ? "game_move_explain" : kind === "game_narrative" ? "game_narrative" : "coach_ai";
    const verb = kind === "game_move" ? "Explained" : kind === "game_narrative" ? "Game explained" : "AI coaching";
    this.calls.push(`${kind}:${what}:${q.model}`);
    this.emit({ id, kind: job, state: "running", progress: null, message: kind === "game_move" ? "Asking the AI…" : "Asking the AI about your game…", error_code: null }); // prettier-ignore
    setTimeout(() => {
      const key = this.gameKey(what, featureOf(kind));
      const hit = this.gameCache.has(key);
      let costUsd = 0;
      if (!hit) {
        const price = this.prices.find((p) => p.provider === q.provider && p.model === q.model)!;
        costUsd = r6(cost(price, ACTUAL_GAME[kind].input, ACTUAL_GAME[kind].output));
        this.spent += costUsd;
        this.spentBy[featureOf(kind)] += costUsd;
        this.gameCache.set(key, make(q.provider, q.model, costUsd));
      } else {
        const x = this.gameCache.get(key)!;
        this.gameCache.set(key, { ...x, cached: true, cost_usd: 0 });
      }
      done?.();
      this.emit({ id, kind: job, state: "done", progress: 1, message: hit ? `${verb} (saved).` : `${verb} for $${costUsd.toFixed(4)}.`, error_code: null }); // prettier-ignore
    }, 600);
    return id;
  }

  gameResult(what: string, feature: Other = "game_review"): Explanation | GameNarrative | CoachAi | null {
    return this.gameCache.get(this.gameKey(what, feature)) ?? null;
  }
}

/** A fixed explanation that follows the puzzle's real solution, with one annotation "discarded". */
function explanationFor(t: ExplainTarget, provider: string, model: string, costUsd: number): Explanation {
  const chess = new Chess(t.startFen);
  const steps = t.solution.map((uci, ply) => {
    const m = chess.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci.length > 4 ? uci[4] : undefined });
    const you = ply % 2 === 0;
    return {
      ply,
      side: (you ? "you" : "opponent") as "you" | "opponent",
      san: m.san,
      uci,
      text: you
        ? `The ${pieceName(m.piece)} lands where it hits two things at once.`
        : "The best defence, but it doesn't save the material.",
      annotations: you
        ? [
            { kind: "arrow" as const, orig: uci.slice(0, 2), dest: uci.slice(2, 4), color: "green" as const },
            { kind: "circle" as const, orig: uci.slice(2, 4), dest: null, color: "yellow" as const },
          ]
        : [{ kind: "arrow" as const, orig: uci.slice(0, 2), dest: uci.slice(2, 4), color: "red" as const }],
      variation: [],
    };
  });
  return {
    summary:
      "Your first move attacks two targets at once, and whatever the opponent saves, the other falls. <b>This text is shown as typed</b>, never as HTML.",
    steps,
    key_ideas: ["fork", "double attack"],
    discarded: 1,
    provider,
    model,
    cost_usd: costUsd,
    cached: false,
    start_fen: t.startFen,
    solution: t.solution,
  };
}

function pieceName(p: string) {
  return { p: "pawn", n: "knight", b: "bishop", r: "rook", q: "queen", k: "king" }[p] ?? "piece";
}
