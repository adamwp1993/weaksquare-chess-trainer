import {
  ActionIcon,
  Alert,
  AppShell,
  Button,
  Center,
  Grid,
  Group,
  Loader,
  Menu,
  Modal,
  Paper,
  Text,
  Title,
} from "@mantine/core";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { TrainingMode } from "./api/ApiClient";
import type {
  CoachLesson,
  FilterSpec,
  PlanTask,
  PlanTaskAction,
  PuzzleDbStatus,
  SoundSettings,
  SuggestionView,
  ThemeGroup,
  TodayPlan,
  UpdateOffer,
  RestoreNotice,
} from "./api/types";
import { when } from "./components/BackupPanel";
import type { JournalDraft } from "./components/JournalTab";
import { LessonTaskModal } from "./components/LessonTaskModal";
import { TodayCard } from "./components/TodayCard";
import { FiltersStrip } from "./components/FiltersStrip";
import { LichessStatus } from "./components/LichessStatus";
import { SpendIndicator } from "./components/SpendIndicator";
import { SuggestionBanner } from "./components/SuggestionBanner";
import { UpdateBanner } from "./components/UpdateBanner";
import { ShortcutsHelp } from "./components/ShortcutsHelp";
import { defaultFilters } from "./state/filters";
import { useLichess } from "./state/lichess";
import { useJob } from "./state/useJob";
import { useShortcuts } from "./state/shortcuts";
import { AboutModal } from "./views/AboutModal";
import { CoachView, type CoachTab } from "./views/CoachView";
import {
  type AnalysisBoardState,
  analysisBoardFromLine,
  AnalysisView,
  newAnalysisBoard,
} from "./views/AnalysisView";
import { type AnalysisLine, hasMoves } from "./state/analysisTree";
import { GamesView } from "./views/GamesView";
import { ImportGameDialog } from "./views/ImportGameDialog";
import { ImportPuzzlesDialog } from "./views/ImportPuzzlesDialog";
import { ReviewView } from "./views/ReviewView";
import { ImportView } from "./views/ImportView";
import { MixerView } from "./views/MixerView";
import { OpeningsView } from "./views/OpeningsView";
import { StudiesView } from "./views/StudiesView";
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
  // v0.8: My games and Game Review are pages; the trainer stays mounted (hidden) so a session survives.
  const [page, setPage] = useState<
    | { kind: "trainer" }
    | { kind: "games" }
    | { kind: "coach" }
    | { kind: "openings"; family?: string; query?: string }
    | { kind: "studies" }
    | { kind: "analysis" }
    | {
        kind: "review"; gameId: number; explain?: boolean; ply?: number; from?: "games" | "coach" | "trainer";
        retry?: boolean; hideBest?: boolean;
      }
  >({ kind: "trainer" }); // prettier-ignore
  // v0.12 (§10.12): the Coach's tab, the plan shared by its Plan tab and the Today card, and what a task's Start opened.
  const [coachTab, setCoachTab] = useState<CoachTab>("report");
  const [today, setToday] = useState<TodayPlan | null>(null);
  const [planVersion, setPlanVersion] = useState(0);
  const planChanged = useCallback(() => setPlanVersion((v) => v + 1), []);
  const [planSession, setPlanSession] = useState<{ title: string; remaining: number | null } | null>(null);
  const [lessonTask, setLessonTask] = useState<{ id: number; lesson: CoachLesson } | null>(null);
  const [journalDraft, setJournalDraft] = useState<JournalDraft | null>(null);
  const [planError, setPlanError] = useState<string | null>(null);
  const [sendIds, setSendIds] = useState<number[]>([]); // Send to Coach (FR-11.30)
  // v0.15 (§20): the Analysis tab's board lives here, so it survives switching tabs (never saved: Adam, v0.15 planning).
  const [analysisBoard, setAnalysisBoard] = useState<AnalysisBoardState>(newAnalysisBoard);
  const [analysisPending, setAnalysisPending] = useState<AnalysisLine | null>(null);
  const clearAnalysisPending = useCallback(() => setAnalysisPending(null), []);
  const openInAnalysis = useCallback(
    (line: AnalysisLine) => {
      // FR-14.6: straight onto an empty board; a board with moves asks first (Adam, v0.15 planning).
      if (hasMoves(analysisBoard.tree)) setAnalysisPending(line);
      else setAnalysisBoard(analysisBoardFromLine(line));
      setPage({ kind: "analysis" });
    },
    [analysisBoard],
  );
  const [suggestion, setSuggestion] = useState<SuggestionView | null>(null); // FR-10.28–10.31
  const [catalog, setCatalog] = useState<ThemeGroup[]>([]);
  const [importOpen, setImportOpen] = useState(false);
  const [puzzlesOpen, setPuzzlesOpen] = useState(false);
  const [settingsAi, setSettingsAi] = useState(false); // opened from the spend indicator
  const [sounds, setSounds] = useState<SoundSettings>({
    on: false,
    volume: 70,
    set: "sfx",
  });
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
  // v0.5: the Modes control (§6), Show move count (FR-4.2), the collapsed panel (FR-1.14), and the
  // dev-only fast-forward (FR-4.6; null in the real app). All saved through the bridge.
  const [mode, setMode] = useState<TrainingMode>("standard");
  const [showLength, setShowLength] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [summary, setSummary] = useState("");
  const [timeOffset, setTimeOffset] = useState<number | null>(null);
  const historyChanged = useCallback(() => setHistoryVersion((v) => v + 1), []);
  const saveTimer = useRef<number | undefined>(undefined);

  // v0.16 (FR-15.4): after the restart that finishes a restore, say what happened, once.
  const [restoreNotice, setRestoreNotice] = useState<RestoreNotice | null>(null);
  useEffect(() => {
    api.takeRestoreNotice().then(setRestoreNotice, () => undefined);
  }, []);

  // The last filters you used come back from user.db (never browser storage).
  useEffect(() => {
    api.getSettings().then(
      (s) => {
        setSpec(s.last_filters ?? defaultFilters());
        setCoordinates(s.coordinates);
        setSounds(s.sounds);
        setAutoCheck(s.auto_check);
        setMode(s.mode);
        setShowLength(s.show_length);
        setCollapsed(s.filters_collapsed);
        setTimeOffset(s.time_offset_days);
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

  // v0.10: the Suggested mix and its banner. Reloaded after each Coach run of yours, and after Apply,
  // since the backend may have replaced your filters (only when they were untouched, FR-10.31).
  const loadSuggestion = useCallback(() => {
    api.getSuggestion().then(setSuggestion, () => undefined);
  }, []);
  useEffect(() => {
    loadSuggestion();
    api.getThemeCatalog().then(setCatalog, () => undefined);
  }, [loadSuggestion]);
  // v0.10-B9: the mode follows the suggestion only between sessions. While one runs, the Mixer keeps
  // showing the session's mode (§6: a mode change starts a new session); the new mode waits for its end.
  const running = useRef(false);
  const pendingMode = useRef<TrainingMode | null>(null);
  useEffect(() => {
    running.current = sessionId !== null;
    if (sessionId === null && pendingMode.current) {
      setMode(pendingMode.current);
      pendingMode.current = null;
    }
  }, [sessionId]);
  const reloadFilters = useCallback(() => {
    api.getSettings().then((s) => {
      if (s.last_filters) setSpec(s.last_filters);
      if (running.current) pendingMode.current = s.mode;
      else setMode(s.mode);
    }, () => undefined); // prettier-ignore
    loadSuggestion();
  }, [loadSuggestion]);
  // v0.10-B3: a Coach run can end while you're on another page (you can keep solving meanwhile). Its
  // suggestion may have replaced your filters in the backend, so the Mixer reloads them whatever page is open.
  useEffect(
    () =>
      api.onEvent((e) => {
        if (e.name === "job" && e.payload.kind === "coach_run" && e.payload.state === "done") reloadFilters();
      }),
    [reloadFilters],
  );
  const applySuggestion = useCallback(() => {
    api.applySuggestion().then(reloadFilters, (e: Error) => setStartError(e.message));
  }, [reloadFilters]);
  const dismissSuggestion = useCallback(() => {
    api.dismissSuggestion().then(setSuggestion, () => undefined);
  }, []);

  const toggleCoordinates = useCallback(() => {
    const on = !coordinates;
    setCoordinates(on);
    api.setSetting("ui.coordinates", on).catch(() => undefined);
  }, [coordinates]);

  const toggleCollapsed = useCallback(() => {
    setCollapsed((was) => {
      api.setSetting("ui.filters_collapsed", !was).catch(() => undefined);
      return !was;
    });
  }, []);

  useShortcuts({
    c: toggleCoordinates,
    f: () => started && toggleCollapsed(),
    "?": () => setShortcutsOpen(true),
  });

  // FR-1.13: the player follows the saved settings; off means silent and nothing loaded.
  useEffect(() => soundPlayer.configure(sounds), [sounds]);
  const changeSounds = useCallback((next: SoundSettings) => {
    setSounds(next);
    api.setSetting("ui.sounds", next).catch(() => undefined);
  }, []);

  /** v0.8-B4: Name the idea and Danger spotting are Lichess-only, so they always use Lichess DB. */
  const forMode = (s: FilterSpec, m: TrainingMode): FilterSpec =>
    (m === "name_idea" || m === "danger_spotting") && s.source !== "lichess" ? { ...s, source: "lichess" } : s;

  /** Starts a session; false if it couldn't (the error is shown). */
  const start = async (requested?: TrainingMode): Promise<boolean> => {
    if (!spec) return false;
    // v0.10-B11: a suggested mode held back while a session ran applies at the next Start too.
    let asMode = requested ?? mode;
    if (requested === undefined && pendingMode.current) {
      asMode = pendingMode.current;
      pendingMode.current = null;
      setMode(asMode);
    }
    setStarting(true);
    setStartError(null);
    setStartNotice(null);
    setPlanSession(null); // a session of your own: back to your filters and mode
    try {
      const info = await api.startSession(forMode(spec, asMode), rated, asMode, showLength);
      setSessionId(info.session_id);
      if (info.empty_buckets.length > 0) {
        const groups = info.empty_buckets
          .map((i) => `group ${i + 1}`)
          .join(" and ");
        setStartNotice(
          `No puzzles match ${groups}, so it's left out; the other groups share its share.`,
        );
      }
      return true;
    } catch (e) {
      setStartError((e as Error).message);
      return false;
    } finally {
      setStarting(false);
    }
  };

  // FR-10.65: ticks come from what the app saw, so the plan is read again whenever something may have happened.
  useEffect(() => {
    if (!started) return;
    api.getTodayPlan().then(setToday, () => undefined);
  }, [started, planVersion, historyVersion, page]);

  const sessionFromTask = useCallback((a: PlanTaskAction, title: string) => {
    if (!a.session) return;
    setSessionId(a.session.session_id);
    setPlanSession({ title, remaining: a.remaining });
    setPage({ kind: "trainer" });
  }, []);

  // FR-10.63: Start opens the task's screen. A puzzle task's session never goes through your filters or mode.
  const startPlanTask = useCallback(
    (task: PlanTask) => {
      setPlanError(null);
      const back = page.kind === "coach" ? ("coach" as const) : ("trainer" as const);
      api.startPlanTask(task.id, rated).then((a) => {
        if (a.kind === "session") sessionFromTask(a, task.title);
        else if ((a.kind === "retry" || a.kind === "review") && a.game_id !== null) {
          setPage({ kind: "review", gameId: a.game_id, from: back, retry: a.kind === "retry", hideBest: a.kind === "review" });
        } else if (a.kind === "lesson" && a.lesson) setLessonTask({ id: task.id, lesson: a.lesson });
        else if (a.kind === "reflection") {
          setJournalDraft({ prompt: a.prompt, game_id: a.game_id, weakness_key: a.weakness_key, plan_day_id: a.plan_day_id, plan_task_id: task.id });
          setCoachTab("journal");
          setPage({ kind: "coach" });
        }
      }, (e: Error) => setPlanError(e.message)); // prettier-ignore
    },
    [page.kind, rated, sessionFromTask],
  );

  // §6: switching mode while a session is running starts a new one in that mode, like Start.
  // If the new session can't start (e.g. nothing is due), the mode stays as it was and the running
  // session carries on, with the reason shown (v0.5-B1).
  const changeMode = async (next: TrainingMode) => {
    pendingMode.current = null; // v0.10-B11: your own pick wins over a held-back suggestion
    if (sessionId !== null && !(await start(next))) return;
    if (spec && forMode(spec, next) !== spec) changeSpec(forMode(spec, next)); // the locked control shows Lichess DB
    setMode(next);
    api.setSetting("trainer.mode", next).catch(() => undefined);
  };
  const changeShowLength = (on: boolean) => {
    setShowLength(on);
    api.setSetting("commit.show_length", on).catch(() => undefined);
  };

  const refresh = useCallback(() => {
    api
      .getPuzzleDbStatus()
      .then(setDbStatus, (e: Error) => setError(e.message));
  }, []);

  useEffect(refresh, [refresh]);

  // FR-2.5: the automatic update check, once per launch (the backend limits it to once a day).
  const refreshOffer = useCallback(() => {
    api.getUpdateOffer().then(setOffer, () => setOffer(null));
  }, []);
  useEffect(() => {
    if (checkStarted.current || !dbStatus?.installed || dbStatus.needs_upgrade)
      return;
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
    sync && (account?.state !== "signed_out" || sync.history_count > 0)
      ? sync.history_count
      : null;

  let main;
  if (!started)
    main = (
      <StartupView
        account={account}
        onContinue={() => setStarted(true)}
        onChanged={refreshLichess}
      />
    );
  else if (error) main = <Text c="red">{error}</Text>;
  else if (!dbStatus)
    main = (
      <Center h={300}>
        <Loader />
      </Center>
    );
  else if (!dbStatus.installed)
    main = (
      <ImportView
        firstRun
        runningJobId={dbStatus.import_job_id}
        onDone={imported}
      />
    );
  else if (dbStatus.needs_upgrade)
    main = (
      <UpgradeView runningJobId={dbStatus.import_job_id} onDone={imported} />
    );
  else if (!spec)
    main = (
      <Center h={300}>
        <Loader />
      </Center>
    );
  else
    main = (
      <>
        {page.kind === "games" && (
          <GamesView
            onReview={(id, explain) => setPage({ kind: "review", gameId: id, explain })}
            onImport={() => setImportOpen(true)}
            onSendToCoach={(ids) => {
              setSendIds(ids);
              setCoachTab("report"); // QA v0.12-B37: what was sent and the run button are on this tab
              setPage({ kind: "coach" });
            }}
          />
        )}
        {page.kind === "studies" && <StudiesView coordinates={coordinates} />}
        {page.kind === "analysis" && (
          <AnalysisView
            board={analysisBoard}
            onBoard={setAnalysisBoard}
            pending={analysisPending}
            onPendingDone={clearAnalysisPending}
            coordinates={coordinates}
          />
        )}
        {page.kind === "openings" && <OpeningsView key={`${page.family ?? ""}:${page.query ?? ""}`} initialFamily={page.family ?? null} initialQuery={page.query ?? ""} coordinates={coordinates} />}
        {page.kind === "coach" && (
          <CoachView
            sendIds={sendIds}
            onClearSend={() => setSendIds([])}
            onReview={(id, ply) => setPage({ kind: "review", gameId: id, ply, from: "coach" })}
            onOpening={(name) => {
              // FR-10.58: its opening in the book, or a search for it when the name doesn't match one.
              api.matchOpeningFamily(name).then(
                (family) => setPage({ kind: "openings", family: family ?? undefined, query: family ? undefined : name }),
                () => setPage({ kind: "openings", query: name }),
              );
            }}
            onLoad={(next, m) => {
              // FR-10.24 Load preset: your click; saved presets don't change.
              changeSpec(next);
              setMode(m);
              api.setSetting("trainer.mode", m).catch(() => undefined);
              setPage({ kind: "trainer" });
            }}
            onRunDone={reloadFilters}
            tab={coachTab}
            onTab={setCoachTab}
            planVersion={planVersion}
            onPlanChanged={planChanged}
            onStartTask={startPlanTask}
            journalDraft={journalDraft}
            onClearDraft={() => setJournalDraft(null)}
            onCloseQuestion={() => setJournalDraft((d) => (d ? { ...d, prompt: null } : d))}
          />
        )}
        {page.kind === "review" && (
          <ReviewView
            key={`${page.gameId}:${page.ply ?? ""}:${page.retry ? "r" : ""}${page.hideBest ? "h" : ""}`}
            gameId={page.gameId}
            initialPly={page.ply}
            startRetry={page.retry ?? false}
            hideBest={page.hideBest ?? false}
            backLabel={page.from === "coach" ? "← Coach" : page.from === "trainer" ? "← Puzzles" : "← My games"}
            onBack={() => setPage({ kind: page.from === "coach" ? "coach" : page.from === "trainer" ? "trainer" : "games" })}
            coordinates={coordinates}
            autoExplain={page.explain ?? false}
            onOpenInAnalysis={openInAnalysis}
            onTrain={(p) => {
              // FR-11.18 Train these: only on your click, after the confirm; saved presets don't change. It sets
              // the themes and rating; themes need Lichess puzzles and no ratios, so those switch only if they
              // must. Match ANY/ALL stays yours (v0.9-B3).
              changeSpec({ ...spec, source: spec.source === "my" ? "lichess" : spec.source, themes: p.themes, ratios: [], rating_min: p.rating_min, rating_max: p.rating_max });
              setPage({ kind: "trainer" });
            }}
          />
        )}
        <Grid
          gap="lg"
          style={page.kind === "trainer" ? undefined : { display: "none" }}
          data-testid="trainer-page"
        >
          {account?.state === "expired" && (
            <Grid.Col span={12}>
              <Alert color="yellow" data-testid="expired-banner">
                <Group justify="space-between">
                  <Text size="sm">
                    Your Lichess sign-in has expired or was revoked. Your solves
                    are kept here and sync after you sign in.
                  </Text>
                  <Button
                    size="xs"
                    onClick={() => setSettingsOpen(true)}
                    data-testid="sign-in-again"
                  >
                    Sign in again
                  </Button>
                </Group>
              </Alert>
            </Grid.Col>
          )}
          {today && (
            <Grid.Col span={12}>
              <TodayCard
                today={today}
                compact={sessionId !== null}
                onChanged={planChanged}
                onStart={startPlanTask}
                onOpenPlan={() => {
                  setCoachTab("plan");
                  setPage({ kind: "coach" });
                }}
              />
            </Grid.Col>
          )}
          {planError && (
            <Grid.Col span={12}>
              <Alert color="red" withCloseButton onClose={() => setPlanError(null)} data-testid="plan-start-error">
                {planError}
              </Alert>
            </Grid.Col>
          )}
          {timeOffset !== null && timeOffset > 0 && (
            <Grid.Col span={12}>
              <Alert color="orange" data-testid="time-offset-banner">
                Time fast-forwarded +{timeOffset}{" "}
                {timeOffset === 1 ? "day" : "days"} (dev). Settings → Debug sets
                it back.
              </Alert>
            </Grid.Col>
          )}
          {offer && (
            <Grid.Col span={12}>
              <UpdateBanner
                offer={offer}
                onUpdate={updateNow}
                onNotNow={() => dismiss("not_now")}
                onSkip={() => dismiss("skip")}
              />
            </Grid.Col>
          )}
          {suggestion && (suggestion.pending || suggestion.active) && (
            <Grid.Col span={12}>
              <SuggestionBanner
                suggestion={suggestion}
                currentMode={mode}
                catalog={catalog}
                onApply={applySuggestion}
                onDismiss={dismissSuggestion}
              />
            </Grid.Col>
          )}
          {collapsed && (
            <Grid.Col span={12}>
              <FiltersStrip
                summary={summary}
                rated={rated}
                onExpand={toggleCollapsed}
              />
            </Grid.Col>
          )}
          {/* Hidden, not unmounted, while collapsed, so the panel comes back exactly as it was (FR-1.14). */}
          <Grid.Col
            span={{ base: 12, md: 4 }}
            style={collapsed ? { display: "none" } : undefined}
            data-testid="mixer-column"
          >
            <MixerView
              mode={mode}
              onMode={changeMode}
              showLength={showLength}
              onShowLength={changeShowLength}
              onCollapse={toggleCollapsed}
              onSummary={setSummary}
              spec={spec}
              onChange={changeSpec}
              dbStatus={dbStatus}
              onStart={() => start()}
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
              <Alert
                color="yellow"
                mt="sm"
                withCloseButton
                onClose={() => setStartNotice(null)}
                data-testid="start-notice"
              >
                {startNotice}
              </Alert>
            )}
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: collapsed ? 12 : 8 }}>
            {startError && collapsed && (
              <Alert color="red" mb="sm" data-testid="start-error-collapsed">
                {startError}
              </Alert>
            )}
            {planSession && sessionId !== null && (
              <Alert color="blue" mb="sm" p="xs" data-testid="plan-session-banner">
                Plan task: {planSession.title}. This session uses the task's own filters and mode; yours are unchanged.
              </Alert>
            )}
            {sessionId === null ? (
              <Paper withBorder p="xl" radius="md">
                <Text c="dimmed">
                  {collapsed
                    ? "Show filters to choose your puzzles, then press Start."
                    : "Choose your puzzles on the left, then press Start."}
                </Text>
              </Paper>
            ) : (
              <TrainerView
                key={sessionId}
                sessionId={sessionId}
                onNewSession={() => {
                  setSessionId(null);
                  setPlanSession(null);
                }}
                onHistoryChange={historyChanged}
                coordinates={coordinates}
                wide={collapsed}
                onOpenGame={(id, ply) => setPage({ kind: "review", gameId: id, ply })}
                onOpenInAnalysis={openInAnalysis}
              />
            )}
          </Grid.Col>
        </Grid>
      </>
    );

  const ready = started && !!dbStatus?.installed && !dbStatus.needs_upgrade;
  return (
    <AppShell header={{ height: 56 }} padding="md">
      <AppShell.Header>
        {/* v0.15: one line, whatever the width. With the Analysis button the nav no longer fits beside the full title in
            a narrow window and wrapped under the header, covering the page; the title shortens and truncates instead. */}
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          {/* QA v0.15-B4: below 1200 px even "WeakSquare" was cut to "W…", so the name is left out there. The window's own
              title bar still names the app. */}
          <Title order={3} visibleFrom="lg" style={{ whiteSpace: "nowrap" }}>
            WeakSquare Chess Trainer
          </Title>
          <Group gap="sm" wrap="nowrap" style={{ flexShrink: 0 }}>
            {ready && (
              <Group gap={4} wrap="nowrap">
                <Button
                  size="xs"
                  variant={page.kind === "trainer" ? "light" : "subtle"}
                  onClick={() => setPage({ kind: "trainer" })}
                  data-testid="nav-puzzles"
                >
                  Puzzles
                </Button>
                <Button
                  size="xs"
                  variant={page.kind === "games" || (page.kind === "review" && page.from !== "coach") ? "light" : "subtle"}
                  onClick={() => setPage({ kind: "games" })}
                  data-testid="nav-games"
                >
                  My games
                </Button>
                <Button
                  size="xs"
                  variant={page.kind === "coach" || (page.kind === "review" && page.from === "coach") ? "light" : "subtle"}
                  onClick={() => setPage({ kind: "coach" })}
                  data-testid="nav-coach"
                >
                  Coach
                </Button>
                <Button
                  size="xs"
                  variant={page.kind === "openings" ? "light" : "subtle"}
                  onClick={() => setPage({ kind: "openings" })}
                  data-testid="nav-openings"
                >
                  Openings
                </Button>
                <Button
                  size="xs"
                  variant={page.kind === "studies" ? "light" : "subtle"}
                  onClick={() => setPage({ kind: "studies" })}
                  data-testid="nav-studies"
                >
                  Studies
                </Button>
                <Button
                  size="xs"
                  variant={page.kind === "analysis" ? "light" : "subtle"}
                  onClick={() => setPage({ kind: "analysis" })}
                  data-testid="nav-analysis"
                >
                  Analysis
                </Button>
                <Button
                  size="xs"
                  variant="subtle"
                  onClick={() => setImportOpen(true)}
                  data-testid="nav-import-game"
                >
                  Import game
                </Button>
              </Group>
            )}
            {started && <LichessStatus account={account} sync={sync} />}
            {started && (
              <SpendIndicator
                onOpen={() => {
                  setSettingsAi(true);
                  setSettingsOpen(true);
                }}
              />
            )}
            <ActionIcon
              variant="subtle"
              size="lg"
              aria-label="Settings"
              onClick={() => setSettingsOpen(true)}
              data-testid="gear"
            >
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
                  <Menu.Item onClick={() => setUpdateOpen(true)}>
                    Update puzzle database…
                  </Menu.Item>
                )}
                {ready && (
                  <Menu.Item
                    onClick={() => setPuzzlesOpen(true)}
                    data-testid="menu-import-puzzles"
                  >
                    Import puzzles from a file…
                  </Menu.Item>
                )}
                <Menu.Item
                  onClick={() => setStatsOpen(true)}
                  disabled={!started || !dbStatus?.installed}
                >
                  Stats
                </Menu.Item>
                <Menu.Item onClick={() => setSettingsOpen(true)}>
                  Settings…
                </Menu.Item>
                <Menu.Item
                  onClick={toggleCoordinates}
                  data-testid="menu-coordinates"
                >
                  {coordinates
                    ? "Hide board coordinates"
                    : "Show board coordinates"}
                </Menu.Item>
                <Menu.Item onClick={() => setShortcutsOpen(true)}>
                  Keyboard shortcuts
                </Menu.Item>
                <Menu.Divider />
                <Menu.Item onClick={() => setAboutOpen(true)}>About</Menu.Item>
              </Menu.Dropdown>
            </Menu>
          </Group>
        </Group>
      </AppShell.Header>
      <AppShell.Main>
        {/* v0.16 (FR-15.4): above whichever screen opens after the restart (startup, import or puzzles) */}
        {restoreNotice && (
          <Alert
            color={restoreNotice.error ? "red" : "green"}
            withCloseButton
            onClose={() => setRestoreNotice(null)}
            mb="md"
            data-testid="restore-notice"
          >
            {restoreNotice.error
              ? restoreNotice.error
              : `Your data was restored from the backup${restoreNotice.created_at ? ` made ${when(restoreNotice.created_at)}` : ""}. Sign in to Lichess again and re-enter any AI key in Settings.`}
          </Alert>
        )}
        {main}
      </AppShell.Main>
      <AboutModal opened={aboutOpen} onClose={() => setAboutOpen(false)} />
      <ImportGameDialog
        opened={importOpen}
        onClose={() => setImportOpen(false)}
        onImported={(id) => {
          setImportOpen(false);
          setPage({ kind: "review", gameId: id });
        }}
      />
      <ImportPuzzlesDialog
        opened={puzzlesOpen}
        onClose={() => setPuzzlesOpen(false)}
        onDone={historyChanged}
      />
      {lessonTask && (
        <LessonTaskModal
          taskId={lessonTask.id}
          lesson={lessonTask.lesson}
          rated={rated}
          onClose={() => setLessonTask(null)}
          onChanged={planChanged}
          onSession={(a) => sessionFromTask(a, `Lesson drill: ${lessonTask.lesson.label}`)}
        />
      )}
      <StatsView opened={statsOpen} onClose={() => setStatsOpen(false)} />
      <ShortcutsHelp
        opened={shortcutsOpen}
        onClose={() => setShortcutsOpen(false)}
      />
      <SettingsModal
        opened={settingsOpen}
        onClose={() => {
          setSettingsOpen(false);
          setSettingsAi(false);
        }}
        focusAi={settingsAi}
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
        timeOffset={timeOffset}
        onTimeOffset={setTimeOffset}
      />
      <Modal
        opened={updateOpen}
        onClose={() => setUpdateOpen(false)}
        title="Update the puzzle database"
        size="lg"
      >
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
