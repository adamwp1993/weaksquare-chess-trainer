// v0.15 (REQUIREMENTS §20): the Analysis tab. A board of its own: set up a position (FR-14.2), import a PGN (FR-14.3),
// and explore with the engine and popular replies (FR-14.4). Nothing here is scored or saved, and nothing goes to an
// LLM (FR-14.5). The lines are kept by App while the app is open, so switching tabs doesn't lose them (Adam, v0.15
// planning). Replacing a board that has moves asks first.
import {
  Alert,
  Button,
  Checkbox,
  Grid,
  Group,
  List,
  Modal,
  Paper,
  Radio,
  SegmentedControl,
  Stack,
  Text,
  Textarea,
  TextInput,
  Title,
} from "@mantine/core";
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { AnalysisPgnImport, EngineStatus } from "../api/types";
import { Board, type EditTool } from "../components/Board";
import { EnginePanel } from "../components/EnginePanel";
import { MoveTree } from "../components/MoveTree";
import { Labeled, OptionInfo } from "../components/OptionInfo";
import { PopularReplies } from "../components/PopularReplies";
import {
  type AnalysisLine,
  type AnalysisTree,
  hasMoves,
  lastMoveLabel,
  newTree,
  playMove,
  START_FEN,
  treeFromLine,
} from "../state/analysisTree";
import { legalArrow } from "../state/engine";
import { useShortcuts } from "../state/shortcuts";
import { backToMainLine, mainLineEnd, onMainLine } from "../state/studyTree";

export interface AnalysisBoardState {
  tree: AnalysisTree;
  orientation: "white" | "black";
}

export function analysisBoardFromLine(line: AnalysisLine): AnalysisBoardState {
  return { tree: treeFromLine(line.startFen, line.ucis, line.cursor), orientation: line.orientation };
}

export function newAnalysisBoard(): AnalysisBoardState {
  return { tree: newTree(START_FEN), orientation: "white" };
}

const EMPTY = "8/8/8/8/8/8/8/8";

