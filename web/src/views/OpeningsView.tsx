// v0.13: the Openings page (REQUIREMENTS §18). Browse the book, learn a line by stepping through or playing along, add
// lines to your repertoire and look after it. Every move here comes from the backend, which takes them from the book,
// the engine, the explorer or you. All text is plain React text.
import {
  Alert,
  Anchor,
  Badge,
  Button,
  Group,
  Loader,
  NumberInput,
  Paper,
  MultiSelect,
  ScrollArea,
  SegmentedControl,
  Stack,
  Switch,
  Tabs,
  Text,
  TextInput,
  Title,
  UnstyledButton,
} from "@mantine/core";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type {
  EngineStatus,
  BookFamily,
  OpeningLine,
  OpeningLines,
  OpeningPage,
  OpeningScope,
  OpeningSettings,
  Repertoire,
  RepertoireRow,
} from "../api/types";
import { Board } from "../components/Board";
import { EngineInstallBanner } from "../components/EngineInstallBanner";
import { EnginePanel } from "../components/EnginePanel";
import { OptionInfo } from "../components/OptionInfo";
import { checkMove, linePositions, moveLabel, sideToMove, sourceLabel, START_FEN } from "../state/openingLine";
import { useJob } from "../state/useJob";

type Color = "white" | "black";
type LearnMode = "step" | "play";

const OPPONENT_REPLY_MS = 350;

