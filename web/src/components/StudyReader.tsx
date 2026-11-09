// v0.14 (FR-13.8, 13.10): working through one study chapter. Normal chapters step forward and back through the move
// tree, side lines included; gamebook chapters are played along, the app making the other side's moves. The chapter's
// text, arrows and highlights appear as you go. Nothing is scored. Comments are plain text: React escapes them, and they
// are never turned into links, even when they hold a web address (FR-13.7).
import {
  ActionIcon,
  Badge,
  Button,
  Grid,
  Group,
  Paper,
  Stack,
  Text,
  Tooltip,
} from "@mantine/core";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { StudyChapter, StudyMove } from "../api/types";
import {
  backToMainLine,
  checkGamebookMove,
  follow,
  mainLineEnd,
  onMainLine,
  pathTo,
  sideToMove,
} from "../state/studyTree";
import { Board } from "./Board";
import { MoveTree } from "./MoveTree";

const OPPONENT_REPLY_MS = 650;
const SAVE_PLACE_MS = 400;

export interface StudyReaderProps {
  chapter: StudyChapter;
  startPath: string[];
  coordinates: boolean;
  onPlace: (path: string[]) => void;
  /** The end of the main line was reached: the chapter counts as finished. */
  onFinished: () => void;
  onNextChapter: (() => void) | null;
}

