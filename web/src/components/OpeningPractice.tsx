// v0.13: Practice, opening stats, "What if they play…?" and Build my repertoire (FR-12.8-12.11, 12.14). Moves come from
// the backend, and yours are checked there. Nothing here affects any rating or your puzzle stats.
import {
  Alert,
  Badge,
  Button,
  Checkbox,
  Group,
  Modal,
  NumberInput,
  Paper,
  Radio,
  ScrollArea,
  SegmentedControl,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
} from "@mantine/core";
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { ReasonKey } from "../api/ApiClient";
import type { Analysis, OpeningDeviation, OpeningStat, PracticeState, PracticeSummary, RepertoireOpeningRow, RepertoireProposal } from "../api/types";
import { sourceLabel } from "../state/openingLine";
import { useJob } from "../state/useJob";
import { Board } from "./Board";
import { OptionInfo } from "./OptionInfo";
import { ReasonChips } from "./ReasonChips";

type Color = "white" | "black";

function message(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

// ---- Practice (FR-12.9, 12.10) --------------------------------------------------------------------------------------

export function PracticeTab({ coordinates, version }: { coordinates: boolean; version: number }) {
  const [color, setColor] = useState<Color>("white");
  const [mode, setMode] = useState<"due" | "new" | "all">("due");
  const [openings, setOpenings] = useState<RepertoireOpeningRow[]>([]);
  const [opening, setOpening] = useState<string | null>(null);
  const [summary, setSummary] = useState<PracticeSummary | null>(null);
  const [tolerance, setTolerance] = useState(false);
  const [s, setS] = useState<PracticeState | null>(null);
  const [refutation, setRefutation] = useState<Analysis | null>(null);
  const [reason, setReason] = useState<ReasonKey | null>(null);
  const [note, setNote] = useState("");
  const [asked, setAsked] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    api.getPracticeSummary(color).then(setSummary, (e: unknown) => setError(message(e)));
    api.getRepertoire(color).then((r) => setOpenings(r.openings), (e: unknown) => setError(message(e)));
    api.getPracticeTolerance().then(setTolerance, () => undefined);
  }, [color]);
  useEffect(refresh, [refresh, version]);

  const apply = (next: PracticeState) => {
    setS(next);
    setError(null);
    setRefutation(null);
    setReason(null);
    setNote("");
    setAsked(true);
    if (next.state === "wrong" && next.wrong_fen) {
      api.analyzeOpeningPosition(next.wrong_fen, "board", next.color as Color).then(setRefutation, () => undefined);
    }
    if (next.state === "finished") refresh();
  };
  const act = (p: Promise<PracticeState>) => p.then(apply, (e: unknown) => setError(message(e)));

  if (!s || s.state === "finished") {
    const nothing = s?.state === "finished" && s.decisions === 0;
    return (
      <Stack gap="sm" data-testid="practice-start">
        {s && s.decisions > 0 && (
          <Alert color="teal" data-testid="practice-finished">
            That's the session: {s.correct} right, {s.wrong} missed, {s.lines_clean} clean {s.lines_clean === 1 ? "line" : "lines"}.
          </Alert>
        )}
        {nothing && (
          <Text size="sm" c="dimmed" data-testid="practice-nothing">
            Nothing's due. Come back when a position's next review arrives, or choose All to go through them now.
          </Text>
        )}
        <Group gap="md" align="flex-end" wrap="wrap">
          <div data-option-group>
            <Text size="sm" fw={500}>
              Side <OptionInfo id="repertoire.color" />
            </Text>
            <SegmentedControl
              size="xs"
              value={color}
              onChange={(v) => {
                setColor(v as Color);
                setOpening(null);
              }}
              data={[
                { value: "white", label: "White" },
                { value: "black", label: "Black" },
              ]}
              data-testid="practice-color"
            />
          </div>
          <div data-option-group>
            <Text size="sm" fw={500}>
              What to practise <OptionInfo id="practice.mode" />
            </Text>
            <SegmentedControl
              size="xs"
              value={mode}
              onChange={(v) => setMode(v as typeof mode)}
              data={[
                { value: "due", label: "Due, then a few new" },
                { value: "new", label: "New lines" },
                { value: "all", label: "All" },
              ]}
              data-testid="practice-mode"
            />
          </div>
          <Select
            size="xs"
            w={240}
            clearable
            label={
              <>
                Opening <OptionInfo id="practice.opening" />
              </>
            }
            placeholder="All my openings"
            data={openings.map((o) => ({ value: String(o.id), label: o.name }))}
            value={opening}
            onChange={setOpening}
            data-testid="practice-opening"
          />
        </Group>
        <Checkbox
          size="sm"
          checked={tolerance}
          onChange={(e) => {
            const on = e.currentTarget.checked;
            api.setPracticeTolerance(on).then(setTolerance, (err: unknown) => setError(message(err)));
          }}
          label={
            <>
              Accept moves close to the engine's best <OptionInfo id="practice.tolerance" />
            </>
          }
          data-testid="practice-tolerance"
        />
        {summary && (
          <Text size="sm" data-testid="practice-summary">
            {summary.due} due, {summary.new} new, {summary.positions} positions in all.
          </Text>
        )}
        {error && (
          <Alert color="red" data-testid="practice-error">
            {error}
          </Alert>
        )}
        <Button
          style={{ alignSelf: "flex-start" }}
          disabled={!summary || summary.positions === 0}
          data-testid="practice-begin"
          onClick={() => act(api.startPractice(color, mode, opening ? Number(opening) : null))}
        >
          Start practice
        </Button>
        {summary?.positions === 0 && (
          <Text size="sm" c="dimmed" data-testid="practice-empty">
            Add some lines to your repertoire first.
          </Text>
        )}
      </Stack>
    );
  }

  const yourTurn = s.state === "your_move";
  const missed = s.state === "wrong" || s.state === "helped";
  return (
    <Group align="flex-start" gap="lg" wrap="wrap" data-testid="practice-session" data-state={s.state}>
      <div style={{ flex: "1 1 360px", maxWidth: 560 }}>
        <Board
          key={`${s.decisions}:${s.state}`}
          fen={s.fen}
          orientation={s.color as Color}
          movable={yourTurn ? (s.color as Color) : null}
          onMove={(uci) => act(api.playPracticeMove(s.session_id, uci))}
          coordinates={coordinates}
          maxWidth={560}
        />
      </div>
      <Stack gap="sm" style={{ flex: "1 1 300px", minWidth: 280 }}>
        <Text size="sm" data-testid="practice-tally">
          {s.correct} right · {s.wrong} missed · {s.remaining} to go
          {s.target_reason === "new" && (
            <Badge ml={6} size="xs" variant="light" style={{ textTransform: "none" }}>
              New
            </Badge>
          )}
        </Text>
        {s.message && (
          <Text size="sm" c="teal" data-testid="practice-message">
            {s.message}
          </Text>
        )}
        {yourTurn && (
          <>
            <Text fw={600} data-testid="practice-your-move">
              Your move: what do you play here?
            </Text>
            <Button size="xs" variant="default" style={{ alignSelf: "flex-start" }} onClick={() => act(api.showPracticeAnswer(s.session_id))} data-testid="practice-show">
              Show the answer (counts as missed)
            </Button>
          </>
        )}
        {missed && (
          <Paper withBorder p="sm" radius="md" data-testid="practice-missed">
            <Stack gap={6}>
              <Text fw={600} c="orange">
                {s.state === "wrong" ? "Not your line." : "Your line plays:"}{" "}
                <Text span data-testid="practice-correct">
                  {s.correct_moves.map((m) => m[1]).join(" or ")}
                </Text>
              </Text>
              {refutation && !refutation.superseded && refutation.lines[0] && (
                <Text size="sm" data-testid="practice-refutation">
                  After your move, Stockfish says {refutation.lines[0].score}.
                </Text>
              )}
              {s.state === "wrong" && s.reason_prompt && asked && (
                <ReasonChips
                  prompt={s.reason_prompt}
                  chosen={reason}
                  busy={false}
                  note={note}
                  onNote={setNote}
                  onChoose={(r) => {
                    setReason(r);
                    api.setPracticeReason(s.attempt_id as number, r, note.trim() || null).catch((e: unknown) => setError(message(e)));
                  }}
                  onSkip={() => setAsked(false)}
                />
              )}
              <Button size="xs" style={{ alignSelf: "flex-start" }} onClick={() => act(api.continuePractice(s.session_id))} data-testid="practice-continue">
                Continue
              </Button>
            </Stack>
          </Paper>
        )}
        {s.state === "line_end" && (
          <Stack gap={6} data-testid="practice-line-end">
            <Text size="sm">That's the end of this line.</Text>
            <Button size="xs" style={{ alignSelf: "flex-start" }} onClick={() => act(api.continuePractice(s.session_id))} data-testid="practice-next-line">
              Next
            </Button>
          </Stack>
        )}
        {error && (
          <Alert color="red" data-testid="practice-error">
            {error}
          </Alert>
        )}
        <Button
          size="xs"
          variant="subtle"
          style={{ alignSelf: "flex-start" }}
          data-testid="practice-stop"
          onClick={() => {
            api.endPractice(s.session_id).catch(() => undefined);
            setS(null);
            refresh();
          }}
        >
          Stop
        </Button>
      </Stack>
    </Group>
  );
}

