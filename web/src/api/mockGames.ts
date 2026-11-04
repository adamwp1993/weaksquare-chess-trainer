// v0.8 mock: the game library, Game Review, Retry mode, Save as puzzle and puzzle files, with fixed data.
// Scenarios: `?games=empty` starts with an empty library; `?chesscom=player_a` starts with that chess.com
// username linked; `?file=none` makes the Open dialogs come back cancelled.
import { Chess } from "chess.js";
import type { GamesSettingsChange, LibraryFilters, ReasonKey } from "./ApiClient";
import { ApiCallError } from "./ApiClient";
import type { MockPuzzle } from "./mockPuzzles";
import type {
  AnalysisQueue,
  ChesscomProfile,
  FilterSpec,
  GameImport,
  GamePage,
  GameReview,
  GameStats,
  GameSummary,
  GamesSettings,
  Job,
  PuzzleImportReport,
  PuzzleSet,
  ReasonStats,
  RetryResult,
  ReviewMove,
  SavedPuzzle,
  SideSummary,
} from "./types";

type Cls = ReviewMove["classification"];

// The Blackburne Shilling trap: you (White) take on e5 and f7 and get mated. Evals are White's, clamped.
const TRAP = ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "c6d4", "f3e5", "d8g5", "e5f7", "g5g2", "h1f1", "g2e4", "c4e2", "d4f3"];
const GRADES: [Cls, number, string, string][] = [
  // classification, eval after (White), eval text, best move
  ["best", 30, "+0.3", "e2e4"],
  ["best", 30, "+0.3", "e7e5"],
  ["best", 35, "+0.4", "g1f3"],
  ["best", 35, "+0.4", "b8c6"],
  ["good", 30, "+0.3", "f1c4"],
  ["inaccuracy", 85, "+0.9", "f8c5"],
  ["blunder", -140, "−1.4", "f3d4"],
  ["best", -140, "−1.4", "d8g5"],
  ["blunder", -900, "−9.0", "e5g4"],
  ["best", -900, "−9.0", "g5g2"],
  ["best", -950, "−9.5", "h1f1"],
  ["best", -1000, "#-2", "g2e4"],
  ["best", -1000, "#-1", "c4e2"],
  ["best", -1000, "#", "d4f3"],
];
const LINES: Record<number, { score: string; pv: string[] }[]> = {
  6: [
    { score: "+0.9", pv: ["f3d4", "e5d4", "e1g1"] },
    { score: "+0.6", pv: ["c2c3", "d4f3", "d1f3"] },
    { score: "+0.4", pv: ["e1g1", "f8c5", "c2c3"] },
  ],
  8: [
    { score: "−1.4", pv: ["e5g4", "d7d5", "e4d5"] },
    { score: "−2.1", pv: ["e1g1", "g5e5", "c2c3"] },
    { score: "−9.0", pv: ["e5f7", "g5g2", "h1f1"] },
  ],
};
const REFUTATION: Record<number, string[]> = {
  6: ["d8g5", "e5f7", "g5g2", "h1f1", "g2e4"],
  8: ["g5g2", "h1f1", "g2e4", "c4e2", "d4f3"],
};
const SCHOLAR = ["e2e4", "e7e5", "d1h5", "b8c6", "f1c4", "g8f6", "h5f7"];
const OTHER = ["d2d4", "d7d5", "c2c4", "e7e6", "b1c3", "g8f6", "c1g5", "f8e7"];

interface MockGame {
  summary: GameSummary;
  moves: string[];
  reasons: Map<number, ReasonKey>;
}

const BASE: Omit<GameSummary, "id" | "source" | "user_color" | "result" | "user_result" | "white" | "black"> = {
  url: null, played_at: null, time_class: null, time_control: null, rated: null, white_rating: null,
  black_rating: null, opponent: null, opponent_rating: null, user_rating: null, eco: null, opening: null,
  accuracy_user: null, accuracy_opponent: null, lichess_analyzed: false, analysis_status: "none",
}; // prettier-ignore

