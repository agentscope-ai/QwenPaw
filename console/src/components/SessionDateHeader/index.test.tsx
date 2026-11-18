// @vitest-environment jsdom
/**
 * SessionDateHeader - the collapsible date divider in the sidebar session list.
 * Rendered from one place, checked by grep before this suite was written:
 *   - `layouts/SidebarSessionList.tsx:200` (imported at `:57`), for rows whose
 *     `kind === "dateHeader"`.
 *
 * Visible contract under test:
 *
 *   1. the whole header is ONE control: `role="button"` with `tabIndex={0}`, so
 *      it is focusable and reachable by assistive tech - the sidebar list is a
 *      virtualized row renderer, which cannot hand out a real `<button>`;
 *   2. `aria-expanded` is the negation of `collapsed`, and it is the only place
 *      the collapsed state is exposed to a screen reader. Both halves are
 *      pinned, plus the default: omitting `collapsed` means expanded, so a
 *      caller that forgets the prop cannot silently collapse a group;
 *   3. `dateGroup` is echoed on the element as `data-date-group` verbatim,
 *      which is how the virtualized list finds the row it just toggled;
 *   4. label and count are two separate slots in a fixed order
 *      (chevron, label, count). The count is a plain number, and `0` still
 *      renders as "0" rather than disappearing - an empty date group must not
 *      look like a label with no number;
 *   5. toggling works from three gestures and each one calls the same handler
 *      exactly once: click, `Enter`, and `Space`. `Space` matters because the
 *      product tests the literal `" "` key, not `"Space"`;
 *   6. both activating keys ALSO call `preventDefault()`, while a non-activating
 *      key does not. That is the part that keeps the page from scrolling when
 *      the user expands a group with Space;
 *   7. a non-activating key never toggles - the handler is not bound to every
 *      keydown. The two activating paths also differ in payload (click passes
 *      the synthetic event through, keys call the handler bare), which is
 *      pinned in its own case rather than left to chance;
 *   8. the chevron slot carries the collapsed modifier class only when
 *      collapsed, and the icon is `lucide-chevron-down` at size 13 in both
 *      states - the same icon is rotated by CSS rather than swapped;
 *   9. the three slots keep their own CSS-module classes, which is what the
 *      stylesheet hangs its geometry on.
 *
 * Harness notes (measured facts, not guesses):
 *
 * - `lucide-react` is a real dependency (`package.json:50`, `^0.562.0`) and is
 *   NOT aliased away by `vite.config.ts`, so the icon renders for real. A probe
 *   read back the actual attributes: `class="lucide lucide-chevron-down"`,
 *   `width="13"`, `height="13"`.
 * - `fireEvent.keyDown` returns `!event.defaultPrevented`, which is what makes
 *   point 6 assertable without touching React internals. A probe measured the
 *   three cases: `Enter` -> false, `" "` -> false, `"a"` -> true.
 * - CSS-module names are read through the imported `styles` object (probe read
 *   back `_header_b4aa42` / `_chevron_b4aa42` / `_collapsed_b4aa42` /
 *   `_label_b4aa42` / `_count_b4aa42`), never hard-coded. Note the chevron slot
 *   is built with a template string, so in the expanded state its class ends
 *   with a trailing space - asserted through `toContain`, not equality.
 * - no `react-i18next` mock is needed: the component takes an already
 *   translated `label` and imports nothing i18n-related.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, fireEvent, cleanup } from "@testing-library/react";
import type { ChatDateGroup } from "../../utils/chatGroups";
import SessionDateHeader from "./index";
import styles from "./SessionDateHeader.module.less";

function renderHeader(props: {
  dateGroup?: ChatDateGroup;
  label?: string;
  count?: number;
  collapsed?: boolean;
  onToggle?: () => void;
}) {
  const onToggle = props.onToggle ?? vi.fn();
  const view = render(
    <SessionDateHeader
      dateGroup={props.dateGroup ?? "today"}
      label={props.label ?? "Today"}
      count={props.count ?? 3}
      {...(props.collapsed === undefined ? {} : { collapsed: props.collapsed })}
      onToggle={onToggle}
    />,
  );
  return { ...view, onToggle, header: view.getByRole("button") };
}

/** The chevron slot: the first child span, holding the icon. */
function chevronSlotOf(header: HTMLElement): HTMLElement | null {
  return header.querySelector("span");
}

afterEach(cleanup);

