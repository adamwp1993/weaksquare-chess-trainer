// Mock client with fixed data, for UI development (`npm.cmd --prefix web run dev -- --mode mock`)
// and for Playwright. Deterministic: no clock or randomness, so screenshots are stable.
import type { ApiClient, BackendEvent } from "./ApiClient";
import type { AppInfo } from "./types";

export class MockClient implements ApiClient {
  private readonly listeners = new Set<(event: BackendEvent) => void>();
  readonly calls: string[] = [];

  async getAppInfo(): Promise<AppInfo> {
    return {
      version: "0.1.0",
      data_dir: "C:\\Users\\you\\AppData\\Local\\WeakSquare",
      logs_dir: "C:\\Users\\you\\AppData\\Local\\WeakSquare\\logs",
      dev_mode: false,
      license: "AGPL-3.0-or-later",
      source_url: "https://github.com/adamwp1993/weaksquare-chess-trainer",
      puzzle_db_export_date: null,
      puzzle_count: null,
    };
  }

  async openFolder(kind: "data" | "logs") {
    this.calls.push(`openFolder:${kind}`);
  }

  async logFrontendError(message: string) {
    this.calls.push(`error:${message}`);
  }

  onEvent(listener: (event: BackendEvent) => void) {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }
}
