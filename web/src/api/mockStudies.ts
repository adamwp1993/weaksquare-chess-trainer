// v0.14: Lichess studies for the mock client (UI development, Playwright, screenshots). Invented studies only: no real
// study text, IDs or usernames (SR-12a). Mirrors services/studies.py closely enough for the UI tests: the same
// checks on links, IDs and usernames, the same errors, and the same flattened move trees (bridge/api.py).
import { Chess } from "chess.js";
import { ApiCallError } from "./ApiClient";
import type {
  AuthorStudy,
  StarterStudy,
  StudyChapter,
  StudyChapterInfo,
  StudyDetail,
  StudyMove,
  StudyPlace,
  StudyRepertoirePreview,
  StudyShape,
  StudySummary,
  StudyUpdate,
} from "./types";

interface Node {
  san?: string;
  comment?: string;
  shapes?: StudyShape[];
  nags?: number[];
  children?: Node[];
}

interface MockChapter {
  key: string;
  title: string;
  mode: "normal" | "gamebook";
  orientation: "white" | "black";
  startFen: string;
  textOnly?: boolean;
  rejected?: string;
  root: Node;
}

interface MockStudy {
  id: string;
  title: string;
  author: string;
  isPrivate: boolean;
  hearted: boolean;
  addedAt: string;
  updatedAt: string;
  checkedAt: string | null;
  chapters: MockChapter[];
  place: { key: string; path: string[] } | null;
  done: Set<string>;
}

const START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
const ID = /^[A-Za-z0-9]{8}$/;
const USER = /^[A-Za-z0-9][A-Za-z0-9_-]{0,28}[A-Za-z0-9]$/;

// A line of moves, each with an optional comment: a short way to write a main line.
function line(...items: (string | [string, string] | [string, string, StudyShape[]])[]): Node {
  const root: Node = {};
  let at = root;
  for (const it of items) {
    const [san, comment, shapes] = typeof it === "string" ? [it, undefined, undefined] : it;
    const n: Node = { san, comment, shapes };
    at.children = [n];
    at = n;
  }
  return root;
}

function gamebookStudy(): MockStudy {
  const welcome = line("e4", ["c6", "Prepare d5.", [{ orig: "d7", dest: "d5", color: "green" }]], "d4", ["d5", "Now the centre is contested."]);
  welcome.comment = "Play the moves for Black.";
  welcome.shapes = [{ orig: "e5", dest: null, color: "green" }];
  welcome.children![0].comment = "White takes the centre.";
  welcome.children![0].children!.push({ san: "e5", comment: "That's a different opening. Try again." });
  const plan = line("e4", "c6", "d4", "d5", ["e5", "The pawn chain."], ["Bf5", "Develop the bishop outside the chain first.", [{ orig: "c8", dest: "f5", color: "green" }]]);
  return {
    id: "TestGb01",
    title: "Invented gamebook",
    author: "player_author",
    isPrivate: false,
    hearted: true,
    addedAt: "2026-11-06T18:00:00+00:00",
    updatedAt: "2026-11-06T18:00:00+00:00",
    checkedAt: null,
    chapters: [
      { key: "Chap0001", title: "Welcome", mode: "gamebook", orientation: "black", startFen: START, root: welcome },
      { key: "Chap0002", title: "The plan", mode: "gamebook", orientation: "black", startFen: START, root: plan },
    ],
    place: { key: "Chap0002", path: ["e2e4", "c7c6"] },
    done: new Set(["Chap0001"]),
  };
}

function analysisStudy(): MockStudy {
  const main = line("e4", "e5", ["Nc3", "The quiet move.", [{ orig: "c3", dest: "d5", color: "green" }, { orig: "f1", dest: "c4", color: "blue" }]], "Nf6", "f4", "d5", "fxe5", "Nxe4");
  main.comment = "An invented chapter with side lines. See https://example.com/notes for more.";
  main.shapes = [{ orig: "e5", dest: null, color: "red" }];
  const nc3 = main.children![0].children![0].children![0];
  const nc6: Node = { san: "Nc6", children: [{ san: "f4", comment: "The gambit.", children: [{ san: "exf4" }] }, { san: "Bc4", comment: "Calmer." }] };
  nc3.children!.push(nc6);
  nc3.children![0].children![0].nags = [1];
  return {
    id: "TestNm02",
    title: "Invented analysis",
    author: "player_author",
    isPrivate: false,
    hearted: false,
    addedAt: "2026-11-07T09:00:00+00:00",
    updatedAt: "2026-11-07T09:00:00+00:00",
    checkedAt: null,
    chapters: [
      { key: "Chap0001", title: "Main line", mode: "normal", orientation: "white", startFen: START, root: main },
      { key: "Chap0002", title: "Broken", mode: "normal", orientation: "white", startFen: START, rejected: "has an illegal or unreadable move (illegal san: 'Ke3')", root: {} },
      { key: "Chap0003", title: "Thanks", mode: "normal", orientation: "white", startFen: "8/8/8/8/8/8/8/8 w - - 0 1", textOnly: true, root: { comment: "Thanks for studying! This board is empty on purpose." } },
    ],
    place: null,
    done: new Set(),
  };
}

