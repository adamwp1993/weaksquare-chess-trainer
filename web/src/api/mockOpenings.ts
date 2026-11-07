// v0.13: the opening trainer in the mock client (REQUIREMENTS §18). A small fixed book for UI work, Playwright and the
// user-guide screenshots. `?openings=ready` starts with the book imported. Its rules match the backend's: moves are
// edges between positions, so a removal keeps what another line still reaches.
import { Chess } from "chess.js";
import { ApiCallError } from "./ApiClient";
import type {
  BookFamily,
  OpeningLine,
  OpeningLines,
  OpeningNote,
  OpeningNoteQuote,
  OpeningDeviation,
  OpeningPrefetchPlan,
  OpeningStat,
  PracticeState,
  PracticeSummary,
  ProposedMove,
  RepertoireProposal,
  OpeningPage,
  OpeningScope,
  OpeningSettings,
  Repertoire,
  RepertoireRow,
} from "./types";

type Color = "white" | "black";

const PRESETS: Record<"light" | "standard" | "deep", [number, number]> = { light: [1, 8], standard: [3, 12], deep: [6, 16] };

const ITALIAN = "e4 e5 Nf3 Nc6 Bc4";
const CARO = "e4 c6";
const BOOK: { family: string; eco: string; lines: { name: string; sans: string }[] }[] = [
  {
    family: "Caro-Kann Defense",
    eco: "B10",
    lines: [
      { name: "Caro-Kann Defense: Advance Variation", sans: `${CARO} d4 d5 e5 Bf5` },
      { name: "Caro-Kann Defense: Classical Variation", sans: `${CARO} d4 d5 Nc3 dxe4 Nxe4 Bf5` },
      { name: "Caro-Kann Defense: Exchange Variation", sans: `${CARO} d4 d5 exd5 cxd5` },
    ],
  },
  {
    family: "Italian Game",
    eco: "C50",
    lines: [
      { name: "Italian Game: Classical Variation", sans: `${ITALIAN} Bc5 c3 Nf6 d4` },
      { name: "Italian Game: Two Knights Defense", sans: `${ITALIAN} Nf6 Ng5 d5` },
      { name: "Italian Game: Evans Gambit", sans: `${ITALIAN} Bc5 b4 Bxb4` },
      { name: "Italian Game: Giuoco Pianissimo", sans: `${ITALIAN} Bc5 d3 Nf6` },
      { name: "Italian Game: Hungarian Defense", sans: `${ITALIAN} Be7` },
      { name: "Italian Game: Rousseau Gambit", sans: `${ITALIAN} f5` },
      { name: "Italian Game: Blackburne Shilling Gambit", sans: `${ITALIAN} Nd4` },
    ],
  },
  {
    family: "London System",
    eco: "D02",
    lines: [{ name: "London System", sans: "d4 d5 Bf4 Nf6 e3" }],
  },
];

// After the book: what Stockfish would continue with in the mock, one per family.
const EXTENSION: Record<string, string> = {
  "Caro-Kann Defense": "Nf3 e6 Be2 c5",
  "Italian Game": "exd4 cxd4 Bb4+ Bd2",
  "London System": "c5 c3 Nc6 Nf3",
};

function keyOf(chess: Chess): string {
  return chess.fen().split(" ").slice(0, 4).join(" ");
}

interface Edge {
  key: string;
  uci: string;
  san: string;
  source: string;
  isMain: boolean;
}

function play(sans: string, source: string, base?: Chess): { uci: string; san: string; source: string; key: string }[] {
  const chess = base ?? new Chess();
  return sans.split(" ").map((san) => {
    const key = keyOf(chess);
    const m = chess.move(san);
    return { uci: m.from + m.to + (m.promotion ?? ""), san: m.san, source, key };
  });
}

export class MockOpenings {
  private ready = new URLSearchParams(window.location.search).get("openings") === "ready";
  private scope: OpeningScope = { preset: "standard", sub_lines: 3, max_moves: 12 };
  private extend = true;
  private extended = new Set<string>();
  private useWikibooks = true;
  private explorerSource: "lichess" | "masters" = "lichess";
  private explorerRatings = [1600, 1800, 2000];
  private edges: Record<Color, Edge[]> = { white: [], black: [] };
  private picked: Record<Color, Set<string>> = { white: new Set(), black: new Set() };

  status() {
    return { ready: this.ready, lines: this.ready ? BOOK.reduce((n, b) => n + b.lines.length, 0) : 0 };
  }

