// v0.14: Lichess studies (REQUIREMENTS §19). My studies and Find studies (FR-13.1, 13.2), and a study's own page with
// its chapters and the reader (FR-13.8). Titles, authors and comments come from other people: they're shown as plain
// text (React escapes them) and never as links; the only links are the ones the app builds from a study's ID.
import {
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Menu,
  Modal,
  NavLink,
  Paper,
  ScrollArea,
  SegmentedControl,
  Select,
  Stack,
  Tabs,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiCallError } from "../api";
import type {
  AuthorStudy,
  Job,
  StarterStudy,
  StudyChapter,
  StudyDetail,
  StudySummary,
  StudyUpdate,
} from "../api/types";
import { OptionInfo } from "../components/OptionInfo";
import { StudyRepertoireModal } from "../components/StudyRepertoireModal";
import { HeartButton, StudyReader } from "../components/StudyReader";

type Filter = "all" | "favorites" | "in_progress" | "finished";
type Open = { studyId: string; chapterKey: string | null; path: string[] };

function message(e: unknown): string {
  return e instanceof ApiCallError || e instanceof Error
    ? e.message
    : String(e);
}

function progressLabel(s: StudySummary): string {
  if (s.status === "finished") return "Finished";
  if (s.place_chapter_title) {
    return `${s.done} of ${s.playable} chapters done · at “${s.place_chapter_title}”`;
  }
  return s.done
    ? `${s.done} of ${s.playable} chapters done`
    : `${s.playable} chapter${s.playable === 1 ? "" : "s"}`;
}

/** Follows the jobs this page started (adding, checking for updates) through the pushed job events. */
function useJobs(onDone: (job: Job) => void) {
  const watched = useRef(new Set<string>());
  const [running, setRunning] = useState<Job | null>(null);
  const onDoneRef = useRef(onDone);
  useEffect(() => {
    onDoneRef.current = onDone;
  }, [onDone]);
  useEffect(
    () =>
      api.onEvent((e) => {
        if (e.name !== "job" || !watched.current.has(e.payload.id)) return;
        if (e.payload.state === "running") setRunning(e.payload);
        else {
          watched.current.delete(e.payload.id);
          setRunning(null);
          onDoneRef.current(e.payload);
        }
      }),
    [],
  );
  const watch = useCallback((id: string) => watched.current.add(id), []);
  return { running, watch };
}

