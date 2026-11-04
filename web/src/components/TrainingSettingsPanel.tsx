import { Button, Group, NumberInput, SegmentedControl, Stack, Text, TextInput } from "@mantine/core";
import { useEffect, useState } from "react";
import { api } from "../api";

// Settings → Training (v0.5): the depth ladder's threshold and window (FR-4.5) and the Spaced
// repetition boxes (FR-4.6); v0.6: when to ask why you missed (FR-5.8) and the Rushed threshold
// (FR-5.9). Saved through the bridge, which validates them again.
export function TrainingSettingsPanel() {
  const [threshold, setThreshold] = useState<number | null>(null);
  const [window, setWindow] = useState<number | null>(null);
  const [intervals, setIntervals] = useState("");
  const [ask, setAsk] = useState<"always" | "game_review" | "off">("always");
  const [rushed, setRushed] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  useEffect(() => {
    api.getSettings().then(
      (s) => {
        setThreshold(s.ladder_threshold);
        setWindow(s.ladder_window);
        setIntervals(s.srs_intervals.join(", "));
        setAsk(s.reasons_ask);
        setRushed(s.rushed_s);
      },
      () => undefined,
    );
  }, []);

  const save = async (what: string, run: () => Promise<void>) => {
    setError(null);
    setSaved(null);
    try {
      await run();
      setSaved(what);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const saveIntervals = () => {
    const days = intervals
      .split(/[,\s]+/)
      .filter(Boolean)
      .map(Number);
    return save("Review boxes saved.", () => api.setSetting("srs.intervals", days));
  };

  if (threshold === null || window === null) return null;
  return (
    <Stack gap="xs" data-testid="training-settings">
      <Text size="sm" fw={500}>
        Depth ladder
      </Text>
      <Group grow align="end">
        <NumberInput
          label="Move up at (%)"
          min={10}
          max={100}
          value={threshold}
          onChange={(v) => typeof v === "number" && setThreshold(v)}
          onBlur={() => save("Ladder threshold saved.", () => api.setSetting("ladder.threshold", threshold))}
          data-testid="ladder-threshold"
        />
        <NumberInput
          label="Over the last (puzzles)"
          min={3}
          max={100}
          value={window}
          onChange={(v) => typeof v === "number" && setWindow(v)}
          onBlur={() => save("Ladder window saved.", () => api.setSetting("ladder.window", window))}
          data-testid="ladder-window"
        />
      </Group>
      <Text size="xs" c="dimmed">
        With Order set to Depth ladder, you move from 2-move to 3-move to 4+ move puzzles once your accuracy at a
        level reaches this, over that many puzzles. You never move back down.
      </Text>
      <Text size="sm" fw={500} mt="xs">
        Spaced repetition
      </Text>
      <Group align="end" gap="xs">
        <TextInput
          label="Review boxes (days)"
          value={intervals}
          onChange={(e) => setIntervals(e.currentTarget.value)}
          style={{ flex: 1 }}
          data-testid="srs-intervals"
        />
        <Button variant="default" onClick={saveIntervals} data-testid="srs-intervals-save">
          Save
        </Button>
      </Group>
      <Text size="xs" c="dimmed">
        A missed puzzle comes back after the first number of days; each time you solve it in Spaced repetition it
        waits for the next one. Solving it from the last box retires it. 2 to 10 boxes, each longer than the one before.
      </Text>
      <Text size="sm" fw={500} mt="xs">
        Why you missed it
      </Text>
      <Group align="end" gap="md">
        <Stack gap={2}>
          <Text size="sm">Ask why you missed</Text>
          <SegmentedControl
            size="xs"
            value={ask}
            onChange={(v) => {
              const value = v as "always" | "game_review" | "off";
              setAsk(value);
              const said = {
                always: "You'll be asked after each failed puzzle and on your game mistakes.",
                game_review: "You'll be asked only in Game Review.",
                off: "You won't be asked.",
              }[value];
              save(said, () => api.setSetting("reasons.ask", value));
            }}
            data={[
              { value: "always", label: "Always" },
              { value: "game_review", label: "Game Review only" },
              { value: "off", label: "Off" },
            ]}
            aria-label="Ask why you missed"
            data-testid="reasons-ask"
          />
        </Stack>
        {rushed !== null && (
          <NumberInput
            label="Suggest Rushed under (seconds)"
            min={1}
            max={30}
            value={rushed}
            onChange={(v) => typeof v === "number" && setRushed(v)}
            onBlur={() => save("Rushed threshold saved.", () => api.setSetting("reasons.rushed_s", rushed))}
            style={{ flex: 1 }}
            data-testid="reasons-rushed"
          />
        )}
      </Group>
      <Text size="xs" c="dimmed">
        After a failed puzzle, six chips ask why you missed it (keys 1–6). The app highlights a likely reason, for
        example Rushed when you moved faster than this; it's only saved when you pick one.
      </Text>
      {error && (
        <Text size="xs" c="red" data-testid="training-settings-error">
          {error}
        </Text>
      )}
      {saved && !error && (
        <Text size="xs" c="green">
          {saved}
        </Text>
      )}
    </Stack>
  );
}

// Settings → Debug, in --dev runs only (FR-4.6): move the app's clock ahead by whole days.
export function DebugPanel({ offset, onOffset }: { offset: number; onOffset: (days: number) => void }) {
  const [days, setDays] = useState(offset);
  const [error, setError] = useState<string | null>(null);
  const apply = async (value: number) => {
    setError(null);
    try {
      await api.setTimeOffset(value);
      setDays(value);
      onOffset(value);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return (
    <Stack gap="xs" data-testid="debug-settings">
      <Group align="end" gap="xs">
        <NumberInput
          label="Fast-forward (days)"
          min={0}
          max={3650}
          value={days}
          onChange={(v) => typeof v === "number" && setDays(v)}
          style={{ flex: 1 }}
          data-testid="time-offset"
        />
        <Button variant="default" onClick={() => apply(days)} data-testid="time-offset-apply">
          Apply
        </Button>
        <Button variant="subtle" onClick={() => apply(0)} disabled={offset === 0} data-testid="time-offset-reset">
          Back to today
        </Button>
      </Group>
      <Text size="xs" c="dimmed">
        Dev runs only. Moves the app's clock ahead so Spaced-repetition misses come due; new attempts get the moved
        date too.
      </Text>
      {error && (
        <Text size="xs" c="red">
          {error}
        </Text>
      )}
    </Stack>
  );
}
