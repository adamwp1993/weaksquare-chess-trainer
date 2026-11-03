import { Alert, Anchor, Badge, Button, Group, Paper, Stack, Text, Title } from "@mantine/core";
import { Chess } from "chess.js";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { ApiCallError, type ReasonKey } from "../api/ApiClient";
import type { AttemptRating, CommitFeedback, Outcome, PuzzleView, ReasonPrompt, SessionStats } from "../api/types";
import { AnalysisControls, analysisMove, openAnalysis, type AnalysisState } from "../components/AnalysisBoard";
import { AnswerPlayer, answerPositions, type AnswerPosition, type AnswerSegment } from "../components/AnswerPlayer";
import { Board } from "../components/Board";
import { CommitControls, CommitResult, entryBoard, entrySound } from "../components/CommitLine";
import { DangerCall, DangerVerdict, sanLine } from "../components/DangerCall";
import { IdeaResult, IdeaTags } from "../components/IdeaTags";
import { MAX_NOTE, ReasonChips } from "../components/ReasonChips";
import { EngineInstallBanner } from "../components/EngineInstallBanner";
import { AnalyzeButton, EnginePanel } from "../components/EnginePanel";
import { RatingChange } from "../components/LichessStatus";
import { SessionBar } from "../components/SessionBar";
import { sounds } from "../sound/player";
import { legalArrow, pvToSan, useEngineStatus } from "../state/engine";
import { useShortcuts } from "../state/shortcuts";

const OPPONENT_DELAY_MS = 500;
const REPLY_DELAY_MS = 300;
const WIDE_BOARD = "min(760px, calc(100vh - 240px))"; // FR-1.14: filters hidden, the board fills the height
const RATING_POLL_MS = 2000; // while a solve shows "Syncing…" (pushed sync events normally win)

type Message = { color: "green" | "red" | "gray"; text: string } | null;

function other(color: "white" | "black"): "white" | "black" {
  return color === "white" ? "black" : "white";
}

function turnMessage(view: PuzzleView, again: boolean): string {
  if (view.mode === "danger_spotting") {
    return again
      ? "Again: is the highlighted move safe? Not scored."
      : `${view.player_color === "white" ? "White" : "Black"} is about to play the highlighted move. Is it safe?`;
  }
  if (view.mode === "name_idea" && !again) return "Name the idea first: pick the setup and payoff, then press Start solving.";
  if (view.mode === "commit_line") {
    return again
      ? "Enter the whole line again: your moves and the replies you expect. Not scored."
      : "Enter the whole line: your moves and the replies you expect. Nothing is checked until you press Submit.";
  }
  return again
    ? `Your turn again: find the best move for ${view.player_color}. Not scored.`
    : `Your turn: find the best move for ${view.player_color}.`;
}

function uciMove(uci: string) {
  return { from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci.length > 4 ? uci[4] : undefined };
}

