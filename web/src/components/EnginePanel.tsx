import {
  Badge,
  Button,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
} from "@mantine/core";
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Analysis, EngineStatus } from "../api/types";
import { pvToSan } from "../state/engine";
import { EngineInstallBanner } from "./EngineInstallBanner";

const DEBOUNCE_MS = 250;

// FR-7.2, 7.3, 7.7: shown only once the puzzle is over (the trainer decides; the backend also refuses
// earlier calls). A pinned line for the puzzle's start position, then the eval and top 3 lines of the
// position on the board, following you through Show answer or the analysis board. All text is plain
// React text (engine output is untrusted and never rendered as HTML).
export function EnginePanel({
  sessionId,
  startFen,
  fen,
  purpose,
  status,
  onStatusChanged,
  onBestMove,
  children,
}: {
  sessionId: number;
  startFen: string;
  fen: string;
  purpose: "panel" | "board";
  status: EngineStatus | null;
  onStatusChanged: () => void;
  /** The current position's best move (UCI), for the analysis board's arrow. */
  onBestMove?: (uci: string | null) => void;
  children?: React.ReactNode;
}) {
  const ready = status?.state === "ready";
  const [start, setStart] = useState<Analysis | null>(null);
  const [current, setCurrent] = useState<Analysis | null>(null);
  const [thinking, setThinking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const latest = useRef(fen);

  useEffect(() => {
    if (!ready) return;
    let alive = true;
    api.analyzePosition(sessionId, startFen, "start").then(
      (a) => alive && !a.superseded && setStart(a),
      (e: Error) => alive && setError(e.message),
    );
    return () => {
      alive = false;
    };
  }, [sessionId, startFen, ready]);

  useEffect(() => {
    latest.current = fen;
    if (!ready || fen === startFen) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setCurrent(null);
      setThinking(false);
      return;
    }
    setThinking(true);
    const timer = window.setTimeout(() => {
      setError(null);
      api.analyzePosition(sessionId, fen, purpose).then(
        (a) => {
          if (a.superseded || latest.current !== fen) return; // a newer position was asked for
          setCurrent(a);
          setThinking(false);
        },
        (e: Error) => {
          if (latest.current !== fen) return;
          setError(e.message);
          setThinking(false);
        },
      );
    }, DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [sessionId, fen, startFen, purpose, ready]);

  const shown = fen === startFen ? start : current;
  const best =
    shown && shown.fen === fen ? (shown.lines[0]?.pv[0] ?? null) : null;
  useEffect(() => {
    onBestMove?.(best);
  }, [best, onBestMove]);

  if (status && !ready) {
    return <EngineInstallBanner status={status} onChanged={onStatusChanged} />;
  }

  return (
    <Paper withBorder p="sm" radius="md" data-testid="engine-panel">
      <Stack gap={6}>
        <Group justify="space-between" gap="xs">
          <Text fw={700}>Stockfish</Text>
          {status?.name && (
            <Text size="xs" c="dimmed">
              {status.name}
            </Text>
          )}
        </Group>
        <Group gap={6} data-testid="engine-start-eval">
          <Text size="sm" c="dimmed">
            Puzzle start:
          </Text>
          {start ? (
            <Badge variant="light" style={{ textTransform: "none" }}>
              {start.game_over ?? start.lines[0]?.score ?? "–"}
            </Badge>
          ) : (
            <Loader size="xs" />
          )}
        </Group>
        {fen !== startFen && (
          <Text size="sm" c="dimmed">
            This position:
          </Text>
        )}
        {thinking || !shown ? (
          <Group gap={6} data-testid="engine-thinking">
            <Loader size="xs" />
            <Text size="sm" c="dimmed">
              Stockfish is thinking…
            </Text>
          </Group>
        ) : shown.game_over ? (
          <Text size="sm" fw={500} data-testid="engine-game-over">
            {shown.game_over}
          </Text>
        ) : (
          <Stack gap={4} data-testid="engine-lines">
            {shown.lines.map((line, i) => (
              <Text key={i} size="sm" data-testid="engine-line">
                <Text span fw={700}>
                  {line.score}
                </Text>{" "}
                <Text span c="dimmed">
                  {pvToSan(shown.fen, line.pv)}
                </Text>
              </Text>
            ))}
          </Stack>
        )}
        {error && (
          <Text size="xs" c="red" data-testid="engine-error">
            {error}
          </Text>
        )}
        {children}
      </Stack>
    </Paper>
  );
}

export function AnalyzeButton({ onClick }: { onClick: () => void }) {
  return (
    <Button
      size="xs"
      variant="light"
      onClick={onClick}
      data-testid="analyze-button"
    >
      Analyze on the board
    </Button>
  );
}
