import { useEffect, useRef } from "react";

export type ShortcutMap = Record<string, () => void>;

// Every shortcut the app has, for the "?" list. Keep in sync with the handlers that use them.
export const SHORTCUTS: { keys: string; action: string }[] = [
  { keys: "N or Enter", action: "Next puzzle (or Skip, which counts as failed)" },
  { keys: "H", action: "Hint" },
  { keys: "A", action: "Show answer" },
  { keys: "← / →", action: "Step back / forward through the answer" },
  { keys: "C", action: "Show or hide the board coordinates" },
  { keys: "?", action: "This list" },
];

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
 * and Space) on a focused button, which already acts on them. Each action decides whether it applies. */
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
      if ((e.key === "Enter" || e.key === " ") && target?.closest("button, a, [role='button']")) return;
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
