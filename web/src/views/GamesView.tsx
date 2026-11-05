// v0.8: My games (FR-11.25–11.31): one list for both linked accounts, filters, Refresh (sync), Analyze
// selected (the background engine, one game at a time), Review, and Open on Lichess / chess.com.
import {
  Alert,
  Badge,
  Button,
  Checkbox,
  Group,
  MultiSelect,
  Select,
  Paper,
  Progress,
  SegmentedControl,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { LibraryFilters } from "../api/ApiClient";
import type { AnalysisQueue, GamePage, GameSummary } from "../api/types";
import { PLATFORM_LABEL, TIME_CLASSES, cap, gameDate, resultLabel } from "../state/games";
import { useLlmSettings } from "../state/llm";
import { useJob } from "../state/useJob";

const PAGE = 50;

const STATUS: Record<GameSummary["analysis_status"], { label: string; color: string }> = {
  none: { label: "Not analyzed", color: "gray" },
  analyzed: { label: "Analyzed", color: "green" },
  ai_reviewed: { label: "AI-reviewed", color: "indigo" }, // v0.9: Explain my game ran (FR-11.25)
};

export function GamesView({
  onReview,
  onImport,
  onSendToCoach,
}: {
  /** `explain`: Review + Explain my game (FR-11.29, v0.9). */
  onReview: (gameId: number, explain?: boolean) => void;
  onImport: () => void;
  /** v0.10 Send to Coach (FR-11.30): run the Coach on exactly these games. */
  onSendToCoach?: (ids: number[]) => void;
}) {
  const aiReady = useLlmSettings()?.features.find((f) => f.feature === "game_review")?.ready ?? false;
  const [filters, setFilters] = useState<LibraryFilters>({});
  const [page, setPage] = useState<GamePage | null>(null);
  const [limit, setLimit] = useState(PAGE);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [syncJob, setSyncJob] = useState<string | null>(null);
  const sync = useJob(syncJob);
  const [queue, setQueue] = useState<AnalysisQueue | null>(null);
  const analysis = useJob(queue?.job_id ?? null);
  const [players, setPlayers] = useState<{ subject: string; label: string }[]>([]); // v0.10: the Player filter
  useEffect(() => {
    api.getCoachDefaults().then((d) => setPlayers(d.players), () => undefined);
  }, []);

  const load = useCallback(() => {
    api.listGames({ ...filters, limit, offset: 0 }).then(setPage, (e: Error) => setError(e.message));
  }, [filters, limit]);
  useEffect(load, [load]);
  useEffect(() => {
    api.getAnalysisQueue().then(setQueue, () => undefined);
  }, []);
  useEffect(() => {
    if (sync && sync.state !== "running") load();
  }, [sync, load]);
  useEffect(() => {
    if (!analysis) return;
    api.getAnalysisQueue().then(setQueue, () => undefined);
    if (analysis.state !== "running") load();
  }, [analysis, load]);

  const set = (patch: Partial<LibraryFilters>) => {
    setFilters((f) => ({ ...f, ...patch }));
    setLimit(PAGE);
  };

  const refresh = async () => {
    setError(null);
    setNotice(null);
    try {
      const job = await api.startGamesSync();
      if (job === null) setNotice("Sign in with Lichess or link a chess.com username in Settings → Games to sync your games.");
      setSyncJob(job);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const analyze = async (ids: number[]) => {
    setError(null);
    try {
      const job = await api.analyzeGames(ids, false);
      if (job === null) setNotice("Those games are already analyzed.");
      setQueue(await api.getAnalysisQueue());
      setSelected(new Set());
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const toggle = (id: number) =>
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const rows = page?.games ?? [];
  return (
    <Stack gap="md" data-testid="games-view">
      <Group justify="space-between">
        <Title order={3}>My games</Title>
        <Group gap="xs">
          <Button variant="default" onClick={onImport} data-testid="games-import">
            Import game
          </Button>
          <Button onClick={refresh} loading={sync?.state === "running"} data-testid="games-refresh">
            Refresh
          </Button>
        </Group>
      </Group>
      {sync?.state === "running" && (
        <Text size="sm" c="dimmed" data-testid="games-sync-progress">
          {sync.message}
        </Text>
      )}
      {sync?.state === "done" && <Text size="sm" data-testid="games-sync-done">{sync.message}</Text>}
      {sync?.state === "failed" && <Alert color="red">{sync.message}</Alert>}
      {notice && (
        <Alert color="blue" withCloseButton onClose={() => setNotice(null)} data-testid="games-notice">
          {notice}
        </Alert>
      )}
      {error && <Alert color="red">{error}</Alert>}
      {queue?.job_id && analysis?.state === "running" && (
        <Paper withBorder p="sm" data-testid="analysis-queue">
          <Group justify="space-between" mb={6}>
            <Text size="sm">{analysis.message}</Text>
            <Button size="compact-xs" variant="subtle" color="red" onClick={() => api.cancelJob(queue.job_id!)} data-testid="analysis-cancel">
              Cancel
            </Button>
          </Group>
          <Progress value={(analysis.progress ?? 0) * 100} animated />
          {queue.waiting.length > 0 && (
            <Text size="xs" c="dimmed" mt={4}>
              {queue.waiting.length} more waiting
            </Text>
          )}
        </Paper>
      )}

      <Paper withBorder p="sm">
        <Group gap="sm" align="end" wrap="wrap">
          {players.length > 0 && (
            <Select
              label="Player"
              size="xs"
              w={180}
              data={[{ value: "me", label: "You" }, ...players.map((p) => ({ value: p.subject, label: p.label }))]}
              value={filters.player ?? "me"}
              onChange={(v) => set({ player: v ?? "me" })}
              allowDeselect={false}
              data-testid="filter-player"
            />
          )}
          <MultiSelect
            label="Platform"
            size="xs"
            w={170}
            data={Object.entries(PLATFORM_LABEL).map(([value, label]) => ({ value, label }))}
            value={filters.platforms ?? []}
            onChange={(v) => set({ platforms: v as LibraryFilters["platforms"] })}
            data-testid="filter-platform"
          />
          <MultiSelect
            label="Time"
            size="xs"
            w={170}
            data={TIME_CLASSES.map((t) => ({ value: t, label: cap(t) }))}
            value={filters.time_classes ?? []}
            onChange={(v) => set({ time_classes: v })}
          />
          <MultiSelect
            label="Result"
            size="xs"
            w={150}
            data={[
              { value: "win", label: "Won" },
              { value: "loss", label: "Lost" },
              { value: "draw", label: "Draw" },
            ]}
            value={filters.results ?? []}
            onChange={(v) => set({ results: v as LibraryFilters["results"] })}
            data-testid="filter-result"
          />
          <MultiSelect
            label="Your color"
            size="xs"
            w={150}
            data={[
              { value: "white", label: "White" },
              { value: "black", label: "Black" },
            ]}
            value={filters.colors ?? []}
            onChange={(v) => set({ colors: v as LibraryFilters["colors"] })}
          />
          <MultiSelect
            label="Status"
            size="xs"
            w={170}
            data={[
              { value: "none", label: "Not analyzed" },
              { value: "analyzed", label: "Analyzed" },
              { value: "ai_reviewed", label: "AI-reviewed" },
            ]}
            value={filters.statuses ?? []}
            onChange={(v) => set({ statuses: v as LibraryFilters["statuses"] })}
            data-testid="filter-status"
          />
          <Stack gap={2}>
            <Text size="xs" fw={500}>
              Rated
            </Text>
            <SegmentedControl
              size="xs"
              value={filters.rated === true ? "rated" : filters.rated === false ? "casual" : "any"}
              onChange={(v) => set({ rated: v === "any" ? null : v === "rated" })}
              data={[
                { value: "any", label: "Any" },
                { value: "rated", label: "Rated" },
                { value: "casual", label: "Casual" },
              ]}
            />
          </Stack>
          <TextInput label="Opponent" size="xs" w={140} value={filters.opponent ?? ""} onChange={(e) => set({ opponent: e.currentTarget.value })} data-testid="filter-opponent" />
          <TextInput label="Opening or ECO" size="xs" w={150} value={filters.opening ?? ""} onChange={(e) => set({ opening: e.currentTarget.value })} />
          <TextInput label="From" type="date" size="xs" w={140} value={filters.date_from ?? ""} onChange={(e) => set({ date_from: e.currentTarget.value || null })} />
          <TextInput label="To" type="date" size="xs" w={140} value={filters.date_to ?? ""} onChange={(e) => set({ date_to: e.currentTarget.value || null })} />
        </Group>
      </Paper>

      <Group justify="space-between">
        <Text size="sm" c="dimmed" data-testid="games-count">
          {page ? `${page.total} game${page.total === 1 ? "" : "s"}` : "Loading…"}
        </Text>
        <Group gap="xs">
          <Button size="xs" disabled={selected.size === 0} onClick={() => analyze([...selected])} data-testid="analyze-selected">
            Analyze selected ({selected.size})
          </Button>
          {onSendToCoach && (filters.player ?? "me") === "me" && (
            <Button size="xs" variant="light" disabled={selected.size === 0} onClick={() => onSendToCoach([...selected])} data-testid="send-to-coach">
              Send to Coach ({selected.size})
            </Button>
          )}
        </Group>
      </Group>

      {page && page.total === 0 ? (
        <Paper withBorder p="xl">
          <Text c="dimmed" data-testid="games-empty">
            No games yet. Press Refresh to sync your linked accounts, or Import game to add one.
          </Text>
        </Paper>
      ) : (
        <Table striped highlightOnHover data-testid="games-table">
          <Table.Thead>
            <Table.Tr>
              <Table.Th w={30} />
              <Table.Th>Date</Table.Th>
              <Table.Th>Platform</Table.Th>
              <Table.Th>You</Table.Th>
              <Table.Th>Opponent</Table.Th>
              <Table.Th>Result</Table.Th>
              <Table.Th>Time</Table.Th>
              <Table.Th>Opening</Table.Th>
              <Table.Th>Accuracy</Table.Th>
              <Table.Th>Status</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((g) => (
              <Table.Tr key={g.id} data-testid={`game-row-${g.id}`}>
                <Table.Td>
                  <Checkbox size="xs" checked={selected.has(g.id)} onChange={() => toggle(g.id)} aria-label="Select game" />
                </Table.Td>
                <Table.Td style={{ whiteSpace: "nowrap" }}>{gameDate(g.played_at)}</Table.Td>
                <Table.Td>{PLATFORM_LABEL[g.source]}</Table.Td>
                <Table.Td>
                  {g.user_color ? cap(g.user_color) : "?"}
                  {g.user_rating ? ` (${g.user_rating})` : ""}
                </Table.Td>
                <Table.Td>
                  {g.opponent ?? `${g.white ?? "?"} – ${g.black ?? "?"}`}
                  {g.opponent_rating ? ` (${g.opponent_rating})` : ""}
                </Table.Td>
                <Table.Td>{resultLabel(g)}</Table.Td>
                <Table.Td>{[g.time_class ? cap(g.time_class) : null, g.time_control].filter(Boolean).join(" · ") || "—"}</Table.Td>
                <Table.Td>
                  <Text size="sm" lineClamp={1} maw={220}>
                    {[g.eco, g.opening].filter(Boolean).join(" ") || "—"}
                  </Text>
                </Table.Td>
                <Table.Td>{g.accuracy_user !== null ? `${Math.round(g.accuracy_user)}%` : "—"}</Table.Td>
                <Table.Td>
                  <Group gap={4}>
                    <Badge size="sm" variant="light" color={STATUS[g.analysis_status].color} data-testid={`status-${g.id}`}>
                      {STATUS[g.analysis_status].label}
                    </Badge>
                    {g.lichess_analyzed && (
                      <Badge size="sm" variant="outline" color="blue" title="Lichess already has computer analysis for this game">
                        Lichess analysis
                      </Badge>
                    )}
                  </Group>
                </Table.Td>
                <Table.Td>
                  <Group gap={4} wrap="nowrap">
                    <Button size="compact-xs" onClick={() => onReview(g.id)} data-testid={`review-${g.id}`}>
                      Review
                    </Button>
                    {aiReady && g.user_color !== null && (
                      <Button size="compact-xs" variant="light" color="indigo" onClick={() => onReview(g.id, true)} data-testid={`review-explain-${g.id}`}>
                        Review + Explain my game
                      </Button>
                    )}
                    {g.url && (
                      <Button size="compact-xs" variant="subtle" onClick={() => api.openGameOnline(g.id)} data-testid={`open-${g.id}`}>
                        {g.source === "chesscom" ? "Open on chess.com" : "Open on Lichess"}
                      </Button>
                    )}
                  </Group>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
      {page && page.total > rows.length && (
        <Button variant="subtle" onClick={() => setLimit((l) => l + PAGE)} data-testid="games-more">
          Show more
        </Button>
      )}
    </Stack>
  );
}
