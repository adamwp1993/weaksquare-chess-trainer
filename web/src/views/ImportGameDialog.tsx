// v0.8: Import game (FR-11.1–11.7): paste a PGN, open a .pgn file (pick a game when it holds several),
// or a Lichess / chess.com URL. When your color can't be told from your linked usernames, it asks.
import { Alert, Button, Group, Modal, Radio, Stack, Tabs, Text, TextInput, Textarea } from "@mantine/core";
import { useEffect, useState } from "react";
import { api } from "../api";
import { ApiCallError } from "../api/ApiClient";
import type { GameImport } from "../api/types";
import { useJob } from "../state/useJob";

export function ImportGameDialog({
  opened,
  onClose,
  onImported,
}: {
  opened: boolean;
  onClose: () => void;
  onImported: (gameId: number) => void;
}) {
  const [tab, setTab] = useState<string | null>("paste");
  const [text, setText] = useState("");
  const [url, setUrl] = useState("");
  const [ccUser, setCcUser] = useState("");
  const [needCcUser, setNeedCcUser] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [listed, setListed] = useState<GameImport | null>(null);
  const [pick, setPick] = useState<string | null>(null);
  const [colorFor, setColorFor] = useState<number | null>(null);
  const [color, setColor] = useState<"white" | "black" | "both">("white");
  const [urlJob, setUrlJob] = useState<string | null>(null);
  const job = useJob(urlJob);

  const reset = () => {
    setError(null);
    setListed(null);
    setPick(null);
    setColorFor(null);
    setUrlJob(null);
    setNeedCcUser(false);
  };

  const done = (r: GameImport) => {
    if (r.choices.length > 0 && r.token) {
      setListed(r);
      setPick(String(r.choices.find((c) => !c.error)?.index ?? 0));
      return;
    }
    if (r.game_id === null) return;
    if (r.needs_color) {
      setColorFor(r.game_id);
      return;
    }
    onImported(r.game_id);
  };

  const run = async (f: () => Promise<GameImport | null>) => {
    setBusy(true);
    setError(null);
    try {
      const r = await f();
      if (r) done(r);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const startUrl = async () => {
    setError(null);
    try {
      setUrlJob(await api.startGameUrlImport(url.trim(), needCcUser && ccUser.trim() ? ccUser.trim() : null));
    } catch (e) {
      if (e instanceof ApiCallError && e.code === "chesscom_username_needed") setNeedCcUser(true);
      setError((e as Error).message);
    }
  };

  useEffect(() => {
    if (!job || !urlJob || job.state === "running") return;
    if (job.state === "done") {
      api.getGameUrlImport(urlJob).then((r) => r && done(r), (e: Error) => setError(e.message));
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reacting to the job pushed by the backend
    } else setError(job.message);
    setUrlJob(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job]);

  const close = () => {
    reset();
    onClose();
  };

  return (
    <Modal opened={opened} onClose={close} title="Import a game" size="lg" data-testid="import-game-dialog">
      {colorFor !== null ? (
        <Stack>
          <Text size="sm">Which side did you play? The app couldn't tell from your linked accounts.</Text>
          <Radio.Group value={color} onChange={(v) => setColor(v as typeof color)}>
            <Group>
              <Radio value="white" label="White" />
              <Radio value="black" label="Black" />
              <Radio value="both" label="Review both sides" />
            </Group>
          </Radio.Group>
          <Group justify="flex-end">
            <Button
              onClick={async () => {
                await api.setGameColor(colorFor, color);
                const id = colorFor;
                reset();
                onImported(id);
              }}
              data-testid="import-color-ok"
            >
              Review
            </Button>
          </Group>
        </Stack>
      ) : listed ? (
        <Stack>
          <Text size="sm">This file holds {listed.choices.length} games. Pick one to review.</Text>
          <Radio.Group value={pick} onChange={setPick}>
            <Stack gap={6}>
              {listed.choices.map((c) => (
                <Radio
                  key={c.index}
                  value={String(c.index)}
                  disabled={c.error !== null}
                  label={c.error ? `${c.label}: ${c.error}` : c.label}
                  data-testid={`import-choice-${c.index}`}
                />
              ))}
            </Stack>
          </Radio.Group>
          <Group justify="flex-end">
            <Button
              disabled={pick === null}
              loading={busy}
              onClick={() => run(() => api.pickImportedGame(listed.token!, Number(pick)))}
              data-testid="import-pick"
            >
              Import this game
            </Button>
          </Group>
        </Stack>
      ) : (
        <Tabs
          value={tab}
          onChange={(t) => {
            reset();
            setTab(t);
          }}
        >
          <Tabs.List>
            <Tabs.Tab value="paste">Paste PGN</Tabs.Tab>
            <Tabs.Tab value="file">PGN file</Tabs.Tab>
            <Tabs.Tab value="url">Game URL</Tabs.Tab>
          </Tabs.List>
          <Tabs.Panel value="paste" pt="sm">
            <Stack>
              <Textarea
                autosize
                minRows={6}
                maxRows={14}
                placeholder={'[White "…"]\n[Black "…"]\n\n1. e4 e5 2. Nf3 …'}
                value={text}
                onChange={(e) => setText(e.currentTarget.value)}
                data-testid="import-pgn-text"
              />
              <Group justify="flex-end">
                <Button loading={busy} disabled={!text.trim()} onClick={() => run(() => api.importGamePgn(text))} data-testid="import-pgn">
                  Import
                </Button>
              </Group>
            </Stack>
          </Tabs.Panel>
          <Tabs.Panel value="file" pt="sm">
            <Stack>
              <Text size="sm" c="dimmed">
                A .pgn file from your PC. If it holds several games, you pick one.
              </Text>
              <Group>
                <Button loading={busy} onClick={() => run(() => api.chooseGameFile())} data-testid="import-file">
                  Choose a PGN file…
                </Button>
              </Group>
            </Stack>
          </Tabs.Panel>
          <Tabs.Panel value="url" pt="sm">
            <Stack>
              <TextInput
                label="Lichess or chess.com game URL"
                placeholder="https://lichess.org/abcdefgh or https://www.chess.com/game/live/123…"
                value={url}
                onChange={(e) => setUrl(e.currentTarget.value)}
                data-testid="import-url"
              />
              {needCcUser && (
                <TextInput
                  label="Your chess.com username"
                  description="chess.com has no single-game lookup, so the app searches your recent monthly archives."
                  value={ccUser}
                  onChange={(e) => setCcUser(e.currentTarget.value)}
                  data-testid="import-cc-user"
                />
              )}
              {job?.state === "running" && <Text size="sm" c="dimmed">{job.message}</Text>}
              <Group justify="flex-end">
                <Button loading={job?.state === "running"} disabled={!url.trim()} onClick={startUrl} data-testid="import-url-go">
                  Import
                </Button>
              </Group>
            </Stack>
          </Tabs.Panel>
        </Tabs>
      )}
      {error && (
        <Alert color="red" mt="sm" data-testid="import-error">
          {error}
        </Alert>
      )}
    </Modal>
  );
}
