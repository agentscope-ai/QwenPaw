/**
 * a11y.ts — Small accessibility helpers for the Desktop OS shell.
 *
 * The shell renders many clickable <div>s (dock items, launcher tiles, space
 * chips…) that keyboard users otherwise cannot reach. `buttonRoleProps` turns
 * such a div into a focusable button: Tab reaches it, Enter/Space activate it.
 */
import type { HTMLAttributes } from "react";

/** Spread onto a clickable div to make it keyboard-accessible. */
export function buttonRoleProps(
  onActivate: () => void,
  label?: string,
): HTMLAttributes<HTMLDivElement> {
  return {
    role: "button",
    tabIndex: 0,
    "aria-label": label,
    onKeyDown: (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        onActivate();
      }
    },
  };
}