describe("SessionDateHeader", () => {
  it("is a single button-role control and is focusable", () => {
    const { container, header } = renderHeader({});
    expect(container.querySelectorAll('[role="button"]')).toHaveLength(1);
    expect(header.getAttribute("tabindex")).toBe("0");
  });

  it("reports expanded when collapsed is omitted", () => {
    const { header } = renderHeader({});
    expect(header.getAttribute("aria-expanded")).toBe("true");
  });

  it("reports expanded when collapsed is false", () => {
    const { header } = renderHeader({ collapsed: false });
    expect(header.getAttribute("aria-expanded")).toBe("true");
  });

  it("reports collapsed when collapsed is true", () => {
    const { header } = renderHeader({ collapsed: true });
    expect(header.getAttribute("aria-expanded")).toBe("false");
  });

  it("carries the wrapper class from the stylesheet", () => {
    const { header } = renderHeader({});
    expect(header.className).toContain(styles.header);
  });

  it("echoes each date group verbatim on data-date-group", () => {
    const groups: ChatDateGroup[] = [
      "pinned",
      "today",
      "week",
      "month",
      "older",
    ];
    const { header, rerender } = renderHeader({ dateGroup: groups[0] });
    expect(header.getAttribute("data-date-group")).toBe("pinned");
    for (const group of groups.slice(1)) {
      rerender(
        <SessionDateHeader
          dateGroup={group}
          label="L"
          count={1}
          onToggle={vi.fn()}
        />,
      );
      expect(header.getAttribute("data-date-group")).toBe(group);
    }
  });

  it("renders the label and the count as two separate slots", () => {
    const { header } = renderHeader({ label: "This week", count: 12 });
    expect(header.querySelector(`.${styles.label}`)?.textContent).toBe(
      "This week",
    );
    expect(header.querySelector(`.${styles.count}`)?.textContent).toBe("12");
  });

  it("still renders a zero count instead of dropping the slot", () => {
    const { header } = renderHeader({ count: 0 });
    expect(header.querySelector(`.${styles.count}`)?.textContent).toBe("0");
    expect(header.querySelector(`.${styles.count}`)).not.toBeNull();
  });

  it("keeps the slot order chevron, label, count", () => {
    const { header } = renderHeader({});
    const slots = Array.from(header.children).map((node) => node.className);
    expect(slots).toHaveLength(3);
    expect(slots[0]).toContain(styles.chevron);
    expect(slots[1]).toBe(styles.label);
    expect(slots[2]).toBe(styles.count);
  });

  it("renders the lucide chevron at size 13", () => {
    const { header } = renderHeader({});
    const svg = header.querySelector("svg");
    expect(svg?.getAttribute("class")).toBe("lucide lucide-chevron-down");
    expect(svg?.getAttribute("width")).toBe("13");
    expect(svg?.getAttribute("height")).toBe("13");
  });

  it("leaves the collapsed class off the chevron slot while expanded", () => {
    const { header } = renderHeader({ collapsed: false });
    const slot = chevronSlotOf(header);
    expect(slot?.className).toContain(styles.chevron);
    expect(slot?.className).not.toContain(styles.collapsed);
  });

  it("adds the collapsed class to the chevron slot when collapsed", () => {
    const { header } = renderHeader({ collapsed: true });
    const slot = chevronSlotOf(header);
    expect(slot?.className).toContain(styles.chevron);
    expect(slot?.className).toContain(styles.collapsed);
    // The icon itself is not swapped: the same chevron is rotated by CSS.
    expect(header.querySelector("svg")?.getAttribute("class")).toBe(
      "lucide lucide-chevron-down",
    );
  });

  it("toggles once on click", () => {
    const onToggle = vi.fn();
    const { header } = renderHeader({ onToggle });
    fireEvent.click(header);
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it("toggles once on Enter and swallows the default action", () => {
    const onToggle = vi.fn();
    const { header } = renderHeader({ onToggle });
    // fireEvent returns !event.defaultPrevented.
    expect(fireEvent.keyDown(header, { key: "Enter" })).toBe(false);
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it("toggles once on Space and swallows the default action", () => {
    const onToggle = vi.fn();
    const { header } = renderHeader({ onToggle });
    // The product tests the literal " " key, not the "Space" name.
    expect(fireEvent.keyDown(header, { key: " " })).toBe(false);
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it("does not toggle on a key that is not an activator", () => {
    const onToggle = vi.fn();
    const { header } = renderHeader({ onToggle });
    expect(fireEvent.keyDown(header, { key: "a" })).toBe(true);
    expect(fireEvent.keyDown(header, { key: "ArrowDown" })).toBe(true);
    expect(onToggle).not.toHaveBeenCalled();
  });

  it("does not swallow the default action for a non-activating key", () => {
    const { header } = renderHeader({});
    expect(fireEvent.keyDown(header, { key: "Escape" })).toBe(true);
  });

  it("routes click and both keys to the same handler, one call each", () => {
    const onToggle = vi.fn();
    const { header } = renderHeader({ onToggle });
    fireEvent.keyDown(header, { key: "Enter" });
    fireEvent.keyDown(header, { key: " " });
    fireEvent.click(header);
    expect(onToggle).toHaveBeenCalledTimes(3);
  });

  it("forwards the click event but no argument from the keyboard path", () => {
    // Measured asymmetry in the product, pinned on purpose: the click handler
    // is `onClick={onToggle}` so React hands the synthetic event straight
    // through, while the keydown handler calls `onToggle()` itself with no
    // argument. The only caller (`layouts/SidebarSessionList.tsx:205`) passes
    // an arrow function that ignores its arguments, so neither shape reaches
    // the user - but a handler that ever read its first argument would see
    // different values depending on how the header was activated.
    const onToggle = vi.fn();
    const { header } = renderHeader({ collapsed: true, onToggle });

    fireEvent.keyDown(header, { key: "Enter" });
    expect(onToggle.mock.calls[0]).toEqual([]);

    fireEvent.click(header);
    expect(onToggle.mock.calls[1]).toHaveLength(1);
    expect(typeof onToggle.mock.calls[1][0]).toBe("object");
  });
});
