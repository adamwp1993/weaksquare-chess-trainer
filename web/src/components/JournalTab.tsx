// FR-10.67-10.70: the Coach's Journal tab: one timeline of your notes, game reflections and the automatic daily log,
// newest first, with filters and search. Entries stay on this PC unless you turn on Include my journal for one AI run
// (FR-10.71). Everything is plain React text, never HTML.
import { Alert, Anchor, Badge, Button, Chip, Group, Paper, Select, Stack, Text, TextInput, Textarea, Title } from "@mantine/core";
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { JournalFilters } from "../api/ApiClient";
import type { DayLog, JournalEntry, JournalGame, JournalItem } from "../api/types";
import { Labeled, OptionInfo } from "./OptionInfo";
import { dayLabel } from "./PlanChecklist";

const MAX = 5000;
const pct = (x: number | null) => (x === null ? "—" : `${Math.round(x * 100)}%`);

export interface JournalDraft {
  prompt: string | null;
  game_id: number | null;
  weakness_key: string | null;
  plan_day_id: number | null;
  plan_task_id: number | null;
}

function LogView({ log }: { log: DayLog }) {
  const lines: string[] = [];
  if (log.overall.attempts) {
    const modes = log.by_mode.map((m) => `${m.label} ${m.attempts}`).join(", ");
    const sources = log.by_source.map((s) => `${s.label} ${s.attempts}`).join(", ");
    lines.push(`Puzzles: ${log.overall.solved} of ${log.overall.attempts} solved first try (${pct(log.overall.accuracy)}). ${modes}. ${sources}.`);
  } else if (log.by_mode.length) {
    lines.push(`Puzzles: ${log.by_mode.map((m) => `${m.label} ${m.attempts}`).join(", ")}.`);
  }
  if (log.missed_themes.length) lines.push(`Missed most: ${log.missed_themes.join(", ")}.`);
  const games = [
    log.games_synced ? `${log.games_synced} synced` : "",
    log.games_analyzed ? `${log.games_analyzed} analyzed` : "",
    log.games_reviewed ? `${log.games_reviewed} reviewed` : "",
  ].filter(Boolean);
  if (games.length) lines.push(`Games: ${games.join(", ")}.`);
  if (log.retries) lines.push(`Retry: ${log.retries_found} of ${log.retries} found.`);
  if (log.plan_tasks_done) lines.push(`Plan tasks done: ${log.plan_tasks_done}.`);
  log.coach_runs.forEach((top) => lines.push(`Coach run${top ? `: top weakness ${top}` : ""}.`));
  return (
    <Paper withBorder p="xs" bg="var(--mantine-color-default-hover)" data-testid="journal-log">
      <Text size="xs" c="dimmed">
        {dayLabel(log.date)} · Daily log
      </Text>
      {lines.map((l, i) => (
        <Text key={i} size="sm">
          {l}
        </Text>
      ))}
    </Paper>
  );
}

function EntryView({
  e,
  weaknessLabel,
  onOpen,
  onChanged,
  onError,
}: {
  e: JournalEntry;
  weaknessLabel: string | null;
  onOpen: (gameId: number, ply: number) => void;
  onChanged: () => void;
  onError: (m: string) => void;
}) {
  const [editing, setEditing] = useState<string | null>(null);
  const save = () =>
    api.editJournalEntry(e.id, editing ?? "", e.weakness_key).then(() => {
      setEditing(null);
      onChanged();
    }, (err: Error) => onError(err.message)); // prettier-ignore
  return (
    <Paper withBorder p="xs" data-testid={`journal-entry-${e.id}`}>
      <Group justify="space-between" wrap="nowrap">
        <Group gap={6}>
          <Text size="xs" c="dimmed">
            {dayLabel(e.entry_date)}
          </Text>
          <Badge size="xs" variant="light" color={e.kind === "reflection" ? "indigo" : "gray"}>
            {e.kind === "reflection" ? "Game reflection" : "Note"}
          </Badge>
          {e.weakness_key && (
            <Badge size="xs" variant="outline">
              {weaknessLabel ?? e.weakness_key}
            </Badge>
          )}
          {e.game_id !== null && (
            <Anchor size="xs" component="button" onClick={() => onOpen(e.game_id!, e.ply === null ? 0 : e.ply + 1)} data-testid={`journal-open-${e.id}`}>
              {e.game_label}
              {e.move ? ` · ${e.move}` : ""}
            </Anchor>
          )}
        </Group>
        {editing === null && (
          <Group gap={4} wrap="nowrap">
            <Button size="compact-xs" variant="subtle" onClick={() => setEditing(e.text)} data-testid={`journal-edit-${e.id}`}>
              Edit
            </Button>
            <Button
              size="compact-xs"
              variant="subtle"
              color="red"
              onClick={() => api.deleteJournalEntry(e.id).then(onChanged, (err: Error) => onError(err.message))}
              data-testid={`journal-delete-${e.id}`}
            >
              Delete
            </Button>
          </Group>
        )}
      </Group>
      {editing === null ? (
        <Text size="sm" style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
          {e.text}
        </Text>
      ) : (
        <Stack gap={4} mt={4}>
          <Textarea autosize minRows={2} maxLength={MAX} value={editing} onChange={(ev) => setEditing(ev.currentTarget.value)} data-no-tip="your own words" data-testid={`journal-edit-text-${e.id}`} />
          <Group gap={4}>
            <Button size="compact-xs" onClick={save} data-testid={`journal-save-${e.id}`}>
              Save
            </Button>
            <Button size="compact-xs" variant="default" onClick={() => setEditing(null)}>
              Cancel
            </Button>
          </Group>
        </Stack>
      )}
    </Paper>
  );
}

