import { Checkbox, Group, Stack, Text, TextInput } from "@mantine/core";
import { useEffect, useState } from "react";
import { api } from "../api";
import { Labeled } from "./OptionInfo";

type Site = "youtube" | "chesscom" | "custom";

// Settings → Coach (v0.11, FR-10.59): which search links lesson pointers show, and an optional custom
// search site. The links themselves are built by the backend; the bridge validates these again.
export function CoachSettingsPanel() {
  const [sites, setSites] = useState<Site[] | null>(null);
  const [custom, setCustom] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  useEffect(() => {
    api.getSettings().then(
      (s) => {
        setSites(s.lesson_sites);
        setCustom(s.lesson_custom_url);
      },
      () => undefined,
    );
  }, []);

  const save = async (what: string, run: () => Promise<void>) => {
    setError(null);
    setSaved(null);
    try {
      await run();
      setSaved(what);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const toggle = (site: Site, on: boolean) => {
    const next = on ? [...(sites ?? []), site] : (sites ?? []).filter((s) => s !== site);
    setSites(next);
    void save("Search sites saved.", () => api.setSetting("coach.lesson_sites", next));
  };

  if (sites === null) return null;
  return (
    <Stack gap="xs" data-testid="coach-settings">
      <Text size="sm" fw={500}>
        Lesson pointers: search links
      </Text>
      <Group gap="md">
        <Checkbox label={<Labeled id="lessons.youtube">YouTube</Labeled>} checked={sites.includes("youtube")} onChange={(e) => toggle("youtube", e.currentTarget.checked)} data-testid="lesson-site-youtube" />
        <Checkbox label={<Labeled id="lessons.chesscom">chess.com</Labeled>} checked={sites.includes("chesscom")} onChange={(e) => toggle("chesscom", e.currentTarget.checked)} data-testid="lesson-site-chesscom" />
        <Checkbox label={<Labeled id="lessons.custom">My own site</Labeled>} checked={sites.includes("custom")} onChange={(e) => toggle("custom", e.currentTarget.checked)} data-testid="lesson-site-custom" />
      </Group>
      <TextInput
        label={<Labeled id="lessons.customUrl">My own search site</Labeled>}
        description="An https:// search address with {q} where the search words go, e.g. https://example.org/search?q={q}"
        value={custom}
        onChange={(e) => setCustom(e.currentTarget.value)}
        onBlur={() => save("Search site saved.", () => api.setSetting("coach.lesson_custom_url", custom.trim()))}
        data-testid="lesson-custom-url"
      />
      <Text size="xs" c="dimmed">
        Links open in your default browser. The app never visits these sites itself; the search words go to the site you click.
      </Text>
      {saved && <Text size="xs" c="dimmed">{saved}</Text>}
      {error && (
        <Text size="xs" c="red" data-testid="coach-settings-error">
          {error}
        </Text>
      )}
    </Stack>
  );
}