function message(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

// ---- Learn: step through or play along (FR-12.6, 12.16) ----------------------------------------------------------

function LearnBoard({
  line,
  color,
  coordinates,
  engine,
  onEngineChanged,
}: {
  line: OpeningLine;
  color: Color;
  coordinates: boolean;
  engine: EngineStatus | null;
  onEngineChanged: () => void;
}) {
  const positions = useMemo(() => linePositions(line.moves), [line]);
  const [step, setStep] = useState(0);
  const [mode, setMode] = useState<LearnMode>("step");
  const [nudge, setNudge] = useState<string | null>(null);
  const [tries, setTries] = useState(0);
  const last = line.moves.length;
  const pos = positions[Math.min(step, last)];
  const analyze = useCallback(
    (fen: string, purpose: "start" | "panel" | "board") => api.analyzeOpeningPosition(fen, purpose, color),
    [color],
  );

  // Play-along: the app makes the other side's moves.
  useEffect(() => {
    if (mode !== "play" || step >= last || sideToMove(pos.fen) === color) return;
    const timer = window.setTimeout(() => setStep((s) => s + 1), OPPONENT_REPLY_MS);
    return () => window.clearTimeout(timer);
  }, [mode, step, last, pos.fen, color]);

  const onMove = useCallback(
    (uci: string) => {
      const result = checkMove(line.moves, step, uci);
      if (result.kind === "correct") {
        setNudge(null);
        setStep((s) => s + 1);
      } else if (result.kind === "wrong") {
        setNudge(result.nudge);
        setTries((n) => n + 1);
      }
    },
    [line, step],
  );

  const yourTurn = mode === "play" && step < last && sideToMove(pos.fen) === color;
  return (
    <Group align="flex-start" gap="lg" wrap="wrap" data-testid="learn-board" data-tries={tries}>
      <div style={{ flex: "1 1 360px", maxWidth: 560 }}>
        {/* A wrong move snaps back: the key changes with each try, so the board redraws at the line's position. */}
        <Board
          key={tries}
          fen={pos.fen}
          orientation={color}
          movable={yourTurn ? color : null}
          lastMove={pos.lastMove}
          onMove={onMove}
          coordinates={coordinates}
          maxWidth={560}
        />
      </div>
      <Stack gap="sm" style={{ flex: "1 1 300px", minWidth: 280 }}>
        <Group gap={6} data-option-group>
          <SegmentedControl
            size="xs"
            value={mode}
            onChange={(v) => {
              setMode(v as LearnMode);
              setStep(0);
              setNudge(null);
            }}
            data={[
              { value: "step", label: "Step through" },
              { value: "play", label: "Play along" },
            ]}
            data-testid="learn-mode"
          />
          <OptionInfo id="openings.learnMode" />
        </Group>
        <Text fw={600} data-testid="learn-line-name">
          {line.name}
        </Text>
        {mode === "step" ? (
          <Group gap="xs">
            <Button size="xs" variant="default" disabled={step <= 0} onClick={() => setStep(0)} aria-label="To the start">
              |‹
            </Button>
            <Button size="xs" variant="default" disabled={step <= 0} onClick={() => setStep(step - 1)} data-testid="learn-back" aria-label="Back">
              ‹
            </Button>
            <Button size="xs" variant="default" disabled={step >= last} onClick={() => setStep(step + 1)} data-testid="learn-forward" aria-label="Forward">
              ›
            </Button>
            <Button size="xs" variant="default" disabled={step >= last} onClick={() => setStep(last)} aria-label="To the end">
              ›|
            </Button>
          </Group>
        ) : (
          <Stack gap={4} data-testid="learn-play-status">
            <Text size="sm">
              {step >= last ? "That's the end of this line. Nothing here is scored." : yourTurn ? "Your move." : "Their move…"}
            </Text>
            {nudge && (
              <Text size="sm" c="orange" data-testid="learn-nudge">
                {nudge}
              </Text>
            )}
            <Button
              size="xs"
              variant="default"
              onClick={() => {
                setStep(0);
                setNudge(null);
              }}
              style={{ alignSelf: "flex-start" }}
              data-testid="learn-restart"
            >
              Start again
            </Button>
          </Stack>
        )}
        <Group gap={4} data-testid="learn-moves">
          {line.moves.map((m, i) => {
            const hidden = mode === "play" && i >= step;
            return (
              <UnstyledButton
                key={i}
                disabled={mode === "play"}
                onClick={() => setStep(i + 1)}
                data-testid={`learn-move-${i}`}
                data-source={m.source}
                style={{ fontSize: 13, padding: "1px 4px", borderRadius: 4, fontWeight: step === i + 1 ? 700 : 400 }}
              >
                {i % 2 === 0 ? `${moveLabel(i)} ` : ""}
                {hidden ? "…" : m.san}
                {!hidden && m.source !== "book" && (
                  <Badge ml={4} size="xs" variant="light" color="gray" style={{ textTransform: "none" }}>
                    {sourceLabel(m.source)}
                  </Badge>
                )}
              </UnstyledButton>
            );
          })}
        </Group>
        <EnginePanel
          analyze={analyze}
          startLabel="Start of the game:"
          startFen={START_FEN}
          fen={mode === "play" && step < last ? START_FEN : pos.fen}
          purpose="panel"
          status={engine}
          onStatusChanged={onEngineChanged}
        />
        <WikibooksPanel sans={line.moves.slice(0, mode === "play" ? 0 : step).map((m) => m.san)} />
      </Stack>
    </Group>
  );
}

// ---- Wikibooks (FR-12.15): fetched only when you open the panel ----------------------------------------------------

function WikibooksPanel({ sans }: { sans: string[] }) {
  const [open, setOpen] = useState(false);
  const [page, setPage] = useState<OpeningPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const moves = sans.join(" ");
  useEffect(() => {
    if (!open) return;
    let alive = true;
    api.getOpeningPage(moves ? moves.split(" ") : []).then(
      (p) => alive && setPage(p),
      (e: unknown) => alive && setError(message(e)),
    );
    return () => {
      alive = false;
    };
  }, [open, moves]);

  return (
    <Paper withBorder p="sm" radius="md" data-testid="wikibooks-panel">
      <Group justify="space-between" gap="xs">
        <Text fw={700} size="sm">
          Wikibooks
        </Text>
        <Button size="compact-xs" variant="subtle" onClick={() => setOpen(!open)} data-testid="wikibooks-toggle">
          {open ? "Hide" : "Read about this position"}
        </Button>
      </Group>
      {open && error && (
        <Text size="sm" c="red">
          {error}
        </Text>
      )}
      {open && page && page.state === "ok" && (
        <Stack gap={6} mt={6}>
          <ScrollArea.Autosize mah={280}>
            <Text size="sm" style={{ whiteSpace: "pre-wrap" }} data-testid="wikibooks-text">
              {page.text}
            </Text>
          </ScrollArea.Autosize>
          <Text size="xs" c="dimmed" data-testid="wikibooks-attribution">
            From Wikibooks, <Anchor size="xs" href={page.url} target="_blank" rel="noreferrer">Chess Opening Theory: {page.label}</Anchor>,{" "}
            <Anchor size="xs" href={page.licence_url} target="_blank" rel="noreferrer">{page.licence}</Anchor>. It's written by volunteers and may be wrong.
          </Text>
        </Stack>
      )}
      {open && page && page.state === "missing" && (
        <Text size="sm" c="dimmed" mt={6} data-testid="wikibooks-missing">
          Wikibooks has no page for this exact move order.
        </Text>
      )}
      {open && page && page.state === "unavailable" && (
        <Text size="sm" c="dimmed" mt={6} data-testid="wikibooks-unavailable">
          Couldn't reach Wikibooks, and this page isn't saved yet.
        </Text>
      )}
      {open && page && page.state === "off" && (
        <Text size="sm" c="dimmed" mt={6} data-testid="wikibooks-off">
          Wikibooks is turned off below.
        </Text>
      )}
    </Paper>
  );
}

// ---- where outside text and popular moves come from (FR-12.2, 12.15) ---------------------------------------------------

const RATING_BANDS = ["0", "1000", "1200", "1400", "1600", "1800", "2000", "2200", "2500"];

function SourceControls({ settings, onChange }: { settings: OpeningSettings; onChange: (s: OpeningSettings) => void }) {
  const save = (use: boolean, source: "lichess" | "masters", ratings: number[]) => {
    if (ratings.length > 0) api.setOpeningSources(use, source, ratings).then(onChange, () => undefined);
  };
  return (
    <Group gap="md" align="flex-end" wrap="wrap" data-testid="opening-sources">
      <Switch
        size="sm"
        checked={settings.use_wikibooks}
        onChange={(e) => save(e.currentTarget.checked, settings.explorer_source, settings.explorer_ratings)}
        label={
          <>
            Use Wikibooks <OptionInfo id="openings.useWikibooks" />
          </>
        }
        data-testid="opening-wikibooks"
      />
      {settings.signed_in ? (
        <>
          <div data-option-group>
            <Text size="sm" fw={500}>
              Popular moves from <OptionInfo id="openings.explorerSource" />
            </Text>
            <SegmentedControl
              size="xs"
              value={settings.explorer_source}
              onChange={(v) => save(settings.use_wikibooks, v as "lichess" | "masters", settings.explorer_ratings)}
              data={[
                { value: "lichess", label: "Lichess games" },
                { value: "masters", label: "Masters" },
              ]}
              data-testid="opening-explorer-source"
            />
          </div>
          {settings.explorer_source === "lichess" && (
            <MultiSelect
              size="xs"
              w={260}
              label={
                <>
                  Rating bands <OptionInfo id="openings.explorerRatings" />
                </>
              }
              data={RATING_BANDS}
              value={settings.explorer_ratings.map(String)}
              onChange={(v) => save(settings.use_wikibooks, settings.explorer_source, v.map(Number))}
              data-testid="opening-explorer-ratings"
            />
          )}
        </>
      ) : (
        <Text size="xs" c="dimmed" data-testid="opening-explorer-signed-out">
          Sign in to Lichess to rank lines by popular moves.
        </Text>
      )}
    </Group>
  );
}

// ---- how much of an opening to show (FR-12.7a, 12.13) --------------------------------------------------------------

function ScopeControls({
  settings,
  onChange,
}: {
  settings: OpeningSettings;
  onChange: (scope: OpeningScope, extend: boolean) => void;
}) {
  const { scope, extend } = settings;
  return (
    <Group gap="md" align="flex-end" wrap="wrap" data-testid="opening-scope">
      <div data-option-group>
        <Text size="sm" fw={500}>
          Lines <OptionInfo id="openings.scope" />
        </Text>
        <SegmentedControl
          size="xs"
          value={scope.preset}
          onChange={(v) => onChange({ ...scope, preset: v as OpeningScope["preset"] }, extend)}
          data={[
            { value: "light", label: "Light" },
            { value: "standard", label: "Standard" },
            { value: "deep", label: "Deep" },
            { value: "custom", label: "Custom" },
          ]}
          data-testid="opening-preset"
        />
      </div>
      {scope.preset === "custom" && (
        <>
          <NumberInput
            size="xs"
            w={110}
            label={
              <>
                Sub-lines <OptionInfo id="openings.subLines" />
              </>
            }
            min={0}
            max={10}
            value={scope.sub_lines}
            onChange={(v) => typeof v === "number" && onChange({ ...scope, sub_lines: v }, extend)}
            data-testid="opening-sub-lines"
          />
          <NumberInput
            size="xs"
            w={130}
            label={
              <>
                Moves per line <OptionInfo id="openings.maxMoves" />
              </>
            }
            min={4}
            max={20}
            value={scope.max_moves}
            onChange={(v) => typeof v === "number" && onChange({ ...scope, max_moves: v }, extend)}
            data-testid="opening-max-moves"
          />
        </>
      )}
      <div data-option-group>
        <Text size="sm" fw={500}>
          After the book <OptionInfo id="openings.extend" />
        </Text>
        <SegmentedControl
          size="xs"
          value={extend ? "extend" : "stop"}
          onChange={(v) => onChange(scope, v === "extend")}
          data={[
            { value: "extend", label: "Extend past the book" },
            { value: "stop", label: "Stop at the book's end" },
          ]}
          data-testid="opening-extend"
        />
      </div>
    </Group>
  );
}

// ---- one opening ----------------------------------------------------------------------------------------------------

function OpeningDetail({
  family,
  coordinates,
  engine,
  onEngineChanged,
  onRepertoireChanged,
}: {
  family: string;
  coordinates: boolean;
  engine: EngineStatus | null;
  onEngineChanged: () => void;
  onRepertoireChanged: () => void;
}) {
  const [color, setColor] = useState<Color>("white");
  const [settings, setSettings] = useState<OpeningSettings | null>(null);
  const [view, setView] = useState<OpeningLines | null>(null);
  const [selected, setSelected] = useState(0);
  const [extendJob, setExtendJob] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [added, setAdded] = useState<string | null>(null);
  const job = useJob(extendJob);

  const reload = useCallback(() => {
    api.getOpeningLines(family).then(setView, (e: unknown) => setError(message(e)));
  }, [family]);

  useEffect(() => {
    api.getOpeningSettings().then(setSettings, (e: unknown) => setError(message(e)));
    reload();
  }, [reload]);

  const jobState = job?.state;
  useEffect(() => {
    if (jobState && jobState !== "running") reload();
  }, [jobState, reload]);

  const change = (scope: OpeningScope, extend: boolean) => {
    const custom = scope.preset === "custom";
    api
      .setOpeningSettings(scope.preset, custom ? scope.sub_lines : null, custom ? scope.max_moves : null, extend)
      .then((s) => {
        setSettings(s);
        setSelected(0);
        reload();
      }, (e: unknown) => setError(message(e)));
  };

  const line = view?.lines[Math.min(selected, view.lines.length - 1)] ?? null;
  const running = job?.state === "running";

  const add = (indices: number[]) => {
    setError(null);
    api.addRepertoireLines(color, family, indices).then((r) => {
      setAdded(
        r.added === 0
          ? "You already have these moves. Nothing changed."
          : `Added ${r.added} ${r.added === 1 ? "move" : "moves"} to your ${color} repertoire.${r.kept ? ` ${r.kept} you already had stayed as they were.` : ""}`,
      );
      onRepertoireChanged();
    }, (e: unknown) => setError(message(e)));
  };

  return (
    <Stack gap="md" data-testid="opening-detail">
      <Group justify="space-between" wrap="wrap">
        <Title order={3}>{family}</Title>
        <Group gap={6} data-option-group>
          <SegmentedControl
            size="xs"
            value={color}
            onChange={(v) => setColor(v as Color)}
            data={[
              { value: "white", label: "As White" },
              { value: "black", label: "As Black" },
            ]}
            data-testid="opening-color"
          />
          <OptionInfo id="openings.color" />
        </Group>
      </Group>
      {settings && <ScopeControls settings={settings} onChange={change} />}
      {settings && <SourceControls settings={settings} onChange={setSettings} />}
      {error && (
        <Alert color="red" data-testid="opening-error">
          {error}
        </Alert>
      )}
      {view && view.extend && view.pending > 0 && (
        <Paper withBorder p="sm" radius="md" data-testid="opening-extend-offer">
          {view.engine_ready ? (
            <Group justify="space-between" wrap="wrap" gap="xs">
              <Text size="sm">
                {running
                  ? job?.message
                  : `${view.pending} ${view.pending === 1 ? "line ends" : "lines end"} before your moves per line. Stockfish can continue them, in the background.`}
              </Text>
              {running ? (
                <Loader size="xs" />
              ) : (
                <Button
                  size="xs"
                  variant="light"
                  data-testid="opening-extend-run"
                  onClick={() => api.startOpeningExtend(family).then((id) => (id ? setExtendJob(id) : reload()), (e: unknown) => setError(message(e)))}
                >
                  Continue with Stockfish
                </Button>
              )}
            </Group>
          ) : (
            <Text size="sm">Install Stockfish to continue these lines past the book.</Text>
          )}
        </Paper>
      )}
      {view && (
        <Stack gap={4} data-testid="opening-lines">
          {view.lines.map((ln, i) => (
            <Group key={`${ln.name}-${i}`} gap="xs" justify="space-between" wrap="nowrap">
              <UnstyledButton onClick={() => setSelected(i)} data-testid={`opening-line-${i}`} style={{ flex: 1, fontWeight: i === selected ? 700 : 400, fontSize: 14 }}>
                {i === 0 ? "Main line: " : ""}
                {ln.name}
                <Text span size="xs" c="dimmed">
                  {" "}
                  ({Math.ceil(ln.moves.length / 2)} moves)
                </Text>
              </UnstyledButton>
              <Button size="compact-xs" variant="subtle" onClick={() => add([i])} data-testid={`opening-add-${i}`}>
                Add to my repertoire
              </Button>
            </Group>
          ))}
          <Button
            size="xs"
            variant="light"
            style={{ alignSelf: "flex-start" }}
            onClick={() => add(view.lines.map((_, i) => i))}
            data-testid="opening-add-all"
          >
            Add all these lines
          </Button>
          {added && (
            <Text size="sm" c="teal" data-testid="opening-added">
              {added}
            </Text>
          )}
        </Stack>
      )}
      {line && (
        <LearnBoard
          key={`${line.name}:${line.moves.length}:${color}`}
          line={line}
          color={color}
          coordinates={coordinates}
          engine={engine}
          onEngineChanged={onEngineChanged}
        />
      )}
    </Stack>
  );
}

// ---- your repertoire (FR-12.4) ------------------------------------------------------------------------------------------

function RepertoireTab({ version }: { version: number }) {
  const [color, setColor] = useState<Color>("white");
  const [rep, setRep] = useState<Repertoire | null>(null);
  const [confirm, setConfirm] = useState<{ row: RepertoireRow; sans: string[] } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getRepertoire(color).then(setRep, (e: unknown) => setError(message(e)));
  }, [color, version]);

  const act = (p: Promise<Repertoire>) => p.then(setRep, (e: unknown) => setError(message(e)));

  return (
    <Stack gap="sm" data-testid="repertoire-tab">
      <Group gap={6} data-option-group>
        <SegmentedControl
          size="xs"
          value={color}
          onChange={(v) => {
            setColor(v as Color);
            setConfirm(null);
          }}
          data={[
            { value: "white", label: "White" },
            { value: "black", label: "Black" },
          ]}
          data-testid="repertoire-color"
        />
        <OptionInfo id="repertoire.color" />
      </Group>
      {error && <Alert color="red">{error}</Alert>}
      {rep && rep.rows.length === 0 && (
        <Text size="sm" c="dimmed" data-testid="repertoire-empty">
          Nothing here yet. Pick an opening in the Book tab and add its lines.
        </Text>
      )}
      {rep && rep.openings.length > 0 && (
        <Text size="sm" data-testid="repertoire-openings">
          {rep.openings.map((o) => `${o.name} (${o.eco})`).join(", ")}
        </Text>
      )}
      {confirm && (
        <Alert color="orange" data-testid="repertoire-confirm">
          <Text size="sm">
            Remove {confirm.sans.length} {confirm.sans.length === 1 ? "move" : "moves"}: {confirm.sans.join(" ")}. A position another line still reaches stays.
          </Text>
          <Group gap="xs" mt="xs">
            <Button
              size="xs"
              color="red"
              data-testid="repertoire-confirm-remove"
              onClick={() => {
                act(api.removeRepertoireMove(color, confirm.row.position_key, confirm.row.move_uci));
                setConfirm(null);
              }}
            >
              Remove
            </Button>
            <Button size="xs" variant="default" onClick={() => setConfirm(null)}>
              Keep
            </Button>
          </Group>
        </Alert>
      )}
      {rep && rep.rows.length > 0 && (
        <ScrollArea.Autosize mah={560}>
          <Stack gap={0} data-testid="repertoire-rows">
            {rep.rows.map((r) => (
              <Group
                key={`${r.position_key}|${r.move_uci}`}
                gap="xs"
                wrap="nowrap"
                style={{ paddingLeft: Math.min(r.depth, 24) * 12 }}
                data-testid="repertoire-row"
                data-san={r.san}
              >
                <Text size="sm" fw={r.yours ? 700 : 400} style={{ minWidth: 56 }}>
                  {r.san}
                </Text>
                {r.is_main && (
                  <Badge size="xs" variant="light" style={{ textTransform: "none" }}>
                    Main
                  </Badge>
                )}
                {r.source !== "book" && (
                  <Badge size="xs" variant="light" color="gray" style={{ textTransform: "none" }}>
                    {sourceLabel(r.source)}
                  </Badge>
                )}
                {r.transposes && (
                  <Text size="xs" c="dimmed">
                    transposes
                  </Text>
                )}
                {!r.is_main && (
                  <Button size="compact-xs" variant="subtle" onClick={() => act(api.setRepertoireMain(color, r.position_key, r.move_uci))} data-testid="repertoire-main">
                    Make main
                  </Button>
                )}
                <Button size="compact-xs" variant="subtle" aria-label={`Move ${r.san} up`} onClick={() => act(api.moveRepertoireMove(color, r.position_key, r.move_uci, "up"))}>
                  ↑
                </Button>
                <Button size="compact-xs" variant="subtle" aria-label={`Move ${r.san} down`} onClick={() => act(api.moveRepertoireMove(color, r.position_key, r.move_uci, "down"))}>
                  ↓
                </Button>
                <Button
                  size="compact-xs"
                  variant="subtle"
                  color="red"
                  data-testid="repertoire-remove"
                  onClick={() =>
                    api.previewRepertoireRemoval(color, r.position_key, r.move_uci).then((sans) => setConfirm({ row: r, sans }), (e: unknown) => setError(message(e)))
                  }
                >
                  Remove
                </Button>
              </Group>
            ))}
          </Stack>
        </ScrollArea.Autosize>
      )}
    </Stack>
  );
}