  importBook() {
    this.ready = true;
  }

  families(query: string): BookFamily[] {
    const q = query.trim().toLowerCase();
    return BOOK.filter((b) => !q || b.family.toLowerCase().includes(q) || b.eco.toLowerCase().startsWith(q)).map((b) => ({
      name: b.family,
      eco: b.eco,
      lines: b.lines.length,
    }));
  }

  settings(): OpeningSettings {
    return {
      scope: { ...this.scope },
      extend: this.extend,
      use_wikibooks: this.useWikibooks,
      explorer_source: this.explorerSource,
      explorer_ratings: [...this.explorerRatings],
      signed_in: new URLSearchParams(window.location.search).get("account") !== "signed_out",
    };
  }

  setSettings(preset: OpeningScope["preset"], subLines: number | null, maxMoves: number | null, extend: boolean | null): OpeningSettings {
    if (preset === "custom") {
      this.scope = {
        preset,
        sub_lines: Math.min(10, Math.max(0, subLines ?? 3)),
        max_moves: Math.min(20, Math.max(4, maxMoves ?? 12)),
      };
    } else {
      const [sub_lines, max_moves] = PRESETS[preset];
      this.scope = { preset, sub_lines, max_moves };
    }
    if (extend !== null) this.extend = extend;
    return this.settings();
  }

  setSources(useWikibooks: boolean, source: "lichess" | "masters", ratings: number[]): OpeningSettings {
    this.useWikibooks = useWikibooks;
    this.explorerSource = source;
    this.explorerRatings = [...ratings];
    return this.settings();
  }

  page(sans: string[]): OpeningPage {
    const label = sans.map((s, i) => (i % 2 === 0 ? `${i / 2 + 1}. ${s}` : `${(i - 1) / 2 + 1}...${s}`)).join(" ") || "Chess Opening Theory";
    const url = `https://en.wikibooks.org/wiki/Chess_Opening_Theory/${label.replace(/ /g, "_")}`;
    const common = { label, url, licence: "CC BY-SA 4.0", licence_url: "https://creativecommons.org/licenses/by-sa/4.0/" };
    if (!this.useWikibooks) return { state: "off", text: "", ...common };
    if (sans.length > 8) return { state: "missing", text: "", ...common };
    return { state: "ok", text: "Invented mock text about this position, its plans and its pawn structure.", ...common };
  }

  private bookFor(family: string) {
    const found = BOOK.find((b) => b.family === family);
    if (!found) throw new ApiCallError({ code: "not_found", message: "That opening isn't in the book.", retryable: false });
    return found;
  }

  private line(family: string, eco: string, name: string, sans: string, withExtension: boolean): OpeningLine {
    const chess = new Chess();
    const moves = play(sans, "book", chess);
    const limit = this.scope.max_moves * 2;
    if (withExtension) moves.push(...play(EXTENSION[family], "engine", chess));
    return { name, eco, moves: moves.slice(0, limit).map(({ uci, san, source, key }) => ({ uci, san, source, position_key: key })) };
  }

  lines(family: string, engineReady: boolean): OpeningLines {
    const book = this.bookFor(family);
    const chosen = book.lines.slice(0, this.scope.sub_lines + 1);
    const grown = this.extend && this.extended.has(family);
    const lines = chosen.map((l, i) => this.line(family, book.eco, l.name, l.sans, grown && i === 0));
    const pending = this.extend && !grown && lines[0].moves.length < this.scope.max_moves * 2 ? 1 : 0;
    return { family, lines, extend: this.extend, pending, engine_ready: engineReady, scope: { ...this.scope } };
  }

  extendLines(family: string) {
    this.extended.add(family);
  }

  // ---- notes ----------------------------------------------------------------------------------------------------

  private notes = new Map<string, OpeningNote>();

  overviewKey(family: string): string {
    const chess = new Chess();
    play(this.bookFor(family).lines[0].sans.split(" ").slice(0, family === "Italian Game" ? 5 : 2).join(" "), "book", chess);
    return keyOf(chess);
  }

  note(key: string, uci: string, kind: "overview" | "move"): OpeningNote | null {
    return this.notes.get(`${key}|${uci}|${kind}`) ?? null;
  }

