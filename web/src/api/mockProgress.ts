// v1.0 (REQUIREMENTS §10.8): checkpoints and the Progress tab in the mock client. `?progress=history` starts with
// four reconstructed checkpoints (the backfill) and two live ones, one weakness of each status and a "not enough
// data yet" point; without it there are no checkpoints yet (the empty state).
import { ApiCallError } from "./ApiClient";
import type {
  CheckpointRow,
  Job,
  CheckpointSettings,
  ProgressPoint,
  ProgressView,
  StatusChange,
  StatusNotice,
  WeaknessCard,
} from "./types";

interface Hooks {
  emit: (job: Job) => void;
  jobId: () => string;
  calls: string[];
  /** A normal Coach report for a live checkpoint; returns its id. */
  report: (n: number, created: string) => number;
}

const bad = (message: string) => new ApiCallError({ code: "invalid_argument", message, retryable: false });

export const DEFAULT_CHECKPOINT_SETTINGS: CheckpointSettings = {
  every_games: 10,
  window: 30,
  schedule: { kind: "off", days: 7, weekday: 6 },
  rated_only: true,
  time_classes: ["rapid", "classical"],
  color: "both",
  thresholds: { improving: 0.75, fixed: 0.5, regressed: 0.9, fixed_streak: 2, puzzle_accuracy: 0.75, puzzle_attempts: 20, guard_count: 5 },
  auto_ai: true,
  notices: true,
};

const DATES = [
  "2026-08-02T18:00:00+00:00", "2026-08-21T19:30:00+00:00", "2026-09-09T17:45:00+00:00", "2026-09-28T20:10:00+00:00",
  "2026-10-20T09:00:00+00:00", "2026-11-03T09:00:00+00:00",
]; // prettier-ignore
const BLUNDERS = [4.0, 3.7, 3.3, 3.0, 2.7, 2.3];
const MISTAKES = [6.0, 6.3, 5.7, 5.3, 5.0, 4.7];
const INACCURACIES = [9.0, 8.7, 8.3, 8.7, 8.0, 7.7];
const ACPL = [62, 60, 57, 55, 52, 49];

function health(i: number): Record<string, unknown> {
  return {
    games: 30,
    per10: { blunders: BLUNDERS[i], mistakes: MISTAKES[i], inaccuracies: INACCURACIES[i] },
    acpl: ACPL[i],
    acpl_by_phase: { opening: 28 + i, middlegame: ACPL[i] + 8, endgame: ACPL[i] + 15 },
    habits: { hungPiece: [2.7, 2.0, 1.3, 1.0, 0.7, 0.7][i] },
    reasons: { process: 0.6, calculation: 0.25, knowledge: 0.1, time: 0.05 },
    results: { win: 14 + i, loss: 12 - i, draw: 4 },
    ratings: { lichess: 1610 + 12 * i, chesscom: 1450 + 9 * i },
  };
}

function points(per10: (number | null)[], accuracy: (number | null)[], guarded: number[] = []): ProgressPoint[] {
  return per10.flatMap((v, i) =>
    v === null ? [] : [{ checkpoint: i + 1, created_at: DATES[i], per10: v, puzzle_accuracy: accuracy[i], guarded: guarded.includes(i + 1), reconstructed: i < 4 }],
  ); // prettier-ignore
}

function seeded(): WeaknessCard[] {
  const last = (p: ProgressPoint[]) => p[p.length - 1];
  const card = (c: Omit<WeaknessCard, "current_per10" | "current_guarded" | "puzzle_accuracy" | "puzzle_themes">): WeaknessCard => ({
    ...c, current_per10: last(c.points).per10, current_guarded: last(c.points).guarded, puzzle_accuracy: last(c.points).puzzle_accuracy,
    puzzle_themes: c.kind !== "time", // nothing trains time use with puzzles
  }); // prettier-ignore
  return [
    card({
      key: "missed:pin", kind: "missed", label: "Missed: Pin", status: "regressed", status_since: 6, baseline_per10: 3.0,
      baseline_games: 50, puzzle_attempts: 31, reasons: { didntLook: 4, miscalculated: 1 },
      points: points([3.0, 2.0, 1.3, 1.0, 2.0, 3.0], [0.62, 0.66, 0.7, 0.71, 0.7, 0.68]), examples: [{ game_id: 1, ply: 23 }],
    }),
    card({
      key: "allowed:fork", kind: "allowed", label: "Allowed: Fork", status: "improving", status_since: 3, baseline_per10: 4.0,
      baseline_games: 50, puzzle_attempts: 58, reasons: { didntLook: 7, miscalculated: 2, rushed: 1 },
      points: points([4.0, 3.7, 3.3, 3.0, 2.7, 2.3], [0.64, 0.66, 0.69, 0.72, 0.74, 0.77]), examples: [{ game_id: 2, ply: 31 }, { game_id: 3, ply: 18 }],
    }),
    card({
      key: "missed:mateIn2", kind: "missed", label: "Missed: Mate in 2", status: "training", status_since: 5, baseline_per10: 2.3,
      baseline_games: 50, puzzle_attempts: 22, reasons: { miscalculated: 3 },
      points: points([2.3, 2.3, 2.7, 2.0, 2.3, 2.0], [0.55, 0.55, 0.56, 0.58, 0.6, 0.61]), examples: [],
    }),
    card({
      key: "time:low_clock", kind: "time", label: "Mistakes under 10% of your clock", status: "new", status_since: 5, baseline_per10: 1.3,
      baseline_games: 30, puzzle_attempts: 0, reasons: { rushed: 2 },
      points: points([null, null, null, null, 1.3, 1.0], [null, null, null, null, null, null], [6]), examples: [{ game_id: 4, ply: 71 }],
    }),
    card({
      key: "habit:hungPiece", kind: "habit", label: "Hung a piece", status: "fixed", status_since: 5, baseline_per10: 2.7,
      baseline_games: 50, puzzle_attempts: 44, reasons: { rushed: 2, didntLook: 1 },
      points: points([2.7, 2.0, 1.3, 1.0, 0.7, 0.7], [0.7, 0.72, 0.76, 0.79, 0.81, 0.82]), examples: [],
    }),
  ]; // prettier-ignore
}

