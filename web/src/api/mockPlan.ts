// v0.12: the training plan and the journal in the mock client (REQUIREMENTS §10.12). Fixed, deterministic data for
// UI work, Playwright and the user-guide screenshots. Today is always 2026-11-05, a Thursday. `?plan=current` starts
// with a plan; `?journal=some` with a few entries. The checklist's rules match the backend's: a hand choice wins.
import { ApiCallError, type JournalEntryInput, type JournalFilters, type PlanParams } from "./ApiClient";
import type {
  CoachLesson,
  DayLog,
  JournalEntry,
  JournalItem,
  JournalTimeline,
  PlanDay,
  PlanPreview,
  PlanPreviewDay,
  PlanPreviewTask,
  PlanSettings,
  PlanTask,
  PlanTaskAction,
  SessionInfo,
  TodayPlan,
  TrainingPlan,
} from "./types";

const TODAY = "2026-11-05";
const bad = (message: string) => new ApiCallError({ code: "invalid_argument", message, retryable: false });
const conflict = (message: string) => new ApiCallError({ code: "conflict", message, retryable: false });

interface Hooks {
  calls: string[];
  hasReport: () => boolean;
  startSession: (spec: Record<string, unknown>, rated: boolean, mode: string) => Promise<SessionInfo>;
}

interface StoredTask extends PlanTask {
  params: Record<string, unknown>;
  day: number;
}

const iso = (d: Date) => d.toISOString().slice(0, 10);

function dates(weeks: number, weekdays: number[]): string[] {
  const out: string[] = [];
  let start = new Date(`${TODAY}T12:00:00Z`);
  while (!weekdays.includes((start.getUTCDay() + 6) % 7)) start = new Date(start.getTime() + 86400000);
  for (let i = 0; i < weeks * 7; i++) {
    const d = new Date(start.getTime() + i * 86400000);
    if (weekdays.includes((d.getUTCDay() + 6) % 7)) out.push(iso(d));
  }
  return out;
}

const TEMPLATE: (Omit<PlanPreviewTask, "minutes"> & { params: Record<string, unknown> })[] = [
  { type: "puzzles", title: "12 Danger-spotting puzzles: Fork", weakness_key: "allowed:fork", params: { themes: ["fork"], mode: "danger_spotting", count: 12 } },
  { type: "retry", title: "Retry your mistakes in your game against opponent_b (2026-10-27)", weakness_key: "allowed:fork", params: { game_id: 1 } },
  { type: "review", title: "Review your game against opponent_b (2026-10-27) with best moves hidden", weakness_key: "missed:pin", params: { game_id: 1 } },
  { type: "game_puzzles", title: "8 puzzles from your games: blunders and mistakes", weakness_key: "missed:pin", params: { severities: ["blunder", "mistake"], count: 8 } },
  { type: "lesson", title: "Lesson: Fork", weakness_key: "allowed:fork", params: { topic: "theme:fork" } },
  { type: "reflection", title: "Reflection: How is this going: Allowed: Fork?", weakness_key: "allowed:fork", params: { prompt: "How is this going: Allowed: Fork?" } },
];

export class MockPlan {
  private settings: PlanSettings;
  private plans: { plan: Omit<TrainingPlan, "done" | "skipped" | "left" | "minutes_spent" | "days" | "today">; tasks: StoredTask[]; days: { id: number; week: number; position: number; date: string }[] }[] = [];
  private nextId = 1;
  private entries: JournalEntry[] = [];
  private nextEntry = 1;
  private readonly reviewed = new Set<number>();

  constructor(
    params: URLSearchParams,
    private readonly h: Hooks,
  ) {
    this.settings = { weeks: 2, weekdays: [0, 1, 2, 3, 4], minutes: 20, carry_over: true, has_report: false };
    if (params.get("plan") === "current") this.store(this.params(), "deterministic");
    if (params.get("journal") === "some") {
      this.add({ text: "I keep missing forks when I'm short of time.", weakness_key: "allowed:fork" });
      this.add({ text: "The knight on e5 was the whole game. I saw it one move too late.", game_id: 1, ply: 6 });
    }
  }

  private params(): PlanParams {
    return { weeks: this.settings.weeks, weekdays: this.settings.weekdays, minutes: this.settings.minutes };
  }

  getSettings(): PlanSettings {
    return { ...this.settings, has_report: this.h.hasReport() };
  }

  setSetting(key: string, value: unknown) {
    if (key === "plan.carry_over") this.settings = { ...this.settings, carry_over: value as boolean };
    if (key === "plan.params") this.settings = { ...this.settings, ...(value as PlanParams) };
  }

