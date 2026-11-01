// Mock client with fixed data, for UI development (`npm.cmd --prefix web run dev -- --mode mock`)
// and for Playwright. Deterministic: no clock-dependent data and no randomness, so screenshots are stable.
//
// Scenario via the page URL: `?scenario=empty` starts with no puzzle database imported.
import type { ApiClient, BackendEvent } from "./ApiClient";
import { ApiCallError } from "./ApiClient";
import type { AppInfo, Job, PuzzleDbStatus } from "./types";

const INSTALLED: PuzzleDbStatus = {
  installed: true,
  puzzle_count: 6157341,
  export_date: "2026-10-02",
  imported_at: "2026-11-01T09:00:00+00:00",
  rating_min: 339,
  rating_max: 3297,
  import_job_id: null,
};

const EMPTY: PuzzleDbStatus = {
  installed: false,
  puzzle_count: null,
  export_date: null,
  imported_at: null,
  rating_min: null,
  rating_max: null,
  import_job_id: null,
};

const IMPORT_STEPS: [number, string][] = [
  [0.05, "Checking the published checksum…"],
  [0.2, "Downloading the puzzle database… 120 MB"],
  [0.4, "Verifying the download…"],
  [0.7, "Importing puzzles… 3,100,000"],
  [0.9, "Building indexes (this takes a minute)…"],
];

export class MockClient implements ApiClient {
  private readonly listeners = new Set<(event: BackendEvent) => void>();
  private status: PuzzleDbStatus;
  private jobs = new Map<string, Job>();
  private nextJob = 1;
  readonly calls: string[] = [];

  constructor(search: string = typeof window !== "undefined" ? window.location.search : "") {
    const scenario = new URLSearchParams(search).get("scenario");
    this.status = scenario === "empty" ? { ...EMPTY } : { ...INSTALLED };
  }

  private emit(job: Job) {
    this.jobs.set(job.id, job);
    this.listeners.forEach((l) => l({ name: "job", payload: job }));
  }

  async getAppInfo(): Promise<AppInfo> {
    return {
      version: "0.1.0",
      data_dir: "C:\\Users\\you\\AppData\\Local\\WeakSquare",
      logs_dir: "C:\\Users\\you\\AppData\\Local\\WeakSquare\\logs",
      dev_mode: false,
      license: "AGPL-3.0-or-later",
      source_url: "https://github.com/adamwp1993/weaksquare-chess-trainer",
      puzzle_db_export_date: this.status.export_date,
      puzzle_count: this.status.puzzle_count,
    };
  }

  async openFolder(kind: "data" | "logs") {
    this.calls.push(`openFolder:${kind}`);
  }

  async logFrontendError(message: string) {
    this.calls.push(`error:${message}`);
  }

  async getPuzzleDbStatus() {
    return { ...this.status };
  }

  async choosePuzzleFile() {
    return "C:\\Users\\you\\Downloads\\lichess_db_puzzle.csv.zst";
  }

  async startPuzzleImport(localPath: string | null) {
    if (this.status.import_job_id) {
      throw new ApiCallError({ code: "conflict", message: "A puzzle import is already running.", retryable: true });
    }
    const id = `job-${this.nextJob++}`;
    this.calls.push(`import:${localPath ?? "download"}`);
    this.status.import_job_id = id;
    this.emit({ id, kind: "puzzle_import", state: "running", progress: 0, message: "Starting…", error_code: null });
    IMPORT_STEPS.forEach(([progress, message], i) => {
      setTimeout(() => {
        if (this.jobs.get(id)?.state !== "running") return;
        this.emit({ id, kind: "puzzle_import", state: "running", progress, message, error_code: null });
      }, 150 * (i + 1));
    });
    setTimeout(() => {
      if (this.jobs.get(id)?.state !== "running") return;
      this.status = { ...INSTALLED };
      this.emit({ id, kind: "puzzle_import", state: "done", progress: 1, message: "Done", error_code: null });
    }, 150 * (IMPORT_STEPS.length + 1));
    return id;
  }

  async getJob(jobId: string) {
    const job = this.jobs.get(jobId);
    if (!job) throw new ApiCallError({ code: "not_found", message: "No such job.", retryable: false });
    return job;
  }

  async cancelJob(jobId: string) {
    const job = this.jobs.get(jobId);
    if (!job || job.state !== "running") return false;
    this.status.import_job_id = null;
    this.emit({ ...job, state: "cancelled", message: "Cancelled" });
    return true;
  }

  onEvent(listener: (event: BackendEvent) => void) {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }
}