  private target(family: string, lineIndex: number, ply: number | null): { key: string; uci: string; kind: "overview" | "move" } {
    if (ply === null) return { key: this.overviewKey(family), uci: "", kind: "overview" };
    const move = this.lines(family, true).lines[lineIndex].moves[ply];
    return { key: move.position_key, uci: move.uci, kind: "move" };
  }

  noteQuote(family: string, lineIndex: number, ply: number | null, regenerate: boolean, ai: boolean): OpeningNoteQuote {
    const base = { provider: "anthropic", model: "claude-haiku-5-5" };
    if (!ai) return { state: "not_configured", message: "Choose an AI provider and save its key in Settings → AI.", typical_usd: null, worst_usd: null, ...base };
    const t = this.target(family, lineIndex, ply);
    if (!regenerate && this.note(t.key, t.uci, t.kind)) return { state: "cached", message: null, typical_usd: 0, worst_usd: 0, ...base };
    return { state: "ok", message: null, typical_usd: 0.0021, worst_usd: 0.004, ...base };
  }

  saveNote(family: string, lineIndex: number, ply: number | null) {
    const t = this.target(family, lineIndex, ply);
    const sections =
      t.kind === "overview"
        ? [
            { heading: "Key ideas", text: "Pressure on f7, and a quick development." },
            { heading: "White's plans", text: "Build a center with c3 and d4." },
          ]
        : [
            { heading: "Why this move", text: "It develops and controls the center." },
            { heading: "If you don't play it", text: "Black gets an easy game." },
          ];
    this.notes.set(`${t.key}|${t.uci}|${t.kind}`, {
      position_key: t.key,
      move_uci: t.uci,
      kind: t.kind,
      sections,
      annotations: t.kind === "overview" ? [{ kind: "arrow", orig: "c4", dest: "f7", color: "green" }] : [],
      provider: "anthropic",
      model: "claude-haiku-5-5",
      other_model: false,
      sources: this.useWikibooks ? [{ label: "1. e4 1...e5", url: "https://en.wikibooks.org/wiki/Chess_Opening_Theory/1._e4/1...e5" }] : [],
      licence: "CC BY-SA 4.0",
      licence_url: "https://creativecommons.org/licenses/by-sa/4.0/",
    });
  }

  private lastOf(moves: string[]): { key: string; uci: string } {
    const chess = this.boardAfter(moves.slice(0, -1));
    return { key: keyOf(chess), uci: moves[moves.length - 1] };
  }

  movesQuote(moves: string[], regenerate: boolean, ai: boolean): OpeningNoteQuote {
    const base = { provider: "anthropic", model: "claude-haiku-5-5" };
    if (!ai) return { state: "not_configured", message: "Choose an AI provider and save its key in Settings → AI.", typical_usd: null, worst_usd: null, ...base };
    const t = this.lastOf(moves);
    if (!regenerate && this.note(t.key, t.uci, "move")) return { state: "cached", message: null, typical_usd: 0, worst_usd: 0, ...base };
    return { state: "ok", message: null, typical_usd: 0.0021, worst_usd: 0.004, ...base };
  }

  saveMovesNote(moves: string[]) {
    const t = this.lastOf(moves);
    this.notes.set(`${t.key}|${t.uci}|move`, {
      position_key: t.key,
      move_uci: t.uci,
      kind: "move",
      sections: [{ heading: "Why this move", text: "It answers their move and keeps your center." }],
      annotations: [],
      provider: "anthropic",
      model: "claude-haiku-5-5",
      other_model: false,
      sources: [],
      licence: "CC BY-SA 4.0",
      licence_url: "https://creativecommons.org/licenses/by-sa/4.0/",
    });
  }

  private withScope<T>(preset: OpeningScope["preset"], subLines: number | null, maxMoves: number | null, extend: boolean, fn: () => T): T {
    const saved = [this.scope, this.extend] as const;
    this.setSettings(preset, subLines, maxMoves, extend);
    try {
      return fn();
    } finally {
      [this.scope, this.extend] = saved;
    }
  }