export function StudyReader({
  chapter,
  startPath,
  coordinates,
  onPlace,
  onFinished,
  onNextChapter,
}: StudyReaderProps) {
  const moves = chapter.moves;
  const info = chapter.info;
  const gamebook = info.mode === "gamebook";
  const player = info.orientation;
  const [cur, setCur] = useState(() => follow(moves, startPath));
  const [feedback, setFeedback] = useState<{
    text: string;
    tone: "nudge" | "covered" | "info";
  } | null>(null);
  const [tries, setTries] = useState(0);
  const [hint, setHint] = useState(false);
  const node = moves[cur];
  const end = useMemo(() => mainLineEnd(moves), [moves]);
  const atEnd = node.children.length === 0;
  const yourTurn = gamebook && !atEnd && sideToMove(node.fen) === player;

  const go = useCallback((id: number) => {
    setCur(id);
    setFeedback(null);
    setTries(0);
    setHint(false);
  }, []);

  // Your place is saved as you go (FR-13.10), a moment after you stop moving.
  const onPlaceRef = useRef(onPlace);
  useEffect(() => {
    onPlaceRef.current = onPlace;
  }, [onPlace]);
  useEffect(() => {
    const t = window.setTimeout(
      () => onPlaceRef.current(pathTo(moves, cur)),
      SAVE_PLACE_MS,
    );
    return () => window.clearTimeout(t);
  }, [moves, cur]);

  // Reaching the end of the main line finishes the chapter. A chapter with no moves (an introduction, or a text
  // chapter) is at its end as soon as it opens, so opening it finishes it (QA v0.14-B4).
  const finishedRef = useRef(false);
  useEffect(() => {
    if (cur === end && !finishedRef.current) {
      finishedRef.current = true;
      onFinished();
    }
  }, [cur, end, onFinished]);

  // Gamebook: the app makes the other side's moves along the main line.
  useEffect(() => {
    if (
      !gamebook ||
      atEnd ||
      sideToMove(node.fen) === player ||
      !onMainLine(moves, cur)
    )
      return;
    const t = window.setTimeout(
      () => setCur(node.children[0]),
      OPPONENT_REPLY_MS,
    );
    return () => window.clearTimeout(t);
  }, [gamebook, atEnd, node, player, moves, cur]);

  const onMove = useCallback(
    (uci: string) => {
      if (gamebook) {
        const r = checkGamebookMove(moves, cur, uci);
        if (r.kind === "correct") go(r.next);
        else {
          setTries((n) => n + 1);
          setFeedback(
            r.kind === "covered"
              ? { text: r.feedback, tone: "covered" }
              : { text: "Not this one. Try again.", tone: "nudge" },
          );
        }
        return;
      }
      const next = node.children.find((c) => moves[c].uci === uci);
      if (next !== undefined) go(next);
      else
        setFeedback({ text: "That move isn't in this chapter.", tone: "info" });
    },
    [gamebook, moves, cur, node, go],
  );

  // Normal chapters: arrow keys move through the tree.
  useEffect(() => {
    if (gamebook) return;
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === "INPUT" || target.tagName === "TEXTAREA")
      )
        return;
      if (e.key === "ArrowRight" && node.children.length) go(node.children[0]);
      else if (e.key === "ArrowLeft" && node.parent !== null) go(node.parent);
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [gamebook, node, go]);

  const lastMove = node.uci
    ? ([node.uci.slice(0, 2), node.uci.slice(2, 4)] as [string, string])
    : null;
  const hintSquare =
    yourTurn && hint
      ? (moves[node.children[0]].uci?.slice(0, 2) ?? null)
      : null;
  const movable = info.text_only
    ? null
    : gamebook
      ? yourTurn
        ? player
        : null
      : "both";

  return (
    // A grid column gives the board a real width; a column sized to its content shrank it to the button row under it
    // (QA v0.14-B6).
    <Grid data-testid="study-reader">
      <Grid.Col span={{ base: 12, md: 7 }}>
        <Stack gap="xs" maw={560}>
          <Board
            fen={node.fen}
            orientation={info.orientation}
            movable={movable}
            lastMove={lastMove}
            onMove={onMove}
            coordinates={coordinates}
            shapes={node.shapes}
            hintSquare={hintSquare}
            fitWindow
            maxWidth={560}
          />
          {!info.text_only && (
            <Group gap={4} justify="center" data-testid="study-nav">
              <Button
                size="xs"
                variant="default"
                onClick={() => go(0)}
                disabled={cur === 0}
                aria-label="To the start"
                data-testid="study-first"
              >
                |◀
              </Button>
              <Button
                size="xs"
                variant="default"
                onClick={() =>
                  node.parent !== null &&
                  go(
                    gamebook
                      ? lastPlayerStart(moves, cur, player)
                      : node.parent,
                  )
                }
                disabled={node.parent === null}
                aria-label="Back"
                data-testid="study-back"
              >
                ◀ Back
              </Button>
              {!gamebook && (
                <>
                  <Button
                    size="xs"
                    variant="default"
                    onClick={() => node.children.length && go(node.children[0])}
                    disabled={atEnd}
                    aria-label="Forward"
                    data-testid="study-forward"
                  >
                    Forward ▶
                  </Button>
                  <Button
                    size="xs"
                    variant="default"
                    onClick={() => go(end)}
                    disabled={cur === end}
                    aria-label="To the end of the main line"
                    data-testid="study-last"
                  >
                    ▶|
                  </Button>
                  {!onMainLine(moves, cur) && (
                    <Button
                      size="xs"
                      variant="light"
                      onClick={() => go(backToMainLine(moves, cur))}
                      data-testid="study-main-line"
                    >
                      Back to main line
                    </Button>
                  )}
                </>
              )}
            </Group>
          )}
        </Stack>
      </Grid.Col>
      <Grid.Col span={{ base: 12, md: 5 }}>
        <Stack gap="sm">
          <Group gap="xs">
            <Badge variant="light">
              {info.text_only
                ? "Text"
                : gamebook
                  ? "Play along"
                  : "Step through"}
            </Badge>
            {!info.text_only && (
              <Badge variant="outline">
                You play {gamebook ? player : "both sides"}
              </Badge>
            )}
          </Group>
          {gamebook || info.text_only ? (
            <GamebookPanel
              moves={moves}
              cur={cur}
              player={player}
              yourTurn={yourTurn}
              atEnd={atEnd}
              feedback={feedback}
              tries={tries}
              onHint={() => setHint(true)}
              onShow={() => go(node.children[0])}
              textOnly={info.text_only}
            />
          ) : (
            <>
              {feedback && (
                <Text size="sm" c="orange" data-testid="study-feedback">
                  {feedback.text}
                </Text>
              )}
              <MoveTree moves={moves} cur={cur} onSelect={go} />
            </>
          )}
          {atEnd && !info.text_only && (
            <Paper withBorder p="sm" data-testid="study-end">
              <Text size="sm" fw={500}>
                {cur === end ? "End of the chapter." : "End of this side line."}
              </Text>
              <Group gap="xs" mt="xs">
                {cur !== end && (
                  <Button
                    size="xs"
                    variant="light"
                    onClick={() => go(backToMainLine(moves, cur))}
                  >
                    Back to main line
                  </Button>
                )}
                {onNextChapter && (
                  <Button
                    size="xs"
                    onClick={onNextChapter}
                    data-testid="study-next-chapter"
                  >
                    Next chapter
                  </Button>
                )}
              </Group>
            </Paper>
          )}
          {info.text_only && onNextChapter && (
            <Group>
              <Button
                size="xs"
                onClick={onNextChapter}
                data-testid="study-next-chapter"
              >
                Next chapter
              </Button>
            </Group>
          )}
        </Stack>
      </Grid.Col>
    </Grid>
  );
}