export function AnalysisView({
  board,
  onBoard,
  pending,
  onPendingDone,
  coordinates,
}: {
  board: AnalysisBoardState;
  onBoard: (b: AnalysisBoardState) => void;
  /** A line sent by Open in Analysis tab while the board had moves: waiting for Replace or Keep my board. */
  pending: AnalysisLine | null;
  onPendingDone: () => void;
  coordinates: boolean;
}) {
  const { tree, orientation } = board;
  const node = tree.moves[tree.cur];
  const fen = node.fen;
  const [engine, setEngine] = useState<EngineStatus | null>(null);
  const [best, setBest] = useState<string | null>(null);
  const [setup, setSetup] = useState<SetupState | null>(null);
  const [pgnOpen, setPgnOpen] = useState(false);
  const [confirm, setConfirm] = useState<{ what: string; apply: () => void } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const loadEngine = useCallback(() => {
    api.getEngineStatus().then(setEngine, () => undefined);
  }, []);
  useEffect(loadEngine, [loadEngine]);
  const analyze = useCallback(
    (f: string, purpose: "start" | "panel" | "board") => api.analyzeBoardPosition(f, purpose),
    [],
  );

  const setTree = useCallback((t: AnalysisTree) => onBoard({ tree: t, orientation }), [onBoard, orientation]);
  const go = (id: number) => setTree({ moves: tree.moves, cur: id });
  const onMove = (uci: string) => {
    const next = playMove(tree, uci);
    if (next) setTree(next);
  };

  /** Replace the board, asking first when it has moves (Adam, v0.15 planning). */
  const replace = useCallback(
    (what: string, apply: () => void) => {
      if (hasMoves(tree)) setConfirm({ what, apply });
      else apply();
    },
    [tree],
  );

  // Open in Analysis tab (FR-14.6) onto a board with moves: App sent it here to be confirmed.
  const asking =
    confirm ??
    (pending
      ? { what: "the position you opened", apply: () => onBoard(analysisBoardFromLine(pending)) }
      : null);
  const closeAsking = () => {
    setConfirm(null);
    if (pending) onPendingDone();
  };

  useShortcuts(
    {
      ArrowLeft: () => node.parent !== null && go(node.parent),
      ArrowRight: () => node.children.length > 0 && go(node.children[0]),
    },
    setup === null,
  );

  const end = mainLineEnd(tree.moves);
  const arrow = setup ? null : legalArrow(fen, best ?? undefined);

  return (
    <Stack gap="md" data-testid="analysis-view">
      <Group justify="space-between">
        <Title order={3}>Analysis board</Title>
        {!setup && (
          <Group gap="xs">
            <Button
              size="xs"
              variant="default"
              onClick={() => replace("a new board", () => onBoard({ tree: newTree(START_FEN), orientation }))}
              data-testid="analysis-new"
            >
              New board
            </Button>
            <Button size="xs" variant="default" onClick={() => setSetup(setupFrom(fen))} data-testid="analysis-setup">
              Set up position
            </Button>
            <Button size="xs" variant="default" onClick={() => setPgnOpen(true)} data-testid="analysis-import-pgn">
              Import PGN
            </Button>
            <Button
              size="xs"
              variant="default"
              onClick={() => onBoard({ tree, orientation: orientation === "white" ? "black" : "white" })}
              data-testid="analysis-flip"
            >
              Flip board
            </Button>
          </Group>
        )}
      </Group>
      <Text size="sm" c="dimmed">
        Move for either side. Nothing here is scored, saved to your stats or sent to an AI.
      </Text>
      {notice && (
        <Alert color="blue" withCloseButton onClose={() => setNotice(null)} data-testid="analysis-notice">
          {notice}
        </Alert>
      )}
      <Grid gap="lg">
        <Grid.Col span={{ base: 12, md: 7 }}>
          <Stack gap="xs" maw={560}>
            {setup ? (
              <Board
                fen={setup.placement}
                orientation={orientation}
                movable={null}
                coordinates={coordinates}
                maxWidth={560}
                editor={{
                  tool: setup.tool,
                  onTool: (tool) => setSetup({ ...setup, tool }),
                  onChange: (placement) => setSetup((s) => (s ? { ...s, placement, problems: [] } : s)),
                }}
              />
            ) : (
              <>
                <Board
                  fen={fen}
                  orientation={orientation}
                  movable="both"
                  onMove={onMove}
                  lastMove={node.uci ? [node.uci.slice(0, 2), node.uci.slice(2, 4)] : null}
                  coordinates={coordinates}
                  arrows={arrow ? [arrow] : undefined}
                  maxWidth={560}
                  fitWindow
                />
                <Group gap={4} justify="center" data-testid="analysis-nav">
                  <Button size="xs" variant="default" onClick={() => go(0)} disabled={tree.cur === 0} aria-label="To the start">
                    |◀
                  </Button>
                  <Button
                    size="xs"
                    variant="default"
                    onClick={() => node.parent !== null && go(node.parent)}
                    disabled={node.parent === null}
                    aria-label="Back"
                    data-testid="analysis-back"
                  >
                    ◀ Back
                  </Button>
                  <Text size="sm" w={110} ta="center" data-testid="analysis-move">
                    {lastMoveLabel(tree.moves, tree.cur)}
                  </Text>
                  <Button
                    size="xs"
                    variant="default"
                    onClick={() => node.children.length && go(node.children[0])}
                    disabled={!node.children.length}
                    aria-label="Forward"
                    data-testid="analysis-forward"
                  >
                    Forward ▶
                  </Button>
                  <Button size="xs" variant="default" onClick={() => go(end)} disabled={tree.cur === end} aria-label="To the end of the main line">
                    ▶|
                  </Button>
                  {!onMainLine(tree.moves, tree.cur) && (
                    <Button size="xs" variant="light" onClick={() => go(backToMainLine(tree.moves, tree.cur))} data-testid="analysis-main-line">
                      Back to main line
                    </Button>
                  )}
                </Group>
              </>
            )}
          </Stack>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 5 }}>
          {setup ? (
            <SetupPanel
              setup={setup}
              onChange={setSetup}
              onCancel={() => setSetup(null)}
              onDone={(checkedFen) => {
                setSetup(null);
                onBoard({ tree: newTree(checkedFen), orientation });
              }}
              hasMoves={hasMoves(tree)}
            />
          ) : (
            <Stack gap="sm">
              <EnginePanel
                analyze={analyze}
                startLabel="Start position:"
                startFen={tree.moves[0].fen}
                fen={fen}
                purpose="board"
                status={engine}
                onStatusChanged={loadEngine}
                onBestMove={setBest}
              />
              <PopularReplies fen={fen} onPlay={onMove} />
              <Paper withBorder p="sm" radius="md">
                <Text fw={700} mb={4}>
                  Your lines
                </Text>
                <MoveTree
                  moves={tree.moves}
                  cur={tree.cur}
                  onSelect={go}
                  testIdPrefix="analysis"
                  emptyText="Make a move on the board. Each different move you try from a position becomes a new line."
                  maxHeight={320}
                />
              </Paper>
            </Stack>
          )}
        </Grid.Col>
      </Grid>

      <PgnModal
        opened={pgnOpen}
        onClose={() => setPgnOpen(false)}
        onOpen={(moves, label, skipped) => {
          setPgnOpen(false);
          replace("the imported game", () => {
            onBoard({ tree: { moves, cur: 0 }, orientation });
            setNotice(skipped ? `Opened ${label}. ${skipped}` : null);
          });
        }}
      />
      <Modal
        opened={asking !== null}
        onClose={closeAsking}
        title="Replace your current board?"
        data-testid="analysis-confirm"
      >
        <Text size="sm">
          Your board has moves on it. Opening {asking?.what} replaces them, and they aren't saved anywhere.
        </Text>
        <Group justify="flex-end" mt="md">
          <Button variant="default" onClick={closeAsking} data-testid="analysis-confirm-keep">
            Keep my board
          </Button>
          <Button
            onClick={() => {
              asking?.apply();
              closeAsking();
            }}
            data-testid="analysis-confirm-replace"
          >
            Replace
          </Button>
        </Group>
      </Modal>
    </Stack>
  );
}