  prefetchPlan(family: string, preset: OpeningScope["preset"], subLines: number | null, maxMoves: number | null, extend: boolean, ai: boolean): OpeningPrefetchPlan {
    return this.withScope(preset, subLines, maxMoves, extend, () => {
      const { lines } = this.lines(family, true);
      const params = new URLSearchParams(window.location.search).get("prefetch");
      let stored = 0;
      const missingLines = lines.filter((ln) => {
        const left = ln.moves.filter((m) => !this.note(m.position_key, m.uci, "move"));
        stored += ln.moves.length - left.length;
        return left.length > 0;
      }).length;
      const hasOverview = this.note(this.overviewKey(family), "", "overview") !== null;
      if (hasOverview) stored += 1;
      const requests = missingLines + (hasOverview ? 0 : 1);
      const usd = requests * 0.006;
      const split = params === "split" && requests > 1;
      const moves = lines.reduce((n, ln) => n + ln.moves.length, 0);
      return {
        lines: lines.length,
        positions: moves,
        requests,
        stored,
        llm: ai,
        state: !ai ? "not_configured" : params === "over_budget" ? "over_budget" : split ? "split" : "ok",
        message: params === "over_budget" ? "You've used this month's AI budget ($5.00 of $5.00). Raise it in Settings → AI, or wait until next month." : null,
        input_tokens: requests * 4000,
        output_tokens: requests * 2500,
        typical_usd: usd,
        worst_usd: usd * 2,
        run_cap_usd: 0.5,
        budget_share: params === "warn" ? 0.4 : 0.01,
        this_run_requests: split ? Math.ceil(requests / 2) : requests,
        runs: split ? 2 : 1,
        llm_seconds: requests * 20,
        engine_seconds: moves * 0.5,
        warnings: params === "warn" ? ["That's 40% of what's left of this month's AI budget."] : [],
        blurb: ai
          ? `About ${moves} moves across ${lines.length} lines: ~${requests} requests, ~$${usd.toFixed(2)} (≈1% of this month's budget), about 2 minutes. Already-saved notes are free. You can keep using the app while it runs, and cancel at any time; whatever is finished stays saved.`
          : `About ${moves} moves across ${lines.length} lines: about 1 minute of Stockfish time. With no AI set up, this saves engine evals only.`,
        scope: { ...this.scope },
        extend: this.extend,
      };
    });
  }

  savePrefetch(family: string, preset: OpeningScope["preset"], subLines: number | null, maxMoves: number | null, extend: boolean): number {
    return this.withScope(preset, subLines, maxMoves, extend, () => {
      const before = this.notes.size;
      this.saveNote(family, 0, null);
      this.lines(family, true).lines.forEach((ln, i) => ln.moves.forEach((_, ply) => this.saveNote(family, i, ply)));
      return this.notes.size - before;
    });
  }

  hasNotes(): boolean {
    return this.notes.size > 0;
  }

  notesDeletion(): { total: number; shared: number } {
    return { total: this.notes.size, shared: Math.min(1, this.notes.size) };
  }

  deleteNotes(): number {
    const n = this.notes.size;
    this.notes.clear();
    return n;
  }

  // ---- "What if they play…?" and Build my repertoire ------------------------------------------------------------

  private boardAfter(moves: string[]): Chess {
    const chess = new Chess();
    for (const m of moves) chess.move({ from: m.slice(0, 2), to: m.slice(2, 4), promotion: m[4] });
    return chess;
  }

  deviation(color: Color, moves: string[], their: string): OpeningDeviation {
    const chess = this.boardAfter(moves);
    if ((chess.turn() === "w") === (color === "white")) {
      throw new ApiCallError({ code: "invalid_argument", message: "It's your move here. A deviation is a move for the other side.", retryable: false });
    }
    let played;
    try {
      played = /^[a-h][1-8][a-h][1-8]/.test(their)
        ? chess.move({ from: their.slice(0, 2), to: their.slice(2, 4), promotion: their[4] })
        : chess.move(their.trim());
    } catch {
      throw new ApiCallError({ code: "invalid_argument", message: "That move isn't legal here.", retryable: false });
    }
    const replies = chess.moves({ verbose: true }).slice(0, 3).map((m, i) => ({ uci: m.from + m.to, san: m.san, score: `+0.${3 - i} for you` }));
    return { their_uci: played.from + played.to, their_san: played.san, fen_after: chess.fen(), replies, game_over: null };
  }

