import {
  Accordion,
  Button,
  Divider,
  Group,
  Loader,
  Paper,
  ScrollArea,
  SegmentedControl,
  Stack,
  Switch,
  Text,
  Title,
} from "@mantine/core";
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { FilterSpec, OpeningFamily, PuzzleDbStatus, ThemeGroup } from "../api/types";
import {
  HistoryControls,
  MoveCountSelect,
  OpeningSelect,
  OrderSelect,
  QualityControls,
  QueueControls,
  RatingSlider,
  SideSelect,
} from "../components/FilterControls";
import { PresetMenu } from "../components/PresetMenu";
import { RatioEditor } from "../components/RatioEditor";
import { ThemePicker } from "../components/ThemePicker";

const COUNT_DEBOUNCE_MS = 250;
// The panel scrolls on its own, so the page (and the board beside it) never does.
const PANEL_MAX_HEIGHT = "calc(100vh - 56px - 2 * var(--mantine-spacing-md))";

// A one-line summary of the "More filters" section, so its defaults are never invisible.
function moreSummary(spec: FilterSpec): string {
  const parts: string[] = [];
  if (spec.openings.length) parts.push(`${spec.openings.length} opening${spec.openings.length === 1 ? "" : "s"}`);
  const q: string[] = [];
  if (spec.min_popularity !== null) q.push(`popularity ≥ ${spec.min_popularity}`);
  if (spec.min_plays !== null) q.push(`≥ ${spec.min_plays.toLocaleString("en-US")} plays`);
  parts.push(q.length ? q.join(", ") : "no quality filter");
  if (spec.only_my_misses) parts.push("only my misses");
  else if (spec.exclude_solved_here) parts.push("solved ones left out");
  return parts.join(" · ");
}

// FR-3.1–3.13: the filter panel, ratios, order, presets, and a live match count (debounced;
// stale answers dropped).
export function MixerView({
  spec,
  onChange,
  dbStatus,
  onStart,
  starting,
  historyVersion = 0,
}: {
  spec: FilterSpec;
  onChange: (spec: FilterSpec) => void;
  dbStatus: PuzzleDbStatus;
  onStart: () => void;
  starting: boolean;
  /** Bumped when an attempt is recorded: Exclude solved / Only my misses change the count. */
  historyVersion?: number;
}) {
  const [catalog, setCatalog] = useState<ThemeGroup[]>([]);
  const [openings, setOpenings] = useState<OpeningFamily[]>([]);
  const [count, setCount] = useState<number | null>(null);
  const [bucketCounts, setBucketCounts] = useState<number[] | null>(null);
  const [countError, setCountError] = useState<string | null>(null);
  const [counting, setCounting] = useState(false);
  const requestId = useRef(0);
  const savedThemes = useRef<string[]>([]);

  useEffect(() => {
    api.getThemeCatalog().then(setCatalog, () => setCatalog([]));
    api.getOpeningCatalog().then(setOpenings, () => setOpenings([]));
  }, [dbStatus.imported_at]);

  useEffect(() => {
    const id = ++requestId.current;
    const timer = setTimeout(() => {
      setCounting(true);
      const buckets = spec.ratios.length > 0 ? api.countBuckets(spec) : Promise.resolve(null);
      Promise.all([api.countMatches(spec), buckets]).then(
        ([n, perBucket]) => {
          if (id !== requestId.current) return;
          setCount(n);
          setBucketCounts(perBucket);
          setCountError(null);
          setCounting(false);
        },
        (e: Error) => {
          if (id !== requestId.current) return;
          setCount(null);
          setBucketCounts(null);
          setCountError(e.message);
          setCounting(false);
        },
      );
    }, COUNT_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [spec, dbStatus.imported_at, historyVersion]);

  const set = (patch: Partial<FilterSpec>) => onChange({ ...spec, ...patch });
  const bounds: [number, number] = [dbStatus.rating_min ?? 400, dbStatus.rating_max ?? 3400];
  const usingRatios = spec.ratios.length > 0;

  const toggleRatios = (on: boolean) => {
    if (on) {
      savedThemes.current = spec.themes;
      set({ themes: [], ratios: [{ themes: spec.themes, weight: 50 }, { themes: [], weight: 50 }] });
    } else {
      set({ ratios: [], themes: savedThemes.current });
    }
  };

  return (
    <Paper withBorder radius="md" style={{ position: "sticky", top: "calc(56px + var(--mantine-spacing-md))" }}>
      <ScrollArea.Autosize mah={PANEL_MAX_HEIGHT} type="auto" offsetScrollbars data-testid="mixer-scroll">
      <Stack gap="md" p="md">
        <Title order={4}>Choose your puzzles</Title>
        <PresetMenu spec={spec} onLoad={onChange} />
        <Switch
          label="Mix by ratio"
          description="e.g. 50% forks, 30% pins, 20% one-movers"
          checked={usingRatios}
          onChange={(e) => toggleRatios(e.currentTarget.checked)}
          data-testid="ratio-switch"
        />
        {usingRatios ? (
          <RatioEditor catalog={catalog} ratios={spec.ratios} counts={bucketCounts} onChange={(ratios) => set({ ratios })} />
        ) : (
          <>
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
          </>
        )}
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
        <Accordion variant="contained" chevronPosition="right">
          <Accordion.Item value="more">
            <Accordion.Control data-testid="more-filters">
              <Text size="sm" fw={500}>
                More filters
              </Text>
              <Text size="xs" c="dimmed" data-testid="more-summary">
                {moreSummary(spec)}
              </Text>
            </Accordion.Control>
            <Accordion.Panel>
              <Stack gap="md">
                <OpeningSelect catalog={openings} value={spec.openings} onChange={(o) => set({ openings: o })} />
                <QualityControls
                  minPopularity={spec.min_popularity}
                  minPlays={spec.min_plays}
                  onChange={(min_popularity, min_plays) => set({ min_popularity, min_plays })}
                />
                <HistoryControls
                  excludeSolved={spec.exclude_solved_here}
                  onlyMisses={spec.only_my_misses}
                  onChange={(exclude_solved_here, only_my_misses) => set({ exclude_solved_here, only_my_misses })}
                />
              </Stack>
            </Accordion.Panel>
          </Accordion.Item>
        </Accordion>
        <OrderSelect value={spec.order} endless={spec.queue_size === null} onChange={(order) => set({ order })} />
        <Divider />
        <Group justify="space-between" align="center">
          <Group gap={6} data-testid="match-count">
            {counting && <Loader size="xs" />}
            {countError ? (
              <Text c="red" size="sm">
                {countError}
              </Text>
            ) : (
              <Text fw={600}>
                {count === null
                  ? "…"
                  : `${count.toLocaleString("en-US")} ${count === 1 ? "puzzle matches" : "puzzles match"}`}
              </Text>
            )}
          </Group>
        </Group>
        <QueueControls value={spec.queue_size} onChange={(queue_size) => set({ queue_size })} />
        <Button onClick={onStart} loading={starting} disabled={count === 0 || countError !== null} data-testid="start">
          Start
        </Button>
      </Stack>
      </ScrollArea.Autosize>
    </Paper>
  );
}
