// v0.16 Settings → Your data (REQUIREMENTS §21): Back up now (FR-15.1), Restore from a backup (FR-15.4) and automatic
// backups (FR-15.3). File paths never come from here: Python opens the dialogs and holds the chosen file behind a token.
import { Alert, Button, Group, Loader, NumberInput, Stack, Switch, Text } from "@mantine/core";
import { useEffect, useState } from "react";
import { api } from "../api";
import type { BackupInfo, BackupStatus } from "../api/types";
import { useJob } from "../state/useJob";
import { Labeled } from "./OptionInfo";

export function when(iso: string): string {
  return new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });
}

const n = (x: number) => x.toLocaleString("en-US");
const plural = (x: number, one: string, many: string) => `${n(x)} ${x === 1 ? one : many}`;

export function BackupPanel() {
  const [s, setS] = useState<BackupStatus | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [backupJob, setBackupJob] = useState<string | null>(null);
  const [restoreInfo, setRestoreInfo] = useState<BackupInfo | null>(null);
  const [restoreJob, setRestoreJob] = useState<string | null>(null);
  const [restoreError, setRestoreError] = useState<string | null>(null);
  const [inputsKey, setInputsKey] = useState(0);
  const backup = useJob(backupJob);
  const restore = useJob(restoreJob);

  const load = () => api.getBackupStatus().then(setS, () => undefined);
  useEffect(() => {
    load();
  }, []);
  useEffect(() => {
    if (backup?.state === "done" || backup?.state === "failed") load();
  }, [backup?.state]);
  if (!s) return null;

  const backUpNow = async () => {
    setMsg(null);
    try {
      const id = await api.backupNow();
      if (id) setBackupJob(id);
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    }
  };
  const chooseRestore = async () => {
    setRestoreError(null);
    setRestoreInfo(null);
    setRestoreJob(null);
    try {
      setRestoreInfo(await api.chooseBackupToRestore());
    } catch (e) {
      setRestoreError((e as Error).message);
    }
  };
  const replace = async () => {
    if (!restoreInfo) return;
    setRestoreError(null);
    try {
      setRestoreJob(await api.restoreBackup(restoreInfo.token));
    } catch (e) {
      setRestoreError((e as Error).message);
      setRestoreInfo(null);
    }
  };
  const save = async (enabled: boolean, folder: string | null, intervalDays: number, keep: number) => {
    try {
      setS(await api.setBackupSettings(enabled, folder, intervalDays, keep));
      setMsg(null);
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
      setInputsKey((k) => k + 1);
    }
  };
  const a = s.settings;
  const toggle = async (on: boolean) => {
    let folder = a.folder;
    if (on && !folder) {
      folder = await api.chooseBackupFolder();
      if (!folder) return; // cancelled: they stay off
    }
    await save(on, folder, a.interval_days, a.keep);
  };
  const chooseFolder = async () => {
    const folder = await api.chooseBackupFolder();
    if (folder) await save(a.enabled, folder, a.interval_days, a.keep);
  };
  const num = (v: string | number) => (typeof v === "number" ? v : Number.parseFloat(v));
  const restoring = restore?.state === "running" || (restoreJob !== null && restore === null);

  return (
    <Stack gap="sm" data-testid="backup-settings">
      <Text size="sm">
        Everything you create is kept in one file on this PC. A backup copies it, so you can keep it safe or move it to a new install.
      </Text>

      <Group gap="sm" align="center">
        <Button onClick={backUpNow} loading={backup?.state === "running"} data-testid="backup-now">
          Back up now
        </Button>
        <Text size="sm" c="dimmed" data-testid="backup-last">
          {s.last_at ? `Last backup on this PC: ${when(s.last_at)}` : "No backup made on this PC yet."}
        </Text>
      </Group>
      <Text size="xs" c="dimmed" data-testid="backup-privacy">
        A backup isn't encrypted. It holds your games, notes, journal and AI explanations, so keep it somewhere private. Your
        Lichess sign-in and AI keys are never included, and WeakSquare never uploads a backup.
      </Text>
      {backup?.state === "done" && (
        <Alert color="green" p="xs" data-testid="backup-done">
          {backup.message}
        </Alert>
      )}
      {backup?.state === "failed" && (
        <Alert color="red" p="xs" data-testid="backup-failed">
          {backup.message}
        </Alert>
      )}

      <Group gap="sm">
        <Button variant="default" onClick={chooseRestore} disabled={restoring} data-testid="restore-choose">
          Restore from a backup…
        </Button>
      </Group>
      {restoreError && (
        <Alert color="red" p="xs" data-testid="restore-error">
          {restoreError}
        </Alert>
      )}
      {restoreInfo && !restoreJob && (
        <Alert color="orange" data-testid="restore-confirm" title="Replace all your data with this backup?">
          <Stack gap="xs">
            <Text size="sm" data-testid="restore-info">
              Made {when(restoreInfo.created_at)} by WeakSquare {restoreInfo.app_version}:{" "}
              {plural(restoreInfo.games, "game", "games")}, {plural(restoreInfo.attempts, "puzzle attempt", "puzzle attempts")} and{" "}
              {plural(restoreInfo.coach_reports, "Coach report", "Coach reports")}.
            </Text>
            <Text size="sm">
              Everything on this PC is replaced; nothing is merged. Your current data is saved first in the backups folder (About →
              Data folder → backups), so you can undo this the same way. The app restarts to finish.
            </Text>
            <Text size="sm">
              Not in a backup: your Lichess sign-in, AI keys, the puzzle database and Stockfish. Afterwards, sign in again and
              re-enter any AI key.
            </Text>
            <Group gap="xs">
              <Button color="red" onClick={replace} data-testid="restore-replace">
                Replace my data
              </Button>
              <Button variant="default" onClick={() => setRestoreInfo(null)} data-testid="restore-cancel">
                Cancel
              </Button>
            </Group>
          </Stack>
        </Alert>
      )}
      {restoreJob && restore?.state !== "failed" && (
        <Group gap="xs" data-testid="restore-progress">
          <Loader size="xs" />
          <Text size="sm">{restore?.message ?? "Checking the backup…"}</Text>
        </Group>
      )}
      {restore?.state === "failed" && (
        <Alert color="red" p="xs" data-testid="restore-failed">
          {restore.message}
        </Alert>
      )}

      <Switch
        mt="xs"
        label={<Labeled id="backup.auto">Automatic backups</Labeled>}
        description="Only while the app is open, or the next time you open it if one came due while it was closed."
        checked={a.enabled}
        onChange={(e) => toggle(e.currentTarget.checked)}
        data-testid="backup-auto"
      />
      <Group gap="sm" align="center">
        <Text size="sm" data-testid="backup-folder">
          Folder: {a.folder ?? <i>none chosen</i>}
        </Text>
        <Button variant="default" size="xs" onClick={chooseFolder} data-testid="backup-folder-choose">
          Choose…
        </Button>
      </Group>
      <Group gap="sm" key={`auto${inputsKey}`}>
        <NumberInput
          label={<Labeled id="backup.interval">Every (days)</Labeled>}
          min={1}
          max={90}
          w={140}
          defaultValue={a.interval_days}
          onBlur={(e) => save(a.enabled, a.folder, num(e.currentTarget.value), a.keep)}
          data-testid="backup-interval"
        />
        <NumberInput
          label={<Labeled id="backup.keep">Keep the last</Labeled>}
          min={1}
          max={50}
          w={140}
          defaultValue={a.keep}
          onBlur={(e) => save(a.enabled, a.folder, a.interval_days, num(e.currentTarget.value))}
          data-testid="backup-keep"
        />
      </Group>
      {a.enabled && s.next_due && (
        <Text size="xs" c="dimmed" data-testid="backup-next">
          Next automatic backup: {when(s.next_due)}
        </Text>
      )}
      {s.last_error && (
        <Alert color="orange" p="xs" data-testid="backup-error">
          {s.last_error}
        </Alert>
      )}
      {msg && (
        <Alert color={msg.ok ? "green" : "red"} p="xs" data-testid="backup-settings-msg">
          {msg.text}
        </Alert>
      )}
    </Stack>
  );
}