  private check(p: PlanParams) {
    if (!Number.isInteger(p.weeks) || p.weeks < 1 || p.weeks > 4) throw bad("A plan lasts 1–4 weeks.");
    if (!Number.isInteger(p.minutes) || p.minutes < 10 || p.minutes > 120) throw bad("Minutes per day must be 10–120.");
    if (!p.weekdays.length) throw bad("Pick at least one training day.");
  }

  private draftDays(p: PlanParams, withDates: boolean): PlanPreviewDay[] {
    const when = dates(p.weeks, p.weekdays);
    const per = p.minutes < 25 ? 2 : p.minutes < 50 ? 3 : 4;
    return when.map((date, i) => ({
      week: Math.floor(i / p.weekdays.length) + 1,
      position: i + 1,
      date: withDates ? date : null,
      tasks: Array.from({ length: per }, (_, n) => {
        const t = TEMPLATE[(i * per + n) % TEMPLATE.length];
        const minutes = Math.floor(p.minutes / per) + (n < p.minutes % per ? 1 : 0);
        return { type: t.type, title: t.title, weakness_key: t.weakness_key, minutes };
      }),
    }));
  }

  preview(params: PlanParams | null): PlanPreview {
    const p = params ?? this.params();
    this.check(p);
    if (!this.h.hasReport() && !this.plans.length) throw bad("Run the Coach first: a plan is built from your latest report.");
    const when = dates(p.weeks, p.weekdays);
    return { weeks: p.weeks, weekdays: [...p.weekdays], minutes: p.minutes, start_date: when[0], replaces: this.current() !== null, days: this.draftDays(p, true) };
  }

  aiPlan(): PlanPreview {
    const p = this.params();
    const days = this.draftDays(p, false).map((d, i) =>
      i === 0 ? { ...d, tasks: [{ type: "puzzles" as const, title: "10 puzzles: Fork, Pin", minutes: d.tasks[0].minutes, weakness_key: "allowed:fork" }, ...d.tasks.slice(1)] } : d,
    );
    return { weeks: p.weeks, weekdays: [...p.weekdays], minutes: p.minutes, start_date: null, replaces: this.current() !== null, days };
  }

  private store(p: PlanParams, source: "deterministic" | "ai") {
    for (const x of this.plans) {
      if (x.plan.status === "current") x.plan = { ...x.plan, status: "replaced", ended_at: `${TODAY}T10:00:00+00:00` };
    }
    const id = this.plans.length + 1;
    const days: { id: number; week: number; position: number; date: string }[] = [];
    const tasks: StoredTask[] = [];
    for (const d of this.draftDays(p, true)) {
      const dayId = id * 1000 + d.position;
      days.push({ id: dayId, week: d.week, position: d.position, date: d.date ?? TODAY });
      d.tasks.forEach((t) => {
        const template = TEMPLATE.find((x) => x.title === t.title);
        const params = template?.params ?? { themes: ["fork", "pin"], mode: "standard", count: 10 };
        const count = typeof params.count === "number" ? params.count : null;
        tasks.push({
          ...t, id: this.nextId++, status: "left", auto: false, manual: null, progress: count !== null ? 0 : null, count,
          minutes_spent: 0, carried: false, params, day: dayId,
        }); // prettier-ignore
      });
    }
    this.plans.push({
      plan: { id, created_at: `${TODAY}T10:00:00+00:00`, source, status: "current", weeks: p.weeks, weekdays: [...p.weekdays], minutes_per_day: p.minutes, start_date: dates(p.weeks, p.weekdays)[0], ended_at: null },
      tasks,
      days,
    });
  }

  private currentRow() {
    return this.plans.find((x) => x.plan.status === "current") ?? null;
  }

  private statusOf(t: StoredTask, date: string): PlanTask["status"] {
    if (t.manual === "done" || (t.manual !== "undone" && t.auto)) return "done";
    if (t.status === "skipped") return "skipped";
    return date < TODAY ? "missed" : "left";
  }

  private view(row: NonNullable<ReturnType<MockPlan["currentRow"]>>): TrainingPlan {
    const days: PlanDay[] = row.days.map((d) => ({
      id: d.id, week: d.week, position: d.position, date: d.date, is_today: d.date === TODAY,
      tasks: row.tasks.filter((t) => t.day === d.id).map((t) => {
        const status = this.statusOf(t, d.date);
        return {
          id: t.id, type: t.type, title: t.title, weakness_key: t.weakness_key, minutes: t.minutes, status, auto: t.auto,
          manual: t.manual, progress: t.progress, count: t.count, minutes_spent: status === "done" ? t.minutes : 0, carried: t.carried,
        }; // prettier-ignore
      }),
    })); // prettier-ignore
    const all = days.flatMap((d) => d.tasks);
    return {
      ...row.plan, done: all.filter((t) => t.status === "done").length, skipped: all.filter((t) => t.status === "skipped").length,
      left: all.filter((t) => t.status === "left").length, minutes_spent: all.reduce((a, t) => a + t.minutes_spent, 0), today: TODAY, days,
    }; // prettier-ignore
  }

