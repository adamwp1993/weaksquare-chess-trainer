// v0.15 (REQUIREMENTS §20): the mock client's Analysis tab. Fixed, invented data. The real checks are python-chess's in
// core/position_setup.py and core/analysis_pgn.py; these only need to behave the same way for the UI tests.
import { Chess, validateFen } from "chess.js";
import type {
  AnalysisPgnGame,
  AnalysisPgnImport,
  PopularReplies,
  PositionCheck,
  StudyMove,
} from "./types";

const PROBLEMS: [RegExp, string][] = [
  [/missing white king/i, "White has no king."],
  [/missing black king/i, "Black has no king."],
  [/too many (white|black) kings/i, "There can be only one king of each color."],
  [/pawns? on (the )?(first|last|edge|back)/i, "A pawn can't stand on the first or last rank."],
];

export function mockCheckPosition(fen: string): PositionCheck {
  const text = fen.trim().split(/\s+/).join(" ");
  if (!text) return { ok: false, fen: null, problems: ["Paste a FEN, or set up a position on the board."] };
  const parts = text.split(" ");
  const board = parts[0] ?? "";
  if (!/^([1-8pnbrqkPNBRQK]+\/){7}[1-8pnbrqkPNBRQK]+$/.test(board) || !/^[wb]$/.test(parts[1] ?? "")) {
    return { ok: false, fen: null, problems: ["That isn't a FEN. A FEN looks like rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"] };
  }
  const problems: string[] = [];
  if (!board.includes("K")) problems.push("White has no king.");
  if (!board.includes("k")) problems.push("Black has no king.");
  const v = validateFen(text);
  if (!v.ok && problems.length === 0) {
    const known = PROBLEMS.find(([re]) => re.test(v.error ?? ""));
    problems.push(known ? known[1] : "That isn't a FEN. A FEN looks like rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1");
  }
  if (problems.length === 0) {
    const c = new Chess(text);
    // The side that isn't to move must not be in check.
    const flipped = text.replace(/ ([wb]) /, (_m, s: string) => ` ${s === "w" ? "b" : "w"} `).replace(/ [a-h][36] /, " - ");
    try {
      if (new Chess(flipped).inCheck()) problems.push("The side that isn't to move is in check, so it can't be their opponent's turn.");
    } catch {
      /* chess.js refuses some flipped positions; the real check is python-chess's */
    }
    if (problems.length === 0) return { ok: true, fen: c.fen(), problems: [] };
  }
  return { ok: false, fen: null, problems };
}

/** A PGN file's games: a header block that comes after some moves starts the next game. */
function games(pgn: string): string[] {
  const out: { text: string; moves: boolean }[] = [];
  for (const block of pgn.split(/\r?\n\s*\r?\n/).map((b) => b.trim()).filter(Boolean)) {
    const headers = block.startsWith("[");
    const cur = out[out.length - 1];
    if (!cur || (headers && cur.moves)) out.push({ text: block, moves: !headers });
    else {
      cur.text += `\n\n${block}`;
      cur.moves ||= !headers;
    }
  }
  return out.map((g) => g.text);
}

function load(text: string): Chess | null {
  const c = new Chess();
  try {
    c.loadPgn(text);
    return c;
  } catch {
    return null;
  }
}

function label(c: Chess, i: number): string {
  const h = c.getHeaders();
  const white = h.White && h.White !== "?" ? h.White : "";
  const black = h.Black && h.Black !== "?" ? h.Black : "";
  if (!white && !black) return `Game ${i + 1}`;
  return `${white || "?"} – ${black || "?"}` + (h.Result && h.Result !== "*" ? ` (${h.Result})` : "");
}

export function mockImportPgn(pgn: string): AnalysisPgnImport {
  if (!pgn.trim()) throw new Error("Paste a PGN first.");
  const out: AnalysisPgnImport = { games: [], skipped: [] };
  games(pgn).forEach((text, i) => {
    const c = load(text);
    if (c) out.games.push({ index: i, label: label(c, i), move_count: c.history().length });
    else out.skipped.push(`Game ${i + 1} has an illegal or unreadable move.`);
  });
  if (!out.games.length) throw new Error(out.skipped[0] ?? "That isn't a PGN. Paste one that starts with tags like [White \"…\"] or with 1. e4.");
  return out;
}

export function mockPgnGame(pgn: string, index: number): AnalysisPgnGame {
  const text = games(pgn)[index];
  const c = text ? load(text) : null;
  if (!c) throw new Error("That game isn't in the PGN.");
  const comments = new Map(c.getComments().map((x) => [x.fen, x.comment.replace(/\[%[^\]]*\]/g, "").trim()]));
  const start = c.getHeaders().FEN ?? new Chess().fen();
  const replay = new Chess(start);
  const moves: StudyMove[] = [
    { id: 0, parent: null, san: null, uci: null, fen: start, ply: 0, comment: "", shapes: [], nags: [], children: [] },
  ];
  for (const m of c.history({ verbose: true })) {
    replay.move(m.san);
    const id = moves.length;
    moves[id - 1].children.push(id);
    moves.push({
      id, parent: id - 1, san: m.san, uci: m.from + m.to + (m.promotion ?? ""), fen: replay.fen(), ply: id,
      comment: comments.get(replay.fen()) ?? "", shapes: [], nags: [], children: [],
    }); // prettier-ignore
  }
  return { index, label: label(c, index), start_fen: start, moves };
}

// Invented counts, for the start position and 1. e4 only.
const POPULAR: Record<string, [string, number, number, number][]> = {
  "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w": [["e2e4", 5200, 600, 4700], ["d2d4", 3900, 500, 3400], ["c2c4", 900, 150, 800], ["g1f3", 800, 130, 720]],
  "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b": [["c7c5", 2100, 250, 2000], ["e7e5", 1900, 300, 1800], ["e7e6", 700, 90, 650], ["c7c6", 600, 80, 560]],
};

export function mockPopular(fen: string, signedIn: boolean): PopularReplies {
  if (!signedIn) return { state: "signed_out", total: 0, moves: [] };
  const rows = POPULAR[fen.split(" ").slice(0, 2).join(" ")] ?? [];
  const c = new Chess(fen);
  const moves = rows.map(([uci, white, draws, black]) => {
    const m = new Chess(c.fen()).move({ from: uci.slice(0, 2), to: uci.slice(2, 4) });
    return { uci, san: m.san, games: white + draws + black, white, draws, black };
  });
  return { state: "ok", total: moves.reduce((s, m) => s + m.games, 0), moves };
}