// Standard mode (FR-4.1): the opponent's first move plays, you answer, replies play automatically.
// Themes stay hidden until the attempt is decided (FR-3.14). A wrong move is a loss (FR-5.3); you
// can keep going to finish the line, or move on. When stuck (§7.2): Hint circles the piece that
// moves next, then Show answer steps through the rest of the line. Before the end, either one is a
// loss (FR-5.2); after it, Show answer is free (FR-5.4) and replays the whole line.
// Stockfish (v0.4): after a wrong move, Show answer starts with the engine's refutation of it (§7.2).
// Once the puzzle is over, the engine panel and the analysis board appear (FR-7.2, 7.7); never before (FR-7.3).
// Commit the line (v0.5, FR-4.2): you move both sides with nothing checked, then Submit grades the line.
// Name the idea first (v0.6, FR-4.3): the board takes moves once you've tagged the idea.
// Danger spotting (v0.6, FR-4.4): no opponent move; call the highlighted move Safe or Unsafe, and after a
// correct Unsafe the board turns to the punishing side for one move.
// Mistake reasons (v0.6, §7.3): after a lost puzzle, once it's over, the reason chips (keys 1–6).
export function TrainerView({
  sessionId,
  onNewSession,
  onHistoryChange,
  coordinates = true,
  wide = false,
}: {
  /** FR-1.14: the filters panel is hidden, so the board may grow (within the window's height). */
  wide?: boolean;
  sessionId: number;
  onNewSession: () => void;
  coordinates?: boolean;
  /** An attempt may have been recorded: the mixer's history filters need a fresh count. */
  onHistoryChange?: () => void;
}) {
  const [view, setView] = useState<PuzzleView | null>(null);
  const [complete, setComplete] = useState(false);
  const [fen, setFen] = useState<string | null>(null);
  const [lastMove, setLastMove] = useState<[string, string] | null>(null);
  const [movable, setMovable] = useState<"white" | "black" | "both" | null>(null);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [lineDone, setLineDone] = useState(false);
  // FR-5.12 Try again: a practice run of the finished puzzle. Nothing is recorded; the result shown
  // stays the first attempt's. `practiceMiss` is whether this run had a wrong move or used help.
  const [practice, setPractice] = useState(false);
  const practiceMiss = useRef(false);
  const [message, setMessage] = useState<Message>(null);
  const [stats, setStats] = useState<SessionStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hintSquare, setHintSquare] = useState<string | null>(null);
  const [hinted, setHinted] = useState(false);
  const [answer, setAnswer] = useState<{ positions: AnswerPosition[]; step: number; segments: AnswerSegment[] } | null>(null);
  const [refutation, setRefutation] = useState<"loading" | "missing" | { error: string } | null>(null);
  const [analysis, setAnalysis] = useState<AnalysisState | null>(null);
  const [whyWrong, setWhyWrong] = useState<{ label: string; positions: AnswerPosition[] } | null>(null);
  // "Show me" (FR-7.7): an engine line stepped through on the board, over the position it came from.
  const [preview, setPreview] = useState<{ from: string; label: string; positions: AnswerPosition[]; step: number } | null>(null);
  const [bestMove, setBestMove] = useState<string | null>(null);
  const [engine, refreshEngine] = useEngineStatus();
  const [helpBusy, setHelpBusy] = useState(false);
  const [rating, setRating] = useState<AttemptRating | null>(null);
  // Commit the line: the moves you've entered (UCI, both sides), and the graded line after Submit.
  const [entry, setEntry] = useState<string[]>([]);
  const [commitResult, setCommitResult] = useState<CommitFeedback | null>(null);
  const [submitting, setSubmitting] = useState(false);
  // Name the idea: the board waits for your tags.
  const [needTags, setNeedTags] = useState(false);
  const [tagging, setTagging] = useState(false);
  // Danger spotting: the call, then (after a correct Unsafe) one punishing move from the other side.
  const [dangerPhase, setDangerPhase] = useState<"call" | "refute" | "done" | null>(null);
  const [calling, setCalling] = useState(false);
  // Mistake reasons (§7.3): the prompt for this puzzle's loss, what you picked, or Skip.
  const [reasonPrompt, setReasonPrompt] = useState<ReasonPrompt | null>(null);
  const [reasonChosen, setReasonChosen] = useState<ReasonKey | null>(null);
  const [reasonSkipped, setReasonSkipped] = useState(false);
  const [reasonBusy, setReasonBusy] = useState(false);
  const [reasonNote, setReasonNote] = useState("");
  const lastMode = useRef<PuzzleView["mode"] | null>(null);
  const chess = useRef<Chess | null>(null);
  const timers = useRef<number[]>([]);
  // One next_puzzle call at a time: a quick second click on Next/Skip would otherwise record a
  // failure for a puzzle you never saw (v0.1-B1).
  const loading = useRef(false);
  const puzzleSeq = useRef(0); // bumps on every load, so late replies for an old puzzle are ignored (v0.4-B3)
  const [busy, setBusy] = useState(false);

  const later = (fn: () => void, ms: number) => {
    timers.current.push(window.setTimeout(fn, ms));
  };

  const refreshStats = useCallback(() => {
    api.getSessionStats(sessionId).then(setStats, () => undefined);
    onHistoryChange?.();
  }, [sessionId, onHistoryChange]);

  const decide = useCallback(
    (o: Outcome) => {
      setOutcome(o);
      setRating(o.lichess);
      refreshStats();
    },
    [refreshStats],
  );

  // FR-6.11b: the change fills in when Lichess replies (pushed), or offline once the queue drains.
  const attemptId = outcome?.attempt_id ?? null;
  useEffect(() => {
    if (attemptId === null) return;
    const unsubscribe = api.onEvent((event) => {
      if (event.name !== "sync") return;
      const mine = event.payload.attempts.find((a) => a.attempt_id === attemptId);
      if (mine) {
        setRating(mine);
        api.getSessionStats(sessionId).then(setStats, () => undefined);
      }
    });
    return unsubscribe;
  }, [attemptId, sessionId]);
  const waitingForLichess = rating?.status === "syncing" || rating?.status === "offline";
  useEffect(() => {
    if (attemptId === null || !waitingForLichess) return;
    const timer = setInterval(() => {
      api.getAttemptRatings([attemptId]).then((r) => {
        if (r[0]) setRating(r[0]);
        if (r[0]?.status === "done") api.getSessionStats(sessionId).then(setStats, () => undefined);
      }, () => undefined);
    }, RATING_POLL_MS);
    return () => clearInterval(timer);
  }, [attemptId, waitingForLichess, sessionId]);

  const load = useCallback(async () => {
    if (loading.current) return;
    loading.current = true;
    puzzleSeq.current += 1;
    setBusy(true);
    timers.current.forEach(clearTimeout);
    timers.current = [];
    setOutcome(null);
    setRating(null);
    setLineDone(false);
    setPractice(false);
    setMessage(null);
    setMovable(null);
    setHintSquare(null);
    setHinted(false);
    setAnswer(null);
    setRefutation(null);
    setWhyWrong(null);
    setAnalysis(null);
    setPreview(null);
    setBestMove(null);
    setEntry([]);
    setCommitResult(null);
    setNeedTags(false);
    setDangerPhase(null);
    setReasonPrompt(null);
    setReasonChosen(null);
    setReasonSkipped(false);
    setReasonNote("");
    // Danger spotting: Stockfish looks at every position before it appears (the same wait whatever the
    // answer, v0.6-B1), so say so instead of leaving the last puzzle's result on screen.
    if (lastMode.current === "danger_spotting") setMessage({ color: "gray", text: "Preparing the position…" });
    const asked = performance.now();
    try {
      const next = await api.nextPuzzle(sessionId);
      if (next?.mode === "danger_spotting") {
        // Stockfish answers a forced position early, and those never have a safe move: so every Danger puzzle
        // appears no sooner than a full search would take, or a quick load would mean "Unsafe" (v0.6-B9).
        // Read every time: you may have changed the think time since the last puzzle (v0.6-B10).
        const thinkMs = await api.getEngineSettings().then((e) => e.think_s * 1000, () => 0);
        const wait = thinkMs - (performance.now() - asked);
        if (wait > 0) await new Promise((resolve) => setTimeout(resolve, wait));
      }
      refreshStats();
      setView(next);
      lastMode.current = next?.mode ?? lastMode.current;
      if (!next) {
        setComplete(true);
        return;
      }
      const c = new Chess(next.fen);
      setFen(next.fen);
      setLastMove(null);
      if (next.mode === "danger_spotting") {
        // The raw position: nothing to animate; the candidate is the arrow.
        chess.current = c;
        setDangerPhase("call");
        setMessage({ color: "gray", text: turnMessage(next, false) });
        return;
      }
      if (next.mode === "name_idea") setNeedTags(true);
      later(() => {
        const opp = next.opponent_move;
        c.move(uciMove(opp));
        chess.current = c;
        setFen(c.fen());
        setLastMove([opp.slice(0, 2), opp.slice(2, 4)]);
        setMovable(next.mode === "commit_line" ? "both" : next.mode === "name_idea" ? null : next.player_color);
        sounds.play(next.opponent_sound); // before you've clicked anything (FR-1.13)
        setMessage({ color: "gray", text: turnMessage(next, false) });
      }, OPPONENT_DELAY_MS);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      loading.current = false;
      setBusy(false);
    }
  }, [sessionId, refreshStats]);

  useEffect(() => {
    // Load the session's first puzzle once, when the trainer opens.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
    const pending = timers.current;
    return () => pending.forEach(clearTimeout);
  }, [load]);

  // Commit the line: enter a move for either side; nothing is checked until Submit (FR-4.2).
  const onCommitMove = (uci: string) => {
    if (!view || !chess.current) return;
    const start = chess.current.fen();
    const board = entryBoard(start, entry);
    if (view.max_plies !== null && entry.length >= view.max_plies) {
      setFen(board.fen());
      return;
    }
    try {
      const move = board.move(uciMove(uci));
      sounds.play(entrySound(move));
    } catch {
      setFen(entryBoard(start, entry).fen()); // illegal: snap back
      return;
    }
    setEntry([...entry, uci]);
    setFen(board.fen());
    setLastMove([uci.slice(0, 2), uci.slice(2, 4)]);
  };

  const undoEntry = (all: boolean) => {
    if (!chess.current) return;
    const rest = all ? [] : entry.slice(0, -1);
    setEntry(rest);
    setFen(entryBoard(chess.current.fen(), rest).fen());
    const last = rest[rest.length - 1];
    setLastMove(last ? [last.slice(0, 2), last.slice(2, 4)] : view ? [view.opponent_move.slice(0, 2), view.opponent_move.slice(2, 4)] : null);
  };

  const submitLine = async () => {
    if (!view || entry.length === 0 || submitting) return;
    setSubmitting(true);
    try {
      const r = await api.submitLine(sessionId, entry);
      setCommitResult(r);
      setMovable(null);
      setLineDone(true);
      setHintSquare(null);
      if (r.outcome) {
        decide(r.outcome);
        sounds.later(r.outcome.win ? "solved" : "failed");
      }
      if (practice) {
        const right = r.grades.filter((g) => g.player).every((g) => g.correct);
        setMessage(right ? { color: "green", text: "Right line! (practice, not scored)" } : { color: "gray", text: "Not quite (practice, not scored)." });
      } else if (r.outcome) {
        setMessage(r.outcome.win ? { color: "green", text: "Solved: your line is right!" } : { color: "red", text: "Not quite: see your line below." });
      } else {
        setMessage({ color: "gray", text: "Here's how your line compares (this puzzle already counted as failed)." });
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  // Name the idea (FR-4.3): send the tags, then the board takes moves.
  const startSolving = async (setup: string[], payoff: string[]) => {
    if (!view || tagging) return;
    setTagging(true);
    try {
      await api.setIdeaTags(sessionId, setup, payoff);
      setNeedTags(false);
      setMovable(view.player_color);
      setMessage({ color: "gray", text: `Your turn: find the best move for ${view.player_color}.` });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setTagging(false);
    }
  };

  // Danger spotting (FR-4.4): your call. A correct Unsafe plays the blunder and turns the board.
  const callDanger = async (call: "safe" | "unsafe") => {
    if (!view || calling || dangerPhase !== "call") return;
    setCalling(true);
    try {
      const fb = await api.callDanger(sessionId, call);
      if (fb.outcome) {
        decide(fb.outcome);
        sounds.later(fb.outcome.win ? "solved" : "failed");
      }
      if (fb.refute && view.candidate) {
        const c = new Chess(fb.fen);
        chess.current = c;
        setFen(fb.fen);
        setLastMove([view.candidate.slice(0, 2), view.candidate.slice(2, 4)]);
        sounds.play(fb.blunder_sound);
        setDangerPhase("refute");
        setMovable(other(view.player_color));
        setMessage({ color: "green", text: `Right, it's unsafe. Now punish it: find the best move for ${other(view.player_color)}.` });
        return;
      }
      setDangerPhase("done");
      setLineDone(true);
      if (practice) {
        setMessage(fb.correct ? { color: "green", text: "Right call! (practice, not scored)" } : { color: "gray", text: "Not this time (practice, not scored)." });
      } else {
        setMessage(fb.correct ? { color: "green", text: "Right call!" } : { color: "red", text: "Wrong call: see why below." });
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setCalling(false);
    }
  };

  const onDangerMove = async (uci: string) => {
    const before = chess.current;
    if (!before || !view) return;
    const after = new Chess(before.fen());
    try {
      after.move(uciMove(uci));
    } catch {
      setFen(before.fen());
      return;
    }
    setFen(after.fen());
    setLastMove([uci.slice(0, 2), uci.slice(2, 4)]);
    setMovable(null);
    try {
      const fb = await api.submitMove(sessionId, uci);
      if (fb.kind === "illegal") {
        setFen(before.fen());
        setMovable(other(view.player_color));
        return;
      }
      sounds.play(fb.move_sound);
      if (fb.outcome) {
        decide(fb.outcome);
        sounds.later(fb.outcome.win ? "solved" : "failed");
      }
      setHintSquare(null);
      setDangerPhase("done");
      setLineDone(true);
      if (fb.kind === "solved") {
        chess.current = after;
        setMessage({ color: "green", text: practice ? "That's the punishment! (practice, not scored)" : "That's the punishment!" });
      } else {
        setFen(before.fen());
        setLastMove(null);
        setMessage({ color: practice ? "gray" : "red", text: practice ? "Not the move (practice, not scored)." : "Not the punishing move: see the answer." });
      }
    } catch (e) {
      setFen(before.fen());
      setMovable(other(view.player_color));
      setError((e as Error).message);
    }
  };

  const onMove = async (uci: string) => {
    if (view?.mode === "commit_line") return onCommitMove(uci);
    if (view?.mode === "danger_spotting") return onDangerMove(uci);
    const before = chess.current;
    if (!before || !view) return;
    const after = new Chess(before.fen());
    try {
      after.move(uciMove(uci));
    } catch {
      setFen(before.fen());
      return;
    }
    setFen(after.fen());
    setLastMove([uci.slice(0, 2), uci.slice(2, 4)]);
    setMovable(null);
    try {
      const fb = await api.submitMove(sessionId, uci);
      sounds.play(fb.move_sound);
      if (fb.outcome) {
        decide(fb.outcome);
        sounds.later(fb.outcome.win ? "solved" : "failed");
      }
      if (fb.kind !== "wrong" && fb.kind !== "illegal") setHintSquare(null);
      if (fb.kind === "correct" && fb.reply) {
        chess.current = after;
        setMessage({ color: "green", text: "Correct. Keep going." });
        const reply = fb.reply;
        later(() => {
          after.move(uciMove(reply));
          setFen(after.fen());
          setLastMove([reply.slice(0, 2), reply.slice(2, 4)]);
          setMovable(view.player_color);
          sounds.play(fb.reply_sound);
        }, REPLY_DELAY_MS);
      } else if (fb.kind === "solved") {
        chess.current = after;
        setLineDone(true);
        if (practice) {
          setMessage(
            practiceMiss.current
              ? { color: "gray", text: "That's the full line (practice, not scored)." }
              : { color: "green", text: "Solved! (practice, not scored)" },
          );
          if (!practiceMiss.current) sounds.later("solved");
        } else {
          const won = fb.outcome?.win ?? outcome?.win ?? false;
          setMessage(won ? { color: "green", text: "Solved!" } : { color: "gray", text: "That's the full line." });
        }
      } else {
        // Wrong (or illegal): take the move back. The attempt is already decided as a loss.
        setFen(before.fen());
        setLastMove(null);
        setMovable(view.player_color);
        if (fb.kind === "wrong" && practice) {
          practiceMiss.current = true;
          setMessage({ color: "red", text: "Not the move. Keep trying (practice, not scored)." });
        } else if (fb.kind === "wrong") {
          setMessage({ color: "red", text: "Not the move. This puzzle counts as failed; keep trying or go to the next one." });
        }
      }
    } catch (e) {
      setFen(before.fen());
      setMovable(view.player_color);
      setError((e as Error).message);
    }
  };

  const requestHelp = async (kind: "hint" | "answer") => {
    if (helpBusy) return;
    setHelpBusy(true);
    try {
      const help = await api.requestHelp(sessionId, kind);
      if (help.outcome) {
        decide(help.outcome);
        sounds.play("failed");
      }
      const lost = help.outcome ? " This puzzle now counts as failed." : "";
      if (practice) practiceMiss.current = true;
      if (kind === "hint") {
        setHintSquare(help.hint_square);
        setHinted(true);
        setMessage({ color: "gray", text: `Hint: the circled piece moves next.${lost}` });
      } else if (help.answer_fen) {
        timers.current.forEach(clearTimeout);
        timers.current = [];
        setHintSquare(null);
        setMovable(null);
        setLineDone(true);
        setAnalysis(null); // the answer replaces the analysis board and any line being shown (FR-5.4)
        setPreview(null);
        const solution = answerPositions(help.answer_fen, help.answer_moves, help.answer_sounds);
        if (view?.mode === "danger_spotting") {
          setDangerPhase("done");
          setLastMove(null);
        }
        setAnswer({ positions: solution, step: 0, segments: [{ label: view?.mode === "danger_spotting" ? "The answer" : "The solution", from: 0 }] });
        setMessage({ color: "gray", text: `The answer: step through it with Back and Forward.${lost}` });
        if (help.refute && !whyWrong) loadRefutation();
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setHelpBusy(false);
    }
  };

  // §7.2 step 2: put Stockfish's answer to your wrong move in front of the solution once it arrives.
  // §7.2 step 2: Stockfish's answer to your wrong move. It sits above the answer with its own Show me;
  // the answer itself is always the correct solution (Adam, v0.4 manual test).
  const loadRefutation = () => {
    setRefutation("loading");
    const seq = puzzleSeq.current;
    api.getRefutation(sessionId).then(
      (r) => {
        if (seq !== puzzleSeq.current) return;
        const positions = answerPositions(r.fen_before, [r.wrong_move, ...r.line]);
        const wrongSan = positions[1]?.san ?? r.wrong_move;
        const verdict = r.score ?? r.game_over ?? "";
        setRefutation(null);
        setWhyWrong({ label: `Why ${wrongSan} fails${verdict ? `: ${verdict}` : ""}`, positions });
      },
      (e: Error) => {
        if (seq !== puzzleSeq.current) return;
        if (e instanceof ApiCallError && e.code === "engine_not_installed") {
          refreshEngine();
          setRefutation("missing");
        } else setRefutation({ error: e.message });
      },
    );
  };

  const decided = outcome !== null;
  const shown = answer ? answer.positions[answer.step] : null;
  const analysisPos = analysis ? analysis.positions[analysis.step] : null;
  const boardFen = analysisPos ? analysisPos.fen : shown ? shown.fen : fen;
  // Where you start: after the opponent's move (Danger spotting: the raw position itself).
  const startFen = view ? (() => { const c = new Chess(view.fen); if (view.opponent_move) c.move(uciMove(view.opponent_move)); return c.fen(); })() : null;
  const danger = view?.mode === "danger_spotting";
  const candidateArrow: [string, string] | null =
    danger && view?.candidate && dangerPhase === "call" ? [view.candidate.slice(0, 2), view.candidate.slice(2, 4)] : null;
  const candidateSan = danger && view?.candidate ? (sanLine(view.fen, [view.candidate])[0] ?? view.candidate) : "";
  // A preview belongs to the position it was opened on: moving on (answer, analysis board) ends it.
  const linePreview = preview && preview.from === boardFen ? preview : null;
  const previewPos = linePreview ? linePreview.positions[linePreview.step] : null;
  const arrow = analysisPos && !previewPos ? legalArrow(analysisPos.fen, bestMove ?? undefined) : null;
  const showLine = (from: string, pv: string[]) =>
    setPreview({ from, label: `Showing: ${pvToSan(from, pv, pv.length)}`, positions: answerPositions(from, pv), step: 0 });
  const stepPreview = (to: number) => {
    if (!linePreview) return;
    setPreview({ ...linePreview, step: Math.min(Math.max(to, 0), linePreview.positions.length - 1) });
  };
  const canHint = view !== null && movable !== null && !lineDone && !answer && !helpBusy;
  // After the end, Show answer stays available: it goes back to the start of the answer (FR-5.4).
  // Danger spotting: before the call there's no Hint, and Show answer (a loss) reveals the truth.
  const canAnswer =
    view !== null && !helpBusy && ((danger && dangerPhase === "call" && !calling) || ((hinted || decided || lineDone) && (lineDone || movable !== null)));
  const canRetry = view !== null && lineDone && !helpBusy && !busy;
  const retry = async () => {
    if (!view || !canRetry) return;
    try {
      await api.retryPuzzle(sessionId);
    } catch (e) {
      setError((e as Error).message);
      return;
    }
    puzzleSeq.current += 1; // late engine replies belong to the run before
    timers.current.forEach(clearTimeout);
    timers.current = [];
    practiceMiss.current = false;
    setPractice(true);
    setLineDone(false);
    setAnswer(null);
    setRefutation(null);
    setWhyWrong(null);
    setAnalysis(null);
    setPreview(null);
    setBestMove(null);
    setHintSquare(null);
    setHinted(false);
    setMovable(null);
    setEntry([]);
    setCommitResult(null);
    setNeedTags(false); // practice runs go straight to solving
    const c = new Chess(view.fen);
    setFen(view.fen);
    setLastMove(null);
    setMessage({ color: "gray", text: "Try again: practice, not scored." });
    if (view.mode === "danger_spotting") {
      chess.current = c;
      setDangerPhase("call");
      setMessage({ color: "gray", text: turnMessage(view, true) });
      return;
    }
    later(() => {
      const opp = view.opponent_move;
      c.move(uciMove(opp));
      chess.current = c;
      setFen(c.fen());
      setLastMove([opp.slice(0, 2), opp.slice(2, 4)]);
      setMovable(view.mode === "commit_line" ? "both" : view.player_color);
      sounds.play(view.opponent_sound);
      setMessage({ color: "gray", text: turnMessage(view, true) });
    }, OPPONENT_DELAY_MS);
  };
  const stepAnalysis = (to: number) => {
    if (!analysis) return;
    setAnalysis({ ...analysis, step: Math.min(Math.max(to, 0), analysis.positions.length - 1) });
  };
  const onAnalysisMove = (uci: string) => {
    if (!analysis) return;
    const next = analysisMove(analysis, uci);
    setAnalysis(next ? next : { ...analysis }); // an illegal move snaps back
  };
  const stepAnswer = (delta: number) => {
    if (linePreview) return stepPreview(linePreview.step + delta);
    if (analysis) return stepAnalysis(analysis.step + delta);
    if (!answer) return;
    const to = Math.min(Math.max(answer.step + delta, 0), answer.positions.length - 1);
    if (to === answer.step) return;
    if (to > answer.step) sounds.play(answer.positions[to].sound);
    setAnswer({ ...answer, step: to });
  };
  const next = () => {
    if (complete) onNewSession();
    else if (view && !busy) load();
  };

  // §7.3: once a lost puzzle is over, ask why (never in practice runs; the backend says whether to ask).
  const lostAttempt = outcome && !outcome.win ? outcome.attempt_id : null;
  useEffect(() => {
    if (lostAttempt === null || !lineDone || reasonPrompt !== null) return;
    const seq = puzzleSeq.current;
    api.getReasonPrompt(sessionId).then(
      (p) => {
        if (seq === puzzleSeq.current && p && p.attempt_id === lostAttempt) setReasonPrompt(p);
      },
      () => undefined,
    );
  }, [lostAttempt, lineDone, reasonPrompt, sessionId]);
  // The chip, and the note you've written so far (by click or by key 1–6: v0.6-B2).
  const chooseReason = async (reason: ReasonKey) => {
    if (!reasonPrompt || reasonBusy) return;
    const typed = reasonNote.trim();
    const note = typed.length > MAX_NOTE ? "" : typed; // too long: save the reason; the box says why
    setReasonBusy(true);
    try {
      await api.setMistakeReason(reasonPrompt.attempt_id, reason, note || null);
      setReasonChosen(reason);
      api.getSessionStats(sessionId).then(setStats, () => undefined); // a misclick leaves the tally
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setReasonBusy(false);
    }
  };
  const showReasons = reasonPrompt !== null && !reasonSkipped;
  const reasonKey = (i: number) => () => {
    const r = showReasons ? reasonPrompt?.reasons[i] : undefined;
    if (r) chooseReason(r.key);
  };

  // Keyboard shortcuts (state/shortcuts.ts has the list). Each does nothing unless its button is enabled.
  useShortcuts({
    n: next,
    Enter: next,
    h: () => canHint && requestHelp("hint"),
    a: () => canAnswer && requestHelp("answer"),
    r: () => canRetry && retry(),
    ArrowLeft: () => stepAnswer(-1),
    ArrowRight: () => stepAnswer(1),
    s: () => danger && dangerPhase === "call" && callDanger("safe"),
    u: () => danger && dangerPhase === "call" && callDanger("unsafe"),
    "1": reasonKey(0),
    "2": reasonKey(1),
    "3": reasonKey(2),
    "4": reasonKey(3),
    "5": reasonKey(4),
    "6": reasonKey(5),
  });

  if (complete) {
    return (
      <Stack gap="md">
        <SessionBar stats={stats} />
        <Paper withBorder p="lg" radius="md" data-testid="session-complete">
          <Stack gap="sm">
            <Title order={3}>Session complete</Title>
            <Text>
              {stats?.solved ?? 0} solved, {stats?.failed ?? 0} failed
              {stats?.accuracy != null && ` (${Math.round(stats.accuracy * 100)}% accuracy)`}.
            </Text>
            <Group>
              <Button onClick={onNewSession}>New session</Button>
            </Group>
          </Stack>
        </Paper>
      </Stack>
    );
  }

  return (
    <Stack gap="md">
      <SessionBar stats={stats} />
      {error && (
        <Alert color="red" withCloseButton onClose={() => setError(null)}>
          {error}
        </Alert>
      )}
      <Group align="flex-start" gap="lg" wrap="nowrap" justify={wide ? "center" : undefined}>
        <div style={wide ? { flex: `0 1 ${WIDE_BOARD}`, minWidth: 320 } : { flex: "1 1 560px", minWidth: 320 }}>
          {fen && view && (
            <Board
              fen={previewPos ? previewPos.fen : (boardFen ?? fen)}
              orientation={danger && dangerPhase === "refute" ? other(view.player_color) : view.player_color}
              movable={previewPos ? null : analysisPos ? "both" : shown ? null : movable}
              lastMove={previewPos ? previewPos.lastMove : analysisPos ? analysisPos.lastMove : shown ? shown.lastMove : lastMove}
              onMove={analysisPos ? onAnalysisMove : onMove}
              hintSquare={analysisPos ? null : hintSquare}
              coordinates={coordinates}
              arrows={arrow ? [arrow] : candidateArrow && !previewPos && !shown && !analysisPos ? [candidateArrow] : undefined}
              maxWidth={wide ? WIDE_BOARD : 560}
            />
          )}
          {showReasons && reasonPrompt && (
            <div style={{ maxWidth: wide ? WIDE_BOARD : 560, marginTop: "var(--mantine-spacing-sm)" }}>
              <ReasonChips
                prompt={reasonPrompt}
                chosen={reasonChosen}
                busy={reasonBusy}
                note={reasonNote}
                onNote={setReasonNote}
                onChoose={chooseReason}
                onSkip={() => setReasonSkipped(true)}
              />
            </div>
          )}
        </div>
        <Stack gap="sm" style={{ flex: "0 0 260px" }}>
          {view && (
            <Text size="sm" c="dimmed" data-testid="puzzle-header">
              Puzzle {view.number}
              {stats?.queue_size ? ` of ${stats.queue_size}` : ""} · rated {view.rating} ·{" "}
              {danger && dangerPhase === "refute"
                ? `you play ${other(view.player_color)}`
                : danger
                  ? `${view.player_color} to move`
                  : `you play ${view.player_color}`}
            </Text>
          )}
          {practice && (
            <Badge color="grape" variant="light" style={{ textTransform: "none" }} data-testid="practice-badge">
              Practice: not scored
            </Badge>
          )}
          {view?.already_played && (
            <Badge
              color="gray"
              variant="light"
              style={{ textTransform: "none", whiteSpace: "normal", height: "auto", lineHeight: 1.4, paddingBlock: 2 }}
              title="You've played this puzzle before, so Lichess won't change your rating for it."
              data-testid="already-played"
            >
              Already played: rating unaffected
            </Badge>
          )}
          {message && (
            <Text c={message.color === "gray" ? undefined : message.color} fw={500} data-testid="trainer-message">
              {message.text}
            </Text>
          )}
          {outcome && (
            <Paper withBorder p="sm" radius="md" data-testid="outcome">
              <Stack gap={6}>
                <Text fw={700} c={outcome.win ? "green" : "red"}>
                  {outcome.win ? "Solved" : "Failed"}
                </Text>
                <Text size="sm">Themes:</Text>
                <Group gap={4} data-testid="outcome-themes">
                  {outcome.themes.map((t) => (
                    <Badge key={t.key} variant="light" style={{ textTransform: "none" }}>
                      {t.name}
                    </Badge>
                  ))}
                </Group>
                {outcome.idea && <IdeaResult idea={outcome.idea} />}
                {outcome.danger && <DangerVerdict fen={view?.fen ?? ""} reveal={outcome.danger} />}
                {outcome.level_up && (
                  <Badge color="teal" variant="light" style={{ textTransform: "none" }} data-testid="level-up">
                    Level up! Now {outcome.level_up.label.toLowerCase()} puzzles ({outcome.level_up.level}
                    {outcome.level_up.top ? "+" : ""} moves)
                  </Badge>
                )}
                {!danger && <RatingChange info={rating} />}
                <Anchor size="sm" href={outcome.puzzle_url} target="_blank" rel="noreferrer">
                  Open this puzzle on Lichess
                </Anchor>
              </Stack>
            </Paper>
          )}
          {view?.mode === "name_idea" && needTags && !lineDone && !decided && movable === null && fen !== view.fen && (
            <IdeaTags busy={tagging} onStart={startSolving} />
          )}
          {danger && dangerPhase === "call" && !lineDone && (
            <DangerCall san={candidateSan} busy={calling || helpBusy} onCall={callDanger} />
          )}
          {view?.mode === "commit_line" && !lineDone && movable !== null && (
            <CommitControls
              entered={entry.length}
              target={view.solution_plies}
              max={view.max_plies}
              busy={submitting}
              onUndo={() => undoEntry(false)}
              onClear={() => undoEntry(true)}
              onSubmit={submitLine}
            />
          )}
          {commitResult && startFen && !analysis && !linePreview && <CommitResult startFen={startFen} result={commitResult} />}
          {answer && !analysis && !linePreview && (
            <AnswerPlayer
              positions={answer.positions}
              step={answer.step}
              segments={answer.segments}
              onStep={(to) => stepAnswer(to - answer.step)}
            />
          )}
          {whyWrong && !linePreview && (
            <Group gap={6} wrap="nowrap" justify="space-between" data-testid="refutation">
              <Text size="sm" fw={600} data-testid="refutation-label">
                {whyWrong.label}
              </Text>
              {boardFen && (
                <Button
                  size="compact-xs"
                  variant="subtle"
                  style={{ flexShrink: 0 }}
                  onClick={() => setPreview({ from: boardFen, label: whyWrong.label, positions: whyWrong.positions, step: 0 })}
                  data-testid="refutation-show"
                >
                  Show me
                </Button>
              )}
            </Group>
          )}
          {refutation === "loading" && (
            <Text size="sm" c="dimmed" data-testid="refutation-loading">
              Stockfish is checking your move…
            </Text>
          )}
          {refutation === "missing" && engine && <EngineInstallBanner status={engine} onChanged={refreshEngine} />}
          {refutation && typeof refutation === "object" && (
            <Text size="xs" c="red" data-testid="refutation-error">
              {refutation.error}
            </Text>
          )}
          {lineDone && view && startFen && boardFen && refutation !== "missing" && (
            <EnginePanel
              sessionId={sessionId}
              startFen={startFen}
              fen={boardFen}
              purpose={analysis ? "board" : "panel"}
              status={engine}
              onStatusChanged={refreshEngine}
              onBestMove={setBestMove}
              onShowLine={showLine}
            >
              {linePreview ? (
                <Stack gap={4} data-testid="line-preview">
                  <AnswerPlayer
                    positions={linePreview.positions}
                    step={linePreview.step}
                    segments={[{ label: linePreview.label, from: 0 }]}
                    onStep={stepPreview}
                  />
                  <Button size="xs" variant="light" color="gray" onClick={() => setPreview(null)} data-testid="line-preview-done">
                    Done
                  </Button>
                </Stack>
              ) : analysis ? (
                <AnalysisControls
                  state={analysis}
                  onStep={stepAnalysis}
                  onReset={() => setAnalysis(openAnalysis(startFen))}
                  onClose={() => setAnalysis(null)}
                  closeLabel={answer ? "Back to the answer" : "Close"}
                />
              ) : (
                <AnalyzeButton onClick={() => setAnalysis(openAnalysis(boardFen))} />
              )}
            </EnginePanel>
          )}
          <Group gap="xs" grow data-testid="help-controls">
            <Button variant="light" color="gray" disabled={!canHint} onClick={() => requestHelp("hint")} data-testid="hint-button">
              Hint
            </Button>
            <Button
              variant="light"
              color="gray"
              disabled={!canAnswer}
              onClick={() => requestHelp("answer")}
              title={hinted || decided || lineDone ? undefined : "Use Hint first"}
              data-testid="answer-button"
            >
              Show answer
            </Button>
          </Group>
          {lineDone && (
            <Button
              variant="light"
              color="grape"
              disabled={!canRetry}
              onClick={retry}
              title="Solve it again from the start. Not scored, nothing is sent to Lichess."
              data-testid="try-again"
            >
              Try again (not scored)
            </Button>
          )}
          {!decided && !lineDone && (
            <Text size="xs" c="dimmed">
              {danger && dangerPhase === "call"
                ? "Show answer counts the puzzle as failed and tells you whether the move was safe."
                : "Hint and Show answer count the puzzle as failed. Show answer unlocks after a Hint."}
              {view?.mode === "commit_line" ? " Hint circles the piece that makes your first move." : ""}
            </Text>
          )}
          <Button
            onClick={load}
            variant={decided || lineDone ? "filled" : "default"}
            disabled={!view || busy}
            data-testid="next-button"
          >
            {decided || lineDone ? "Next puzzle" : "Skip (counts as failed)"}
          </Button>
        </Stack>
      </Group>
    </Stack>
  );
}
