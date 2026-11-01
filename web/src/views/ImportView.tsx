import { Alert, Button, Group, Progress, Stack, Text, Title } from "@mantine/core";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useJob } from "../state/useJob";

// FR-2.1: first-run download (or local file) and import, with progress and Cancel.
// Used full-page when there's no puzzle database yet, and in a dialog to update it.
export function ImportView({
  firstRun,
  runningJobId,
  onDone,
}: {
  firstRun: boolean;
  runningJobId: string | null;
  onDone: () => void;
}) {
  const [jobId, setJobId] = useState<string | null>(runningJobId);
  const [startError, setError] = useState<string | null>(null);
  const job = useJob(jobId);
  const finished = job !== null && job.state !== "running";
  const error = startError ?? (job?.state === "failed" ? job.message : null);

  useEffect(() => {
    if (job?.state === "done") onDone();
  }, [job, onDone]);

  const start = async (localPath: string | null) => {
    setError(null);
    try {
      setJobId(await api.startPuzzleImport(localPath));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const chooseFile = async () => {
    try {
      const path = await api.choosePuzzleFile();
      if (path) await start(path);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const running = jobId !== null && !finished;

  return (
    <Stack gap="md" maw={640} data-testid="import-view">
      {firstRun && <Title order={2}>Get the puzzle database</Title>}
      <Text>
        WeakSquare uses the Lichess open puzzle database, free and public domain.
        {firstRun ? " It's needed once, before your first puzzle." : " Updating replaces it with the newest export."}
      </Text>
      <Text size="sm" c="dimmed" data-testid="import-what">
        <b>Download from Lichess</b> fetches the <b>entire</b> Lichess puzzle database, every puzzle, not a sample:
        about 300 MB compressed, about 6 million puzzles, and roughly 1.5 GB on disk once imported. It comes from
        database.lichess.org, is checked against the checksum Lichess publishes, and takes a few minutes to import.
        Nothing about you is sent. Your attempts and settings are never touched.
      </Text>

      {error && (
        <Alert color="red" title="The import didn't finish" data-testid="import-error">
          {error}
        </Alert>
      )}

      {running ? (
        <Stack gap="xs">
          <Progress
            value={(job?.progress ?? 0) * 100}
            animated={job?.progress == null || job.progress < 1}
            size="lg"
            aria-label="Import progress"
          />
          <Group justify="space-between">
            <Text size="sm" data-testid="import-message">
              {job?.message ?? "Starting…"}
            </Text>
            <Button variant="default" onClick={() => jobId && api.cancelJob(jobId)}>
              Cancel
            </Button>
          </Group>
          <Text size="xs" c="dimmed">
            {firstRun
              ? "You can cancel at any time; a download picks up where it left off next time."
              : "You can keep training while this runs. The new puzzles are switched in when it's finished."}
          </Text>
        </Stack>
      ) : (
        <Group>
          <Button onClick={() => start(null)}>Download from Lichess</Button>
          <Button variant="default" onClick={chooseFile}>
            Use a file I already have…
          </Button>
        </Group>
      )}
    </Stack>
  );
}
