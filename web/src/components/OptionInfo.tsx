// FR-10.72: the ⓘ next to an option. It opens on hover and on keyboard focus, and its text comes only from the table
// in text/tooltips.ts. Plain text, like everything else the app shows.
//
// The mark sits inside the control's <label>, so it must add nothing to the control's name: "Rated" stays "Rated" for a
// screen reader. It's an icon with no text, and the tooltip's words reach assistive tech as the mark's own description.
import { Tooltip, UnstyledButton } from "@mantine/core";
import type { MouseEvent, ReactNode } from "react";
import { TOOLTIPS, type TooltipId } from "../text/tooltips";

export function OptionInfo({ id }: { id: TooltipId }) {
  const text = TOOLTIPS[id];
  return (
    <Tooltip label={text} multiline w={320} events={{ hover: true, focus: true, touch: true }} withArrow zIndex={1000}>
      <UnstyledButton
        component="span"
        role="note"
        tabIndex={0}
        aria-description={text}
        data-option-info={id}
        style={{ display: "inline-flex", cursor: "help", marginLeft: 4, opacity: 0.7, verticalAlign: "-0.1em" }}
        onClick={(e: MouseEvent) => e.preventDefault()} // a click on the label's mark mustn't change the option
      >
        <svg width="0.9em" height="0.9em" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
          <circle cx="8" cy="8" r="7" fill="none" stroke="currentColor" strokeWidth="1.3" />
          <circle cx="8" cy="4.8" r="1" fill="currentColor" />
          <rect x="7.2" y="7" width="1.6" height="5" rx="0.5" fill="currentColor" />
        </svg>
      </UnstyledButton>
    </Tooltip>
  );
}

/** An option's label with its ⓘ, for Mantine's `label` prop. */
export function Labeled({ id, children }: { id: TooltipId; children: ReactNode }) {
  return (
    <>
      {children}
      <OptionInfo id={id} />
    </>
  );
}
