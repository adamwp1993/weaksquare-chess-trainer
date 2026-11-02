import { useEffect, useRef } from "react";

export type ShortcutMap = Record<string, () => void>;

// Every shortcut the app has, for the "?" list. Keep in sync with the handlers that use them.
export const SHORTCUTS: { keys: string; action: string }[] = [
  { keys: "N or Enter", action: "Next puzzle (or Skip, which counts as failed)" },
  { keys: "H", action: "Hint" },
  { keys: "A", action: "Show answer" },
  { keys: "← / →", action: "Step back / forward (the answer, the analysis board, a line you chose with Show me)" },
  { keys: "C", action: "Show or hide the board coordinates" },
  { keys: "?", action: "This list" },
];

// How focus last moved: a pointer press (a click leaves focus on the clicked button, and clicks on
// the board don't move it) or Tab. (:focus-visible can't tell: Chromium sets it on the Enter keydown.)
let focusByPointer = false;
if (typeof window !== "undefined") {
  window.addEventListener("pointerdown", () => (focusByPointer = true), true);
  window.addEventListener(
    "keydown",
    (e) => {
      if (e.key === "Tab") focusByPointer = false;
    },
    true,
  );
}

function typingInto(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  if (tag === "TEXTAREA" || tag === "SELECT") return true;
  if (tag === "INPUT") {
    const type = (target as HTMLInputElement).type;
    return !["checkbox", "radio", "button", "submit", "range"].includes(type);
  }
  return false;
}

/** Key → action, while `enabled`. Keys are KeyboardEvent.key values ("n", "Enter", "ArrowLeft", "?").
 * Ignored while you type in a field, with Ctrl/Alt/Meta held, while a dialog is open, and (for Enter
 * and Space) on a button you moved to with the keyboard, which acts on them itself. Each action
 * decides whether it applies. */
export function useShortcuts(map: ShortcutMap, enabled = true): void {
  const ref = useRef(map);
  useEffect(() => {
    ref.current = map;
  });
  useEffect(() => {
    if (!enabled) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.altKey || e.metaKey || e.repeat || typingInto(e.target)) return;
      if (document.querySelector('[role="dialog"]')) return;
      const target = e.target as HTMLElement | null;
      const control = target?.closest<HTMLElement>("button, a, [role='button']");
      // A focused button acts on Space and Enter itself, but only when you moved to it with the
      // keyboard: a mouse click leaves focus on the button too (Start, Hint…), and Enter then means
      // Next, not "press Start again" (v0.2-B1).
      if (e.key === " " && control) return;
      if (e.key === "Enter" && control && !focusByPointer) return;
      const key = e.key.length === 1 ? e.key.toLowerCase() : e.key;
      const action = ref.current[key] ?? ref.current[e.key];
      if (action) {
        e.preventDefault();
        action();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [enabled]);
}
