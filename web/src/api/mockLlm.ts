// The mock client's AI side (v0.7): settings, the price table, the guardrails and Explain, with fixed data.
// Scenarios via the page URL:
//   ?ai=on       Anthropic with a key and Claude Haiku 5.5 picked (default: no AI set up)
//   ?ai=warn     as on, with 85% of the monthly budget used (the yellow indicator)
//   ?ai=over     as on, with the budget used up (Explain blocked, cached results still free)
//   ?ai=failed   as on, but the launch check failed (the startup page opens the full form)
//   ?ai=nomodel  Anthropic with a key and no model picked
// The mock's explanations follow the puzzle's real solution and always include one discarded
// annotation, so the "some annotations were discarded" note can be seen and tested.
import { Chess } from "chess.js";
import type { LlmPriceChange, LlmProvider, LlmSettingsChange } from "./ApiClient";
import { ApiCallError } from "./ApiClient";
import type { ExplainQuote, Explanation, Job, LlmPrice, LlmSettings, LlmSpend } from "./types";

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
    };
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
