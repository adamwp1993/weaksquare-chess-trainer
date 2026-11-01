import { Button, Divider, Group, Loader, Paper, SegmentedControl, Stack, Text, Title } from "@mantine/core";
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { FilterSpec, PuzzleDbStatus, ThemeGroup } from "../api/types";
import { MoveCountSelect, QueueControls, RatingSlider, SideSelect } from "../components/FilterControls";
import { ThemePicker } from "../components/ThemePicker";

const COUNT_DEBOUNCE_MS = 250;

// FR-3.1–3.5, 3.12: the filter panel with a live match count (debounced; stale answers dropped).
export function MixerView({
  spec,
  onChange,
  dbStatus,
  onStart,
  starting,
}: {
  spec: FilterSpec;
  onChange: (spec: FilterSpec) => void;
  dbStatus: PuzzleDbStatus;
  onStart: () => void;
  starting: boolean;
}) {
  const [catalog, setCatalog] = useState<ThemeGroup[]>([]);
  const [count, setCount] = useState<number | null>(null);
  const [countError, setCountError] = useState<string | null>(null);
  const [counting, setCounting] = useState(false);
  const requestId = useRef(0);

  useEffect(() => {
    api.getThemeCatalog().then(setCatalog, () => setCatalog([]));
  }, [dbStatus.imported_at]);

  useEffect(() => {
    const id = ++requestId.current;
    const timer = setTimeout(() => {
      setCounting(true);
      api.countMatches(spec).then(
        (n) => {
          if (id !== requestId.current) return;
          setCount(n);
          setCountError(null);
          setCounting(false);
        },
        (e: Error) => {
          if (id !== requestId.current) return;
          setCount(null);
          setCountError(e.message);
          setCounting(false);
        },
      );
    }, COUNT_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [spec, dbStatus.imported_at]);

  const set = (patch: Partial<FilterSpec>) => onChange({ ...spec, ...patch });
  const bounds: [number, number] = [dbStatus.rating_min ?? 400, dbStatus.rating_max ?? 3400];

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="md">
        <Title order={4}>Choose your puzzles</Title>
        <ThemePicker
          label="Themes"
          catalog={catalog}
          value={spec.themes}
          onChange={(themes) => set({ themes })}
          emptyLabel="All themes"
          testId="themes-picker"
        />
        <Group gap="xs">
          <Text size="sm">Match</Text>
          <SegmentedControl
            size="xs"
            value={spec.match}
            onChange={(v) => set({ match: v as "any" | "all" })}
            data={[
              { value: "any", label: "ANY" },
              { value: "all", label: "ALL" },
            ]}
            aria-label="Theme match mode"
          />
          <Text size="xs" c="dimmed">
            {spec.match === "any" ? "at least one theme" : "every theme"}
          </Text>
        </Group>
        <ThemePicker
          label="Exclude themes"
          catalog={catalog}
          value={spec.exclude_themes}
          onChange={(exclude_themes) => set({ exclude_themes })}
          emptyLabel="None"
          testId="exclude-picker"
        />
        <RatingSlider
          bounds={bounds}
          min={spec.rating_min}
          max={spec.rating_max}
          onChange={(rating_min, rating_max) => set({ rating_min, rating_max })}
        />
        <MoveCountSelect value={spec.lengths} onChange={(lengths) => set({ lengths })} />
        <SideSelect value={spec.side} onChange={(side) => set({ side })} />
        <Divider />
        <Group justify="space-between" align="center">
          <Group gap={6} data-testid="match-count">
            {counting && <Loader size="xs" />}
            {countError ? (
              <Text c="red" size="sm">
                {countError}
              </Text>
            ) : (
              <Text fw={600}>{count === null ? "…" : `${count.toLocaleString("en-US")} puzzles match`}</Text>
            )}
          </Group>
        </Group>
        <QueueControls value={spec.queue_size} onChange={(queue_size) => set({ queue_size })} />
        <Button onClick={onStart} loading={starting} disabled={count === 0 || countError !== null}>
          Start
        </Button>
      </Stack>
    </Paper>
  );
}
