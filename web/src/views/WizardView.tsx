// v1.0 the first-run wizard (NFR-8, FR-15.4). Shown on a fresh install instead of the startup page. Its step comes
// from the backend (core/setup.py), worked out from what's installed, so closing the app resumes where you were.
// Each step reuses what the app already has: the puzzle importer, the Stockfish installer and the Lichess sign-in.
import { Alert, Button, Center, Group, Loader, Paper, Stack, Stepper, Text, Title } from "@mantine/core";
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { AccountStatus, BackupInfo, EngineStatus, SetupState } from "../api/types";
import { AccountPanel } from "../components/AccountPanel";
import { when } from "../components/BackupPanel";
import { EngineInstallBanner } from "../components/EngineInstallBanner";
import { useJob } from "../state/useJob";
import { ImportView } from "./ImportView";

const ORDER = ["welcome", "puzzles", "engine", "lichess", "done"] as const;

function Welcome({ onFresh, onChanged }: { onFresh: () => void; onChanged: () => void }) {
  const [info, setInfo] = useState<BackupInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const job = useJob(jobId);
  useEffect(() => {
    if (job?.state === "failed") onChanged();
  }, [job?.state]); // eslint-disable-line react-hooks/exhaustive-deps

  const choose = async () => {
    setError(null);
    try {
      setInfo(await api.chooseBackupToRestore());
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const restore = async () => {
    if (!info) return;
    setError(null);
    try {
      await api.chooseSetup("restore"); // kept through the restart: the wizard comes back at the puzzle step
      setJobId(await api.restoreBackup(info.token));
    } catch (e) {
      setError((e as Error).message);
      setInfo(null);
    }
  };
  return (
    <Stack gap="md" data-testid="wizard-welcome">
      <Title order={3}>Welcome to WeakSquare</Title>
      <Text size="sm">
        A few steps get you ready: the Lichess puzzle database, Stockfish, and (if you like) your Lichess sign-in. Starting on a new PC? Restore a
        backup you made with <b>Back up now</b> and carry on where you left off.
      </Text>
      <Group>
        <Button onClick={onFresh} data-testid="wizard-fresh">
          Start fresh
        </Button>
        <Button variant="default" onClick={choose} data-testid="wizard-restore">
          Restore from a backup…
        </Button>
      </Group>
      {info && !jobId && (
        <Alert color="orange" title="Restore this backup?" data-testid="wizard-restore-confirm">
          <Stack gap="xs">
            <Text size="sm" data-testid="wizard-restore-info">
              Made {when(info.created_at)} by WeakSquare {info.app_version}: {info.games} games, {info.attempts} puzzle attempts and{" "}
              {info.coach_reports} Coach reports.
            </Text>
            <Text size="sm">
              The app restarts to finish, then carries on here with the puzzle database. Not in a backup: your Lichess sign-in, AI keys, the puzzle
              database and Stockfish.
            </Text>
            <Group gap="xs">
              <Button color="orange" onClick={restore} data-testid="wizard-restore-go">
                Restore and restart
              </Button>
              <Button variant="default" onClick={() => setInfo(null)}>
                Cancel
              </Button>
            </Group>
          </Stack>
        </Alert>
      )}
      {jobId && job?.state !== "failed" && (
        <Group gap="xs" data-testid="wizard-restore-progress">
          <Loader size="xs" />
          <Text size="sm">{job?.message ?? "Checking the backup…"}</Text>
        </Group>
      )}
      {(error || job?.state === "failed") && (
        <Alert color="red" data-testid="wizard-error">
          {error ?? job?.message}
        </Alert>
      )}
    </Stack>
  );
}

export function WizardView({
  state,
  account,
  onChanged,
  onAccountChanged,
  onFinished,
}: {
  state: SetupState;
  account: AccountStatus | null;
  /** Re-read the setup state (a step's fact may have changed). */
  onChanged: () => void;
  onAccountChanged: () => void;
  onFinished: () => void;
}) {
  const [engine, setEngine] = useState<EngineStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const loadEngine = useCallback(() => {
    api.getEngineStatus().then(setEngine, () => undefined);
  }, []);
  useEffect(loadEngine, [loadEngine, state.step]);
  // The account changes outside this view (the sign-in job): re-read the step when it does.
  useEffect(onChanged, [account?.state]); // eslint-disable-line react-hooks/exhaustive-deps

  const act = (p: Promise<unknown>) =>
    p.then(onChanged, (e: Error) => setError(e.message));
  const finish = () => {
    setError(null);
    api.finishSetup().then(onFinished, (e: Error) => setError(e.message));
  };
  const active = ORDER.indexOf(state.step);
  const stepper = (
    <Stepper active={Math.max(0, active)} size="sm" mb="lg" data-testid="wizard-stepper">
      <Stepper.Step label="Welcome" />
      <Stepper.Step label="Puzzles" />
      <Stepper.Step label="Stockfish" />
      <Stepper.Step label="Lichess" />
    </Stepper>
  );

  return (
    <Center mih="calc(100vh - 56px - 2 * var(--mantine-spacing-md))">
      <Paper withBorder radius="md" p="xl" w={720} data-testid="wizard" data-step={state.step}>
        {stepper}
        {state.step === "welcome" && <Welcome onFresh={() => act(api.chooseSetup("fresh"))} onChanged={onChanged} />}
        {state.step === "puzzles" && (
          <Stack gap="md" data-testid="wizard-puzzles">
            {state.choice === "restore" && (
              <Alert color="green" data-testid="wizard-restored">
                Your data is restored. The puzzle database and Stockfish aren't part of a backup, so they come next.
              </Alert>
            )}
            <ImportView firstRun runningJobId={state.puzzle_job} onDone={onChanged} />
          </Stack>
        )}
        {state.step === "engine" && (
          <Stack gap="md" data-testid="wizard-engine">
            <Title order={3}>Stockfish</Title>
            <Text size="sm">
              Stockfish is the chess engine that shows why a move fails, analyzes your games and powers the Coach. It runs on your PC. You can skip
              this and install it later from any screen that needs it.
            </Text>
            {engine && <EngineInstallBanner status={engine} onChanged={() => { loadEngine(); onChanged(); }} />}
            <Group>
              <Button variant="default" onClick={() => act(api.skipSetupStep("engine"))} data-testid="wizard-skip-engine">
                Skip for now
              </Button>
            </Group>
          </Stack>
        )}
        {state.step === "lichess" && (
          <Stack gap="md" data-testid="wizard-lichess">
            <Title order={3}>Lichess (optional)</Title>
            <Text size="sm">
              Signing in syncs your puzzle solves, shows your puzzle rating and fetches your games for the Coach. chess.com games can be linked later in
              Settings. Everything works without it.
            </Text>
            <AccountPanel account={account} onChanged={() => { onAccountChanged(); onChanged(); }} compact />
            <Group>
              <Button variant="default" onClick={() => act(api.skipSetupStep("lichess"))} data-testid="wizard-skip-lichess">
                Continue without signing in
              </Button>
            </Group>
          </Stack>
        )}
        {state.step === "done" && (
          <Stack gap="md" data-testid="wizard-done">
            <Title order={3}>You're ready</Title>
            <Text size="sm">
              {state.engine_ready ? "" : "Stockfish isn't installed yet: the app offers it wherever it's needed. "}
              Choose your puzzles on the left of the main page and press Start. The User Guide's First run chapter has more.
            </Text>
            <Group>
              <Button onClick={finish} data-testid="wizard-finish">
                Start training
              </Button>
            </Group>
          </Stack>
        )}
        {error && (
          <Alert color="red" mt="md" data-testid="wizard-error">
            {error}
          </Alert>
        )}
      </Paper>
    </Center>
  );
}