function libraryGames(): MockGame[] {
  const g = (summary: GameSummary, moves: string[]): MockGame => ({ summary, moves, reasons: new Map() });
  return [
    g({ ...BASE, id: 1, source: "lichess", url: "https://lichess.org/GAMEID01", played_at: "2026-10-30T18:20:00+00:00",
        time_class: "rapid", time_control: "600+0", rated: true, white: "your_name", black: "opponent_b",
        white_rating: 1612, black_rating: 1598, user_color: "white", opponent: "opponent_b", opponent_rating: 1598,
        user_rating: 1612, result: "0-1", user_result: "loss", eco: "C50", opening: "Italian Game: Blackburne Shilling Gambit",
        accuracy_user: 54, accuracy_opponent: 96, lichess_analyzed: true, analysis_status: "analyzed" }, TRAP), // prettier-ignore
    g({ ...BASE, id: 2, source: "chesscom", url: "https://www.chess.com/game/live/100000002", played_at: "2026-10-29T20:05:00+00:00",
        time_class: "blitz", time_control: "180+2", rated: true, white: "opponent_e", black: "player_a",
        white_rating: 1450, black_rating: 1462, user_color: "black", opponent: "opponent_e", opponent_rating: 1450,
        user_rating: 1462, result: "1-0", user_result: "loss", eco: "C20", opening: "King's Pawn Game", accuracy_user: 38, accuracy_opponent: 71 }, SCHOLAR), // prettier-ignore
    g({ ...BASE, id: 3, source: "lichess", url: "https://lichess.org/GAMEID03", played_at: "2026-10-27T09:40:00+00:00",
        time_class: "classical", time_control: "1800+20", rated: false, white: "opponent_c", black: "your_name",
        white_rating: 1701, black_rating: 1622, user_color: "black", opponent: "opponent_c", opponent_rating: 1701,
        user_rating: 1622, result: "1/2-1/2", user_result: "draw", eco: "D53", opening: "Queen's Gambit Declined" }, OTHER), // prettier-ignore
  ];
}

function sideOf(ply: number): "white" | "black" {
  return ply % 2 === 0 ? "white" : "black";
}

function sans(fen: string, pv: string[]): string[] {
  const c = new Chess(fen);
  const out: string[] = [];
  for (const u of pv) {
    try {
      out.push(c.move({ from: u.slice(0, 2), to: u.slice(2, 4), promotion: u[4] }).san);
    } catch {
      break;
    }
  }
  return out;
}

const ERRORS = new Set(["inaccuracy", "mistake", "blunder"]);

export class MockGames {
  private games: MockGame[];
  private nextGame = 10;
  private chesscom: string | null;
  private settings = { sync_on_open: true, first_sync_days: 90, first_sync_max: 200, think_s: 0.3, thresholds: { inaccuracy: 50, mistake: 100, blunder: 200, decided: 500 }, tolerance_cp: 30, key_moments: 5, puzzle_level: "mistakes" as "blunders" | "mistakes" | "inaccuracies", puzzle_think_s: 1.0 }; // prettier-ignore
  private urlResults = new Map<string, GameImport>();
  private reports = new Map<string, PuzzleImportReport>();
  private sets = new Map<string, number>();
  private saved = new Map<string, number>(); // "game:ply" -> puzzle id
  private retries: { id: number; found: boolean }[] = [];
  private retryReasons = new Map<number, ReasonKey>();
  private queueJob: string | null = null;
  private current: number | null = null;
  private waiting: number[] = [];
  readonly mine: MockPuzzle[] = [];
  private readonly fileCancelled: boolean;

