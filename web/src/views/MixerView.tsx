import {
  Accordion,
  ActionIcon,
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
import type { TrainingMode } from "../api/ApiClient";
import type { FilterSpec, LadderInfo, OpeningFamily, PuzzleDbStatus, SrsStatus, ThemeGroup } from "../api/types";
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
import { MODES, modeLabel, shortDate } from "../state/modes";

const COUNT_DEBOUNCE_MS = 250;
// The panel scrolls on its own, so the page (and the board beside it) never does.
// (56px header, the page padding above and below, and the panel's two 1px borders: v0.2-B9.)
const PANEL_MAX_HEIGHT = "calc(100vh - 56px - 2 * var(--mantine-spacing-md) - 2px)";

// A one-line summary of the "More filters" section, so its defaults are never invisible.
function moreSummary(spec: FilterSpec, lichess: boolean): string {
  const parts: string[] = [];
  if (spec.openings.length) parts.push(`${spec.openings.length} opening${spec.openings.length === 1 ? "" : "s"}`);
  const q: string[] = [];
  if (spec.min_popularity !== null) q.push(`popularity ≥ ${spec.min_popularity}`);
  if (spec.min_plays !== null) q.push(`≥ ${spec.min_plays.toLocaleString("en-US")} plays`);
  parts.push(q.length ? q.join(", ") : "no quality filter");
  const played = lichess && spec.exclude_played_on_lichess;
  if (spec.only_my_misses) parts.push("only my misses");
  else if (spec.exclude_solved_here && played) parts.push("solved or played on Lichess left out");
  else if (spec.exclude_solved_here) parts.push("solved ones left out");
  else if (played) parts.push("played on Lichess left out");
  return parts.join(" · ");
}

/** FR-1.14: the one-line summary the collapsed panel shows. */
export function filtersSummary(
  spec: FilterSpec, mode: TrainingMode, count: number | null, srs: SrsStatus | null, catalog: ThemeGroup[],
): string {
  if (mode === "spaced_repetition") return `${modeLabel(mode)} · ${srs ? `${srs.due} due` : "…"}`;
  const names = new Map(catalog.flatMap((g) => g.themes.map((t) => [t.key, t.name] as const)));
  const name = (k: string) => names.get(k) ?? k;
  const parts: string[] = [modeLabel(mode)];
  if (spec.ratios.length) parts.push(spec.ratios.map((r) => `${r.weight}% ${r.themes.map(name).join("/") || "…"}`).join(", "));
  else if (spec.themes.length === 0) parts.push("All themes");
  else parts.push(spec.themes.length <= 3 ? spec.themes.map(name).join(", ") : `${spec.themes.length} themes`);
  if (spec.rating_min !== null || spec.rating_max !== null) parts.push(`${spec.rating_min ?? "…"}–${spec.rating_max ?? "…"}`);
  if (spec.order === "depth_ladder") parts.push("depth ladder");
  if (count !== null) parts.push(`${count.toLocaleString("en-US")} ${count === 1 ? "puzzle" : "puzzles"}`);
  return parts.join(" · ");
}

// FR-3.1–3.13: the filter panel, ratios, order, presets, and a live match count (debounced;
// stale answers dropped). v0.5: the Modes control (§6), Show move count (FR-4.2), the Spaced
// repetition due line (FR-4.6), the depth-ladder status (FR-4.5) and Hide filters (FR-1.14).
export function MixerView({
  spec,
  onChange,
  dbStatus,
  onStart,
  starting,
  historyVersion = 0,
  rated,
  onRated,
  playedCount,
  mode,
  onMode,
  showLength,
  onShowLength,
  onCollapse,
  onSummary,
}: {
  mode: TrainingMode;
  onMode: (mode: TrainingMode) => void;
  showLength: boolean;
  onShowLength: (on: boolean) => void;
  /** FR-1.14: Hide filters. */
  onCollapse: () => void;
  /** FR-1.14: the collapsed strip's summary, kept current. */
  onSummary: (text: string) => void;
  /** FR-1.9: the next session's Rated toggle (on at each launch, never saved). */
  rated: boolean;
  onRated: (on: boolean) => void;
  playedCount: number | null;
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
  const [srs, setSrs] = useState<SrsStatus | null>(null);
  const [ladder, setLadder] = useState<LadderInfo | null>(null);
  const requestId = useRef(0);
  const savedThemes = useRef<string[]>([]);

  useEffect(() => {
    api.getThemeCatalog().then(setCatalog, () => setCatalog([]));
    api.getOpeningCatalog().then(setOpenings, () => setOpenings([]));
  }, [dbStatus.imported_at]);

  // FR-4.6: what's due, whenever you might have just missed (or reviewed) something.
  useEffect(() => {
    api.getSrsStatus().then(setSrs, () => setSrs(null));
  }, [historyVersion, mode]);

  // FR-4.5: where a depth-ladder session with these themes would start.
  useEffect(() => {
    if (spec.order !== "depth_ladder") return;
    let live = true;
    api.getLadderStatus(spec).then((p) => live && setLadder(p.ladder), () => live && setLadder(null));
    return () => {
      live = false;
    };
  }, [spec, historyVersion]);

  useEffect(() => {
    onSummary(filtersSummary(spec, mode, count, srs, catalog));
  }, [spec, mode, count, srs, catalog, onSummary]);

  useEffect(() => {
    const id = ++requestId.current;
    const timer = setTimeout(() => {
      setCounting(true);
      // A ratio mix gets its total and its groups from one call (one scan of the database).
      const counted =
        spec.ratios.length > 0
          ? api.countBuckets(spec).then((c) => [c.total, c.buckets] as const)
          : api.countMatches(spec).then((n) => [n, null] as const);
      counted.then(
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
  }, [spec, dbStatus.imported_at, historyVersion, playedCount]);

  const set = (patch: Partial<FilterSpec>) => onChange({ ...spec, ...patch });
  const bounds: [number, number] = [dbStatus.rating_min ?? 400, dbStatus.rating_max ?? 3400];
  const usingRatios = spec.ratios.length > 0;
  const srsMode = mode === "spaced_repetition";
  const ladderOrder = spec.order === "depth_ladder";
  const modeInfo = MODES.find((m) => m.value === mode);

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
        <Group justify="space-between" wrap="nowrap">
          <Title order={4}>Choose your puzzles</Title>
          <ActionIcon
            variant="subtle"
            color="gray"
            onClick={onCollapse}
            aria-label="Hide filters"
            title="Hide filters (F)"
            data-testid="hide-filters"
          >
            «
          </ActionIcon>
        </Group>
        <Stack gap={4}>
          <Text size="sm" fw={500}>
            Mode
          </Text>
          <SegmentedControl
            size="xs"
            fullWidth
            value={mode}
            onChange={(v) => onMode(v as TrainingMode)}
            data={MODES.map((m) => ({ value: m.value, label: m.label }))}
            aria-label="Training mode"
            data-testid="mode-control"
          />
          <Text size="xs" c="dimmed" data-testid="mode-description">
            {modeInfo?.description}
          </Text>
        </Stack>
        {mode === "commit_line" && (
          <Switch
            label="Show move count"
            description={
              showLength
                ? "You see how many moves the solution has. Lichess counts these solves for less, because you knew the length."
                : "Hidden: you decide where your line ends. From the next session."
            }
            checked={showLength}
            onChange={(e) => onShowLength(e.currentTarget.checked)}
            data-testid="show-length-switch"
          />
        )}
        {srsMode && (
          <Stack gap={2}>
            <Text fw={600} data-testid="srs-due">
              {srs === null
                ? "…"
                : `${srs.due} ${srs.due === 1 ? "puzzle" : "puzzles"} due now${srs.next_due ? ` · next: ${shortDate(srs.next_due)}` : ""}`}
            </Text>
            <Text size="sm" data-testid="srs-note">
              Spaced repetition serves the puzzles that are due, so the filters below don't apply (only the number of
              puzzles does).
            </Text>
          </Stack>
        )}
        <fieldset
          disabled={srsMode}
          style={{ border: 0, padding: 0, margin: 0, minWidth: 0, opacity: srsMode ? 0.45 : 1 }}
          aria-disabled={srsMode}
          data-testid="filters-fieldset"
        >
        <Stack gap="md">
        <PresetMenu spec={spec} onLoad={onChange} />
        <Switch
          label="Mix by ratio"
          description={ladderOrder ? "Can't be combined with the depth ladder." : "e.g. 50% forks, 30% pins, 20% one-movers"}
          checked={usingRatios}
          disabled={ladderOrder}
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
        <MoveCountSelect value={spec.lengths} onChange={(lengths) => set({ lengths })} setByLadder={ladderOrder} />
        <SideSelect value={spec.side} onChange={(side) => set({ side })} />
        <Accordion variant="contained" chevronPosition="right">
          <Accordion.Item value="more">
            <Accordion.Control data-testid="more-filters">
              <Text size="sm" fw={500}>
                More filters
              </Text>
              <Text size="xs" c="dimmed" data-testid="more-summary">
                {moreSummary(spec, playedCount !== null)}
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
                  excludePlayed={spec.exclude_played_on_lichess}
                  playedCount={playedCount}
                  onChange={(exclude_solved_here, only_my_misses) => set({ exclude_solved_here, only_my_misses })}
                  onPlayed={(exclude_played_on_lichess) => set({ exclude_played_on_lichess })}
                />
              </Stack>
            </Accordion.Panel>
          </Accordion.Item>
        </Accordion>
        <OrderSelect
          value={spec.order}
          endless={spec.queue_size === null}
          onChange={(order) => set({ order })}
          ratios={usingRatios}
          ladder={ladderOrder ? ladder : null}
        />
        </Stack>
        </fieldset>
        <Divider />
        <Group justify="space-between" align="center">
          {srsMode ? (
            <Text size="sm" c="dimmed">
              {srs && srs.due === 0 ? "Nothing to review yet." : "Ready to review."}
            </Text>
          ) : (
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
                {count !== null && ladderOrder && ladder ? ` at ${ladder.label.toLowerCase()}` : ""}
              </Text>
            )}
          </Group>
          )}
        </Group>
        <QueueControls value={spec.queue_size} onChange={(queue_size) => set({ queue_size })} />
        <Switch
          label="Rated"
          description={rated ? "Solves count toward your Lichess puzzle rating." : "Solves sync to Lichess as unrated."}
          checked={rated}
          onChange={(e) => onRated(e.currentTarget.checked)}
          data-testid="rated-switch"
        />
        <Button
          onClick={onStart}
          loading={starting}
          disabled={srsMode ? !srs || srs.due === 0 : count === 0 || countError !== null}
          data-testid="start"
        >
          Start
        </Button>
      </Stack>
      </ScrollArea.Autosize>
    </Paper>
  );
}
