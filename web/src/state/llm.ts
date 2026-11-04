import { useEffect, useState } from "react";
import { api } from "../api";
import type { LlmSettings } from "../api/types";

// v0.7: one copy of the AI settings for every view (the header's spend indicator, Settings → AI, the
// startup page and the trainer's Explain button). Every change returns the new settings, which are
// published here; finished Explain and key-test jobs refresh it (the spend changed). Nothing is kept
// in browser storage (ARCHITECTURE §3 decision 14), and no key is ever in it (SR-1).
let current: LlmSettings | null = null;
const listeners = new Set<(s: LlmSettings) => void>();
const REFRESH_JOBS = new Set(["explain", "llm_key_test", "llm_launch_check", "game_move_explain", "game_narrative"]);

export function publishLlm(s: LlmSettings) {
  current = s;
  listeners.forEach((l) => l(s));
}

export function refreshLlm() {
  return api.getLlmSettings().then(publishLlm, () => undefined);
}

export function useLlmSettings(): LlmSettings | null {
  const [settings, setSettings] = useState<LlmSettings | null>(current);
  useEffect(() => {
    listeners.add(setSettings);
    if (current === null) refreshLlm();
    const off = api.onEvent((e) => {
      if (e.name === "job" && REFRESH_JOBS.has(e.payload.kind) && e.payload.state !== "running") refreshLlm();
    });
    return () => {
      listeners.delete(setSettings);
      off();
    };
  }, []);
  return settings;
}

/** "$0.0012", "$0.03", "$5.00": cents unless it's under a cent. */
export function dollars(x: number): string {
  if (x > 0 && x < 0.01) return `$${x.toFixed(4)}`;
  return `$${x.toFixed(2)}`;
}