const AVAILABLE: Record<string, () => MockStudy> = { TestGb01: gamebookStudy, TestNm02: analysisStudy };

const STARTER: { study_id: string; title: string; author: string; opening: string }[] = [
  { study_id: "TestGb01", title: "Invented gamebook", author: "player_author", opening: "Caro-Kann Defence" },
  { study_id: "TestNm02", title: "Invented analysis", author: "player_author", opening: "Vienna Game" },
  { study_id: "TestSt03", title: "Invented starter study", author: "player_other", opening: "Italian Game" },
];

function fail(code: string, message: string, retryable = false): never {
  throw new ApiCallError({ code, message, retryable });
}

function parseRef(text: string): { id: string; chapter: string | null } | null {
  const s = text.trim();
  if (ID.test(s)) return { id: s, chapter: null };
  const m = /^(?:https:\/\/)?(?:www\.)?lichess\.org\/study\/([A-Za-z0-9]{8})(?:\/([A-Za-z0-9]{8}))?\/?(?:[?#].*)?$/i.exec(s);
  return m ? { id: m[1], chapter: m[2] ?? null } : null;
}

function cleanUser(text: string): string | null {
  let s = text.trim();
  for (const p of ["https://lichess.org/@/", "lichess.org/@/", "@"]) {
    if (s.toLowerCase().startsWith(p)) {
      s = s.slice(p.length).replace(/\/+$/, "");
      break;
    }
  }
  return USER.test(s) ? s : null;
}

function count(n: Node): number {
  return 1 + (n.children ?? []).reduce((a, c) => a + count(c), 0);
}

export type AddOutcome =
  | { ok: true; studyId: string; chapterKey: string | null; already: boolean; message: string }
  | { ok: false; code: string; message: string };

export class MockStudies {
  private studies = new Map<string, MockStudy>([["TestGb01", gamebookStudy()]]);
  private pending = new Map<string, { title: string; update: StudyUpdate }>();

  // ---- adding ---------------------------------------------------------------------------------------------------
  parse(text: string): { id: string; chapter: string | null } {
    const ref = parseRef(text);
    if (!ref) fail("not_a_study", "That isn't a Lichess study link. Paste an address like https://lichess.org/study/AbCd1234, or just its 8-character ID.");
    return ref;
  }

  checkIds(studyId: string, chapterId: string | null) {
    if (!ID.test(studyId) || (chapterId !== null && !ID.test(chapterId))) fail("not_a_study", "That isn't a Lichess study ID.");
  }

  add(id: string, chapter: string | null): AddOutcome {
    const existing = this.studies.get(id);
    const chapterKey = (s: MockStudy) => (chapter && s.chapters.some((c) => c.key === chapter && !c.rejected) ? chapter : null);
    if (existing) return { ok: true, studyId: id, chapterKey: chapterKey(existing), already: true, message: "Already in My studies" };
    if (id === "TestPr03") return { ok: false, code: "study_scope", message: "This study is private. Sign in again to allow reading your private studies: your current sign-in is from before WeakSquare could read studies." };
    const make = AVAILABLE[id];
    if (!make) return { ok: false, code: "study_not_found", message: "Lichess has no study with that ID. It may have been deleted." };
    const s = make();
    s.hearted = false;
    s.place = null;
    s.done = new Set();
    this.studies.set(id, s);
    const rejected = s.chapters.filter((c) => c.rejected).length;
    const n = s.chapters.length;
    return {
      ok: true, studyId: id, chapterKey: chapterKey(s), already: false,
      message: `Added “${s.title}” (${n} chapter${n === 1 ? "" : "s"})${rejected ? `; ${rejected} couldn't be used` : ""}`,
    }; // prettier-ignore
  }

  byAuthor(text: string): AuthorStudy[] {
    const name = cleanUser(text);
    if (!name) fail("bad_username", "That isn't a Lichess username.");
    if (name !== "player_author") fail("user_not_found", `Lichess has no user called ${name}.`);
    return [
      { study_id: "TestGb01", name: "Invented gamebook", updated_ms: 1730500000000, saved: this.studies.has("TestGb01") },
      { study_id: "TestNm02", name: "Invented analysis", updated_ms: 1730600000000, saved: this.studies.has("TestNm02") },
    ];
  }

  starter(): StarterStudy[] {
    return STARTER.map((e) => ({ ...e, url: `https://lichess.org/study/${e.study_id}`, saved: this.studies.has(e.study_id) }));
  }

  // ---- My studies -------------------------------------------------------------------------------------------------
  private get(id: string): MockStudy {
    const s = this.studies.get(id);
    if (!s) fail("study_not_found", "That study isn't in My studies.");
    return s;
  }

  private summary(s: MockStudy): StudySummary {
    const playable = s.chapters.filter((c) => !c.rejected);
    const done = playable.filter((c) => s.done.has(c.key)).length;
    const status = playable.length && done >= playable.length ? "finished" : s.place || done ? "in_progress" : "new";
    return {
      id: s.id, title: s.title, author: s.author, url: `https://lichess.org/study/${s.id}`, hearted: s.hearted,
      private: s.isPrivate, chapters: s.chapters.length, playable: playable.length, done, status,
      place_chapter_key: s.place?.key ?? null, place_chapter_title: s.chapters.find((c) => c.key === s.place?.key)?.title ?? null,
      added_at: s.addedAt, updated_at: s.updatedAt, checked_at: s.checkedAt,
    }; // prettier-ignore
  }

  list(which: "all" | "favorites" | "in_progress" | "finished"): StudySummary[] {
    const all = [...this.studies.values()].map((s) => this.summary(s));
    if (which === "favorites") return all.filter((s) => s.hearted);
    if (which === "in_progress") return all.filter((s) => s.status === "in_progress");
    if (which === "finished") return all.filter((s) => s.status === "finished");
    return all;
  }

  private info(s: MockStudy, c: MockChapter, index: number): StudyChapterInfo {
    return {
      key: c.key, index, title: c.title, mode: c.mode, orientation: c.orientation, text_only: !!c.textOnly,
      rejected: c.rejected ?? null, move_count: count(c.root) - 1, done: s.done.has(c.key),
    }; // prettier-ignore
  }

  detail(id: string): StudyDetail {
    const s = this.get(id);
    return { summary: this.summary(s), chapters: s.chapters.map((c, i) => this.info(s, c, i)) };
  }

  chapter(id: string, key: string): StudyChapter {
    const s = this.get(id);
    const index = s.chapters.findIndex((c) => c.key === key);
    if (index < 0) fail("chapter_not_found", "That chapter isn't in this study any more.");
    const c = s.chapters[index];
    if (c.rejected) fail("chapter_rejected", `This chapter ${c.rejected}.`);
    const moves: StudyMove[] = [];
    const visit = (n: Node, parent: number | null, chess: Chess | null, ply: number, uci: string | null) => {
      const id = moves.length;
      moves.push({
        id, parent, san: n.san ?? null, uci, fen: chess ? chess.fen() : c.startFen, ply, comment: n.comment ?? "",
        shapes: n.shapes ?? [], nags: n.nags ?? [], children: [],
      }); // prettier-ignore
      const kids: number[] = [];
      for (const child of n.children ?? []) {
        if (!chess) break;
        const next = new Chess(chess.fen());
        const m = next.move(child.san!);
        kids.push(visit(child, id, next, ply + 1, m.from + m.to + (m.promotion ?? "")));
      }
      moves[id] = { ...moves[id], children: kids };
      return id;
    };
    let start: Chess | null;
    try {
      start = c.textOnly ? null : new Chess(c.startFen);
    } catch {
      start = null;
    }
    visit(c.root, null, start, 0, null);
    return { study_id: id, info: this.info(s, c, index), start_fen: c.startFen, moves };
  }

  setPlace(id: string, key: string, path: string[]) {
    const s = this.get(id);
    this.chapter(id, key); // checks the chapter
    s.place = { key, path: [...path] };
  }

  continueTarget(id: string): StudyPlace {
    const s = this.get(id);
    const usable = s.chapters.filter((c) => !c.rejected);
    if (s.place && usable.some((c) => c.key === s.place!.key)) return { chapter_key: s.place.key, path: s.place.path };
    const next = usable.find((c) => !s.done.has(c.key)) ?? usable[0];
    return { chapter_key: next.key, path: [] };
  }

  setDone(id: string, key: string, done: boolean) {
    const s = this.get(id);
    if (done) s.done.add(key);
    else s.done.delete(key);
  }

  restart(id: string) {
    const s = this.get(id);
    s.place = null;
    s.done.clear();
  }

  heart(id: string, hearted: boolean) {
    this.get(id).hearted = hearted;
  }

  remove(id: string) {
    this.get(id);
    this.studies.delete(id);
    this.pending.delete(id);
  }

  // ---- Add to my repertoire (FR-13.11) ----------------------------------------------------------------------------
  /** The mock repertoire plays 2. Nf3 as White after 1. e4 e5, so the Vienna chapter conflicts there. */
  private preview: StudyRepertoirePreview | null = null;

  repertoirePreview(id: string, key: string | null, color: "white" | "black", sideLines: boolean): StudyRepertoirePreview {
    const s = this.get(id);
    const picked = s.chapters.filter((c) => key === null || c.key === key);
    const used = picked.filter((c) => !c.rejected && !c.textOnly);
    const skipped = picked.filter((c) => c.rejected || c.textOnly).map((c) => `${c.title} (${c.rejected ? `it ${c.rejected}` : "no moves"})`);
    let yours = 0;
    let theirs = 0;
    for (const c of used) {
      const walk = (n: Node, ply: number) => {
        const kids = sideLines ? (n.children ?? []) : (n.children ?? []).slice(0, 1);
        for (const k of kids) {
          if ((ply % 2 === 0) === (color === "white")) yours += 1;
          else theirs += 1;
          walk(k, ply + 1);
        }
      };
      walk(c.root, 0);
    }
    const vienna = color === "white" && used.some((c) => c.key === "Chap0001" && s.id === "TestNm02");
    const conflicts = vienna ? [{ position_key: "pos-after-e4-e5", path: ["e4", "e5"], yours: ["Nf3"], study: ["Nc3"] }] : [];
    this.preview = {
      id: "study-rep-1", color, side_lines: sideLines, chapters: used.map((c) => c.title), skipped,
      yours, theirs, already: vienna ? 1 : 0, unreachable: 0, conflicts,
    }; // prettier-ignore
    return this.preview;
  }

  /** The added moves, for the mock repertoire: the Vienna chapter's main line (or nothing past the conflict). */
  repertoireSave(previewId: string, choices: Record<string, "mine" | "study">): { added: number; kept: number; color: "white" | "black"; ucis: string[] } {
    const p = this.preview;
    if (!p || p.id !== previewId) fail("no_preview", "That preview has expired. Open Add to my repertoire again.");
    this.preview = null;
    const keepMine = p.conflicts.some((c) => choices[c.position_key] !== "study");
    const ucis = keepMine ? ["e2e4", "e7e5"] : ["e2e4", "e7e5", "b1c3", "g8f6", "f2f4", "d7d5", "f4e5", "f6e4"];
    return { added: keepMine ? Math.max(0, p.yours + p.theirs - 6) : p.yours + p.theirs, kept: p.already, color: p.color, ucis };
  }

  discardRepertoirePreview() {
    this.preview = null;
  }

  // ---- Check for updates ----------------------------------------------------------------------------------------
  /** The mock author has edited TestGb01 (one changed chapter); every other study is up to date. */
  check(id: string): string {
    const s = this.get(id);
    s.checkedAt = "2026-11-07T12:00:00+00:00";
    if (id !== "TestGb01") return "No changes: your copy is up to date";
    this.pending.set(id, {
      title: s.title,
      update: { study_id: id, new_title: s.title, title_changed: false, added: [], removed: [], changed: ["The plan"], unchanged: 1 },
    });
    return "Changes found: review them before updating";
  }

  update(id: string): StudyUpdate | null {
    return this.pending.get(id)?.update ?? null;
  }

  apply(id: string) {
    const p = this.pending.get(id);
    if (!p) fail("no_update", "Check for updates first.");
    const s = this.get(id);
    const plan = s.chapters.find((c) => c.key === "Chap0002");
    if (plan) plan.root.comment = "Updated by the author.";
    s.updatedAt = "2026-11-07T12:00:00+00:00";
    this.pending.delete(id);
  }

  discard(id: string) {
    this.pending.delete(id);
  }
}