// ---- FR-14.2: set up a position ---------------------------------------------------------------------------------

interface SetupState {
  placement: string;
  turn: "w" | "b";
  castling: { K: boolean; Q: boolean; k: boolean; q: boolean };
  tool: EditTool;
  fenText: string;
  problems: string[];
  busy: boolean;
}

function setupFrom(fen: string): SetupState {
  const [placement, turn, castling] = fen.split(" ");
  const has = (c: string) => (castling ?? "").includes(c);
  return {
    placement,
    turn: turn === "b" ? "b" : "w",
    castling: { K: has("K"), Q: has("Q"), k: has("k"), q: has("q") },
    tool: null,
    fenText: "",
    problems: [],
    busy: false,
  };
}

/** The piece on `square` ("e1") in a FEN's board part, as its letter, or "". */
function pieceAt(placement: string, square: string): string {
  const rank = placement.split("/")[8 - Number(square[1])] ?? "";
  let file = 0;
  for (const ch of rank) {
    if (/\d/.test(ch)) file += Number(ch);
    else {
      if (file === square.charCodeAt(0) - 97) return ch;
      file += 1;
    }
  }
  return "";
}

/** Castling a side can only have with its king and that rook on their starting squares. */
function castlingPossible(placement: string): SetupState["castling"] {
  const at = (sq: string, p: string) => pieceAt(placement, sq) === p;
  return {
    K: at("e1", "K") && at("h1", "R"),
    Q: at("e1", "K") && at("a1", "R"),
    k: at("e8", "k") && at("h8", "r"),
    q: at("e8", "k") && at("a8", "r"),
  };
}