// ---- stats (FR-12.11) ----------------------------------------------------------------------------------------------------

function percent(correct: number, attempts: number): string {
  return attempts ? `${Math.round((correct / attempts) * 100)}%` : "–";
}

export function OpeningStatsTab({ version }: { version: number }) {
  const [color, setColor] = useState<Color>("white");
  const [stats, setStats] = useState<OpeningStat[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.getOpeningStats(color).then(setStats, (e: unknown) => setError(message(e)));
  }, [color, version]);
  return (
    <Stack gap="sm" data-testid="opening-stats">
      <Group gap={6} data-option-group>
        <SegmentedControl
          size="xs"
          value={color}
          onChange={(v) => setColor(v as Color)}
          data={[
            { value: "white", label: "White" },
            { value: "black", label: "Black" },
          ]}
          data-testid="opening-stats-color"
        />
        <OptionInfo id="repertoire.color" />
      </Group>
      <Text size="xs" c="dimmed">
        Kept on your PC, never sent to Lichess, and no effect on any rating.
      </Text>
      {error && <Alert color="red">{error}</Alert>}
      {stats?.length === 0 && (
        <Text size="sm" c="dimmed" data-testid="opening-stats-empty">
          Nothing here yet. Add an opening to your repertoire and practise it.
        </Text>
      )}
      {stats?.map((o) => (
        <Paper key={o.id} withBorder p="sm" radius="md" data-testid="opening-stat">
          <Group justify="space-between" wrap="wrap">
            <Text fw={700}>
              {o.name} ({o.eco})
            </Text>
            <Text size="sm">
              {percent(o.correct, o.attempts)} of {o.attempts} · {o.due} due · {o.positions} positions
            </Text>
          </Group>
          {o.lines.length > 0 && (
            <Table mt="xs" verticalSpacing={2} data-testid="opening-stat-lines">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Line</Table.Th>
                  <Table.Th>Accuracy</Table.Th>
                  <Table.Th>Due</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {o.lines.map((l, i) => (
                  <Table.Tr key={i}>
                    <Table.Td>{l.name}</Table.Td>
                    <Table.Td>
                      {percent(l.correct, l.attempts)} of {l.attempts}
                    </Table.Td>
                    <Table.Td>{l.due}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          )}
          {o.weakest.length > 0 && (
            <Stack gap={2} mt="xs" data-testid="opening-stat-weakest">
              <Text size="sm" fw={600}>
                Weakest positions
              </Text>
              {o.weakest.map((p) => (
                <Text size="sm" key={p.position_key}>
                  {p.label}: {percent(p.correct, p.attempts)} of {p.attempts}
                </Text>
              ))}
            </Stack>
          )}
        </Paper>
      ))}
    </Stack>
  );
}

// ---- "What if they play…?" (FR-12.8) --------------------------------------------------------------------------------------

export function WhatIfPanel({
  color,
  moves,
  boardMove,
  onPreview,
  onAdded,
}: {
  color: Color;
  moves: string[];
  /** Their move, played on the board. */
  boardMove: string | null;
  onPreview: (fen: string | null) => void;
  onAdded: () => void;
}) {
  const [text, setText] = useState("");
  const [d, setD] = useState<OpeningDeviation | null>(null);
  const [reply, setReply] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  const ask = useCallback(
    (move: string) => {
      setError(null);
      setSaved(null);
      setBusy(true);
      api.getOpeningDeviation(color, moves, move).then(
        (next) => {
          setD(next);
          setReply(next.replies[0]?.uci ?? null);
          onPreview(next.fen_after);
          setBusy(false);
        },
        (e: unknown) => {
          setError(message(e));
          setBusy(false);
        },
      );
    },
    [color, moves, onPreview],
  );

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- it starts a request; the board's move is its input
    if (boardMove) ask(boardMove);
  }, [boardMove, ask]);

  return (
    <Paper withBorder p="sm" radius="md" data-testid="what-if">
      <Text fw={700} size="sm" mb={4}>
        What if they play…?
      </Text>
      <Text size="xs" c="dimmed" mb={6}>
        Play their move on the board, or type it.
      </Text>
      <Group gap="xs" data-no-tip="free text: a move you type">
        <TextInput
          size="xs"
          w={110}
          placeholder="e.g. a6"
          aria-label="Their move"
          value={text}
          onChange={(e) => setText(e.currentTarget.value)}
          data-testid="what-if-move"
        />
        <Button size="xs" variant="light" disabled={!text.trim() || busy} onClick={() => ask(text)} data-testid="what-if-go">
          {busy ? "Stockfish is thinking…" : "Find replies"}
        </Button>
      </Group>
      {error && (
        <Text size="sm" c="red" mt={6} data-testid="what-if-error">
          {error}
        </Text>
      )}
      {d && (
        <Stack gap={6} mt={8} data-testid="what-if-replies">
          <Text size="sm">
            After <b>{d.their_san}</b>, your best replies:
          </Text>
          {d.game_over && <Text size="sm">{d.game_over}</Text>}
          <div data-no-tip="a row you select">
            <Radio.Group value={reply} onChange={setReply}>
              <Stack gap={4}>
                {d.replies.map((r) => (
                  <Radio key={r.uci} size="xs" value={r.uci} label={`${r.san}  (${r.score})`} data-testid="what-if-reply" />
                ))}
              </Stack>
            </Radio.Group>
          </div>
          <Group gap="xs">
            <Button
              size="xs"
              disabled={!reply}
              data-testid="what-if-add"
              onClick={() =>
                api.addOpeningDeviation(color, moves, d.their_uci, reply as string).then(
                  (r) => {
                    setSaved(`Added to your ${color} repertoire (${r.added} new ${r.added === 1 ? "move" : "moves"}). Practice will drill it.`);
                    onAdded();
                  },
                  (e: unknown) => setError(message(e)),
                )
              }
            >
              Add to my repertoire
            </Button>
            <Button
              size="xs"
              variant="default"
              onClick={() => {
                setD(null);
                setText("");
                setSaved(null);
                onPreview(null);
              }}
              data-testid="what-if-clear"
            >
              Clear
            </Button>
          </Group>
        </Stack>
      )}
      {saved && (
        <Text size="sm" c="teal" mt={6} data-testid="what-if-saved">
          {saved}
        </Text>
      )}
    </Paper>
  );
}