  addDeviation(color: Color, moves: string[], their: string, reply: string) {
    const chess = new Chess();
    let added = 0;
    let kept = 0;
    const store = (uci: string, source: string) => {
      const key = keyOf(chess);
      const m = chess.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] });
      const here = this.edges[color].filter((e) => e.key === key);
      if (here.some((e) => e.uci === uci)) {
        kept++;
        return;
      }
      added++;
      this.edges[color].push({ key, uci, san: m.san, source, isMain: here.length === 0 });
    };
    moves.forEach((m) => store(m, "book"));
    store(their, "you");
    store(reply, "engine");
    return { added, kept };
  }

  private proposals = new Map<string, RepertoireProposal>();

  build(color: Color, family: string): string {
    const params = new URLSearchParams(window.location.search);
    const chess = new Chess();
    const sans = this.bookFor(family).lines[0].sans.split(" ");
    const moves: ProposedMove[] = sans.map((s, i) => {
      const key = keyOf(chess);
      const m = chess.move(s);
      const yours = (i % 2 === 0) === (color === "white");
      const flagged = i === sans.length - 1;
      return {
        position_key: key,
        move_uci: m.from + m.to,
        san: m.san,
        source: flagged ? "engine" : i > 4 ? "explorer" : "book",
        yours,
        depth: i,
        share: !yours && i > 4 ? 0.6 : null,
        already_yours: this.edges[color].some((e) => e.key === key && e.uci === m.from + m.to),
        flags: flagged ? ["engine_answer"] : params.get("account") === "signed_out" ? [] : i === 2 ? ["few_games"] : [],
      };
    });
    const id = `b${this.proposals.size + 1}`;
    this.proposals.set(id, { id, color, family, moves });
    return id;
  }

  proposal(id: string): RepertoireProposal {
    const found = this.proposals.get(id);
    if (!found) throw new ApiCallError({ code: "not_found", message: "That proposal has gone. Build it again.", retryable: false });
    return found;
  }

  saveProposal(id: string) {
    const p = this.proposal(id);
    let added = 0;
    let kept = 0;
    for (const m of p.moves) {
      const here = this.edges[p.color].filter((e) => e.key === m.position_key);
      if (here.some((e) => e.uci === m.move_uci)) {
        kept++;
        continue;
      }
      added++;
      this.edges[p.color].push({ key: m.position_key, uci: m.move_uci, san: m.san, source: m.source, isMain: here.length === 0 });
    }
    this.picked[p.color].add(p.family);
    this.proposals.delete(id);
    return { added, kept };
  }

  discardProposal(id: string) {
    this.proposals.delete(id);
  }

  // ---- Practice and stats ----------------------------------------------------------------------------------------

  tolerance = false;
  private session: { color: Color; chess: Chess; state: PracticeState["state"]; correct: number; wrong: number; decisions: number; clean: number; targets: number; attempts: Map<string, [number, number]>; wrongFen: string | null } | null = null;
  private attempts: Record<Color, Map<string, [number, number]>> = { white: new Map(), black: new Map() };
  private seen: Record<Color, Set<string>> = { white: new Set(), black: new Set() };

  private yourPositions(color: Color): string[] {
    const turn = color === "white" ? "w" : "b";
    return [...new Set(this.edges[color].filter((e) => e.key.split(" ")[1] === turn).map((e) => e.key))];
  }

  practiceSummary(color: Color): PracticeSummary {
    const mine = this.yourPositions(color);
    const newOnes = mine.filter((k) => !this.seen[color].has(k)).length;
    return { due: 0, new: newOnes, positions: mine.length };
  }

  private practiceState(correct: [string, string][] = [], replies: [string, string][] = [], attempt: number | null = null): PracticeState {
    const s = this.session as NonNullable<typeof this.session>;
    return {
      session_id: "p1",
      state: s.state,
      fen: s.chess.fen(),
      color: s.color,
      decisions: s.decisions,
      correct: s.correct,
      wrong: s.wrong,
      lines_clean: s.clean,
      lines_lost: 0,
      remaining: Math.max(0, s.targets - s.decisions),
      target_reason: "new",
      replies,
      correct_moves: correct,
      attempt_id: attempt,
      message: null,
      wrong_fen: s.wrongFen,
      position_key: keyOf(s.chess),
      line_cut: false,
      reason_prompt:
        s.state === "wrong"
          ? {
              attempt_id: attempt ?? 1,
              source: "opening",
              suggested: null,
              reasons: [
                { key: "didntLook", label: "I didn't look at their reply", gap: "process" },
                { key: "missedResource", label: "I missed their reply", gap: "calculation" },
                { key: "miscalculated", label: "I miscalculated", gap: "calculation" },
                { key: "unknownPattern", label: "I didn't know the pattern", gap: "knowledge" },
                { key: "rushed", label: "I rushed", gap: "time" },
                { key: "misclick", label: "Misclick", gap: "noise" },
              ],
            }
          : null,
    };
  }

  private advance(): [string, string][] {
    const s = this.session as NonNullable<typeof this.session>;
    const replies: [string, string][] = [];
    const yourTurn = () => (s.chess.turn() === "w") === (s.color === "white");
    while (!yourTurn()) {
      const moves = this.edges[s.color].filter((e) => e.key === keyOf(s.chess));
      if (moves.length === 0) break;
      const m = moves.find((e) => e.isMain) ?? moves[0];
      s.chess.move({ from: m.uci.slice(0, 2), to: m.uci.slice(2, 4), promotion: m.uci[4] });
      replies.push([m.uci, m.san]);
    }
    const here = this.edges[s.color].filter((e) => e.key === keyOf(s.chess));
    s.state = yourTurn() && here.length > 0 ? "your_move" : "line_end";
    if (s.state === "line_end") s.clean += 1;
    return replies;
  }

  practiceBranches(color: Color): { position_key: string; label: string }[] {
    const here = this.edges[color];
    return here
      .filter((e) => here.filter((o) => o.key === e.key).length > 1)
      .map((e) => {
        const chess = new Chess(`${e.key} 0 1`);
        chess.move(e.san);
        return { position_key: keyOf(chess), label: e.san };
      });
  }

  startPractice(color: Color, mode: "due" | "new" | "all"): PracticeState {
    const targets = mode === "all" ? this.yourPositions(color).length : this.practiceSummary(color).new;
    this.session = { color, chess: new Chess(), state: "your_move", correct: 0, wrong: 0, decisions: 0, clean: 0, targets, attempts: this.attempts[color], wrongFen: null };
    if (targets === 0) {
      this.session.state = "finished";
      return this.practiceState();
    }
    const replies = this.advance();
    return this.practiceState([], replies);
  }

  private tally(key: string, ok: boolean) {
    const s = this.session as NonNullable<typeof this.session>;
    const [n, good] = s.attempts.get(key) ?? [0, 0];
    s.attempts.set(key, [n + 1, good + (ok ? 1 : 0)]);
    this.seen[s.color].add(key);
  }

  playPractice(uci: string): PracticeState {
    const s = this.session as NonNullable<typeof this.session>;
    const key = keyOf(s.chess);
    const answers = this.edges[s.color].filter((e) => e.key === key);
    s.decisions += 1;
    if (answers.some((e) => e.uci === uci)) {
      this.tally(key, true);
      s.correct += 1;
      s.chess.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] });
      const replies = this.advance();
      return this.practiceState([], replies);
    }
    this.tally(key, false);
    s.wrong += 1;
    s.state = "wrong";
    const probe = new Chess(s.chess.fen());
    probe.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] });
    s.wrongFen = probe.fen();
    return this.practiceState(answers.map((a) => [a.uci, a.san]), [], s.decisions);
  }

  showAnswer(): PracticeState {
    const s = this.session as NonNullable<typeof this.session>;
    const key = keyOf(s.chess);
    this.tally(key, false);
    s.decisions += 1;
    s.wrong += 1;
    s.state = "helped";
    return this.practiceState(this.edges[s.color].filter((e) => e.key === key).map((a) => [a.uci, a.san]), [], s.decisions);
  }

  continuePractice(): PracticeState {
    const s = this.session as NonNullable<typeof this.session>;
    s.wrongFen = null;
    if (s.state === "wrong" || s.state === "helped") {
      const answers = this.edges[s.color].filter((e) => e.key === keyOf(s.chess));
      const m = answers[0];
      s.chess.move({ from: m.uci.slice(0, 2), to: m.uci.slice(2, 4), promotion: m.uci[4] });
      const replies = this.advance();
      return this.practiceState([], replies);
    }
    s.state = "finished";
    return this.practiceState();
  }

  stats(color: Color): OpeningStat[] {
    const rows = [...this.attempts[color].entries()];
    return [...this.picked[color]].map((name, i) => {
      const attempts = rows.reduce((n, [, r]) => n + r[0], 0);
      const correct = rows.reduce((n, [, r]) => n + r[1], 0);
      return {
        id: i + 1,
        name,
        eco: this.bookFor(name).eco,
        positions: this.yourPositions(color).length,
        attempts,
        correct,
        due: 0,
        lines: [{ name, positions: this.yourPositions(color).length, attempts, correct, due: 0 }],
        weakest: rows.filter(([, r]) => r[1] < r[0]).map(([k, r]) => ({ position_key: k, label: "1. e4", attempts: r[0], correct: r[1], due: false })),
      };
    });
  }

  match(name: string): string | null {
    const wanted = name.split(":")[0].trim().toLowerCase();
    return BOOK.find((b) => b.family.toLowerCase() === wanted)?.family ?? null;
  }

  // ---- the repertoire --------------------------------------------------------------------------------------

  addLines(color: Color, family: string, indices: number[]) {
    const { lines } = this.lines(family, true);
    let added = 0;
    let kept = 0;
    for (const i of indices) {
      const chess = new Chess();
      for (const m of lines[i].moves) {
        const key = keyOf(chess);
        const played = chess.move({ from: m.uci.slice(0, 2), to: m.uci.slice(2, 4), promotion: m.uci[4] });
        const here = this.edges[color].filter((e) => e.key === key);
        if (here.some((e) => e.uci === m.uci)) {
          kept++;
          continue;
        }
        added++;
        this.edges[color].push({ key, uci: m.uci, san: played.san, source: m.source, isMain: here.length === 0 });
      }
    }
    this.picked[color].add(family);
    return { added, kept };
  }

  private next(edge: Edge): string {
    const chess = new Chess(`${edge.key} 0 1`);
    chess.move({ from: edge.uci.slice(0, 2), to: edge.uci.slice(2, 4), promotion: edge.uci[4] });
    return keyOf(chess);
  }

  private reachable(edges: Edge[]): Set<Edge> {
    const out = new Set<Edge>();
    const seen = new Set<string>();
    const stack = [keyOf(new Chess())];
    while (stack.length) {
      const key = stack.pop() as string;
      if (seen.has(key)) continue;
      seen.add(key);
      for (const e of edges.filter((x) => x.key === key)) {
        out.add(e);
        stack.push(this.next(e));
      }
    }
    return out;
  }

  private removal(color: Color, key: string, uci: string): Edge[] {
    const edges = this.edges[color];
    if (!edges.some((e) => e.key === key && e.uci === uci)) {
      throw new ApiCallError({ code: "not_found", message: "That move isn't in your repertoire.", retryable: false });
    }
    const keep = this.reachable(edges.filter((e) => !(e.key === key && e.uci === uci)));
    return edges.filter((e) => !keep.has(e));
  }

  previewRemoval(color: Color, key: string, uci: string): string[] {
    return this.removal(color, key, uci).map((e) => e.san);
  }

  remove(color: Color, key: string, uci: string): Repertoire {
    const gone = new Set(this.removal(color, key, uci));
    this.edges[color] = this.edges[color].filter((e) => !gone.has(e));
    return this.repertoire(color);
  }

  setMain(color: Color, key: string, uci: string): Repertoire {
    for (const e of this.edges[color]) if (e.key === key) e.isMain = e.uci === uci;
    return this.repertoire(color);
  }

  move(color: Color, key: string, uci: string, direction: "up" | "down"): Repertoire {
    const edges = this.edges[color];
    const here = edges.filter((e) => e.key === key);
    const i = here.findIndex((e) => e.uci === uci);
    const other = here[direction === "up" ? i - 1 : i + 1];
    if (i >= 0 && other) {
      const a = edges.indexOf(here[i]);
      const b = edges.indexOf(other);
      [edges[a], edges[b]] = [edges[b], edges[a]];
    }
    return this.repertoire(color);
  }

  repertoire(color: Color): Repertoire {
    const rows: RepertoireRow[] = [];
    const seen = new Set<string>();
    const edges = this.edges[color];
    const walk = (key: string, depth: number) => {
      seen.add(key);
      const here = edges.filter((e) => e.key === key).sort((a, b) => Number(b.isMain) - Number(a.isMain));
      const yours = key.split(" ")[1] === (color === "white" ? "w" : "b");
      for (const e of here) {
        const next = this.next(e);
        const transposes = seen.has(next);
        rows.push({ depth, position_key: key, move_uci: e.uci, san: e.san, source: e.source, is_main: e.isMain, yours, transposes });
        if (!transposes) walk(next, depth + 1);
      }
    };
    walk(keyOf(new Chess()), 0);
    const openings = [...this.picked[color]].map((name, i) => ({ id: i + 1, name, eco: this.bookFor(name).eco }));
    return { color, rows, openings };
  }
}
