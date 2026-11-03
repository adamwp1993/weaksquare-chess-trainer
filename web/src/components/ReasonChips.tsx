import { Badge, Button, Group, Paper, Stack, Text, TextInput } from "@mantine/core";
import { useState } from "react";
import type { ReasonKey } from "../api/ApiClient";
import type { ReasonPrompt } from "../api/types";

// Why you missed it (§7.3, FR-5.6–5.9): a row of six chips below the board, keys 1–6, never blocking. The
// suggested reason is only highlighted; nothing is saved until you click. You can change it until you move on.

export const MAX_NOTE = 200;
// Chip labels short enough for one row under the board; the full label is the tooltip.
const SHORT: Record<string, string> = {
  didntLook: "Didn't look",
  missedResource: "Missed their reply",
  miscalculated: "Miscalculated",
  unknownPattern: "Didn't know the pattern",
  rushed: "Rushed",
  misclick: "Misclick",
};

export function ReasonChips({
  prompt,
  chosen,
  busy,
  onChoose,
  onSkip,
}: {
  prompt: ReasonPrompt;
  chosen: ReasonKey | null;
  busy: boolean;
  onChoose: (reason: ReasonKey, note: string | null) => void;
  onSkip: () => void;
}) {
  const [noteOpen, setNoteOpen] = useState(false);
  const [note, setNote] = useState("");
  const tooLong = note.trim().length > MAX_NOTE;
  return (
    <Paper withBorder p="sm" radius="md" data-testid="reason-chips">
      <Stack gap={6}>
        <Group justify="space-between" gap={4}>
          <Text size="sm" fw={600}>
            Why did you miss it?{" "}
            <Text span size="xs" c="dimmed" fw={400}>
              Keys 1–6
            </Text>
          </Text>
          <Group gap={4}>
            {noteOpen ? null : (
              <Button size="compact-xs" variant="subtle" onClick={() => setNoteOpen(true)} data-testid="reason-add-note">
                Add a note
              </Button>
            )}
            {!chosen && (
              <Button size="compact-xs" variant="subtle" color="gray" onClick={onSkip} data-testid="reason-skip">
                Skip
              </Button>
            )}
          </Group>
        </Group>
        <Group gap={6}>
          {prompt.reasons.map((r, i) => {
            const suggested = prompt.suggested === r.key;
            const picked = chosen === r.key;
            return (
              <Button
                key={r.key}
                size="compact-sm"
                variant={picked ? "filled" : suggested ? "light" : "default"}
                color={picked ? "blue" : suggested ? "yellow" : "gray"}
                disabled={busy}
                onClick={() => onChoose(r.key, noteOpen && !tooLong ? note.trim() || null : null)}
                rightSection={
                  suggested && !picked ? (
                    <Badge size="xs" color="yellow" variant="filled" style={{ textTransform: "none" }}>
                      Suggested
                    </Badge>
                  ) : undefined
                }
                title={r.label}
                aria-pressed={picked}
                data-testid={`reason-${r.key}`}
              >
                {i + 1}. {SHORT[r.key] ?? r.label}
              </Button>
            );
          })}
        </Group>
        {chosen && (
          <Text size="xs" c="dimmed" data-testid="reason-saved">
            Saved. Pick another to change it.
          </Text>
        )}
        {noteOpen && (
          <Group gap={4} align="start">
            <TextInput
              style={{ flex: 1 }}
              size="xs"
              placeholder="A short note (optional)"
              value={note}
              onChange={(e) => setNote(e.currentTarget.value)}
              error={tooLong ? `Keep it under ${MAX_NOTE} characters.` : undefined}
              data-testid="reason-note"
            />
            {chosen && (
              <Button size="xs" variant="light" disabled={busy || tooLong} onClick={() => onChoose(chosen, note.trim() || null)}
                      data-testid="reason-note-save">
                Save note
              </Button>
            )}
          </Group>
        )}
      </Stack>
    </Paper>
  );
}