// ---- Build my repertoire (FR-12.14) -------------------------------------------------------------------------------------------

const FLAG_TEXT: Record<string, string> = {
  engine_answer: "No book or popular answer: Stockfish's best",
  few_games: "Few games to go on",
  bad_eval: "You're clearly worse here",
};

export function BuildDialog({
  family,
  color,
  signedIn,
  onClose,
  onSaved,
}: {
  family: string;
  color: Color;
  signedIn: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [maxMoves, setMaxMoves] = useState(12);
  const [share, setShare] = useState(5);
  const [replies, setReplies] = useState(3);
  const [positions, setPositions] = useState(60);
  const [jobId, setJobId] = useState<string | null>(null);
  const [proposal, setProposal] = useState<RepertoireProposal | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const job = useJob(jobId);

  useEffect(() => {
    if (job?.state === "done") api.getRepertoireProposal(job.message).then(setProposal, (e: unknown) => setError(message(e)));
  }, [job]);

  const running = jobId !== null && (job === null || job.state === "running");
  const gaps = proposal?.moves.filter((m) => m.flags.length > 0) ?? [];

  return (
    <Modal opened onClose={onClose} title={`Build my repertoire: ${family} as ${color}`} size="lg" data-testid="build-dialog">
      <Stack gap="sm">
        {!proposal && (
          <>
            <Text size="sm">
              {signedIn
                ? "It adds the replies you're likely to meet, from Lichess's opening explorer, with one answer for you at each position."
                : "You're signed out, so replies come from the opening book, which covers fewer of them. Sign in to Lichess for what's actually played."}{" "}
              Nothing is saved until you've looked it over.
            </Text>
            <Group gap="md">
              <NumberInput size="xs" w={120} min={2} max={20} label={<>Moves <OptionInfo id="build.moves" /></>} value={maxMoves} onChange={(v) => typeof v === "number" && setMaxMoves(v)} data-testid="build-moves" />
              <NumberInput size="xs" w={140} min={0} max={50} label={<>Reply share (%) <OptionInfo id="build.share" /></>} value={share} onChange={(v) => typeof v === "number" && setShare(v)} data-testid="build-share" />
              <NumberInput size="xs" w={140} min={1} max={6} label={<>Replies per position <OptionInfo id="build.replies" /></>} value={replies} onChange={(v) => typeof v === "number" && setReplies(v)} data-testid="build-replies" />
              <NumberInput size="xs" w={120} min={5} max={200} label={<>Positions <OptionInfo id="build.positions" /></>} value={positions} onChange={(v) => typeof v === "number" && setPositions(v)} data-testid="build-positions" />
            </Group>
            {running && (
              <Text size="sm" c="dimmed" data-testid="build-running">
                {job?.message ?? "Starting…"}
              </Text>
            )}
            <Group justify="flex-end" gap="xs">
              <Button variant="default" size="xs" onClick={onClose}>
                Close
              </Button>
              <Button
                size="xs"
                disabled={running}
                data-testid="build-start"
                onClick={() => {
                  setError(null);
                  api
                    .startRepertoireBuild(color, family, { max_moves: maxMoves, min_share: share / 100, max_replies: replies, max_positions: positions })
                    .then(setJobId, (e: unknown) => setError(message(e)));
                }}
              >
                Build
              </Button>
            </Group>
          </>
        )}
        {(error ?? (job?.state === "failed" ? job.message : null)) && (
          <Alert color="red" data-testid="build-error">
            {error ?? job?.message}
          </Alert>
        )}
        {proposal && !saved && (
          <>
            <Text size="sm" data-testid="build-summary">
              {proposal.moves.length} moves. {gaps.length} {gaps.length === 1 ? "needs" : "need"} a look.
            </Text>
            <ScrollArea.Autosize mah={420}>
              <Stack gap={2} data-testid="build-moves-list">
                {proposal.moves.map((m) => (
                  <Group key={`${m.position_key}|${m.move_uci}`} gap={6} wrap="nowrap" style={{ paddingLeft: Math.min(m.depth, 24) * 8 }} data-testid="build-move">
                    <Text size="sm" fw={m.yours ? 700 : 400} style={{ minWidth: 48 }}>
                      {m.san}
                    </Text>
                    {m.share !== null && (
                      <Text size="xs" c="dimmed">
                        {Math.round(m.share * 100)}%
                      </Text>
                    )}
                    <Badge size="xs" variant="light" color={m.already_yours ? "teal" : "gray"} style={{ textTransform: "none" }}>
                      {m.already_yours ? "Yours already" : sourceLabel(m.source)}
                    </Badge>
                    {m.flags.map((f) => (
                      <Badge key={f} size="xs" variant="light" color="orange" style={{ textTransform: "none" }} data-testid="build-flag">
                        {FLAG_TEXT[f] ?? f}
                      </Badge>
                    ))}
                  </Group>
                ))}
              </Stack>
            </ScrollArea.Autosize>
            <Group justify="flex-end" gap="xs">
              <Button
                size="xs"
                variant="default"
                data-testid="build-discard"
                onClick={() => {
                  api.discardRepertoireProposal(proposal.id).catch(() => undefined);
                  setProposal(null);
                  setJobId(null);
                }}
              >
                Discard
              </Button>
              <Button
                size="xs"
                data-testid="build-save"
                onClick={() =>
                  api.saveRepertoireProposal(proposal.id).then(
                    (r) => {
                      setSaved(`Added ${r.added} moves. ${r.kept} you already had stayed as they were.`);
                      onSaved();
                    },
                    (e: unknown) => setError(message(e)),
                  )
                }
              >
                Add to my repertoire
              </Button>
            </Group>
          </>
        )}
        {saved && (
          <>
            <Text size="sm" c="teal" data-testid="build-saved">
              {saved}
            </Text>
            <Button size="xs" variant="default" style={{ alignSelf: "flex-end" }} onClick={onClose}>
              Close
            </Button>
          </>
        )}
      </Stack>
    </Modal>
  );
}
