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
import type { SoundSettings } from "../api/types";
import { sounds as player } from "../sound/player";

const SETS: { value: SoundSettings["set"]; label: string }[] = [
  { value: "sfx", label: "Standard effects (sfx)" },
  { value: "piano", label: "Piano" },
  { value: "nes", label: "8-bit (NES)" },
  { value: "futuristic", label: "Futuristic" },
];

// FR-1.12 and FR-1.13: appearance and sounds, saved in user.db through the bridge and applied at once.
// (The gear settings of FR-1.8 arrive with the Lichess sign-in; these move there then.)
export function SettingsModal({
  opened,
  onClose,
  coordinates,
  onCoordinates,
  sounds,
  onSounds,
  autoCheck,
  onAutoCheck,
}: {
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

  return (
    <Modal opened={opened} onClose={onClose} title="Settings" size="md">
      <Stack gap="lg" data-testid="settings">
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
          <Title order={5}>Puzzle database</Title>
          <Switch
            label="Check for a newer puzzle database once a day"
            description="Asks database.lichess.org for its checksum list, the file's date and size, and the puzzle count. Nothing about you is sent."
            checked={autoCheck}
            onChange={(e) => onAutoCheck(e.currentTarget.checked)}
            data-testid="auto-check-switch"
          />
        </Stack>
      </Stack>
    </Modal>
  );
}