export function StudiesView({ coordinates }: { coordinates: boolean }) {
  const [open, setOpen] = useState<Open | null>(null);
  const [tab, setTab] = useState<string | null>("mine");
  const [version, setVersion] = useState(0);
  const [notice, setNotice] = useState<{
    text: string;
    code: string | null;
    ok: boolean;
  } | null>(null);

  const { running, watch } = useJobs(
    useCallback(async (job: Job) => {
      if (job.kind !== "study_add") return;
      if (job.state !== "done") {
        setNotice({ text: job.message, code: job.error_code, ok: false });
        return;
      }
      setNotice({ text: job.message, code: null, ok: true });
      setVersion((v) => v + 1);
      const r = await api.getStudyAddResult(job.id);
      if (r)
        setOpen({ studyId: r.study_id, chapterKey: r.chapter_key, path: [] });
    }, []),
  );

  // FR-13.4: a study added in the Lichess window downloads like a pasted one.
  useEffect(
    () =>
      api.onEvent((e) => {
        if (
          e.name === "study_window" &&
          e.payload.kind === "added" &&
          e.payload.job_id
        )
          watch(e.payload.job_id);
      }),
    [watch],
  );

  const startAdd = useCallback(
    async (start: () => Promise<string>) => {
      setNotice(null);
      try {
        watch(await start());
      } catch (e) {
        setNotice({
          text: message(e),
          code: e instanceof ApiCallError ? e.code : null,
          ok: false,
        });
      }
    },
    [watch],
  );

  if (open) {
    return (
      <StudyPage
        key={open.studyId}
        open={open}
        coordinates={coordinates}
        onBack={() => {
          setOpen(null);
          setVersion((v) => v + 1);
        }}
      />
    );
  }

  return (
    <Stack gap="md" data-testid="studies-view">
      <Group justify="space-between">
        <Title order={3}>Lichess studies</Title>
      </Group>
      {running && (
        <Group gap="xs" data-testid="study-job">
          <Loader size="xs" />
          <Text size="sm">{running.message}</Text>
        </Group>
      )}
      {notice && <Notice notice={notice} onClose={() => setNotice(null)} />}
      <Tabs value={tab} onChange={setTab}>
        <Tabs.List>
          <Tabs.Tab value="mine" data-testid="studies-tab-mine">
            My studies
          </Tabs.Tab>
          <Tabs.Tab value="find" data-testid="studies-tab-find">
            Find studies
          </Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="mine" pt="md">
          <MyStudies
            version={version}
            onOpen={(id, chapterKey, path) =>
              setOpen({ studyId: id, chapterKey, path })
            }
            onFind={() => setTab("find")}
          />
        </Tabs.Panel>
        <Tabs.Panel value="find" pt="md">
          <FindStudies version={version} busy={!!running} onAdd={startAdd} />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}

function Notice({
  notice,
  onClose,
}: {
  notice: { text: string; code: string | null; ok: boolean };
  onClose: () => void;
}) {
  const [signing, setSigning] = useState(false);
  return (
    <Alert
      color={notice.ok ? "green" : "orange"}
      withCloseButton
      onClose={onClose}
      data-testid="study-notice"
    >
      <Text size="sm">{notice.text}</Text>
      {(notice.code === "study_scope" || notice.code === "study_private") && (
        <Group gap="xs" mt="xs">
          <Button
            size="xs"
            variant="light"
            loading={signing}
            onClick={async () => {
              setSigning(true);
              try {
                await api.startSignIn();
              } finally {
                setSigning(false);
              }
            }}
            data-testid="study-sign-in"
          >
            {notice.code === "study_scope"
              ? "Sign in again"
              : "Sign in with Lichess"}
          </Button>
          <Text size="xs" c="dimmed">
            Approve in your browser, then add the study again.
          </Text>
        </Group>
      )}
    </Alert>
  );
}

// ---- My studies (FR-13.1, 13.9) ----------------------------------------------------------------------------------
function MyStudies({
  version,
  onOpen,
  onFind,
}: {
  version: number;
  onOpen: (id: string, chapterKey: string | null, path: string[]) => void;
  onFind: () => void;
}) {
  const [filter, setFilter] = useState<Filter>("all");
  const [rows, setRows] = useState<StudySummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mine, setMine] = useState(0);
  const reload = useCallback(() => setMine((v) => v + 1), []);

  useEffect(() => {
    let live = true;
    api.listStudies(filter).then(
      (r) => live && setRows(r),
      (e) => live && setError(message(e)),
    );
    return () => {
      live = false;
    };
  }, [filter, version, mine]);

  const cont = async (s: StudySummary) => {
    try {
      const p = await api.getStudyContinue(s.id);
      onOpen(s.id, p.chapter_key, p.path);
    } catch (e) {
      setError(message(e));
    }
  };

  return (
    <Stack gap="sm">
      <Group gap="xs" data-option-group>
        <SegmentedControl
          size="xs"
          value={filter}
          onChange={(v) => setFilter(v as Filter)}
          data={[
            { value: "all", label: "All" },
            { value: "favorites", label: "Favorites" },
            { value: "in_progress", label: "In progress" },
            { value: "finished", label: "Finished" },
          ]}
          data-testid="studies-filter"
        />
        <OptionInfo id="studies.filter" />
      </Group>
      {error && (
        <Text c="red" size="sm">
          {error}
        </Text>
      )}
      {rows === null ? (
        <Loader size="sm" />
      ) : rows.length === 0 ? (
        <Paper withBorder p="md" data-testid="studies-empty">
          <Text size="sm">
            {filter === "all"
              ? "You haven't added any studies yet."
              : "No studies here."}{" "}
            {filter === "all" && (
              <Anchor component="button" onClick={onFind}>
                Find studies
              </Anchor>
            )}
          </Text>
        </Paper>
      ) : (
        rows.map((s) => (
          <Card key={s.id} withBorder padding="sm" data-testid="study-card">
            <Group justify="space-between" wrap="nowrap" align="flex-start">
              <Stack gap={2} style={{ minWidth: 0 }}>
                <Group gap="xs" wrap="nowrap">
                  <Text
                    fw={600}
                    style={{ overflowWrap: "anywhere" }}
                    data-testid="study-title"
                  >
                    {s.title}
                  </Text>
                  {s.private && (
                    <Badge size="xs" variant="outline">
                      Private
                    </Badge>
                  )}
                </Group>
                <Text size="xs" c="dimmed">
                  by {s.author ?? "unknown"} · {progressLabel(s)}
                </Text>
              </Stack>
              <Group gap={4} wrap="nowrap">
                <HeartButton
                  hearted={s.hearted}
                  onChange={async (h) => {
                    await api.heartStudy(s.id, h);
                    reload();
                  }}
                />
                <Button
                  size="xs"
                  onClick={() => cont(s)}
                  data-testid="study-continue"
                >
                  {s.status === "new"
                    ? "Start"
                    : s.status === "finished"
                      ? "Open"
                      : "Continue"}
                </Button>
              </Group>
            </Group>
          </Card>
        ))
      )}
    </Stack>
  );
}

