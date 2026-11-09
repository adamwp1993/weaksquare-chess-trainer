// v0.15 (FR-14.4): the Lichess explorer's most played moves in the position on the Analysis board. Only the position
// goes to Lichess, and only when you're signed in. Signed out, offline or asked to wait, the panel just says so.
import { Box, Group, Loader, Paper, Stack, Text, UnstyledButton } from "@mantine/core";
import { useEffect, useState } from "react";
import { api } from "../api";
import type { PopularReplies as Replies } from "../api/types";

const DEBOUNCE_MS = 300;

export function PopularReplies({ fen, onPlay }: { fen: string; onPlay: (uci: string) => void }) {
  const [found, setFound] = useState<{ fen: string; replies: Replies | null } | null>(null);

  useEffect(() => {
    let alive = true;
    const t = window.setTimeout(() => {
      api.getPopularReplies(fen).then(
        (r) => alive && setFound({ fen, replies: r }),
        () => alive && setFound({ fen, replies: null }), // an error is shown nowhere: the panel goes quiet
      );
    }, DEBOUNCE_MS);
    return () => {
      alive = false;
      window.clearTimeout(t);
    };
  }, [fen]);

  const r = found?.fen === fen ? found.replies : undefined;
  return (
    <Paper withBorder p="sm" radius="md" data-testid="popular-replies">
      <Stack gap={6}>
        <Text fw={700}>Popular replies</Text>
        {r === undefined ? (
          <Loader size="xs" />
        ) : r === null || r.state === "unavailable" ? (
          <Text size="sm" c="dimmed" data-testid="popular-unavailable">
            Popular replies aren't available right now. You may be offline, or Lichess asked the app to wait a minute.
          </Text>
        ) : r.state === "signed_out" ? (
          <Text size="sm" c="dimmed" data-testid="popular-signed-out">
            Sign in to Lichess to see popular replies.
          </Text>
        ) : r.moves.length === 0 ? (
          <Text size="sm" c="dimmed" data-testid="popular-none">
            No games in the explorer reached this position.
          </Text>
        ) : (
          <Stack gap={4}>
            {r.moves.map((m) => (
              <UnstyledButton key={m.uci} onClick={() => onPlay(m.uci)} data-testid="popular-move" data-uci={m.uci}>
                <Group gap="xs" wrap="nowrap">
                  <Text size="sm" fw={600} w={56}>
                    {m.san}
                  </Text>
                  <Text size="xs" c="dimmed" w={88} ta="right">
                    {m.games.toLocaleString()} games
                  </Text>
                  <ResultBar white={m.white} draws={m.draws} black={m.black} />
                </Group>
              </UnstyledButton>
            ))}
          </Stack>
        )}
      </Stack>
    </Paper>
  );
}

/** White wins, draws and Black wins, as shares of the games. */
function ResultBar({ white, draws, black }: { white: number; draws: number; black: number }) {
  const total = white + draws + black || 1;
  const pct = (n: number) => Math.round((n / total) * 100);
  const parts: [number, string, string][] = [
    [white, "var(--mantine-color-gray-0)", "var(--mantine-color-dark-9)"],
    [draws, "var(--mantine-color-gray-5)", "var(--mantine-color-dark-9)"],
    [black, "var(--mantine-color-dark-7)", "var(--mantine-color-gray-0)"],
  ];
  return (
    <Box
      style={{ display: "flex", flex: 1, height: 18, borderRadius: 4, overflow: "hidden", border: "1px solid var(--mantine-color-default-border)" }}
      title={`White wins ${pct(white)}%, draws ${pct(draws)}%, Black wins ${pct(black)}%`}
      aria-label={`White wins ${pct(white)}%, draws ${pct(draws)}%, Black wins ${pct(black)}%`}
    >
      {parts.map(([n, bg, fg], i) =>
        n > 0 ? (
          <Box key={i} style={{ width: `${(n / total) * 100}%`, background: bg, color: fg, fontSize: 11, lineHeight: "16px", textAlign: "center" }}>
            {pct(n) >= 12 ? `${pct(n)}%` : ""}
          </Box>
        ) : null,
      )}
    </Box>
  );
}
