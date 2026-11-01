import { ActionIcon, Alert, AppShell, Center, Grid, Group, Loader, Menu, Modal, Paper, Text, Title } from "@mantine/core";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { FilterSpec, PuzzleDbStatus } from "./api/types";
import { defaultFilters } from "./state/filters";
import { AboutModal } from "./views/AboutModal";
import { ImportView } from "./views/ImportView";
import { MixerView } from "./views/MixerView";
import { TrainerView } from "./views/TrainerView";

const SAVE_FILTERS_DEBOUNCE_MS = 500;

export function App() {
  const [aboutOpen, setAboutOpen] = useState(false);
  const [updateOpen, setUpdateOpen] = useState(false);
  const [dbStatus, setDbStatus] = useState<PuzzleDbStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [spec, setSpec] = useState<FilterSpec | null>(null);
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const saveTimer = useRef<number | undefined>(undefined);

  // The last filters you used come back from user.db (never browser storage).
  useEffect(() => {
    api.getSettings().then(
      (s) => setSpec(s.last_filters ?? defaultFilters()),
      () => setSpec(defaultFilters()),
    );
  }, []);

  const changeSpec = useCallback((next: FilterSpec) => {
    setSpec(next);
    window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => {
      api.setSetting("mixer.filters", next).catch(() => undefined);
    }, SAVE_FILTERS_DEBOUNCE_MS);
  }, []);

  const start = async () => {
    if (!spec) return;
    setStarting(true);
    setStartError(null);
    try {
      const info = await api.startSession(spec);
      setSessionId(info.session_id);
    } catch (e) {
      setStartError((e as Error).message);
    } finally {
      setStarting(false);
    }
  };

  const refresh = useCallback(() => {
    api.getPuzzleDbStatus().then(setDbStatus, (e: Error) => setError(e.message));
  }, []);

  useEffect(refresh, [refresh]);

  const imported = useCallback(() => {
    setUpdateOpen(false);
    refresh();
  }, [refresh]);

  let main;
  if (error) main = <Text c="red">{error}</Text>;
  else if (!dbStatus)
    main = (
      <Center h={300}>
        <Loader />
      </Center>
    );
  else if (!dbStatus.installed)
    main = <ImportView firstRun runningJobId={dbStatus.import_job_id} onDone={imported} />;
  else if (!spec)
    main = (
      <Center h={300}>
        <Loader />
      </Center>
    );
  else
    main = (
      <Grid gap="lg">
        <Grid.Col span={{ base: 12, md: 4 }}>
          <MixerView spec={spec} onChange={changeSpec} dbStatus={dbStatus} onStart={start} starting={starting} />
          {startError && (
            <Alert color="red" mt="sm" data-testid="start-error">
              {startError}
            </Alert>
          )}
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 8 }}>
          {sessionId === null ? (
            <Paper withBorder p="xl" radius="md">
              <Text c="dimmed">Choose your puzzles on the left, then press Start.</Text>
            </Paper>
          ) : (
            <TrainerView key={sessionId} sessionId={sessionId} onNewSession={() => setSessionId(null)} />
          )}
        </Grid.Col>
      </Grid>
    );

  return (
    <AppShell header={{ height: 56 }} padding="md">
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Title order={3}>WeakSquare Chess Trainer</Title>
          <Menu position="bottom-end" width={240}>
            <Menu.Target>
              <ActionIcon variant="subtle" size="lg" aria-label="Menu">
                ☰
              </ActionIcon>
            </Menu.Target>
            <Menu.Dropdown>
              {dbStatus?.installed && (
                <Menu.Item onClick={() => setUpdateOpen(true)}>Update puzzle database…</Menu.Item>
              )}
              <Menu.Item onClick={() => setAboutOpen(true)}>About</Menu.Item>
            </Menu.Dropdown>
          </Menu>
        </Group>
      </AppShell.Header>
      <AppShell.Main>{main}</AppShell.Main>
      <AboutModal opened={aboutOpen} onClose={() => setAboutOpen(false)} />
      <Modal opened={updateOpen} onClose={() => setUpdateOpen(false)} title="Update the puzzle database" size="lg">
        <ImportView firstRun={false} runningJobId={dbStatus?.import_job_id ?? null} onDone={imported} />
      </Modal>
    </AppShell>
  );
}