  current(): TrainingPlan | null {
    const row = this.currentRow();
    return row ? this.view(row) : null;
  }

  today(): TodayPlan | null {
    const v = this.current();
    if (!v) return null;
    const day = v.days.find((d) => d.date === TODAY) ?? null;
    const later = v.days.filter((d) => d.date > TODAY);
    return { plan_id: v.id, today: TODAY, day, next_date: later[0]?.date ?? null, finished: !day && !later.length };
  }

  history(): TrainingPlan[] {
    return [...this.plans].reverse().map((p) => this.view(p));
  }

  create(p: PlanParams, confirmed: boolean): TrainingPlan {
    this.check(p);
    if (!this.h.hasReport() && !this.plans.length) throw bad("Run the Coach first: a plan is built from your latest report.");
    if (this.current() && !confirmed) throw conflict("Confirm first: this replaces your current plan.");
    this.settings = { ...this.settings, ...p };
    this.store(p, "deterministic");
    this.h.calls.push(`createPlan:${p.weeks}:${p.weekdays.join("")}:${p.minutes}`);
    return this.current()!;
  }

  useAi(runId: number, confirmed: boolean): TrainingPlan {
    if (this.current() && !confirmed) throw conflict("Confirm first: this replaces your current plan.");
    this.store(this.params(), "ai");
    this.h.calls.push(`useAiPlan:${runId}`);
    return this.current()!;
  }

  private task(id: number): StoredTask {
    const row = this.currentRow();
    const t = row?.tasks.find((x) => x.id === id);
    if (!t) throw new ApiCallError({ code: "not_found", message: "That task isn't in your plan.", retryable: false });
    return t;
  }

  tick(id: number, done: boolean) {
    const t = this.task(id);
    t.manual = done ? "done" : "undone";
    if (t.status === "skipped") t.status = "left";
    this.h.calls.push(`tick:${id}:${done}`);
  }

  skip(id: number, skipped: boolean) {
    this.task(id).status = skipped ? "skipped" : "left";
    this.h.calls.push(`skip:${id}:${skipped}`);
  }

  swap(id: number): number {
    const t = this.task(id);
    t.title = `Lesson: Pin (swapped from task ${id})`;
    t.type = "lesson";
    t.params = { topic: "theme:pin" };
    t.count = null;
    t.progress = null;
    t.manual = null;
    t.auto = false;
    t.status = "left";
    this.h.calls.push(`swap:${id}`);
    return id;
  }

  private lesson(topic: string): CoachLesson {
    return { topic, label: topic.replace("theme:", ""), drill: null, curated: ["Lichess Practice: The Fork"], sites: ["youtube", "chesscom"] };
  }

  async start(id: number, rated: boolean): Promise<PlanTaskAction> {
    const t = this.task(id);
    this.h.calls.push(`startTask:${id}:${t.type}`);
    const base: PlanTaskAction = {
      kind: "session", task_id: id, session: null, remaining: null, mode: null, game_id: null, lesson: null, prompt: null,
      weakness_key: t.weakness_key, plan_day_id: t.day,
    }; // prettier-ignore
    if (t.type === "puzzles" || t.type === "game_puzzles") {
      const left = Math.max(1, (t.count ?? 1) - (t.progress ?? 0));
      const mode = String(t.params.mode ?? "standard");
      const session = await this.h.startSession(
        t.type === "game_puzzles"
          ? { source: "my", my_severities: t.params.severities, queue_size: left }
          : { themes: t.params.themes ?? [], queue_size: left },
        rated,
        mode,
      );
      return { ...base, session, remaining: left, mode };
    }
    if (t.type === "retry" || t.type === "review") return { ...base, kind: t.type, game_id: Number(t.params.game_id) };
    if (t.type === "lesson") return { ...base, kind: "lesson", lesson: this.lesson(String(t.params.topic)) };
    return { ...base, kind: "reflection", prompt: String(t.params.prompt ?? "") };
  }

  openLesson(id: number, target: string) {
    const t = this.task(id);
    if (!/^(curated:\d+|youtube|chesscom|custom)$/.test(target)) throw bad("Unknown lesson link.");
    t.auto = true;
    this.h.calls.push(`openPlanLesson:${id}:${target}`);
  }

