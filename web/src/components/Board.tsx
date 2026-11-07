import "chessground/assets/chessground.base.css";
import "chessground/assets/chessground.brown.css";
import "chessground/assets/chessground.cburnett.css";
import "./board.css";
import { Button, Group, Paper, Text } from "@mantine/core";
import { Chess, type Square } from "chess.js";
import { Chessground } from "chessground";
import type { Api } from "chessground/api";
import type { Key } from "chessground/types";
import { type RefObject, useEffect, useLayoutEffect, useRef, useState } from "react";

export interface BoardProps {
  fen: string;
  orientation: "white" | "black";
  /** Which side may move ("both": the analysis board, FR-7.7), or null when the board is read-only. */
  movable: "white" | "black" | "both" | null;
  lastMove?: [string, string] | null;
  onMove?: (uci: string) => void;
  /** Hint (§7.2): circle the piece that moves next. */
  hintSquare?: string | null;
  /** Show the file and rank letters around the board. */
  coordinates?: boolean;
  /** CSS max width; 560 px unless the filters panel is hidden (FR-1.14). */
  maxWidth?: number | string;
  /** Shrink (to no less than 320 px) so the whole board and its file letters fit under its top edge in the window. */
  fitWindow?: boolean;
  /** Arrows [from, to], e.g. the engine's best move on the analysis board. Callers check legality first. */
  arrows?: [string, string][];
  /** Explain's annotations (v0.7, FR-8.5): arrows and circles, already validated by the backend (FR-8.4). */
  shapes?: BoardShape[];
}

export interface BoardShape {
  orig: string;
  dest: string | null; // null: a circle
  color: "green" | "red" | "blue" | "yellow";
}

const NO_ARROWS: [string, string][] = [];
const NO_SHAPES: BoardShape[] = [];
const RANKS = ["1", "2", "3", "4", "5", "6", "7", "8"];
const FILES = ["a", "b", "c", "d", "e", "f", "g", "h"];

const PROMOTIONS: { piece: string; label: string }[] = [
  { piece: "q", label: "Queen" },
  { piece: "r", label: "Rook" },
  { piece: "b", label: "Bishop" },
  { piece: "n", label: "Knight" },
];

function legalDests(chess: Chess): Map<Key, Key[]> {
  const dests = new Map<Key, Key[]>();
  for (const m of chess.moves({ verbose: true })) {
    const list = dests.get(m.from as Key) ?? [];
    if (!list.includes(m.to as Key)) list.push(m.to as Key);
    dests.set(m.from as Key, list);
  }
  return dests;
}

const MIN_FIT_PX = 320;
const FIT_MARGIN_PX = 12;

/** The width at which a square frame starting where `frame` starts ends inside the window, or null when
 * off. The frame is as tall as it is wide (the rank strip and the file strip are the same size), and what
 * sits above it doesn't depend on its size, so measuring its top can't feed back into itself. */
