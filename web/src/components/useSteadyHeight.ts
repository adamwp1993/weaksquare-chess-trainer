import { type RefObject, useLayoutEffect, useRef } from "react";

/** Lets an element grow but not shrink until `resetKey` changes.
 *
 * On the Openings learn board the panels under the step buttons change height from move to move (Adam,
 * 2026-11-07). When the page got shorter while scrolled down, the browser pulled it down, so the next click
 * in the same spot missed the button or hit another one. Holding the tallest height seen keeps the page
 * still. It sets `min-height` on the element directly, so React never re-renders for it. */
export function useSteadyHeight(ref: RefObject<HTMLElement | null>, resetKey: unknown): void {
  const tallest = useRef(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    tallest.current = 0;
    el.style.minHeight = "";
    const hold = () => {
      const h = el.getBoundingClientRect().height;
      if (h > tallest.current) {
        tallest.current = h;
        el.style.minHeight = `${h}px`;
      }
    };
    hold();
    const observer = new ResizeObserver(hold);
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref, resetKey]);
}