const CHANGES: Record<number, StatusChange[]> = {
  3: [{ key: "allowed:fork", label: "Allowed: Fork", old: "new", new: "improving" }],
  5: [{ key: "habit:hungPiece", label: "Hung a piece", old: "improving", new: "fixed" }],
  6: [{ key: "missed:pin", label: "Missed: Pin", old: "improving", new: "regressed" }],
};

export class MockProgress {
  private settings: CheckpointSettings = structuredClone(DEFAULT_CHECKPOINT_SETTINGS);
  private cards: WeaknessCard[] = [];
  private checkpoints: CheckpointRow[] = [];
  private newGames = 0;
  private running: string | null = null;
  private notices: StatusNotice[] = [];

  constructor(
    params: URLSearchParams,
    private readonly h: Hooks,
  ) {
    if (params.get("progress") === "history") {
      this.cards = seeded();
      this.checkpoints = DATES.map((d, i) => ({
        number: i + 1, created_at: d, trigger: i < 4 ? "backfill" : i === 4 ? "count" : "manual",
        report_id: i < 4 ? null : h.report(i + 1, d), reconstructed: i < 4, games: 30, health: health(i),
        changes: CHANGES[i + 1] ?? [], ai_run_id: i === 5 ? 1 : null,
      })); // prettier-ignore
      this.newGames = 4;
      this.notices = (CHANGES[6] ?? []).map((change) => ({ checkpoint: 6, change }));
    }
  }

  view(): ProgressView {
    return structuredClone({
      settings: this.settings, new_games: this.newGames, running_job: this.running, weaknesses: this.cards, checkpoints: this.checkpoints,
    }); // prettier-ignore
  }

  getSettings(): CheckpointSettings {
    return structuredClone(this.settings);
  }

  setSettings(s: CheckpointSettings): CheckpointSettings {
    const whole = (v: number, lo: number, hi: number, what: string) => {
      if (!Number.isInteger(v) || v < lo || v > hi) throw bad(`${what} must be a whole number from ${lo} to ${hi}.`);
    };
    whole(s.every_games, 5, 200, "Games between checkpoints");
    whole(s.window, 10, 100, "The rolling window");
    whole(s.schedule.days, 1, 60, "The number of days");
    whole(s.thresholds.fixed_streak, 1, 5, "Checkpoints in a row");
    whole(s.thresholds.puzzle_attempts, 5, 200, "Puzzle attempts");
    const t = s.thresholds;
    if (!(t.fixed < t.improving && t.improving < t.regressed)) throw bad("The thresholds must go Fixed < Improving < Regressed.");
    if (s.time_classes.length === 0) throw bad("Choose at least one time control.");
    this.settings = structuredClone({ ...s, thresholds: { ...s.thresholds, guard_count: 5 } });
    this.h.calls.push(`checkpointSettings:${s.every_games}:${s.window}:${s.schedule.kind}:${s.auto_ai}:${s.notices}`);
    return this.getSettings();
  }

  runNow(): string {
    if (this.running) throw new ApiCallError({ code: "conflict", message: "A checkpoint is already running.", retryable: true });
    const id = this.h.jobId();
    this.running = id;
    this.h.calls.push("runCheckpointNow");
    this.h.emit({ id, kind: "checkpoint", state: "running", progress: null, message: "Syncing your games…", error_code: null });
    setTimeout(() => {
      const n = this.checkpoints.length + 1;
      const created = "2026-11-10T09:00:00+00:00";
      const i = Math.min(this.checkpoints.length, DATES.length - 1);
      this.checkpoints.push({
        number: n, created_at: created, trigger: "manual", report_id: this.h.report(n, created), reconstructed: false, games: 30,
        health: health(i), changes: [], ai_run_id: null,
      }); // prettier-ignore
      if (this.cards.length === 0) {
        const first = (key: string, kind: string, label: string, per10: number): WeaknessCard => ({
          key, kind, label, status: "training", status_since: n, baseline_per10: per10, baseline_games: 30, current_per10: per10,
          current_guarded: false, puzzle_accuracy: 0.66, puzzle_attempts: 24, reasons: { didntLook: 2 },
          points: [{ checkpoint: n, created_at: created, per10, puzzle_accuracy: 0.66, guarded: false, reconstructed: false }], examples: [],
          puzzle_themes: true,
        }); // prettier-ignore
        this.cards = [first("allowed:fork", "allowed", "Allowed: Fork", 4.0), first("missed:pin", "missed", "Missed: Pin", 3.0)];
      }
      this.newGames = 0;
      this.running = null;
      this.h.emit({ id, kind: "checkpoint", state: "done", progress: 1, message: `Checkpoint #${n} saved: 30 games`, error_code: null });
    }, 300);
    return id;
  }

  takeNotices(): StatusNotice[] {
    const out = this.settings.notices ? this.notices : [];
    this.notices = [];
    return structuredClone(out);
  }
}
