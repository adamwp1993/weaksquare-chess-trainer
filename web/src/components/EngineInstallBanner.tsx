import { Alert, Button, Group, Progress, Stack, Text } from "@mantine/core";
import { useEffect, useState } from "react";
import { api } from "../api";
import type { EngineStatus } from "../api/types";
import { useJob } from "../state/useJob";

// FR-7.5 "In the app": wherever an engine feature would appear and there's no engine, this says so and
// offers Install, which runs the same installer as setup.py as a background job with progress.
export function EngineInstallBanner({
  status,
  onChanged,
}: {
  status: EngineStatus;
  onChanged: () => void;
}) {
  const [jobId, setJobId] = useState<string | null>(status.install_job_id);
  const [error, setError] = useState<string | null>(null);
  const job = useJob(jobId);

  useEffect(() => {
    if (job && job.state !== "running") onChanged();
  }, [job, onChanged]);

  const install = () => {
    setError(null);
    api
      .startEngineInstall(false)
      .then(setJobId, (e: Error) => setError(e.message));
  };
  const useManaged = () =>
    api.clearCustomEngine().then(onChanged, (e: Error) => setError(e.message));

  if (status.state === "ready") return null;
  const running = job?.state === "running" || (jobId !== null && job === null);
  const failed = job?.state === "failed" || job?.state === "cancelled";

  return (
    <Alert
      color="yellow"
      variant="light"
      title={titleFor(status)}
      data-testid="engine-banner"
    >
      <Stack gap="xs">
        {status.state === "not_installed" && (
          <Text size="sm">
            Stockfish shows why a wrong move fails and evaluates positions after
            each puzzle. Install downloads the official Stockfish 19 build from
            GitHub (about 80 MB) and checks it before using it.
          </Text>
        )}
        {status.state !== "not_installed" && status.message && (
          <Text size="sm">{status.message}</Text>
        )}
        {running && (
          <Stack gap={4} data-testid="engine-install-progress">
            <Progress value={(job?.progress ?? 0) * 100} animated />
            <Text size="xs" c="dimmed">
              {job?.message ?? "Starting…"}
            </Text>
          </Stack>
        )}
        {failed && (
          <Text size="sm" c="red" data-testid="engine-install-error">
            {job?.message}
          </Text>
        )}
        {error && (
          <Text size="sm" c="red">
            {error}
          </Text>
        )}
        <Group gap="xs">
          {status.state === "not_installed" && !running && (
            <Button size="xs" onClick={install} data-testid="engine-install">
              {failed ? "Try again" : "Install Stockfish"}
            </Button>
          )}
          {status.state === "custom_invalid" && (
            <Button
              size="xs"
              variant="default"
              onClick={useManaged}
              data-testid="engine-use-managed"
            >
              Use the managed Stockfish
            </Button>
          )}
        </Group>
      </Stack>
    </Alert>
  );
}

function titleFor(status: EngineStatus) {
  if (status.state === "custom_invalid")
    return "Your custom engine can't be found";
  if (status.state === "unsupported_platform")
    return "Stockfish isn't available for this computer";
  return "Stockfish isn't installed";
}