// ---- Find studies (FR-13.2–13.6, 13.5a) ---------------------------------------------------------------------------
function FindStudies({
  version,
  busy,
  onAdd,
}: {
  version: number;
  busy: boolean;
  onAdd: (start: () => Promise<string>) => void;
}) {
  const [text, setText] = useState("");
  const [author, setAuthor] = useState("");
  const [authorRows, setAuthorRows] = useState<AuthorStudy[] | null>(null);
  const [authorError, setAuthorError] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);
  const [starter, setStarter] = useState<StarterStudy[]>([]);
  const [opening, setOpening] = useState<string | null>(null);
  const [windowOpen, setWindowOpen] = useState(false);
  const [windowStudy, setWindowStudy] = useState<string | null>(null);
  const [windowError, setWindowError] = useState<string | null>(null);

  useEffect(() => {
    api.getStudyStarterList().then(setStarter, () => setStarter([]));
    api.isLichessWindowOpen().then(setWindowOpen, () => setWindowOpen(false));
  }, [version]);

  useEffect(
    () =>
      api.onEvent((e) => {
        if (e.name !== "study_window") return;
        if (e.payload.kind === "closed") {
          setWindowOpen(false);
          setWindowStudy(null);
        } else if (e.payload.kind === "page")
          setWindowStudy(e.payload.study_id);
      }),
    [],
  );

  const openings = useMemo(
    () => [...new Set(starter.map((s) => s.opening))].sort(),
    [starter],
  );
  const shown = opening
    ? starter.filter((s) => s.opening === opening)
    : starter;

  const search = async () => {
    setSearching(true);
    setAuthorError(null);
    try {
      setAuthorRows(await api.findAuthorStudies(author));
    } catch (e) {
      setAuthorRows(null);
      setAuthorError(message(e));
    } finally {
      setSearching(false);
    }
  };

  return (
    <Stack gap="lg">
      <Paper withBorder p="md">
        <Text fw={600} mb={4}>
          Paste a study link
        </Text>
        <Text size="sm" c="dimmed" mb="xs">
          A Lichess study address (or a link to one of its chapters), or just
          its 8-character ID.
        </Text>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            onAdd(() => api.addStudy(text));
          }}
        >
          <Group
            gap="xs"
            align="flex-end"
            data-no-tip="free text: a link you paste"
          >
            <TextInput
              style={{ flex: 1 }}
              placeholder="https://lichess.org/study/…"
              value={text}
              onChange={(e) => setText(e.currentTarget.value)}
              aria-label="Study link or ID"
              data-testid="study-paste"
            />
            <Button
              type="submit"
              disabled={!text.trim() || busy}
              data-testid="study-paste-add"
            >
              Add
            </Button>
          </Group>
        </form>
        <Group gap="xs" mt="sm">
          <Button
            size="xs"
            variant="default"
            onClick={() => api.openLichessStudiesInBrowser()}
            data-testid="study-open-browser"
          >
            Open Lichess in your browser
          </Button>
          <Button
            size="xs"
            variant="default"
            onClick={async () => {
              setWindowError(null);
              try {
                await api.openLichessWindow();
                setWindowOpen(true);
              } catch (e) {
                setWindowError(message(e));
              }
            }}
            data-testid="study-open-window"
          >
            {windowOpen
              ? "Bring the Lichess window forward"
              : "Browse Lichess in a window"}
          </Button>
        </Group>
        <Text size="xs" c="dimmed" mt={6}>
          The Lichess window shows lichess.org only, in its own process with no
          access to WeakSquare, your settings or your sign-in. You're signed out
          of Lichess there. On a study, click <b>Add this study</b> at its top.
        </Text>
        {windowOpen && windowStudy && (
          <Group gap="xs" mt="xs">
            <Text size="sm">The Lichess window is showing a study.</Text>
            <Button
              size="xs"
              variant="light"
              disabled={busy}
              onClick={() => onAdd(() => api.addStudyById(windowStudy, null))}
              data-testid="study-add-from-window"
            >
              Add it
            </Button>
          </Group>
        )}
        {windowError && (
          <Text size="sm" c="red" mt="xs">
            {windowError}
          </Text>
        )}
      </Paper>

      <Paper withBorder p="md">
        <Text fw={600} mb={4}>
          Studies by author
        </Text>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void search();
          }}
        >
          <Group
            gap="xs"
            align="flex-end"
            data-no-tip="free text: a username you type"
          >
            <TextInput
              style={{ flex: 1 }}
              placeholder="Lichess username"
              value={author}
              onChange={(e) => setAuthor(e.currentTarget.value)}
              aria-label="Lichess username"
              data-testid="study-author"
            />
            <Button
              type="submit"
              variant="default"
              loading={searching}
              disabled={!author.trim()}
              data-testid="study-author-search"
            >
              Search
            </Button>
          </Group>
        </form>
        {authorError && (
          <Text size="sm" c="red" mt="xs" data-testid="study-author-error">
            {authorError}
          </Text>
        )}
        {authorRows && (
          <Stack gap={4} mt="sm" data-testid="study-author-results">
            {authorRows.length === 0 && (
              <Text size="sm" c="dimmed">
                No public studies.
              </Text>
            )}
            {authorRows.map((s) => (
              <Group key={s.study_id} justify="space-between" wrap="nowrap">
                <Text size="sm" style={{ overflowWrap: "anywhere" }}>
                  {s.name}
                </Text>
                <Button
                  size="xs"
                  variant="light"
                  disabled={busy}
                  onClick={() =>
                    onAdd(() => api.addStudyById(s.study_id, null))
                  }
                >
                  {s.saved ? "Open" : "Add"}
                </Button>
              </Group>
            ))}
          </Stack>
        )}
      </Paper>

      <Paper withBorder p="md">
        <Group justify="space-between" mb="xs">
          <Text fw={600}>Starter list</Text>
          <Select
            size="xs"
            placeholder="Any opening"
            clearable
            data={openings}
            value={opening}
            onChange={setOpening}
            label={
              <>
                Opening <OptionInfo id="studies.starterOpening" />
              </>
            }
            data-testid="study-starter-opening"
          />
        </Group>
        <Text size="xs" c="dimmed" mb="xs">
          Comes with WeakSquare: links, titles and authors only. A study is
          downloaded when you add it.
        </Text>
        <ScrollArea.Autosize mah={320}>
          <Stack gap={4} data-testid="study-starter">
            {shown.length === 0 && (
              <Text size="sm" c="dimmed">
                No starter studies.
              </Text>
            )}
            {shown.map((s) => (
              <Group key={s.study_id} justify="space-between" wrap="nowrap">
                <Stack gap={0} style={{ minWidth: 0 }}>
                  <Text size="sm" style={{ overflowWrap: "anywhere" }}>
                    {s.title}
                  </Text>
                  <Text size="xs" c="dimmed">
                    by {s.author} · {s.opening}
                  </Text>
                </Stack>
                <Button
                  size="xs"
                  variant="light"
                  disabled={busy}
                  onClick={() =>
                    onAdd(() => api.addStudyById(s.study_id, null))
                  }
                >
                  {s.saved ? "Open" : "Add"}
                </Button>
              </Group>
            ))}
          </Stack>
        </ScrollArea.Autosize>
      </Paper>
    </Stack>
  );
}