/** Gamebook Back: to your previous turn, so you can try a move again. */
function lastPlayerStart(
  moves: StudyMove[],
  cur: number,
  player: "white" | "black",
): number {
  let id = moves[cur].parent ?? 0;
  while (id !== 0 && sideToMove(moves[id].fen) !== player)
    id = moves[id].parent ?? 0;
  return id;
}

function GamebookPanel({
  moves,
  cur,
  player,
  yourTurn,
  atEnd,
  feedback,
  tries,
  onHint,
  onShow,
  textOnly,
}: {
  moves: StudyMove[];
  cur: number;
  player: "white" | "black";
  yourTurn: boolean;
  atEnd: boolean;
  feedback: { text: string; tone: "nudge" | "covered" | "info" } | null;
  tries: number;
  onHint: () => void;
  onShow: () => void;
  textOnly: boolean;
}) {
  const node = moves[cur];
  // The text for this point: the comment on the move just made and, when the app has just answered your move, the
  // comment on your move too (it would otherwise vanish as the reply lands).
  const parent = node.parent !== null ? moves[node.parent] : null;
  const replied =
    parent !== null &&
    parent.parent !== null &&
    sideToMove(node.fen) === player;
  const texts = [replied && parent ? parent.comment : "", node.comment].filter(
    Boolean,
  );
  return (
    <Stack gap="xs">
      {texts.map((t, i) => (
        <Paper key={i} withBorder p="sm" data-testid="study-comment">
          <Text
            size="sm"
            style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}
          >
            {t}
          </Text>
        </Paper>
      ))}
      {!textOnly && (
        <Text size="sm" fw={500} data-testid="study-turn">
          {yourTurn ? "Your move." : atEnd ? "" : "Waiting for the other side…"}
        </Text>
      )}
      {feedback && (
        <Paper
          withBorder
          p="sm"
          bg={
            feedback.tone === "covered"
              ? "var(--mantine-color-orange-light)"
              : undefined
          }
          data-testid="study-feedback"
        >
          <Text
            size="sm"
            style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}
          >
            {feedback.text}
          </Text>
        </Paper>
      )}
      {yourTurn && tries >= 2 && (
        <Group gap="xs">
          <Button
            size="xs"
            variant="light"
            onClick={onHint}
            data-testid="study-hint"
          >
            Hint
          </Button>
          <Button
            size="xs"
            variant="subtle"
            onClick={onShow}
            data-testid="study-show"
          >
            Show the move
          </Button>
        </Group>
      )}
    </Stack>
  );
}

export function HeartButton({
  hearted,
  onChange,
}: {
  hearted: boolean;
  onChange: (h: boolean) => void;
}) {
  return (
    <Tooltip
      label={
        hearted
          ? "Remove from favorites"
          : "Add to favorites (only in WeakSquare)"
      }
    >
      <ActionIcon
        variant="subtle"
        color="red"
        onClick={() => onChange(!hearted)}
        aria-label={hearted ? "Unheart" : "Heart"}
        aria-pressed={hearted}
        data-testid="study-heart"
      >
        {hearted ? "♥" : "♡"}
      </ActionIcon>
    </Tooltip>
  );
}
