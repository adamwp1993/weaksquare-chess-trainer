// v0.8 (FR-10.46–10.50): import puzzles from a PGN, EPD or CSV file of your own as a labelled set. The file
// is read on this PC and never sent anywhere. Bad entries are listed in the report and skipped.
import { Alert, Button, Group, Modal, Progress, Stack, Table, Text, TextInput } from "@mantine/core";
import { useEffect, useState } from "react";
import { api } from "../api";
import type { PuzzleImportReport } from "../api/types";
import { useJob } from "../state/useJob";

export function ImportPuzzlesDialog({ opened, onClose, onDone }: { opened: boolean; onClose: () => void; onDone: () => void }) {
  const [label, setLabel] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const job = useJob(jobId);
  const [report, setReport] = useState<PuzzleImportReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!job || !jobId || job.state === "running") return;
    if (job.state === "done") {
      api.getPuzzleImportReport(jobId).then(setReport, (e: Error) => setError(e.message));
      onDone();
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reacting to the job pushed by the backend
    } else if (job.state === "failed") setError(job.message);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job]);

  const start = async () => {
    setError(null);
    setReport(null);
    try {
      setJobId(await api.chooseAndImportPuzzles(label));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const close = () => {
    setJobId(null);
    setReport(null);
    setError(null);
    onClose();
  };

  return (
    <Modal opened={opened} onClose={close} title="Import puzzles from a file" size="lg" data-testid="import-puzzles-dialog">
      <Stack>
        <Text size="sm">
          A PGN (each game's FEN tag is the position, its moves the solution), EPD (bm or pv) or CSV (fen, solution, name)
          file of your own. The file is read on this PC and never sent anywhere. Imported puzzles train under{" "}
          <b>My puzzles</b> and are checked strictly, like Lichess puzzles.
        </Text>
        <TextInput
          label="Set label"
          description="For example the book's title. You can filter My puzzles by it."
          value={label}
          maxLength={60}
          onChange={(e) => setLabel(e.currentTarget.value)}
          data-testid="import-puzzles-label"
        />
        <Group justify="flex-end">
          <Button onClick={start} disabled={!label.trim() || job?.state === "running"} data-testid="import-puzzles-choose">
            Choose a file…
          </Button>
        </Group>
        {job?.state === "running" && (
          <Stack gap={4}>
            <Text size="sm">{job.message}</Text>
            <Progress value={(job.progress ?? 0) * 100} animated />
            <Group>
              <Button size="xs" variant="subtle" color="red" onClick={() => jobId && api.cancelJob(jobId)}>
                Cancel
              </Button>
            </Group>
          </Stack>
        )}
        {job?.state === "cancelled" && <Text size="sm">Cancelled: nothing was imported.</Text>}
        {error && <Alert color="red">{error}</Alert>}
        {report && (
          <Stack gap="xs" data-testid="import-report">
            <Text size="sm" fw={600}>
              {report.file_name}: {report.added} added, {report.duplicates} already there, {report.skipped} skipped
            </Text>
            {report.errors.length > 0 && (
              <Table striped withTableBorder>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th w={80}>Entry</Table.Th>
                    <Table.Th>Why it was skipped</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {report.errors.map((e) => (
                    <Table.Tr key={e.n}>
                      <Table.Td>{e.n}</Table.Td>
                      <Table.Td>{e.reason}</Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            )}
            {report.skipped > report.errors.length && (
              <Text size="xs" c="dimmed">
                The first {report.errors.length} of {report.skipped} skipped entries are listed.
              </Text>
            )}
          </Stack>
        )}
      </Stack>
    </Modal>
  );
}