function SetupPanel({
  setup,
  onChange,
  onCancel,
  onDone,
  hasMoves,
}: {
  setup: SetupState;
  onChange: (s: SetupState) => void;
  onCancel: () => void;
  onDone: (fen: string) => void;
  hasMoves: boolean;
}) {
  const possible = castlingPossible(setup.placement);
  const check = (fen: string) => {
    onChange({ ...setup, busy: true, problems: [] });
    api.checkBoardPosition(fen).then(
      (r) => (r.ok && r.fen ? onDone(r.fen) : onChange({ ...setup, busy: false, problems: r.problems })),
      (e: Error) => onChange({ ...setup, busy: false, problems: [e.message] }),
    );
  };
  const done = () => {
    const rights = (["K", "Q", "k", "q"] as const).filter((c) => setup.castling[c] && possible[c]).join("");
    check(`${setup.placement} ${setup.turn} ${rights || "-"} - 0 1`);
  };
  const castle = (c: keyof SetupState["castling"], label: string) => (
    <Checkbox
      label={label}
      checked={setup.castling[c] && possible[c]}
      disabled={!possible[c]}
      onChange={(e) => onChange({ ...setup, castling: { ...setup.castling, [c]: e.currentTarget.checked } })}
      data-testid={`setup-castle-${c}`}
    />
  );
  return (
    <Paper withBorder p="sm" radius="md" data-testid="analysis-setup-panel">
      <Stack gap="sm">
        <Text fw={700}>Set up a position</Text>
        <Text size="sm" c="dimmed">
          Drag pieces from the rows above and below the board, or pick one and click squares. Drag a piece off the board, or
          pick the bin, to remove it.
          {hasMoves && " Done replaces your current board and its lines."}
        </Text>
        <Group gap="xs">
          <Button size="xs" variant="default" onClick={() => onChange({ ...setup, placement: EMPTY, problems: [] })} data-testid="setup-clear">
            Clear board
          </Button>
          <Button
            size="xs"
            variant="default"
            onClick={() => onChange({ ...setupFrom(START_FEN), tool: setup.tool })}
            data-testid="setup-start"
          >
            Start position
          </Button>
        </Group>
        <Stack gap={4} data-option-group>
          <Text size="sm" fw={500}>
            <Labeled id="analysis.sideToMove">Side to move</Labeled>
          </Text>
          <SegmentedControl
            size="xs"
            value={setup.turn}
            onChange={(v) => onChange({ ...setup, turn: v === "b" ? "b" : "w", problems: [] })}
            data={[
              { value: "w", label: "White to move" },
              { value: "b", label: "Black to move" },
            ]}
            data-testid="setup-turn"
          />
        </Stack>
        <Stack gap={4} data-option-group>
          <Text size="sm" fw={500}>
            <Labeled id="analysis.castling">Castling rights</Labeled>
          </Text>
          <Group gap="md">
            {castle("K", "White O-O")}
            {castle("Q", "White O-O-O")}
            {castle("k", "Black O-O")}
            {castle("q", "Black O-O-O")}
          </Group>
        </Stack>
        <Group gap="xs" align="flex-end" wrap="nowrap" data-option-group>
          <TextInput
            style={{ flex: 1 }}
            size="xs"
            label={
              <>
                Or paste a FEN
                <OptionInfo id="analysis.fen" />
              </>
            }
            placeholder="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
            value={setup.fenText}
            onChange={(e) => onChange({ ...setup, fenText: e.currentTarget.value, problems: [] })}
            onKeyDown={(e) => e.key === "Enter" && setup.fenText.trim() && check(setup.fenText)}
            data-testid="setup-fen"
          />
          <Button size="xs" variant="light" disabled={!setup.fenText.trim() || setup.busy} onClick={() => check(setup.fenText)} data-testid="setup-fen-use">
            Use this FEN
          </Button>
        </Group>
        {setup.problems.length > 0 && (
          <Alert color="red" title="This position can't be analyzed" data-testid="setup-problems">
            <List size="sm">
              {setup.problems.map((p) => (
                <List.Item key={p}>{p}</List.Item>
              ))}
            </List>
          </Alert>
        )}
        <Group justify="flex-end" gap="xs">
          <Button size="xs" variant="default" onClick={onCancel} data-testid="setup-cancel">
            Cancel
          </Button>
          <Button size="xs" onClick={done} loading={setup.busy} data-testid="setup-done">
            Done
          </Button>
        </Group>
      </Stack>
    </Paper>
  );
}

