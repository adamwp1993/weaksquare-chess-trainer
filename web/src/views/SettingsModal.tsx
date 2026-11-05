import { useEffect, useRef } from "react";
import {
  Button,
  Group,
  Modal,
  SegmentedControl,
  Select,
  Slider,
  Stack,
  Switch,
  Text,
  Title,
  useMantineColorScheme,
} from "@mantine/core";
import type { AccountStatus, SoundSettings } from "../api/types";
import { AccountPanel } from "../components/AccountPanel";
import { AiSettingsPanel } from "../components/AiSettingsPanel";
import { CoachSettingsPanel } from "../components/CoachSettingsPanel";
import { GamesSettingsPanel } from "../components/GamesSettingsPanel";
import { EngineSettingsPanel } from "../components/EngineSettingsPanel";
import { DebugPanel, TrainingSettingsPanel } from "../components/TrainingSettingsPanel";
import { sounds as player } from "../sound/player";

const SETS: { value: SoundSettings["set"]; label: string }[] = [
  { value: "sfx", label: "Standard effects (sfx)" },
  { value: "piano", label: "Piano" },
  { value: "nes", label: "8-bit (NES)" },
  { value: "futuristic", label: "Futuristic" },
];

// The gear settings (FR-1.8): your Lichess account, appearance (FR-1.12), sounds (FR-1.13), the engine
// (FR-7.4, 7.5), training (v0.5: FR-4.5, 4.6), AI explanations and their cost (v0.7: FR-1.2–1.4, §9.3)
// and, in --dev runs, Debug (fast-forward time), saved in
// user.db through the bridge and applied at once. The same dialog opens from the gear and from ☰.
export function SettingsModal({
  opened,
  onClose,
  coordinates,
  onCoordinates,
  sounds,
  onSounds,
  autoCheck,
  onAutoCheck,
  account,
  onAccountChanged,
  timeOffset = null,
  onTimeOffset = () => undefined,
  focusAi = false,
}: {
  /** Open scrolled to AI explanations (the spend indicator, v0.7-B5). */
  focusAi?: boolean;
  /** FR-4.6 fast-forward: a number in --dev runs, null in the real app (no Debug section). */
  timeOffset?: number | null;
  onTimeOffset?: (days: number) => void;
  account: AccountStatus | null;
  onAccountChanged: () => void;
  opened: boolean;
  onClose: () => void;
  coordinates: boolean;
  onCoordinates: () => void;
  sounds: SoundSettings;
  onSounds: (s: SoundSettings) => void;
  autoCheck: boolean;
  onAutoCheck: (on: boolean) => void;
}) {
  const { colorScheme, setColorScheme } = useMantineColorScheme();
  const aiRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!opened || !focusAi) return;
    const t = window.setTimeout(() => aiRef.current?.scrollIntoView({ block: "start" }), 50);
    return () => window.clearTimeout(t);
  }, [opened, focusAi]);

  return (
    <Modal opened={opened} onClose={onClose} title="Settings" size="lg">
      <Stack gap="lg" data-testid="settings">
        <Stack gap="xs">
          <Title order={5}>Lichess account</Title>
          <AccountPanel account={account} onChanged={onAccountChanged} />
        </Stack>
        <Stack gap="xs">
          <Title order={5}>Appearance</Title>
          <SegmentedControl
            value={colorScheme}
            onChange={(v) => setColorScheme(v as "light" | "dark" | "auto")}
            data={[
              { value: "light", label: "Light" },
              { value: "dark", label: "Dark" },
              { value: "auto", label: "Match system" },
            ]}
            aria-label="Color scheme"
            data-testid="color-scheme"
          />
          <Text size="xs" c="dimmed">
            Match system follows the Windows app mode (Settings → Personalization → Colors), even while the app is open.
          </Text>
          <Switch label="Board coordinates" checked={coordinates} onChange={onCoordinates} data-testid="coordinates-switch" />
        </Stack>

        <Stack gap="xs">
          <Title order={5}>Sounds</Title>
          <Switch
            label="Move sounds"
            description="Moves, captures, checks, mates, and solved or failed puzzles."
            checked={sounds.on}
            onChange={(e) => onSounds({ ...sounds, on: e.currentTarget.checked })}
            data-testid="sounds-switch"
          />
          <Text size="sm" mt={4}>
            Volume
          </Text>
          <Slider
            value={sounds.volume}
            onChangeEnd={(volume) => onSounds({ ...sounds, volume })}
            min={0}
            max={100}
            step={5}
            disabled={!sounds.on}
            label={(v) => `${v}%`}
            aria-label="Volume"
            data-testid="volume"
          />
          <Group align="end" gap="xs">
            <Select
              label="Sound set"
              data={SETS}
              value={sounds.set}
              onChange={(v) => v && onSounds({ ...sounds, set: v as SoundSettings["set"] })}
              allowDeselect={false}
              disabled={!sounds.on}
              style={{ flex: 1 }}
              data-testid="sound-set"
            />
            <Button variant="default" disabled={!sounds.on} onClick={() => player.play("capture")} data-testid="sound-test">
              Play a sample
            </Button>
          </Group>
          <Text size="xs" c="dimmed">
            The sound sets are by Enigmahack for Lichess (AGPL-3.0). See web/public/sounds/CREDITS.md.
          </Text>
        </Stack>

        <Stack gap="xs">
          <Title order={5}>Engine</Title>
          {opened && <EngineSettingsPanel />}
        </Stack>

        <Stack gap="xs">
          <Title order={5}>Training</Title>
          {opened && <TrainingSettingsPanel />}
        </Stack>

        <Stack gap="xs" data-testid="settings-games">
          <Title order={5}>Games</Title>
          {opened && <GamesSettingsPanel />}
        </Stack>

        <Stack gap="xs" data-testid="settings-coach">
          <Title order={5}>Coach</Title>
          {opened && <CoachSettingsPanel />}
        </Stack>

        <Stack gap="xs" data-testid="settings-ai" ref={aiRef}>
          <Title order={5}>AI explanations</Title>
          {opened && <AiSettingsPanel full />}
        </Stack>

        <Stack gap="xs">
          <Title order={5}>Puzzle database</Title>
          <Switch
            label="Check for a newer puzzle database once a day"
            description="Asks database.lichess.org for its checksum list, the file's date and size, and the puzzle count. Nothing about you is sent."
            checked={autoCheck}
            onChange={(e) => onAutoCheck(e.currentTarget.checked)}
            data-testid="auto-check-switch"
          />
        </Stack>

        {timeOffset !== null && (
          <Stack gap="xs">
            <Title order={5}>Debug</Title>
            {opened && <DebugPanel offset={timeOffset} onOffset={onTimeOffset} />}
          </Stack>
        )}
      </Stack>
    </Modal>
  );
}