  /** The app saw progress on a task: the tests' way of playing puzzles (`window.__mockPlanProgress`). */
  progress(id: number, n: number) {
    const t = this.task(id);
    t.progress = (t.progress ?? 0) + n;
    if (t.count !== null && t.progress >= t.count) t.auto = true;
  }

  retried(gameId: number) {
    for (const t of this.currentRow()?.tasks ?? []) {
      if (t.type === "retry" && t.params.game_id === gameId) t.auto = true;
    }
  }

  markPly(gameId: number, ply: number): boolean {
    this.h.calls.push(`markPly:${gameId}:${ply}`);
    if (this.reviewed.has(gameId) || ply < 8) return false; // the mock's game ends at ply 8 or later
    this.reviewed.add(gameId);
    for (const t of this.currentRow()?.tasks ?? []) {
      if (t.type === "review" && t.params.game_id === gameId) t.auto = true;
    }
    return true;
  }

  // ---- the journal ------------------------------------------------------------------------------
  add(e: JournalEntryInput): JournalEntry {
    const text = (e.text ?? "").trim();
    if (!text) throw bad("Write something first.");
    if (text.length > 5000) throw bad("An entry can be at most 5,000 characters.");
    const entry: JournalEntry = {
      id: this.nextEntry++, created_at: `${TODAY}T10:00:00+00:00`, updated_at: `${TODAY}T10:00:00+00:00`, entry_date: e.entry_date ?? TODAY,
      kind: e.game_id ? "reflection" : "note", text, game_id: e.game_id ?? null, ply: e.ply ?? null,
      move: e.ply !== undefined && e.ply !== null ? "4. Nxe5" : null, game_label: e.game_id ? "player_a – opponent_b" : null,
      weakness_key: e.weakness_key ?? null, plan_day_id: e.plan_day_id ?? null, plan_task_id: e.plan_task_id ?? null,
    }; // prettier-ignore
    this.entries.push(entry);
    this.h.calls.push(`journalAdd:${entry.kind}`);
    if (e.plan_task_id) {
      const t = this.currentRow()?.tasks.find((x) => x.id === e.plan_task_id);
      if (t) t.auto = true;
    }
    return entry;
  }

  edit(id: number, text: string, weakness: string | null): JournalEntry {
    const e = this.entries.find((x) => x.id === id);
    if (!e) throw new ApiCallError({ code: "not_found", message: "That entry isn't in your journal.", retryable: false });
    if (!text.trim()) throw bad("Write something first.");
    e.text = text.trim();
    e.weakness_key = weakness;
    return e;
  }

  remove(id: number) {
    this.entries = this.entries.filter((x) => x.id !== id);
  }

  gameNotes(gameId: number): JournalEntry[] {
    return this.entries.filter((e) => e.game_id === gameId);
  }

  private log(): DayLog {
    const tally = (key: string, label: string, attempts: number, solved: number) => ({ key, label, attempts, solved, accuracy: attempts ? solved / attempts : null });
    return {
      date: "2026-11-04", overall: tally("all", "All puzzles", 20, 14), by_mode: [tally("standard", "Standard", 12, 9), tally("danger_spotting", "Danger spotting", 8, 5)],
      by_source: [tally("lichess", "Lichess puzzles", 16, 11), tally("my", "My puzzles", 4, 3)], missed_themes: ["Fork", "Pin"], misclicks: 1,
      games_synced: 3, games_analyzed: 3, games_reviewed: 1, retries: 4, retries_found: 2, plan_tasks_done: 2, coach_runs: ["Allowed: Fork"],
    }; // prettier-ignore
  }

  timeline(f: JournalFilters): JournalTimeline {
    const q = f.query?.trim().toLowerCase();
    const kinds = f.kinds?.length ? f.kinds : ["note", "reflection", "log"];
    const entries = this.entries.filter(
      (e) =>
        kinds.includes(e.kind) &&
        (!q || e.text.toLowerCase().includes(q)) &&
        (!f.weakness_key || e.weakness_key === f.weakness_key) &&
        (!f.game_id || e.game_id === f.game_id),
    );
    const items: JournalItem[] = [...entries].reverse().map((entry) => ({ date: entry.entry_date, entry, log: null }));
    if (kinds.includes("log") && !q && !f.weakness_key && !f.game_id) items.push({ date: "2026-11-04", entry: null, log: this.log() });
    const games = this.entries.filter((e) => e.game_id !== null).map((e) => ({ id: e.game_id as number, label: e.game_label ?? "" }));
    return { items, window_start: "2026-10-07", older: !f.before && !q && !f.weakness_key && !f.game_id, games: games.filter((g, i) => games.findIndex((x) => x.id === g.id) === i) };
  }
}