// ---- FR-14.3: import a PGN --------------------------------------------------------------------------------------

function PgnModal({
  opened,
  onClose,
  onOpen,
}: {
  opened: boolean;
  onClose: () => void;
  onOpen: (moves: AnalysisTree["moves"], label: string, skipped: string | null) => void;
}) {
  const [text, setText] = useState("");
  const [listed, setListed] = useState<AnalysisPgnImport | null>(null);
  const [pick, setPick] = useState<string>("0");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reset = () => {
    setListed(null);
    setError(null);
    setBusy(false);
  };
  const close = () => {
    reset();
    setText("");
    onClose();
  };
  const open = (index: number, found: AnalysisPgnImport) => {
    setBusy(true);
    api.getAnalysisPgnGame(text, index).then(
      (g) => {
        const skipped = found.skipped.length ? `${found.skipped.length} game(s) in the PGN couldn't be used.` : null;
        reset();
        setText("");
        onOpen(g.moves, g.label, found.games.length === 1 ? skipped : null);
      },
      (e: Error) => {
        setBusy(false);
        setError(e.message);
      },
    );
  };
  const read = () => {
    setBusy(true);
    setError(null);
    api.importAnalysisPgn(text).then(
      (r) => {
        if (r.games.length === 1) open(r.games[0].index, r);
        else {
          setBusy(false);
          setListed(r);
          setPick(String(r.games[0].index));
        }
      },
      (e: Error) => {
        setBusy(false);
        setError(e.message); // the board is unchanged (FR-14.3)
      },
    );
  };

  return (
    <Modal opened={opened} onClose={close} title="Import a PGN" size="lg" data-testid="analysis-pgn-modal">
      <Stack gap="sm">
        {listed ? (
          <>
            <Text size="sm">This PGN has {listed.games.length} games. Pick one to open.</Text>
            <Radio.Group value={pick} onChange={setPick} data-no-tip="a row you select">
              <Stack gap={4} mah={300} style={{ overflowY: "auto" }} data-testid="analysis-pgn-games">
                {listed.games.map((g) => (
                  <Radio key={g.index} value={String(g.index)} label={`${g.label} · ${g.move_count} moves`} />
                ))}
              </Stack>
            </Radio.Group>
            {listed.skipped.length > 0 && (
              <Alert color="yellow" title="Some games couldn't be used">
                <List size="sm">
                  {listed.skipped.map((s) => (
                    <List.Item key={s}>{s}</List.Item>
                  ))}
                </List>
              </Alert>
            )}
          </>
        ) : (
          <Textarea
            label="Paste a PGN"
            description="Its side lines and comments come with it. Headers and clocks are left out. The game isn't added to My games."
            data-no-tip="free text you type"
            autosize
            minRows={6}
            maxRows={14}
            value={text}
            onChange={(e) => {
              setText(e.currentTarget.value);
              setError(null);
            }}
            data-testid="analysis-pgn-text"
          />
        )}
        {error && (
          <Alert color="red" data-testid="analysis-pgn-error">
            {error}
          </Alert>
        )}
        <Group justify="flex-end" gap="xs">
          {listed && (
            <Button variant="default" onClick={reset}>
              Back
            </Button>
          )}
          <Button variant="default" onClick={close}>
            Cancel
          </Button>
          {listed ? (
            <Button loading={busy} onClick={() => open(Number(pick), listed)} data-testid="analysis-pgn-open">
              Open
            </Button>
          ) : (
            <Button loading={busy} disabled={!text.trim()} onClick={read} data-testid="analysis-pgn-read">
              Import
            </Button>
          )}
        </Group>
      </Stack>
    </Modal>
  );
}
