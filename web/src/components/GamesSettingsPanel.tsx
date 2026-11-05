// v0.8 Settings → Games (FR-11.23–11.27, FR-11.8, 11.9, 11.15): linked accounts, sync, and the analysis.
// v0.10: which of your mistakes become puzzles (FR-10.40) and the think time for checking them (FR-10.41).
import { Alert, Button, Group, NumberInput, Select, Stack, Switch, Text, TextInput } from "@mantine/core";
import { useEffect, useState } from "react";
import { api } from "../api";
import type { GamesSettingsChange } from "../api/ApiClient";
import type { ChesscomProfile, GamesSettings } from "../api/types";

export function GamesSettingsPanel() {
  const [s, setS] = useState<GamesSettings | null>(null);
  const [user, setUser] = useState("");
  const [profile, setProfile] = useState<ChesscomProfile | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    api.getGamesSettings().then((v) => {
      setS(v);
      setUser(v.chesscom_username ?? "");
    }, () => undefined);
  }, []);
  if (!s) return null;

  const save = async (change: GamesSettingsChange, said: string) => {
    try {
      setS(await api.setGamesSettings(change));
      setMsg({ ok: true, text: said });
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    }
  };
  const verify = async () => {
    setProfile(null);
    try {
      setProfile(await api.verifyChesscom(user));
      setMsg(null);
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    }
  };
  const link = async (name: string | null) => {
    try {
      const v = await api.setChesscomUsername(name);
      setS(v);
      setUser(v.chesscom_username ?? "");
      setMsg({ ok: true, text: name ? `Linked ${name}.` : "chess.com unlinked." });
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    }
  };
  const num = (v: string | number) => (typeof v === "number" ? v : Number.parseFloat(v));

  return (
    <Stack gap="sm" data-testid="games-settings">
      <Text size="sm">
        Lichess: {s.lichess_username ? <b>{s.lichess_username}</b> : "sign in with Lichess to sync your Lichess games"}
      </Text>
      <Group align="end" gap="xs">
        <TextInput
          label="chess.com username"
          description="Public games only: chess.com needs no login, so linking by username grants nothing."
          value={user}
          onChange={(e) => setUser(e.currentTarget.value)}
          w={300}
          data-testid="chesscom-user"
        />
        <Button variant="default" onClick={verify} disabled={!user.trim()} data-testid="chesscom-verify">
          Verify
        </Button>
        <Button onClick={() => link(user.trim())} disabled={!user.trim() || user.trim() === s.chesscom_username} data-testid="chesscom-link">
          Link
        </Button>
        {s.chesscom_username && (
          <Button variant="subtle" color="red" onClick={() => link(null)}>
            Unlink
          </Button>
        )}
      </Group>
      {profile && (
        <Text size="sm" data-testid="chesscom-profile">
          Found {profile.username}
          {profile.name ? ` (${profile.name})` : ""} on chess.com.
        </Text>
      )}
      <Switch
        label="Sync new games when the app opens"
        checked={s.sync_on_open}
        onChange={(e) => save({ sync_on_open: e.currentTarget.checked }, "Saved.")}
        data-testid="games-sync-on-open"
      />
      <Group gap="sm">
        <NumberInput label="First sync: days back" min={1} max={3650} w={170} value={s.first_sync_days}
          onBlur={(e) => save({ first_sync_days: num(e.currentTarget.value) }, "Saved.")} />
        <NumberInput label="First sync: at most (games)" min={1} max={5000} w={190} value={s.first_sync_max}
          onBlur={(e) => save({ first_sync_max: num(e.currentTarget.value) }, "Saved.")} />
      </Group>
      <Group gap="sm">
        <NumberInput label="Analysis: seconds per position" min={0.1} max={5} step={0.1} decimalScale={2} w={210} value={s.think_s}
          onBlur={(e) => save({ think_s: num(e.currentTarget.value) }, "Saved. New analyses use it.")} data-testid="games-think" />
        <NumberInput label="Key moments" min={1} max={10} w={130} value={s.key_moments}
          onBlur={(e) => save({ key_moments: num(e.currentTarget.value) }, "Saved.")} />
        <NumberInput label="Retry tolerance (cp)" min={0} max={300} w={160} value={s.tolerance_cp}
          onBlur={(e) => save({ tolerance_cp: num(e.currentTarget.value) }, "Saved.")} />
      </Group>
      <Group gap="sm">
        {(["inaccuracy", "mistake", "blunder"] as const).map((k) => (
          <NumberInput
            key={k}
            label={`${k[0].toUpperCase()}${k.slice(1)} from (cp)`}
            min={1}
            max={2000}
            w={160}
            value={s.thresholds[k]}
            onBlur={(e) => save({ thresholds: { ...s.thresholds, [k]: num(e.currentTarget.value) } }, "Saved. New analyses use it.")}
          />
        ))}
      </Group>
      <Group gap="sm" align="flex-end">
        <Select
          label="Puzzles from your games"
          w={280}
          data={[
            { value: "blunders", label: "Blunders only" },
            { value: "mistakes", label: "Mistakes and blunders" },
            { value: "inaccuracies", label: "Inaccuracies, mistakes and blunders" },
          ]}
          value={s.puzzle_level}
          allowDeselect={false}
          onChange={(v) =>
            v &&
            save(
              { puzzle_level: v as GamesSettings["puzzle_level"] },
              "Saved. Puzzles outside the level are archived, not deleted; nothing is analyzed again.",
            )
          }
          data-testid="games-puzzle-level"
        />
        <NumberInput label="Checking a puzzle: seconds per position" min={0.2} max={5} step={0.1} decimalScale={2} w={250}
          value={s.puzzle_think_s} onBlur={(e) => save({ puzzle_think_s: num(e.currentTarget.value) }, "Saved.")} />
      </Group>
      <Text size="xs" c="dimmed">
        A mistake becomes a puzzle only if it has one clear answer (Lichess's rules), so inaccuracies add few puzzles.
      </Text>
      {msg && (
        <Alert color={msg.ok ? "green" : "red"} p="xs" data-testid="games-settings-msg">
          {msg.text}
        </Alert>
      )}
    </Stack>
  );
}
