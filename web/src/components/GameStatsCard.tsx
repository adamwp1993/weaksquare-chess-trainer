// v0.8: Retry mode's found rate (FR-11.15) and accuracy per puzzle source (FR-3.15) on the Stats page.
import { Group, Paper, Stack, Text, Title } from "@mantine/core";
import { useEffect, useState } from "react";
import { api } from "../api";
import type { GameStats } from "../api/types";

const pct = (wins: number, n: number) => (n ? `${Math.round((wins / n) * 100)}%` : "—");

export function GameStatsCard() {
  const [s, setS] = useState<GameStats | null>(null);
  useEffect(() => {
    api.getGameStats().then(setS, () => setS(null));
  }, []);
  if (!s) return null;
  return (
    <Paper withBorder p="sm" data-testid="game-stats">
      <Stack gap={4}>
        <Title order={5}>My games and my puzzles</Title>
        <Text size="sm" data-testid="retry-stats">
          Retry: found {s.retry_found} of {s.retry_tried}
          {s.retry_tried ? ` (${pct(s.retry_found, s.retry_tried)})` : ""}
        </Text>
        <Group gap="lg">
          {s.sources.map((src) => (
            <Text key={src.source} size="sm" data-testid={`source-acc-${src.source}`}>
              {src.source === "my" ? "My puzzles" : "Lichess puzzles"}: {pct(src.wins, src.attempts)} of {src.attempts}
            </Text>
          ))}
        </Group>
      </Stack>
    </Paper>
  );
}
