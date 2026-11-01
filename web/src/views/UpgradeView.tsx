import { Alert, Button, Progress, Stack, Text, Title } from "@mantine/core";
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useJob } from "../state/useJob";

// v0.2: an older puzzle database is rebuilt from its own rows for the new filters. No download,
// no choice to make, so it starts by itself; your attempts and settings aren't touched.
export function UpgradeView({ runningJobId, onDone }: { runningJobId: string | null; onDone: () => void }) {
  const [jobId, setJobId] = useState<string | null>(runningJobId);
  const [startError, setStartError] = useState<string | null>(null);
  const job = useJob(jobId);
  const started = useRef(runningJobId !== null);

  const start = () => {
    setStartError(null);
    api.startPuzzleDbUpgrade().then(setJobId, (e: Error) => setStartError(e.message));
  };

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    start();
  }, []);

  useEffect(() => {
    if (job?.state === "done") onDone();
  }, [job, onDone]);

  const error = startError ?? (job && (job.state === "failed" || job.state === "cancelled") ? job.message : null);

  return (
    <Stack gap="md" maw={640} data-testid="upgrade-view">
      <Title order={2}>Upgrading your puzzle database</Title>
      <Text>
        This version adds the opening and quality filters, so your puzzle database is rebuilt once for them. It uses
        the copy you already have: nothing is downloaded. It takes about 2 minutes, and your attempts and settings
        aren't touched.
      </Text>
      {error ? (
        <Alert color="red" title="The upgrade didn't finish" data-testid="upgrade-error">
          <Stack gap="xs">
            <Text size="sm">{error} Your current puzzle database is unchanged.</Text>
            <Button size="xs" onClick={start} w="fit-content">
              Try again
            </Button>
          </Stack>
        </Alert>
      ) : (
        <Stack gap="xs">
          <Progress value={(job?.progress ?? 0) * 100} animated size="lg" aria-label="Upgrade progress" />
          <Text size="sm" data-testid="upgrade-message">
            {job?.message ?? "Starting…"}
          </Text>
        </Stack>
      )}
    </Stack>
  );
}
