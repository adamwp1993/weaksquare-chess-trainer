import { Chess } from "chess.js";
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { EngineStatus } from "../api/types";

const ENGINE_JOBS = new Set(["stockfish_install", "engine_check"]);

/** The engine's status, refreshed when an install or a custom-engine check finishes. */
export function useEngineStatus(): [EngineStatus | null, () => void] {
  const [status, setStatus] = useState<EngineStatus | null>(null);
  const refresh = useCallback(() => {
    api.getEngineStatus().then(setStatus, () => undefined);
  }, []);
  useEffect(() => {
    // Read once on mount, then on every finished engine job (pushed events).
    refresh();
    return api.onEvent((event) => {
      if (
        event.name === "job" &&
        ENGINE_JOBS.has(event.payload.kind) &&
        event.payload.state !== "running"
      )
        refresh();
    });
  }, [refresh]);
  return [status, refresh];
}

function move(chess: Chess, uci: string) {
  return chess.move({
    from: uci.slice(0, 2),
    to: uci.slice(2, 4),
    promotion: uci.length > 4 ? uci[4] : undefined,
  });
}

/**
 * An engine line as numbered SAN ("12. Nf3 Nc6 13. Bb5" or "12… Nc6 13. Bb5"). Engine output is
 * untrusted: it stops at the first move that isn't legal, so nothing illegal is ever shown.
 */
export function pvToSan(fen: string, pv: string[], max = 8): string {
  let chess: Chess;
  try {
    chess = new Chess(fen);
  } catch {
    return "";
  }
  const parts: string[] = [];
  for (const [i, uci] of pv.slice(0, max).entries()) {
    const white = chess.turn() === "w";
    const number = chess.moveNumber();
    let san: string;
    try {
      san = move(chess, uci).san;
    } catch {
      break;
    }
    if (white) parts.push(`${number}. ${san}`);
    else parts.push(i === 0 ? `${number}… ${san}` : san);
  }
  return parts.join(" ");
}

/** The [from, to] of `uci` if it's a legal move in `fen`, else null (checked before drawing an arrow). */
export function legalArrow(
  fen: string,
  uci: string | undefined,
): [string, string] | null {
  if (!uci) return null;
  try {
    move(new Chess(fen), uci);
    return [uci.slice(0, 2), uci.slice(2, 4)];
  } catch {
    return null;
  }
}