function useWindowFit(frame: RefObject<HTMLDivElement | null>, on: boolean): number | null {
  const [fit, setFit] = useState<number | null>(null);
  useLayoutEffect(() => {
    if (!on || !frame.current) return;
    const measure = () => {
      if (!frame.current) return;
      const top = frame.current.getBoundingClientRect().top + window.scrollY;
      setFit(Math.max(MIN_FIT_PX, Math.floor(window.innerHeight - top - FIT_MARGIN_PX)));
    };
    measure();
    // Content above the board (the side question, the Analyze panel, a notice) comes and goes.
    const observer = new ResizeObserver(measure);
    observer.observe(document.body);
    window.addEventListener("resize", measure);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [frame, on]);
  return on ? fit : null;
}

// The only chessground wrapper in the app (ARCHITECTURE §3 decision 11). It shows positions and
// reports moves as UCI; whether a move is right is decided by the backend, never here.
export function Board({
  fen,
  orientation,
  movable,
  lastMove,
  onMove,
  hintSquare = null,
  coordinates = true,
  maxWidth = 560,
  fitWindow = false,
  arrows = NO_ARROWS,
  shapes = NO_SHAPES,
}: BoardProps) {
  const frame = useRef<HTMLDivElement>(null);
  const fit = useWindowFit(frame, fitWindow);
  const el = useRef<HTMLDivElement>(null);
  const cg = useRef<Api | null>(null);
  const onMoveRef = useRef(onMove);
  const [promotion, setPromotion] = useState<{ from: string; to: string } | null>(null);

  useEffect(() => {
    onMoveRef.current = onMove;
  }, [onMove]);

  useEffect(() => {
    if (!el.current) return;
    cg.current = Chessground(el.current, {
      coordinates: false, // drawn by us, outside the board (see board.css)
      animation: { enabled: true, duration: 250 },
      highlight: { lastMove: true, check: true },
      premovable: { enabled: false },
      draggable: { showGhost: true },
    });
    // Chessground remembers where the board is and re-measures only on a resize or a scroll. Content
    // above it (a notice, the session bar wrapping, the filters panel in a narrow window) can move the
    // board without either, and clicks then land on the wrong square unless they hit a square's middle.
    // Forget the old position before chessground handles each press (capture phase: before its own).
    const wrapper = el.current;
    const remeasure = () => cg.current?.state.dom.bounds.clear();
    const presses = ["mousedown", "touchstart"] as const;
    presses.forEach((ev) => wrapper.addEventListener(ev, remeasure, { capture: true, passive: true }));
    return () => {
      presses.forEach((ev) => wrapper.removeEventListener(ev, remeasure, { capture: true }));
      cg.current?.destroy();
      cg.current = null;
    };
  }, []);

  useEffect(() => {
    const chess = new Chess(fen);
    const turn = chess.turn() === "w" ? "white" : "black";
    cg.current?.set({
      fen,
      orientation,
      turnColor: turn,
      check: chess.inCheck(),
      lastMove: (lastMove as Key[] | undefined) ?? undefined,
      movable: {
        free: false,
        color: movable ?? undefined,
        dests: movable === turn || movable === "both" ? legalDests(chess) : new Map(),
        showDests: true,
        events: {
          after: (from, to) => {
            const piece = chess.get(from as Square);
            const lastRank = to[1] === "8" || to[1] === "1";
            if (piece?.type === "p" && lastRank) setPromotion({ from, to });
            else onMoveRef.current?.(`${from}${to}`);
          },
        },
      },
      drawable: {
        autoShapes: [
          ...(hintSquare ? [{ orig: hintSquare as Key, brush: "green" }] : []),
          ...arrows.map(([orig, dest]) => ({ orig: orig as Key, dest: dest as Key, brush: "paleBlue" })),
          ...shapes.map((s) => ({ orig: s.orig as Key, dest: (s.dest ?? undefined) as Key | undefined, brush: s.color })),
        ],
      },
    });
  }, [fen, orientation, movable, lastMove, hintSquare, arrows, shapes]);

  // Rank numbers down the left and file letters along the bottom, outside the squares, so no piece
  // or square color can hide them (Adam, 2026-11-07: still missing on Game Review inside the board).
  const white = orientation === "white";
  const ranks = white ? [...RANKS].reverse() : RANKS;
  const files = white ? FILES : [...FILES].reverse();

  return (
    <div
      ref={frame}
      className={coordinates ? "ws-board-frame ws-board-frame-coords" : "ws-board-frame"}
      style={{
        width: "100%",
        maxWidth: fit === null ? maxWidth : `min(${typeof maxWidth === "number" ? `${maxWidth}px` : maxWidth}, ${fit}px)`,
      }}
    >
      {coordinates && (
        <div className="ws-coords ws-coords-ranks" data-testid="board-ranks" aria-hidden="true">
          {ranks.map((r) => (
            <span key={r}>{r}</span>
          ))}
        </div>
      )}
      <div style={{ position: "relative", width: "100%", aspectRatio: "1 / 1" }}>
      <div
        ref={el}
        className="ws-board"
        data-testid="board"
        data-hint={hintSquare ?? ""}
        data-arrows={arrows.map(([a, b]) => a + b).join(" ")}
        data-shapes={shapes.map((s) => `${s.color}:${s.orig}${s.dest ?? ""}`).join(" ")}
        data-fen={fen}
        style={{ width: "100%", height: "100%" }}
      />
      {promotion && (
        <Paper
          shadow="md"
          p="sm"
          withBorder
          style={{ position: "absolute", top: "40%", left: "10%", right: "10%", zIndex: 10 }}
        >
          <Text size="sm" mb="xs">
            Promote to:
          </Text>
          <Group gap="xs">
            {PROMOTIONS.map(({ piece, label }) => (
              <Button
                key={piece}
                size="xs"
                variant="light"
                onClick={() => {
                  setPromotion(null);
                  onMoveRef.current?.(`${promotion.from}${promotion.to}${piece}`);
                }}
              >
                {label}
              </Button>
            ))}
          </Group>
        </Paper>
      )}
      </div>
      {coordinates && (
        <div className="ws-coords ws-coords-files" data-testid="board-files" aria-hidden="true">
          {files.map((f) => (
            <span key={f}>{f}</span>
          ))}
        </div>
      )}
    </div>
  );
}
