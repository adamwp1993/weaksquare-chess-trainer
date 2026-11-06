// v0.13: the opening trainer in the mock client (REQUIREMENTS §18). A small fixed book for UI work, Playwright and the
// user-guide screenshots. `?openings=ready` starts with the book imported. Its rules match the backend's: moves are
// edges between positions, so a removal keeps what another line still reaches.
import { Chess } from "chess.js";
import { ApiCallError } from "./ApiClient";
import type {
  BookFamily,
  OpeningLine,
  OpeningLines,
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
    return { scope: { ...this.scope }, extend: this.extend };
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
    return { name, eco, moves: moves.slice(0, limit).map(({ uci, san, source }) => ({ uci, san, source })) };
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
