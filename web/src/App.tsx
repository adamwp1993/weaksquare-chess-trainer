import { ActionIcon, Alert, AppShell, Button, Center, Grid, Group, Loader, Menu, Modal, Paper, Text, Title } from "@mantine/core";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { FilterSpec, PuzzleDbStatus, SoundSettings, UpdateOffer } from "./api/types";
import { LichessStatus } from "./components/LichessStatus";
import { UpdateBanner } from "./components/UpdateBanner";
import { ShortcutsHelp } from "./components/ShortcutsHelp";
import { defaultFilters } from "./state/filters";
import { useLichess } from "./state/lichess";
import { useJob } from "./state/useJob";
import { useShortcuts } from "./state/shortcuts";
import { AboutModal } from "./views/AboutModal";
import { ImportView } from "./views/ImportView";
import { MixerView } from "./views/MixerView";
import { sounds as soundPlayer } from "./sound/player";
import { SettingsModal } from "./views/SettingsModal";
import { StartupView } from "./views/StartupView";
import { StatsView } from "./views/StatsView";
import { TrainerView } from "./views/TrainerView";
import { UpgradeView } from "./views/UpgradeView";

const SAVE_FILTERS_DEBOUNCE_MS = 500;

export function App() {
  // FR-1.1/1.5: the startup page comes first at every launch.
  const [started, setStarted] = useState(false);
  const { account, sync, refresh: refreshLichess } = useLichess();
  // FR-1.9: Rated is on at each launch and applies to the next session; it's never saved.
  const [rated, setRated] = useState(true);
  const [aboutOpen, setAboutOpen] = useState(false);
  const [statsOpen, setStatsOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [coordinates, setCoordinates] = useState(true);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [sounds, setSounds] = useState<SoundSettings>({ on: false, volume: 70, set: "sfx" });
  const [autoCheck, setAutoCheck] = useState(true);
  const [offer, setOffer] = useState<UpdateOffer | null>(null);
  const [checkJob, setCheckJob] = useState<string | null>(null);
  const checkStatus = useJob(checkJob);
  const checkStarted = useRef(false);
  const [updateOpen, setUpdateOpen] = useState(false);
  const [dbStatus, setDbStatus] = useState<PuzzleDbStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [spec, setSpec] = useState<FilterSpec | null>(null);
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const [startNotice, setStartNotice] = useState<string | null>(null);
  const [historyVersion, setHistoryVersion] = useState(0);
  const historyChanged = useCallback(() => setHistoryVersion((v) => v + 1), []);
  const saveTimer = useRef<number | undefined>(undefined);

  // The last filters you used come back from user.db (never browser storage).
  useEffect(() => {
    api.getSettings().then(
      (s) => {
        setSpec(s.last_filters ?? defaultFilters());
        setCoordinates(s.coordinates);
        setSounds(s.sounds);
        setAutoCheck(s.auto_check);
      },
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

  const toggleCoordinates = useCallback(() => {
    const on = !coordinates;
    setCoordinates(on);
    api.setSetting("ui.coordinates", on).catch(() => undefined);
  }, [coordinates]);

  useShortcuts({ c: toggleCoordinates, "?": () => setShortcutsOpen(true) });

  // FR-1.13: the player follows the saved settings; off means silent and nothing loaded.
  useEffect(() => soundPlayer.configure(sounds), [sounds]);
  const changeSounds = useCallback((next: SoundSettings) => {
    setSounds(next);
    api.setSetting("ui.sounds", next).catch(() => undefined);
  }, []);

  const start = async () => {
    if (!spec) return;
    setStarting(true);
    setStartError(null);
    setStartNotice(null);
    try {
      const info = await api.startSession(spec, rated);
      setSessionId(info.session_id);
      if (info.empty_buckets.length > 0) {
        const groups = info.empty_buckets.map((i) => `group ${i + 1}`).join(" and ");
        setStartNotice(`No puzzles match ${groups}, so it's left out; the other groups share its share.`);
      }
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

  // FR-2.5: the automatic update check, once per launch (the backend limits it to once a day).
  const refreshOffer = useCallback(() => {
    api.getUpdateOffer().then(setOffer, () => setOffer(null));
  }, []);
  useEffect(() => {
    if (checkStarted.current || !dbStatus?.installed || dbStatus.needs_upgrade) return;
    checkStarted.current = true;
    api.checkForDbUpdate(false).then(setCheckJob, () => undefined);
  }, [dbStatus]);
  useEffect(() => {
    if (checkStatus && checkStatus.state !== "running") refreshOffer();
  }, [checkStatus, refreshOffer]);

  const dismiss = (kind: "not_now" | "skip") => {
    setOffer(null);
    api.dismissUpdate(kind).catch(() => undefined);
  };
  const updateNow = async () => {
    setOffer(null);
    try {
      await api.startPuzzleImport(null);
    } catch (e) {
      setError((e as Error).message);
      return;
    }
    refresh();
    setUpdateOpen(true);
  };

  // After an import the update dialog stays open, showing the exact new/removed numbers (FR-2.5).
  const imported = useCallback(() => {
    refresh();
    refreshOffer();
  }, [refresh, refreshOffer]);

  // "Exclude played on Lichess" needs a history: none while signed out with nothing imported.
  const playedCount =
    sync && (account?.state !== "signed_out" || sync.history_count > 0) ? sync.history_count : null;

  let main;
  if (!started) main = <StartupView account={account} onContinue={() => setStarted(true)} onChanged={refreshLichess} />;
  else if (error) main = <Text c="red">{error}</Text>;
  else if (!dbStatus)
    main = (
      <Center h={300}>
        <Loader />
      </Center>
    );
  else if (!dbStatus.installed)
    main = <ImportView firstRun runningJobId={dbStatus.import_job_id} onDone={imported} />;
  else if (dbStatus.needs_upgrade) main = <UpgradeView runningJobId={dbStatus.import_job_id} onDone={imported} />;
  else if (!spec)
    main = (
      <Center h={300}>
        <Loader />
      </Center>
    );
  else
    main = (
      <Grid gap="lg">
        {account?.state === "expired" && (
          <Grid.Col span={12}>
            <Alert color="yellow" data-testid="expired-banner">
              <Group justify="space-between">
                <Text size="sm">
                  Your Lichess sign-in has expired or was revoked. Your solves are kept here and sync after you sign in.
                </Text>
                <Button size="xs" onClick={() => setSettingsOpen(true)} data-testid="sign-in-again">
                  Sign in again
                </Button>
              </Group>
            </Alert>
          </Grid.Col>
        )}
        {offer && (
          <Grid.Col span={12}>
            <UpdateBanner offer={offer} onUpdate={updateNow} onNotNow={() => dismiss("not_now")} onSkip={() => dismiss("skip")} />
          </Grid.Col>
        )}
        <Grid.Col span={{ base: 12, md: 4 }}>
          <MixerView
            spec={spec}
            onChange={changeSpec}
            dbStatus={dbStatus}
            onStart={start}
            starting={starting}
            historyVersion={historyVersion}
            rated={rated}
            onRated={setRated}
            playedCount={playedCount}
          />
          {startError && (
            <Alert color="red" mt="sm" data-testid="start-error">
              {startError}
            </Alert>
          )}
          {startNotice && (
            <Alert color="yellow" mt="sm" withCloseButton onClose={() => setStartNotice(null)} data-testid="start-notice">
              {startNotice}
            </Alert>
          )}
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 8 }}>
          {sessionId === null ? (
            <Paper withBorder p="xl" radius="md">
              <Text c="dimmed">Choose your puzzles on the left, then press Start.</Text>
            </Paper>
          ) : (
            <TrainerView
              key={sessionId}
              sessionId={sessionId}
              onNewSession={() => setSessionId(null)}
              onHistoryChange={historyChanged}
              coordinates={coordinates}
            />
          )}
        </Grid.Col>
      </Grid>
    );

  return (
    <AppShell header={{ height: 56 }} padding="md">
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Title order={3}>WeakSquare Chess Trainer</Title>
          <Group gap="sm">
          {started && <LichessStatus account={account} sync={sync} />}
          <ActionIcon variant="subtle" size="lg" aria-label="Settings" onClick={() => setSettingsOpen(true)} data-testid="gear">
            {"\u2699\uFE0E"}
          </ActionIcon>
          <Menu position="bottom-end" width={240}>
            <Menu.Target>
              <ActionIcon variant="subtle" size="lg" aria-label="Menu">
                ☰
              </ActionIcon>
            </Menu.Target>
            <Menu.Dropdown>
              {started && dbStatus?.installed && (
                <Menu.Item onClick={() => setUpdateOpen(true)}>Update puzzle database…</Menu.Item>
              )}
              <Menu.Item onClick={() => setStatsOpen(true)} disabled={!started || !dbStatus?.installed}>
                Stats
              </Menu.Item>
              <Menu.Item onClick={() => setSettingsOpen(true)}>Settings…</Menu.Item>
              <Menu.Item onClick={toggleCoordinates} data-testid="menu-coordinates">
                {coordinates ? "Hide board coordinates" : "Show board coordinates"}
              </Menu.Item>
              <Menu.Item onClick={() => setShortcutsOpen(true)}>Keyboard shortcuts</Menu.Item>
              <Menu.Divider />
              <Menu.Item onClick={() => setAboutOpen(true)}>About</Menu.Item>
            </Menu.Dropdown>
          </Menu>
          </Group>
        </Group>
      </AppShell.Header>
      <AppShell.Main>{main}</AppShell.Main>
      <AboutModal opened={aboutOpen} onClose={() => setAboutOpen(false)} />
      <StatsView opened={statsOpen} onClose={() => setStatsOpen(false)} />
      <ShortcutsHelp opened={shortcutsOpen} onClose={() => setShortcutsOpen(false)} />
      <SettingsModal
        opened={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        coordinates={coordinates}
        onCoordinates={toggleCoordinates}
        sounds={sounds}
        onSounds={changeSounds}
        autoCheck={autoCheck}
        onAutoCheck={(on) => {
          setAutoCheck(on);
          api.setSetting("puzzle_db.auto_check", on).catch(() => undefined);
        }}
        account={account}
        onAccountChanged={refreshLichess}
      />
      <Modal opened={updateOpen} onClose={() => setUpdateOpen(false)} title="Update the puzzle database" size="lg">
        <ImportView
          firstRun={false}
          runningJobId={dbStatus?.import_job_id ?? null}
          onDone={imported}
          onChecked={refreshOffer}
        />
      </Modal>
    </AppShell>
  );
}