  constructor(
    params: URLSearchParams,
    private readonly emit: (job: Job) => void,
    private readonly newJobId: () => string,
    private readonly lichessUser: () => string | null,
  ) {
    this.games = params.get("games") === "empty" ? [] : libraryGames();
    this.chesscom = params.get("chesscom");
    this.fileCancelled = params.get("file") === "none";
    if (params.get("mine") === "1") {
      this.addMine("1", "6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1", ["d1d8"], "import", "Back-rank drills");
      this.sets.set("Back-rank drills", 1);
    }
  }

  // ---- settings and accounts ----------------------------------------------------------------
  getSettings(): GamesSettings {
    const s = this.settings;
    return { lichess_username: this.lichessUser(), chesscom_username: this.chesscom, ...s, thresholds: { ...s.thresholds }, puzzle_job_id: null };
  }

  setSettings(c: GamesSettingsChange): GamesSettings {
    if (c.think_s !== undefined && (c.think_s < 0.1 || c.think_s > 5)) throw this.invalid("The think time must be 0.1–5 s per position.");
    if (c.key_moments !== undefined && (c.key_moments < 1 || c.key_moments > 10)) throw this.invalid("Key moments must be a whole number from 1 to 10.");
    if (c.tolerance_cp !== undefined && (c.tolerance_cp < 0 || c.tolerance_cp > 300)) throw this.invalid("the tolerance must be a whole number of centipawns from 0 to 300");
    if (c.thresholds && !(c.thresholds.inaccuracy < c.thresholds.mistake && c.thresholds.mistake < c.thresholds.blunder)) {
      throw this.invalid("thresholds must rise: inaccuracy < mistake < blunder, and 'decided' within 100–1000");
    }
    const { thresholds, ...rest } = c;
    Object.assign(this.settings, Object.fromEntries(Object.entries(rest).filter(([, v]) => v !== undefined)));
    if (thresholds) this.settings.thresholds = { ...this.settings.thresholds, ...thresholds };
    return this.getSettings();
  }

