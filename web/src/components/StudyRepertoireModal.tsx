// v0.14 (FR-13.11): Add to my repertoire from a study. Shows what would be added and asks at each conflict; nothing is
// saved until you confirm. The moves come from the study's checked moves, never from an AI.
import { Alert, Button, Group, Loader, Modal, Paper, Radio, SegmentedControl, Stack, Switch, Text } from "@mantine/core";
import { useEffect, useState } from "react";
import { api, ApiCallError } from "../api";
import type { StudyRepertoirePreview } from "../api/types";
import { OptionInfo } from "./OptionInfo";

/** "1. e4 e5 2. Nc3" from SAN moves played from the start. */
export function sanPath(sans: string[]): string {
  return sans.map((s, i) => (i % 2 === 0 ? `${i / 2 + 1}. ${s}` : s)).join(" ");
}

export function StudyRepertoireModal({
  studyId,
  chapterKey,
  chapterTitle,
  defaultColor,
  onClose,
}: {
  studyId: string;
  chapterKey: string | null;
  chapterTitle: string | null;
  defaultColor: "white" | "black";
  onClose: () => void;
}) {
  const [color, setColor] = useState<"white" | "black">(defaultColor);
  const [scope, setScope] = useState<"chapter" | "study">(chapterKey ? "chapter" : "study");
  const [sideLines, setSideLines] = useState(false);
  const [preview, setPreview] = useState<StudyRepertoirePreview | null>(null);
  const [choices, setChoices] = useState<Record<string, "mine" | "study">>({});
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let live = true;
    /* eslint-disable react-hooks/set-state-in-effect */
    setPreview(null);
    setChoices({});
    setError(null);
    /* eslint-enable react-hooks/set-state-in-effect */
    api.previewStudyRepertoire(studyId, scope === "chapter" ? chapterKey : null, color, sideLines).then(
      (p) => live && setPreview(p),
      (e) => live && setError(e instanceof ApiCallError ? e.message : String(e)),
    );
    return () => {
      live = false;
    };
  }, [studyId, chapterKey, scope, color, sideLines]);

  const close = () => {
    if (!done) api.discardStudyRepertoire().catch(() => undefined);
    onClose();
  };

  const save = async () => {
    if (!preview) return;
    setSaving(true);
    try {
      const r = await api.saveStudyRepertoire(preview.id, choices);
      setDone(
        `Added ${r.added} move${r.added === 1 ? "" : "s"} to your ${color === "white" ? "White" : "Black"} repertoire` +
          (r.kept ? `; ${r.kept} you already had stayed as they were` : "") +
          ". Drill them under Openings → Practice.",
      );
    } catch (e) {
      setError(e instanceof ApiCallError ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const total = preview ? preview.yours + preview.theirs : 0;
  return (
    <Modal opened onClose={close} title="Add to my repertoire" size="lg">
      {done ? (
        <Stack>
          <Alert color="green" data-testid="study-rep-done">{done}</Alert>
          <Group justify="flex-end"><Button onClick={onClose}>Close</Button></Group>
        </Stack>
      ) : (
        <Stack gap="sm" data-testid="study-rep-modal">
          <Group gap="xs" data-option-group>
            <SegmentedControl size="xs" value={color} onChange={(v) => setColor(v as "white" | "black")}
              data={[{ value: "white", label: "My White repertoire" }, { value: "black", label: "My Black repertoire" }]}
              data-testid="study-rep-color" />
            <OptionInfo id="studies.repertoireColor" />
          </Group>
          {chapterKey && (
            <Group gap="xs" data-option-group>
              <SegmentedControl size="xs" value={scope} onChange={(v) => setScope(v as "chapter" | "study")}
                data={[{ value: "chapter", label: chapterTitle ? `This chapter: ${chapterTitle}` : "This chapter" }, { value: "study", label: "Whole study" }]}
                data-testid="study-rep-scope" />
              <OptionInfo id="studies.repertoireScope" />
            </Group>
          )}
          <Switch checked={sideLines} onChange={(e) => setSideLines(e.currentTarget.checked)}
            label={<>Include side lines <OptionInfo id="studies.sideLines" /></>} data-testid="study-rep-side-lines" />
          {error && <Text c="red" size="sm">{error}</Text>}
          {!preview && !error && <Loader size="sm" />}
          {preview && (
            <Paper withBorder p="sm" data-testid="study-rep-summary">
              <Text size="sm">
                {total === 0 && preview.conflicts.length === 0
                  ? "Nothing new to add."
                  : `Adds ${preview.yours} move${preview.yours === 1 ? "" : "s"} for you and ${preview.theirs} repl${preview.theirs === 1 ? "y" : "ies"} for the other side.`}
                {preview.already > 0 && ` You already have ${preview.already}.`}
              </Text>
              {preview.unreachable > 0 && (
                <Text size="sm" c="dimmed">
                  {preview.unreachable} move{preview.unreachable === 1 ? "" : "s"} start from a position your repertoire doesn't reach yet, so
                  {preview.unreachable === 1 ? " it's" : " they're"} skipped. Your repertoire starts from the first move.
                </Text>
              )}
              {preview.skipped.length > 0 && <Text size="sm" c="dimmed">Skipped: {preview.skipped.join("; ")}.</Text>}
            </Paper>
          )}
          {preview && preview.conflicts.length > 0 && (
            <Stack gap="xs" data-testid="study-rep-conflicts">
              <Text size="sm" fw={600}>The study plays a different move from yours here:</Text>
              {preview.conflicts.map((c) => (
                <Paper key={c.position_key} withBorder p="xs" data-option-group data-testid="study-rep-conflict">
                  <Text size="sm">
                    After <b>{sanPath(c.path) || "the start"}</b>: you play <b>{c.yours.join(", ")}</b>, the study plays{" "}
                    <b>{c.study.join(", ")}</b>. <OptionInfo id="studies.conflict" />
                  </Text>
                  <Radio.Group value={choices[c.position_key] ?? "mine"} onChange={(v) => setChoices((x) => ({ ...x, [c.position_key]: v as "mine" | "study" }))}>
                    <Group gap="md" mt={4}>
                      <Radio value="mine" label="Keep mine" />
                      <Radio value="study" label="Use the study's (mine stays as a sideline)" data-testid="study-rep-use-study" />
                    </Group>
                  </Radio.Group>
                </Paper>
              ))}
            </Stack>
          )}
          <Group justify="flex-end">
            <Button variant="default" onClick={close}>Cancel</Button>
            <Button onClick={save} loading={saving} disabled={!preview || (total === 0 && preview.conflicts.length === 0)} data-testid="study-rep-save">
              Add to my repertoire
            </Button>
          </Group>
        </Stack>
      )}
    </Modal>
  );
}