export function JournalTab({
  weaknesses,
  draft,
  onClearDraft,
  onOpen,
  onChanged,
}: {
  weaknesses: { value: string; label: string }[]; // from your latest report, for tagging and the filter
  draft: JournalDraft | null; // a reflection task's Start
  onClearDraft: () => void;
  /** Opens Game Review with this many moves played: a note on a move shows that move. */
  onOpen: (gameId: number, movesPlayed: number) => void;
  onChanged: () => void; // an entry saved from a task ticks it
}) {
  const [text, setText] = useState("");
  const [tag, setTag] = useState<string | null>(draft?.weakness_key ?? null);
  const [items, setItems] = useState<JournalItem[]>([]);
  const [windowStart, setWindowStart] = useState<string | null>(null);
  const [older, setOlder] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<JournalFilters>({ kinds: [] });
  const [query, setQuery] = useState("");
  const [filterGames, setFilterGames] = useState<JournalGame[]>([]);
  // FR-10.67: what the composer can tag, besides a weakness.
  const [gameTag, setGameTag] = useState<string | null>(draft?.game_id ? String(draft.game_id) : null);
  const [dayTag, setDayTag] = useState<string | null>(draft?.plan_day_id ? String(draft.plan_day_id) : null);
  const [gameOptions, setGameOptions] = useState<{ value: string; label: string }[]>([]);
  const [dayOptions, setDayOptions] = useState<{ value: string; label: string }[]>([]);
  useEffect(() => {
    api.listGames({ limit: 50 }).then((p) => setGameOptions(p.games.map((g) => ({ value: String(g.id), label: `${g.white ?? "?"} – ${g.black ?? "?"} (${(g.played_at ?? "").slice(0, 10)})` }))), () => undefined); // prettier-ignore
    api.getCurrentPlan().then((p) => setDayOptions((p?.days ?? []).map((d) => ({ value: String(d.id), label: `Week ${d.week} · ${dayLabel(d.date)}` }))), () => undefined); // prettier-ignore
  }, []);

  const load = useCallback(() => {
    api.getJournal({ ...filters, query: query.trim() || undefined }).then((t) => {
      setItems(t.items);
      setWindowStart(t.window_start);
      setOlder(t.older);
      setFilterGames(t.games);
    }, (e: Error) => setError(e.message)); // prettier-ignore
  }, [filters, query]);
  useEffect(load, [load]);

  const loadOlder = () => {
    if (!windowStart) return;
    api.getJournal({ ...filters, query: query.trim() || undefined, before: windowStart }).then((t) => {
      setItems([...items, ...t.items]);
      setWindowStart(t.window_start);
      setOlder(t.older);
    }, (e: Error) => setError(e.message)); // prettier-ignore
  };
  const add = () => {
    setError(null);
    api
      .addJournalEntry({
        text, weakness_key: tag, game_id: gameTag ? Number(gameTag) : null, plan_day_id: dayTag ? Number(dayTag) : null,
        plan_task_id: draft?.plan_task_id ?? null,
      }) // prettier-ignore
      .then(() => {
        setText("");
        setTag(null);
        setGameTag(null);
        setDayTag(null);
        onClearDraft();
        load();
        onChanged();
      }, (e: Error) => setError(e.message)); // prettier-ignore
  };

  return (
    <Stack gap="md" data-testid="journal-tab">
      <Paper withBorder p="md" data-testid="journal-composer">
        <Stack gap="xs">
          <Title order={5}>Write a note</Title>
          {draft?.prompt && (
            <Alert color="blue" p="xs" withCloseButton onClose={onClearDraft} data-testid="journal-prompt">
              {draft.prompt}
            </Alert>
          )}
          <Textarea
            autosize
            minRows={3}
            maxLength={MAX}
            placeholder="What did you notice? What will you do differently?"
            value={text}
            onChange={(e) => setText(e.currentTarget.value)}
            data-no-tip="your own words"
            data-testid="journal-text"
          />
          <Group justify="space-between" align="flex-end">
            <Select
              w={280}
              size="xs"
              clearable
              label={<Labeled id="journal.tag">Tag a weakness (optional)</Labeled>}
              value={tag}
              onChange={setTag}
              data={weaknesses}
              data-testid="journal-tag"
            />
            <Select
              w={280}
              size="xs"
              clearable
              searchable
              label={<Labeled id="journal.tagGame">Tag a game (optional)</Labeled>}
              value={gameTag}
              onChange={setGameTag}
              data={gameOptions}
              data-testid="journal-tag-game"
            />
            <Select
              w={200}
              size="xs"
              clearable
              label={<Labeled id="journal.tagDay">Tag a plan day (optional)</Labeled>}
              value={dayTag}
              onChange={setDayTag}
              data={dayOptions}
              data-testid="journal-tag-day"
            />
            <Group gap="xs">
              <Text size="xs" c="dimmed" data-testid="journal-count">
                {text.length.toLocaleString("en-US")} / {MAX.toLocaleString("en-US")}
              </Text>
              <Button size="xs" onClick={add} disabled={!text.trim()} data-testid="journal-save">
                Save
              </Button>
            </Group>
          </Group>
          <Text size="xs" c="dimmed">
            Your journal stays on this PC. It goes to the AI only if you turn on Include my journal for a run, after a preview.
          </Text>
        </Stack>
      </Paper>
      <Paper withBorder p="sm" data-testid="journal-filters">
        <Group align="flex-end" gap="sm">
          <Stack gap={4} data-option-group>
            <Text size="sm" fw={500}>
              Show
              <OptionInfo id="journal.show" />
            </Text>
            <Chip.Group multiple value={filters.kinds ?? []} onChange={(v) => setFilters({ ...filters, kinds: v as JournalFilters["kinds"] })}>
              <Group gap={4}>
                <Chip size="xs" value="note" wrapperProps={{ "data-testid": "journal-filter-note" }}>
                  Notes
                </Chip>
                <Chip size="xs" value="reflection" wrapperProps={{ "data-testid": "journal-filter-reflection" }}>
                  Reflections
                </Chip>
                <Chip size="xs" value="log" wrapperProps={{ "data-testid": "journal-filter-log" }}>
                  Daily log
                </Chip>
              </Group>
            </Chip.Group>
          </Stack>
          <Select
            w={220}
            size="xs"
            clearable
            label={<Labeled id="journal.filterWeakness">Weakness</Labeled>}
            value={filters.weakness_key ?? null}
            onChange={(v) => setFilters({ ...filters, weakness_key: v ?? undefined })}
            data={weaknesses}
            data-testid="journal-filter-weakness"
          />
          <Select
            w={220}
            size="xs"
            clearable
            label={<Labeled id="journal.filterGame">Game</Labeled>}
            value={filters.game_id ? String(filters.game_id) : null}
            onChange={(v) => setFilters({ ...filters, game_id: v ? Number(v) : undefined })}
            data={filterGames.map((g) => ({ value: String(g.id), label: g.label }))}
            data-testid="journal-filter-game"
          />
          <TextInput
            size="xs"
            type="date"
            label={<Labeled id="journal.from">From</Labeled>}
            value={filters.date_from ?? ""}
            onChange={(e) => setFilters({ ...filters, date_from: e.currentTarget.value || undefined })}
            data-testid="journal-filter-from"
          />
          <TextInput
            size="xs"
            type="date"
            label={<Labeled id="journal.to">To</Labeled>}
            value={filters.date_to ?? ""}
            onChange={(e) => setFilters({ ...filters, date_to: e.currentTarget.value || undefined })}
            data-testid="journal-filter-to"
          />
          <TextInput
            size="xs"
            label="Search"
            placeholder="Words in your entries"
            value={query}
            onChange={(e) => setQuery(e.currentTarget.value)}
            data-no-tip="a search box"
            data-testid="journal-search"
          />
        </Group>
      </Paper>
      {error && (
        <Alert color="red" p="xs" data-testid="journal-error">
          {error}
        </Alert>
      )}
      <Stack gap="xs" data-testid="journal-timeline">
        {items.length === 0 && (
          <Text size="sm" c="dimmed" data-testid="journal-empty">
            Nothing here for these days and filters.
          </Text>
        )}
        {items.map((i) =>
          i.entry ? (
            <EntryView key={`e${i.entry.id}`} e={i.entry} weaknessLabel={weaknesses.find((w) => w.value === i.entry?.weakness_key)?.label ?? null} onOpen={onOpen} onChanged={load} onError={setError} />
          ) : i.log ? (
            <LogView key={`l${i.date}`} log={i.log} />
          ) : null,
        )}
        {older && (
          <Group>
            <Button size="xs" variant="subtle" onClick={loadOlder} data-testid="journal-older">
              Show older days
            </Button>
          </Group>
        )}
      </Stack>
    </Stack>
  );
}