// ---- one study: its chapters and the reader (FR-13.7, 13.8, 13.10) ----------------------------------------------
function StudyPage({
  open,
  coordinates,
  onBack,
}: {
  open: Open;
  coordinates: boolean;
  onBack: () => void;
}) {
  const [detail, setDetail] = useState<StudyDetail | null>(null);
  const [chapterKey, setChapterKey] = useState<string | null>(open.chapterKey);
  const [startPath, setStartPath] = useState<string[]>(open.path);
  const [chapter, setChapter] = useState<StudyChapter | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [update, setUpdate] = useState<StudyUpdate | null>(null);
  const [updateNote, setUpdateNote] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [repertoireOpen, setRepertoireOpen] = useState(false);
  const id = open.studyId;

  useEffect(() => {
    api.getStudy(id).then(
      (d) => {
        setDetail(d);
        setChapterKey(
          (k) => k ?? d.chapters.find((c) => !c.rejected)?.key ?? null,
        );
      },
      (e) => setError(message(e)),
    );
  }, [id, reload]);

  useEffect(() => {
    if (!chapterKey) return;
    let live = true;
    api.getStudyChapter(id, chapterKey).then(
      (c) => live && (setChapter(c), setError(null)),
      (e) => live && setError(message(e)),
    );
    return () => {
      live = false;
    };
  }, [id, chapterKey, reload]);

  const { running, watch } = useJobs(
    useCallback(
      async (job: Job) => {
        if (job.kind !== "study_update") return;
        if (job.state !== "done") {
          setUpdateNote(job.message);
          return;
        }
        const u = await api.getStudyUpdate(id);
        setUpdate(u);
        setUpdateNote(u ? null : job.message);
      },
      [id],
    ),
  );

  const usable = detail?.chapters.filter((c) => !c.rejected) ?? [];
  const idx = usable.findIndex((c) => c.key === chapterKey);
  const next = idx >= 0 && idx + 1 < usable.length ? usable[idx + 1] : null;
  const pick = (key: string) => {
    setChapter(null);
    setStartPath([]);
    setChapterKey(key);
  };
  const onPlace = useCallback((path: string[]) => {
    if (chapterKey) api.setStudyPlace(id, chapterKey, path).catch(() => undefined);
  }, [id, chapterKey]); // prettier-ignore
  const onFinished = useCallback(() => {
    if (!chapterKey) return;
    api.setStudyChapterDone(id, chapterKey, true).then(
      () =>
        setDetail((d) =>
          d
            ? {
                ...d,
                chapters: d.chapters.map((c) =>
                  c.key === chapterKey ? { ...c, done: true } : c,
                ),
              }
            : d,
        ),
      () => undefined,
    );
  }, [id, chapterKey]);

  if (!detail) return error ? <Text c="red">{error}</Text> : <Loader />;
  const s = detail.summary;
  return (
    <Stack gap="sm" data-testid="study-page">
      <Group justify="space-between" wrap="nowrap" align="flex-start">
        <Stack gap={2} style={{ minWidth: 0 }}>
          <Group gap="xs">
            <Button
              size="xs"
              variant="subtle"
              onClick={onBack}
              data-testid="study-back-to-list"
            >
              ← My studies
            </Button>
          </Group>
          <Title
            order={3}
            style={{ overflowWrap: "anywhere" }}
            data-testid="study-page-title"
          >
            {s.title}
          </Title>
          <Text size="sm" c="dimmed">
            by {s.author ?? "unknown"} ·{" "}
            <Anchor
              component="button"
              size="sm"
              onClick={() => api.openStudyOnLichess(id, chapterKey)}
              data-testid="study-on-lichess"
            >
              Open on Lichess
            </Anchor>{" "}
            · your copy, saved on this PC
          </Text>
        </Stack>
        <Group gap={4} wrap="nowrap">
          {/* Only the summary changes: reloading would remount the reader and lose your place (QA v0.14-B5). */}
          <HeartButton
            hearted={s.hearted}
            onChange={async (h) => {
              await api.heartStudy(id, h);
              setDetail((d) =>
                d ? { ...d, summary: { ...d.summary, hearted: h } } : d,
              );
            }}
          />
          <Menu position="bottom-end">
            <Menu.Target>
              <Button size="xs" variant="default" data-testid="study-menu">
                More
              </Button>
            </Menu.Target>
            <Menu.Dropdown>
              <Menu.Item
                onClick={() => setRepertoireOpen(true)}
                data-testid="study-add-repertoire"
              >
                Add to my repertoire…
              </Menu.Item>
              <Menu.Item
                onClick={async () => {
                  setUpdateNote(null);
                  watch(await api.checkStudyUpdates(id));
                }}
                data-testid="study-check-updates"
              >
                Check for updates
              </Menu.Item>
              <Menu.Item
                onClick={() => chapterKey && pick(chapterKey)}
                data-testid="study-restart-chapter"
              >
                Restart this chapter
              </Menu.Item>
              <Menu.Item
                onClick={async () => {
                  await api.restartStudy(id);
                  setStartPath([]);
                  setChapter(null);
                  setChapterKey(usable[0]?.key ?? null);
                  setReload((v) => v + 1);
                }}
                data-testid="study-restart"
              >
                Restart the study
              </Menu.Item>
              <Menu.Divider />
              <Menu.Item
                color="red"
                onClick={() => setConfirmDelete(true)}
                data-testid="study-delete"
              >
                Delete from My studies
              </Menu.Item>
            </Menu.Dropdown>
          </Menu>
        </Group>
      </Group>
      {running && (
        <Group gap="xs">
          <Loader size="xs" />
          <Text size="sm">{running.message}</Text>
        </Group>
      )}
      {updateNote && (
        <Alert
          color="blue"
          withCloseButton
          onClose={() => setUpdateNote(null)}
          data-testid="study-update-note"
        >
          {updateNote}
        </Alert>
      )}
      {update && (
        <UpdateReview
          update={update}
          onApply={async () => {
            await api.applyStudyUpdate(id);
            setUpdate(null);
            setUpdateNote("Your copy is updated.");
            setChapter(null);
            setReload((v) => v + 1);
          }}
          onDiscard={async () => {
            await api.discardStudyUpdate(id);
            setUpdate(null);
          }}
        />
      )}
      <Group align="flex-start" gap="lg" wrap="nowrap">
        <ScrollArea.Autosize mah="70vh" style={{ flex: "0 0 240px" }}>
          <Stack gap={0} data-testid="study-chapters">
            {detail.chapters.map((c) => (
              <NavLink
                key={c.key}
                active={c.key === chapterKey}
                disabled={!!c.rejected}
                onClick={() => !c.rejected && pick(c.key)}
                label={
                  <Text size="sm" style={{ overflowWrap: "anywhere" }}>
                    {c.index + 1}. {c.title}
                  </Text>
                }
                description={
                  c.rejected
                    ? `Can't be used: it ${c.rejected}`
                    : c.text_only
                      ? "Text"
                      : c.mode === "gamebook"
                        ? "Play along"
                        : undefined
                }
                rightSection={
                  c.done ? (
                    <Text size="xs" c="green">
                      ✓
                    </Text>
                  ) : null
                }
                data-testid="study-chapter"
              />
            ))}
          </Stack>
        </ScrollArea.Autosize>
        <Stack gap="sm" style={{ flex: 1, minWidth: 0 }}>
          {error && (
            <Text c="red" size="sm">
              {error}
            </Text>
          )}
          {chapter ? (
            <>
              <Text
                fw={600}
                data-testid="study-chapter-title"
                style={{ overflowWrap: "anywhere" }}
              >
                {chapter.info.title}
              </Text>
              <StudyReader
                key={`${chapter.info.key}:${reload}:${startPath.join(" ")}`}
                chapter={chapter}
                startPath={startPath}
                coordinates={coordinates}
                onPlace={onPlace}
                onFinished={onFinished}
                onNextChapter={next ? () => pick(next.key) : null}
              />
            </>
          ) : (
            !error && <Loader size="sm" />
          )}
        </Stack>
      </Group>
      {repertoireOpen && (
        <StudyRepertoireModal
          studyId={id}
          chapterKey={
            chapter && !chapter.info.text_only ? chapter.info.key : null
          }
          chapterTitle={chapter?.info.title ?? null}
          defaultColor={chapter?.info.orientation ?? "white"}
          onClose={() => setRepertoireOpen(false)}
        />
      )}
      <Modal
        opened={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        title="Delete this study?"
      >
        <Text size="sm">
          Your copy, your place and your progress in it are deleted from this
          PC. The study on Lichess isn't touched.
        </Text>
        <Group justify="flex-end" mt="md">
          <Button variant="default" onClick={() => setConfirmDelete(false)}>
            Cancel
          </Button>
          <Button
            color="red"
            onClick={async () => {
              await api.deleteStudy(id);
              onBack();
            }}
            data-testid="study-delete-confirm"
          >
            Delete
          </Button>
        </Group>
      </Modal>
    </Stack>
  );
}

function UpdateReview({
  update,
  onApply,
  onDiscard,
}: {
  update: StudyUpdate;
  onApply: () => void;
  onDiscard: () => void;
}) {
  const list = (label: string, items: string[]) =>
    items.length > 0 && (
      <Text size="sm">
        <b>{label}:</b> {items.join(", ")}
      </Text>
    );
  return (
    <Paper withBorder p="md" data-testid="study-update">
      <Text fw={600}>The study has changed on Lichess</Text>
      <Text size="sm" c="dimmed" mb="xs">
        Nothing changes in your copy until you update it. Your place is kept if
        its chapter is still there.
      </Text>
      {update.title_changed && (
        <Text size="sm">
          <b>New title:</b> {update.new_title}
        </Text>
      )}
      {list("New chapters", update.added)}
      {list("Removed chapters", update.removed)}
      {list("Changed chapters", update.changed)}
      {update.unchanged > 0 && (
        <Text size="sm">
          {update.unchanged} chapter{update.unchanged === 1 ? "" : "s"}{" "}
          unchanged.
        </Text>
      )}
      <Group gap="xs" mt="sm">
        <Button size="xs" onClick={onApply} data-testid="study-update-apply">
          Update my copy
        </Button>
        <Button
          size="xs"
          variant="default"
          onClick={onDiscard}
          data-testid="study-update-discard"
        >
          Keep my copy
        </Button>
      </Group>
    </Paper>
  );
}
