// FR-10.69: your notes on a game and its moves, in Game Review. Each one is a journal entry that links back here.
import { Anchor, Button, Checkbox, Group, Modal, Paper, Stack, Text, Textarea, Title } from "@mantine/core";
import { useState } from "react";
import { api } from "../api";
import type { JournalEntry } from "../api/types";
import { Labeled } from "./OptionInfo";

const MAX = 5000;

export function GameNotes({
  gameId,
  notes,
  ply,
  moveLabel,
  onChanged,
  onGo,
}: {
  gameId: number;
  notes: JournalEntry[];
  ply: number | null; // the move on the board, 0-based; null before the first move
  moveLabel: string | null;
  onChanged: () => void;
  onGo: (ply: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [onMove, setOnMove] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const save = () => {
    setError(null);
    api.addJournalEntry({ text, game_id: gameId, ply: onMove ? ply : null }).then(() => {
      setText("");
      setOpen(false);
      onChanged();
    }, (e: Error) => setError(e.message)); // prettier-ignore
  };
  return (
    <Paper withBorder p="xs" data-testid="game-notes">
      <Stack gap={4}>
        <Group justify="space-between">
          <Title order={5}>Your notes</Title>
          <Button size="compact-xs" variant="light" onClick={() => setOpen(true)} data-testid="game-note-add">
            Add a note
          </Button>
        </Group>
        {notes.length === 0 && (
          <Text size="xs" c="dimmed">
            Notes you add here also appear in your journal.
          </Text>
        )}
        {notes.map((n) => (
          <Text key={n.id} size="sm" style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }} data-testid={`game-note-${n.id}`}>
            {n.ply !== null ? (
              <Anchor size="sm" component="button" onClick={() => onGo(n.ply!)} data-testid={`game-note-go-${n.id}`}>
                {n.move ?? `Move ${n.ply + 1}`}:
              </Anchor>
            ) : (
              <Text span size="xs" c="dimmed">
                The game:{" "}
              </Text>
            )}{" "}
            {n.text}
          </Text>
        ))}
      </Stack>
      <Modal opened={open} onClose={() => setOpen(false)} title="Add a note" data-testid="game-note-modal">
        <Stack gap="xs">
          <Textarea
            autosize
            minRows={3}
            maxLength={MAX}
            placeholder="What were you thinking here? What did you miss?"
            value={text}
            onChange={(e) => setText(e.currentTarget.value)}
            data-no-tip="your own words"
            data-testid="game-note-text"
          />
          {ply !== null && (
            <Checkbox
              label={<Labeled id="review.noteOnMove">On this move{moveLabel ? ` (${moveLabel})` : ""}</Labeled>}
              checked={onMove}
              onChange={(e) => setOnMove(e.currentTarget.checked)}
              data-testid="game-note-on-move"
            />
          )}
          {error && (
            <Text size="xs" c="red" data-testid="game-note-error">
              {error}
            </Text>
          )}
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button onClick={save} disabled={!text.trim()} data-testid="game-note-save">
              Save
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Paper>
  );
}