// ---- the page ---------------------------------------------------------------------------------------------------------------

export function OpeningsView({ initialFamily, coordinates }: { initialFamily: string | null; coordinates: boolean }) {
  const [ready, setReady] = useState<boolean | null>(null);
  const [importJob, setImportJob] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<BookFamily[]>([]);
  const [family, setFamily] = useState<string | null>(initialFamily);
  const [engine, setEngine] = useState<EngineStatus | null>(null);
  const [repVersion, setRepVersion] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const job = useJob(importJob);
  const started = useRef(false);

  const refreshEngine = useCallback(() => {
    api.getEngineStatus().then(setEngine, () => undefined);
  }, []);
  useEffect(refreshEngine, [refreshEngine]);

  useEffect(() => {
    api.getOpeningBookStatus().then((s) => {
      setReady(s.ready);
      if (!s.ready && !started.current) {
        started.current = true;
        api.startOpeningBookImport().then(setImportJob, (e: unknown) => setError(message(e)));
      }
    }, (e: unknown) => setError(message(e)));
  }, []);

  useEffect(() => {
    if (job?.state === "done") {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setReady(true);
    } else if (job?.state === "failed") {
      setError(job.message);
    }
  }, [job]);

  useEffect(() => {
    if (!ready) return;
    api.getOpeningFamilies(query).then(setFound, (e: unknown) => setError(message(e)));
  }, [ready, query]);

  if (error && !ready) {
    return (
      <Alert color="red" m="md" data-testid="openings-error">
        {error}
      </Alert>
    );
  }
  if (!ready) {
    return (
      <Group gap="xs" p="md" data-testid="openings-importing">
        <Loader size="sm" />
        <Text size="sm">{job?.message ?? "Getting the opening book ready…"}</Text>
      </Group>
    );
  }
  return (
    <Stack p="md" gap="md" data-testid="openings-view">
      {engine && engine.state !== "ready" && <EngineInstallBanner status={engine} onChanged={refreshEngine} />}
      <Tabs defaultValue="book" keepMounted={false}>
        <Tabs.List>
          <Tabs.Tab value="book" data-testid="openings-tab-book">
            Book
          </Tabs.Tab>
          <Tabs.Tab value="repertoire" data-testid="openings-tab-repertoire">
            My repertoire
          </Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="book" pt="md">
          <Group align="flex-start" gap="lg" wrap="wrap">
            <Stack gap="xs" style={{ flex: "0 0 260px" }}>
              <div data-no-tip="free text: search box">
                <TextInput
                  size="xs"
                  placeholder="Search by name or ECO code"
                  aria-label="Search openings"
                  value={query}
                  onChange={(e) => setQuery(e.currentTarget.value)}
                  data-testid="openings-search"
                />
              </div>
              <ScrollArea.Autosize mah={640}>
                <Stack gap={2} data-testid="openings-list">
                  {found.map((f) => (
                    <UnstyledButton
                      key={f.name}
                      onClick={() => setFamily(f.name)}
                      data-testid="opening-family"
                      data-name={f.name}
                      style={{ fontSize: 14, padding: "2px 6px", borderRadius: 4, fontWeight: f.name === family ? 700 : 400 }}
                    >
                      {f.name}{" "}
                      <Text span size="xs" c="dimmed">
                        {f.eco} · {f.lines}
                      </Text>
                    </UnstyledButton>
                  ))}
                  {found.length === 0 && (
                    <Text size="sm" c="dimmed">
                      No opening matches that.
                    </Text>
                  )}
                </Stack>
              </ScrollArea.Autosize>
            </Stack>
            <div style={{ flex: "1 1 600px", minWidth: 0 }}>
              {family ? (
                <OpeningDetail
                  key={family}
                  family={family}
                  coordinates={coordinates}
                  engine={engine}
                  onEngineChanged={refreshEngine}
                  onRepertoireChanged={() => setRepVersion((v) => v + 1)}
                />
              ) : (
                <Text size="sm" c="dimmed" data-testid="openings-pick">
                  Pick an opening to see its lines.
                </Text>
              )}
            </div>
          </Group>
        </Tabs.Panel>
        <Tabs.Panel value="repertoire" pt="md">
          <RepertoireTab version={repVersion} />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}
