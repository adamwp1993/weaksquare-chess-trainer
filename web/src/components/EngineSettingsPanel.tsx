import { Button, Code, Group, NumberInput, Progress, Stack, Text } from "@mantine/core";
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { EngineSettingsChange } from "../api/ApiClient";
import type { EngineSettings } from "../api/types";
import { useEngineStatus } from "../state/engine";
import { useJob } from "../state/useJob";
import { EngineInstallBanner } from "./EngineInstallBanner";

// Settings → Engine (FR-7.4, 7.5): which engine is in use, Install / Reinstall, think time, threads,
// hash, and the advanced custom engine (saved only after the same self-test the installer runs).
export function EngineSettingsPanel() {
  const [status, refreshStatus] = useEngineStatus();
  const [settings, setSettings] = useState<EngineSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [inputsKey, setInputsKey] = useState(0); // remounts the inputs so a refused value snaps back (v0.4-B7)
  const job = useJob(jobId);

  useEffect(() => {
    api.getEngineSettings().then(setSettings, (e: Error) => setError(e.message));
  }, []);

  const refreshAll = useCallback(() => {
    refreshStatus();
    api.getEngineSettings().then(setSettings, () => undefined);
  }, [refreshStatus]);

  useEffect(() => {
    if (job && job.state !== "running") refreshAll();
  }, [job, refreshAll]);

  const save = (change: EngineSettingsChange) => {
    setError(null);
    api.setEngineSettings(change).then(setSettings, (e: Error) => {
      setError(e.message);
      setInputsKey((k) => k + 1);
    });
  };
  const chooseCustom = async () => {
    setError(null);
    try {
      const path = await api.chooseEngineFile();
      if (path) setJobId(await api.startCustomEngineCheck(path));
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const useManaged = () => api.clearCustomEngine().then(refreshAll, (e: Error) => setError(e.message));
  const reinstall = () => api.startEngineInstall(true).then(setJobId, (e: Error) => setError(e.message));

  const running = job?.state === "running";
  return (
    <Stack gap="xs" data-testid="engine-settings">
      {status && status.state !== "ready" ? (
        <EngineInstallBanner status={status} onChanged={refreshAll} />
      ) : (
        status && (
          <Stack gap={4}>
            <Text size="sm" data-testid="engine-in-use">
              Using <b>{status.name}</b> ({status.source === "custom" ? "your own engine" : `managed, ${status.tag}`})
            </Text>
            {status.path && <Code style={{ wordBreak: "break-all" }}>{status.path}</Code>}
          </Stack>
        )
      )}
      {settings && (
        <Group grow align="flex-start" key={inputsKey}>
          <NumberInput
            label="Think time (s)"
            description="Per position"
            defaultValue={settings.think_s}
            min={0.2}
            max={10}
            step={0.5}
            decimalScale={1}
            onBlur={(e) => save({ think_s: Number(e.currentTarget.value) })}
            data-testid="engine-think"
          />
          <NumberInput
            label="Threads"
            description={`1 to ${settings.max_threads}`}
            defaultValue={settings.threads}
            min={1}
            max={settings.max_threads}
            allowDecimal={false}
            onBlur={(e) => save({ threads: Number(e.currentTarget.value) })}
            data-testid="engine-threads"
          />
          <NumberInput
            label="Hash (MB)"
            description="16 to 2048"
            defaultValue={settings.hash_mb}
            min={16}
            max={2048}
            step={64}
            allowDecimal={false}
            onBlur={(e) => save({ hash_mb: Number(e.currentTarget.value) })}
            data-testid="engine-hash"
          />
        </Group>
      )}
      {running && (
        <Stack gap={4}>
          <Progress value={(job?.progress ?? 0) * 100} animated />
          <Text size="xs" c="dimmed">
            {job?.message}
          </Text>
        </Stack>
      )}
      {job && job.state !== "running" && (
        <Text size="sm" c={job.state === "done" ? "green" : "red"} data-testid="engine-job-result">
          {job.message}
        </Text>
      )}
      {error && (
        <Text size="sm" c="red" data-testid="engine-settings-error">
          {error}
        </Text>
      )}
      <Group gap="xs">
        <Button size="xs" variant="default" onClick={chooseCustom} disabled={running} data-testid="engine-choose">
          Use my own engine…
        </Button>
        {settings?.custom_path && (
          <Button size="xs" variant="default" onClick={useManaged} disabled={running} data-testid="engine-use-managed">
            Use the managed Stockfish
          </Button>
        )}
        {status?.state === "ready" && status.source === "managed" && (
          <Button size="xs" variant="subtle" onClick={reinstall} disabled={running} data-testid="engine-reinstall">
            Reinstall
          </Button>
        )}
      </Group>
      <Text size="xs" c="dimmed">
        Stockfish runs on this PC. It only ever thinks for the think time on each position you look at after a
        puzzle, never while you're solving. Your own engine must speak UCI and pass a short self-test.
      </Text>
    </Stack>
  );
}