  verifyChesscom(username: string): ChesscomProfile {
    const u = username.trim().replace(/^.*chess\.com\/member\//, "");
    if (!/^[A-Za-z0-9_-]{2,30}$/.test(u)) throw this.invalid("That isn't a chess.com username.");
    if (u.toLowerCase().startsWith("nobody")) {
      throw new ApiCallError({ code: "not_found", message: `There's no chess.com player called ${u}.`, retryable: false });
    }
    return { username: u, name: null, url: `https://www.chess.com/member/${u}`, joined: 1600000000 };
  }

  setChesscom(username: string | null): GamesSettings {
    this.chesscom = username ? username.trim() : null;
    return this.getSettings();
  }

  startSync(): string | null {
    if (!this.lichessUser() && !this.chesscom) return null;
    const id = this.newJobId();
    const kind = "games_sync";
    this.emit({ id, kind, state: "running", progress: null, message: "Syncing your Lichess games…", error_code: null });
    setTimeout(() => {
      const fresh = !this.games.some((g) => g.summary.id === 4);
      if (fresh && this.games.length) {
        this.games.unshift({
          summary: { ...BASE, id: 4, source: "lichess", url: "https://lichess.org/GAMEID04", played_at: "2026-11-02T19:00:00+00:00",
            time_class: "rapid", time_control: "900+10", rated: true, white: "your_name", black: "opponent_d", white_rating: 1620,
            black_rating: 1580, user_color: "white", opponent: "opponent_d", opponent_rating: 1580, user_rating: 1620, result: "1-0",
            user_result: "win", eco: "B01", opening: "Scandinavian Defense" }, // prettier-ignore
          moves: ["e2e4", "d7d5", "e4d5", "d8d5", "b1c3", "d5a5"],
          reasons: new Map(),
        });
      }
      this.emit({ id, kind, state: "done", progress: 1, message: fresh ? "1 new game" : "0 new games", error_code: null });
    }, 400);
    return id;
  }

  list(f: LibraryFilters): GamePage {
    let rows = this.games.map((g) => g.summary);
    const has = <T>(list: T[] | undefined, v: T) => !list || list.length === 0 || list.includes(v);
    rows = rows.filter(
      (g) =>
        has(f.platforms, g.source) &&
        has(f.time_classes, g.time_class ?? "") &&
        has(f.results, g.user_result ?? ("" as "win")) &&
        has(f.colors, (g.user_color ?? "") as "white") &&
        has(f.statuses, g.analysis_status) &&
        (f.rated === undefined || f.rated === null || g.rated === f.rated) &&
        (!f.opponent || (g.opponent ?? `${g.white} ${g.black}`).toLowerCase().includes(f.opponent.toLowerCase())) &&
        (!f.opening || (g.opening ?? "").toLowerCase().includes(f.opening.toLowerCase()) || g.eco?.toLowerCase() === f.opening.toLowerCase()),
    );
    const offset = f.offset ?? 0;
    return { games: rows.slice(offset, offset + (f.limit ?? 50)), total: rows.length };
  }

  // ---- imports ----------------------------------------------------------------------------------
  private added(moves: string[], needsColor: boolean, source: GameSummary["source"]): GameImport {
    const id = this.nextGame++;
    this.games.unshift({
      summary: { ...BASE, id, source, white: needsColor ? "Player one" : "your_name", black: "Player two",
                 user_color: needsColor ? null : "white", result: "*", user_result: null }, // prettier-ignore
      moves,
      reasons: new Map(),
    });
    return { game_id: id, created: true, needs_color: needsColor, analyzed: false, choices: [], token: null };
  }

  importPgn(text: string): GameImport {
    if (!text.trim()) throw this.invalid("Paste a PGN first.");
    if (/\[Variant "(?!Standard)/i.test(text)) throw this.invalid("Game 1 is Chess960: only standard chess is supported.", "bad_pgn");
    if (!/\d\.\s*[a-hNBRQKO]/.test(text)) throw this.invalid("No game found. Paste a PGN that starts with tags like [White \"…\"] or with 1. e4.", "bad_pgn");
    if ((text.match(/\[Event /g) ?? []).length > 1) {
      return { game_id: null, created: false, needs_color: false, analyzed: false, token: "pgn-1",
               choices: [{ index: 0, label: "Player one – Player two, 2026.10.01 (1-0)", error: null },
                         { index: 1, label: "Game 2", error: "Game 2 has an illegal or unreadable move (illegal san: 'Ke3')." }] }; // prettier-ignore
    }
    if (text.includes("Blackburne")) return { ...this.importOutcome(1), created: false };
    return this.added(SCHOLAR, !text.includes("your_name"), "paste");
  }

  private importOutcome(id: number): GameImport {
    const g = this.game(id);
    return { game_id: id, created: false, needs_color: g.summary.user_color === null, analyzed: g.summary.analysis_status !== "none", choices: [], token: null };
  }

  chooseFile(): GameImport | null {
    if (this.fileCancelled) return null;
    return this.importPgn('[Event "a"]\n1. e4 e5 *\n[Event "b"]\n1. e4 e5 2. Ke3 *');
  }

  pick(token: string, index: number): GameImport {
    if (token !== "pgn-1") throw new ApiCallError({ code: "not_found", message: "That file's game list has expired. Open the file again.", retryable: false });
    if (index === 1) throw this.invalid("Game 2 has an illegal or unreadable move (illegal san: 'Ke3').", "bad_pgn");
    return this.added(SCHOLAR, true, "file");
  }

  startUrl(url: string, chesscomUsername: string | null): string {
    const lichess = /lichess\.org\/([A-Za-z0-9]{8})/.exec(url);
    const cc = /chess\.com\/(?:game\/)?(live|daily)\/(?:game\/)?(\d+)/.exec(url);
    if (!lichess && !cc) throw this.invalid("That isn't a Lichess or chess.com game URL.", "bad_url");
    if (cc && !(chesscomUsername || this.chesscom)) {
      throw this.invalid("To find a chess.com game, the app needs your chess.com username.", "chesscom_username_needed");
    }
    const id = this.newJobId();
    const kind = "game_url_import";
    this.emit({ id, kind, state: "running", progress: null, message: lichess ? "Fetching the game from Lichess…" : "Searching your chess.com games… month 1 of 6", error_code: null });
    setTimeout(() => {
      if (cc && cc[2] !== "100000002") {
        this.emit({ id, kind, state: "failed", progress: null, error_code: "not_found",
                    message: "That game isn't in your last 6 months of games. Paste its PGN instead (on chess.com: Share → PGN)." }); // prettier-ignore
        return;
      }
      this.urlResults.set(id, this.importOutcome(lichess ? 1 : 2));
      this.emit({ id, kind, state: "done", progress: 1, message: "Game imported", error_code: null });
    }, 300);
    return id;
  }

  urlResult(jobId: string): GameImport | null {
    return this.urlResults.get(jobId) ?? null;
  }

  setColor(gameId: number, color: "white" | "black" | "both") {
    const g = this.game(gameId);
    g.summary = { ...g.summary, user_color: color };
  }

  onlineUrl(gameId: number): string {
    const url = this.game(gameId).summary.url;
    if (!url) throw new ApiCallError({ code: "not_found", message: "This game has no Lichess or chess.com page.", retryable: false });
    return url;
  }

  // ---- analysis ---------------------------------------------------------------------------------
  analyze(ids: number[], force: boolean): string | null {
    const todo = ids.filter((id) => force || this.game(id).summary.analysis_status === "none");
    if (todo.length === 0) return this.queueJob;
    if (this.queueJob) {
      this.waiting.push(...todo.filter((id) => id !== this.current && !this.waiting.includes(id)));
      return this.queueJob;
    }
    const id = this.newJobId();
    this.queueJob = id;
    this.waiting = todo.slice(1);
    this.current = todo[0];
    const kind = "game_analysis";
    const total = todo.length;
    let done = 0;
    const step = () => {
      if (this.queueJob !== id) return; // cancelled
      if (this.current === null) {
        this.queueJob = null;
        this.emit({ id, kind, state: "done", progress: 1, message: `Analyzed ${done} game${done === 1 ? "" : "s"}`, error_code: null });
        return;
      }
      const g = this.game(this.current);
      g.summary = { ...g.summary, analysis_status: "analyzed" };
      done++;
      this.current = this.waiting.shift() ?? null;
      this.emit({ id, kind, state: "running", progress: done / total, message: `Analyzing game ${Math.min(done + 1, total)} of ${total}`, error_code: null });
      setTimeout(step, 250);
    };
    this.emit({ id, kind, state: "running", progress: 0, message: `Analyzing game 1 of ${total}: move 1 of ${this.game(todo[0]).moves.length}`, error_code: null });
    setTimeout(step, 400);
    return id;
  }

  cancel(jobId: string): boolean {
    if (jobId !== this.queueJob) return false;
    this.queueJob = null;
    this.current = null;
    this.waiting = [];
    this.emit({ id: jobId, kind: "game_analysis", state: "cancelled", progress: null, message: "Cancelled", error_code: null });
    return true;
  }

  queue(): AnalysisQueue {
    return { job_id: this.queueJob, current: this.current, waiting: [...this.waiting] };
  }

  // ---- the review -------------------------------------------------------------------------------
  review(gameId: number): GameReview {
    const g = this.game(gameId);
    const analyzed = g.summary.analysis_status !== "none";
    const trap = g.moves === TRAP;
    const chess = new Chess();
    const yours = (ply: number) => g.summary.user_color === "both" || g.summary.user_color === sideOf(ply);
    const moves: ReviewMove[] = g.moves.map((uci, ply) => {
      const fen = chess.fen();
      const san = chess.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] }).san;
      const [cls, ev, text, best] = trap ? GRADES[ply] : (["good", 20, "+0.2", uci] as [Cls, number, string, string]);
      const lines = (trap ? LINES[ply] : undefined) ?? [{ score: text, pv: [best] }];
      const err = analyzed && cls !== null && ERRORS.has(cls) && yours(ply);
      return {
        ply, san, uci, mover: sideOf(ply), fen_before: fen,
        classification: analyzed ? cls : null,
        symbol: analyzed && cls ? ({ inaccuracy: "?!", mistake: "?", blunder: "??" } as Record<string, string>)[cls] ?? null : null,
        cp_loss: analyzed ? (cls === "blunder" ? (ply === 6 ? 225 : 760) : cls === "inaccuracy" ? 55 : 0) : null,
        eval_white: analyzed ? ev : null, eval_text: analyzed ? text : null,
        best_move: analyzed ? best : null, best_san: analyzed ? sans(fen, [best])[0] ?? null : null,
        lines: analyzed ? lines.map((l) => ({ score: l.score, pv: l.pv, sans: sans(fen, l.pv) })) : [],
        refutation: analyzed ? (trap ? REFUTATION[ply] ?? [] : []) : [],
        kind: err && cls !== "inaccuracy" ? (ply === 6 ? "allowed" : "allowed") : null,
        phase: analyzed ? (ply < 10 ? "opening" : "middlegame") : null,
        low_clock: analyzed ? false : null,
        reason: g.reasons.get(ply) ?? null,
        suggested_reason: err ? "missedResource" : null,
        saved: this.saved.has(`${gameId}:${ply}`),
      }; // prettier-ignore
    });
    const errorsOf = (c: "white" | "black") => moves.filter((m) => m.mover === c && m.classification && ERRORS.has(m.classification));
    const summary = (c: "white" | "black"): SideSummary => {
      const mine = moves.filter((m) => m.mover === c);
      const n = (k: string) => mine.filter((m) => m.classification === k).length;
      const loss = mine.reduce((a, m) => a + (m.cp_loss ?? 0), 0);
      return {
        color: c, moves: mine.length, inaccuracies: n("inaccuracy"), mistakes: n("mistake"), blunders: n("blunder"),
        avg_cp_loss: mine.length ? Math.round((loss / mine.length) * 10) / 10 : null,
        platform_accuracy: c === g.summary.user_color ? g.summary.accuracy_user : g.summary.accuracy_opponent,
        phases: (["opening", "middlegame", "endgame"] as const).map((p) => {
          const ms = mine.filter((m) => m.phase === p);
          return { phase: p, moves: ms.length, inaccuracies: ms.filter((m) => m.classification === "inaccuracy").length,
                   mistakes: ms.filter((m) => m.classification === "mistake").length, blunders: ms.filter((m) => m.classification === "blunder").length,
                   avg_cp_loss: ms.length ? Math.round((ms.reduce((a, m) => a + (m.cp_loss ?? 0), 0) / ms.length) * 10) / 10 : null }; // prettier-ignore
        }),
        low_clock_errors: null,
      }; // prettier-ignore
    };
    const colors = g.summary.user_color === "both" ? (["white", "black"] as const) : g.summary.user_color ? [g.summary.user_color] : [];
    const yourErrors = colors.flatMap((c) => errorsOf(c));
    const key = [...yourErrors].sort((a, b) => (b.cp_loss ?? 0) - (a.cp_loss ?? 0)).slice(0, this.settings.key_moments).map((m) => m.ply).sort((a, b) => a - b);
    return {
      game: g.summary,
      start_fen: new Chess().fen(),
      moves,
      analyzed,
      current: analyzed,
      summaries: analyzed ? [summary("white"), summary("black")] : [],
      key_moments: analyzed ? key : [],
      retry_plies: analyzed ? yourErrors.filter((m) => m.classification !== "inaccuracy").map((m) => m.ply) : [],
      ask_reasons: true,
    };
  }

  retry(gameId: number, ply: number, uci: string): RetryResult {
    const v = this.review(gameId);
    const m = v.moves[ply];
    if (!v.analyzed) throw new ApiCallError({ code: "conflict", message: "Analyze this game first.", retryable: false });
    if (!m || !v.retry_plies.includes(ply)) throw this.invalid("Retry works on your mistakes and blunders.");
    const c = new Chess(m.fen_before);
    let san: string;
    try {
      san = c.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] || undefined }).san;
    } catch {
      throw this.invalid("That move isn't legal here.");
    }
    const hit = m.lines.findIndex((l) => l.pv[0] === uci);
    const found = hit === 0 || hit === 1; // the best and a close second are within 30 cp in the mock
    const id = this.retries.length + 1;
    this.retries.push({ id, found });
    return {
      retry_id: id, found, played_san: san, played_score: hit >= 0 ? m.lines[hit].score : "−3.0",
      best_san: m.best_san, best_line: m.lines[0]?.pv ?? [], reply_line: found ? [] : uci === m.uci ? m.refutation : ["d8g5"],
      suggested_reason: found ? null : "missedResource", engine_checked: true,
    }; // prettier-ignore
  }

  savePuzzle(gameId: number, ply: number): SavedPuzzle {
    const v = this.review(gameId);
    const m = v.moves[ply];
    if (!v.analyzed || !m) throw new ApiCallError({ code: "conflict", message: "Analyze this game first.", retryable: false });
    const k = `${gameId}:${ply}`;
    const had = this.saved.get(k);
    if (had !== undefined) return { puzzle_id: had, created: false };
    const id = this.mine.length + 100;
    this.saved.set(k, id);
    const line = m.lines[0]?.pv ?? [];
    this.addMine(String(id), m.fen_before, line.slice(0, line.length % 2 === 0 ? line.length - 1 : line.length), "manual", null);
    return { puzzle_id: id, created: true };
  }

  setGameReason(gameId: number, ply: number, reason: ReasonKey) {
    this.game(gameId).reasons.set(ply, reason);
  }

  setRetryReason(retryId: number, reason: ReasonKey) {
    const r = this.retries.find((x) => x.id === retryId);
    if (!r) throw new ApiCallError({ code: "not_found", message: "That retry isn't recorded.", retryable: false });
    if (r.found) throw this.invalid("Reasons are for misses.");
    this.retryReasons.set(retryId, reason);
  }

  stats(lichess: { attempts: number; wins: number }): GameStats {
    return {
      retry_found: this.retries.filter((r) => r.found).length,
      retry_tried: this.retries.length,
      sources: [{ source: "lichess", ...lichess }, ...(this.mine.length ? [{ source: "my" as const, attempts: 3, wins: 2 }] : [])],
    };
  }

  reasonStats(): ReasonStats {
    const counts = new Map<string, number>();
    for (const g of this.games) for (const r of g.reasons.values()) counts.set(r, (counts.get(r) ?? 0) + 1);
    for (const r of this.retryReasons.values()) counts.set(r, (counts.get(r) ?? 0) + 1);
    const keys: [ReasonKey, string, ReasonStats["reasons"][number]["gap"]][] = [
      ["didntLook", "Didn't look for it", "process"], ["missedResource", "Missed their reply / defense / threat", "process"],
      ["miscalculated", "Saw the idea, calculated it wrong", "calculation"], ["unknownPattern", "Didn't know this pattern", "knowledge"],
      ["rushed", "Rushed / time pressure", "time"],
    ]; // prettier-ignore
    const tagged = keys.reduce((a, [k]) => a + (counts.get(k) ?? 0), 0);
    return {
      reasons: keys.map(([key, label, gap]) => ({ key, label, gap, count: counts.get(key) ?? 0, share: tagged ? (counts.get(key) ?? 0) / tagged : null })),
      tagged, untagged: Math.max(0, 3 - tagged), misclicks: 0, misclick_warning: false, trend: [],
    };
  }

  // ---- your own puzzles -------------------------------------------------------------------------
  private addMine(id: string, fen: string, line: string[], origin: "manual" | "import", label: string | null) {
    this.mine.push({ id, fen, moves: ["", ...line], rating: 0, themes: [], source: "my", origin, set_label: label } as MockPuzzle);
  }

  myPool(spec: FilterSpec): MockPuzzle[] {
    return this.mine.filter((p) => {
      const meta = p as MockPuzzle & { origin?: string; set_label?: string | null };
      return (
        (spec.my_origins.length === 0 || spec.my_origins.includes(meta.origin ?? "")) &&
        (spec.my_sets.length === 0 || spec.my_sets.includes(meta.set_label ?? "")) &&
        (spec.my_severities.length === 0 || spec.my_severities.includes(meta.severity ?? ""))
      );
    });
  }

  importPuzzles(label: string): string | null {
    if (!label.trim()) throw this.invalid("Give the set a label, e.g. the book's title.");
    if (this.fileCancelled) return null;
    const id = this.newJobId();
    const kind = "puzzle_file_import";
    this.emit({ id, kind, state: "running", progress: null, message: "Reading the file…", error_code: null });
    setTimeout(() => {
      const before = this.sets.get(label.trim()) ?? 0;
      const added = before ? 0 : 12;
      if (added) {
        this.sets.set(label.trim(), 12);
        for (let i = 0; i < 12; i++) this.addMine(`i${i}`, "6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1", ["d1d8"], "import", label.trim());
      }
      this.reports.set(id, {
        label: label.trim(), file_name: "my-book.pgn", format: "pgn", entries: 14, added, duplicates: 12 - added, skipped: 2,
        errors: [{ n: 4, reason: "it has no FEN tag, so there's no puzzle position" }, { n: 9, reason: "a move in its solution isn't legal" }],
      }); // prettier-ignore
      this.emit({ id, kind, state: "done", progress: 1, message: `${added} added, ${12 - added} already there, 2 skipped`, error_code: null });
    }, 400);
    return id;
  }

  importReport(jobId: string): PuzzleImportReport | null {
    return this.reports.get(jobId) ?? null;
  }

  puzzleSets(): PuzzleSet[] {
    return [...this.sets.entries()].sort().map(([label, count]) => ({ label, count }));
  }

  // ---- helpers ----------------------------------------------------------------------------------
  // ---- v0.9: Game Review AI ------------------------------------------------------------------------
  /** Explain my game finished on the current analysis (FR-11.25). Re-analysis sets it back to analyzed. */
  markAiReviewed(gameId: number) {
    const g = this.game(gameId);
    if (g.summary.analysis_status === "analyzed") g.summary = { ...g.summary, analysis_status: "ai_reviewed" };
  }

  /** Your `n` largest errors in game order (the backend's top_moments); n null: the Key moments setting. */
  aiMoments(gameId: number, n: number | null): { n: number; plies: number[] } {
    const count = n ?? this.settings.key_moments;
    if (!Number.isInteger(count) || count < 1 || count > 10) throw this.invalid("Explain my game covers 1 to 10 key moments.");
    const v = this.review(gameId);
    const yours = (m: ReviewMove) => v.game.user_color === "both" || v.game.user_color === m.mover;
    const errs = v.moves.filter((m) => yours(m) && m.classification && ERRORS.has(m.classification));
    const plies = [...errs].sort((a, b) => (b.cp_loss ?? 0) - (a.cp_loss ?? 0) || a.ply - b.ply).slice(0, count).map((m) => m.ply);
    return { n: count, plies: plies.sort((a, b) => a - b) };
  }

  private game(id: number): MockGame {
    const g = this.games.find((x) => x.summary.id === id);
    if (!g) throw new ApiCallError({ code: "not_found", message: "That game isn't in your library.", retryable: false });
    return g;
  }

  private invalid(message: string, code = "invalid_argument") {
    return new ApiCallError({ code, message, retryable: false });
  }
}
