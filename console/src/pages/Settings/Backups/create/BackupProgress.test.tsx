// @vitest-environment jsdom
/**
 * BackupProgress - the progress bar plus status line shown while a backup
 * stream is running. Purely presentational: it takes `progress` and
 * `progressMsg` and renders them, owning no state and calling nothing back.
 *
 * Rendered from two places, both checked by grep before this suite was written
 * (`grep -rn --include=*.ts --include=*.tsx BackupProgress src | grep -v
 * "\.test\."`; the other hits are the unrelated `BackupProgressEvent` API type
 * in `api/types/backup.ts:58` and its consumers):
 *   - `pages/Settings/Backups/create/CreateBackupModal.tsx:14` (import) +
 *     `:103` (JSX), shown while `runner.loading`;
 *   - `pages/Settings/Backups/create/SilentBackupModal.tsx:7` (import) + `:60`
 *     (JSX), the pre-restore snapshot step.
 * Both feed it `runner.progress` / `runner.progressMsg` from
 * `shared/useBackupRunner.ts` (`:30-31`, `:175`). Not dead code.
 *
 * Visible contract under test:
 *
 *   1. the bar reports the number it was given, both to assistive tech
 *      (`aria-valuenow` on a `progressbar` role, with `valuemin` 0 and
 *      `valuemax` 100) and in the readable percent text;
 *   2. `progress < 100` is the ACTIVE shape and `progress >= 100` is the
 *      SUCCESS shape. The 99 / 100 boundary is the product's own condition
 *      (`progress < 100 ? "active" : "success"`), so it is pinned at 99, 100 and
 *      101 rather than only at 0 and 100 - a flipped comparison would show a
 *      half-finished backup as complete;
 *   3. on success antd replaces the percent text with a check icon, so the
 *      readable text is empty at 100 while `aria-valuenow` still says 100.
 *      Both call sites rely on this to tell the user the stream ended;
 *   4. the status message is rendered verbatim next to the bar, as secondary
 *      text. It is the only thing telling the user which stage the stream is
 *      in, so an empty message must not break the layout and a long one must
 *      not be truncated by this component;
 *   5. the component re-renders as the parent pushes new values - the bar
 *      follows `progress` and the line follows `progressMsg` independently.
 *
 * Harness notes (measured facts, not guesses):
 *
 * - antd renders for real here (`Progress, Typography` come straight from
 *   `antd`, which `vite.config.ts` does not alias). The shared design stub
 *   `src/test/design-mock.ts` is not involved because this component never
 *   imports `@agentscope-ai/design`.
 * - DOM facts below were probed in this worktree rather than read off antd
 *   source: the bar is `.ant-progress` with `role="progressbar"`,
 *   `aria-valuemin="0"`, `aria-valuemax="100"`; the status modifier is
 *   `ant-progress-status-active` below 100 and `ant-progress-status-success` at
 *   and above it; the readable percent lives in `.ant-progress-text` and at 100
 *   its textContent is the empty string while `.anticon-check-circle` appears;
 *   the message is a `SPAN` carrying `ant-typography-secondary`.
 * - CSS module class names carry a hash (`_wrapper_f7a94a`), so they are never
 *   asserted; only antd's own stable classes and ARIA attributes are.
 * - `aria-valuenow` comes back as a string, so it is compared as one. Asserting
 *   the number 42 against the attribute would silently pass a `toBe` on a
 *   string only by accident of the matcher, and a string comparison is what the
 *   DOM actually offers.
 * - `cleanup()` runs after every case.
 */
import { describe, it, expect, afterEach } from "vitest";
import { render, cleanup } from "@testing-library/react";
import BackupProgress from "./BackupProgress";

afterEach(() => cleanup());

const bar = (root: ParentNode) => root.querySelector(".ant-progress");
const barEl = (root: ParentNode) =>
  root.querySelector<HTMLElement>('[role="progressbar"]');
const percentText = (root: ParentNode) =>
  root.querySelector(".ant-progress-text")?.textContent;
const messageEl = (root: ParentNode) => root.querySelector(".ant-typography");

describe("BackupProgress - the number it reports", () => {
  it("exposes the value to assistive tech on a 0..100 progressbar", () => {
    const { container } = render(
      <BackupProgress progress={42} progressMsg="Streaming agents" />,
    );
    const pb = barEl(container);
    expect(pb).not.toBeNull();
    expect(pb?.getAttribute("role")).toBe("progressbar");
    expect(pb?.getAttribute("aria-valuemin")).toBe("0");
    expect(pb?.getAttribute("aria-valuemax")).toBe("100");
    expect(pb?.getAttribute("aria-valuenow")).toBe("42");
  });

  it("renders the same number as readable percent text", () => {
    const { container } = render(
      <BackupProgress progress={42} progressMsg="Streaming agents" />,
    );
    expect(percentText(container)).toBe("42%");
  });

  it("starts at zero without pretending to be finished", () => {
    // N=0 of the stream: both call sites mount this the moment the backup
    // starts, so 0 has to read as "just started" (active) not as "done".
    const { container } = render(
      <BackupProgress progress={0} progressMsg="" />,
    );
    expect(barEl(container)?.getAttribute("aria-valuenow")).toBe("0");
    expect(percentText(container)).toBe("0%");
    expect(bar(container)?.className).toContain("ant-progress-status-active");
    expect(bar(container)?.className).not.toContain(
      "ant-progress-status-success",
    );
  });
});

describe("BackupProgress - active versus success", () => {
  it("shows the active shape at 99", () => {
    const { container } = render(
      <BackupProgress progress={99} progressMsg="almost" />,
    );
    expect(bar(container)?.className).toContain("ant-progress-status-active");
    expect(bar(container)?.className).not.toContain(
      "ant-progress-status-success",
    );
    expect(percentText(container)).toBe("99%");
  });

  it("shows the success shape at exactly 100", () => {
    const { container } = render(
      <BackupProgress progress={100} progressMsg="Done" />,
    );
    expect(bar(container)?.className).toContain("ant-progress-status-success");
    expect(bar(container)?.className).not.toContain(
      "ant-progress-status-active",
    );
  });

  it("keeps the success shape above 100", () => {
    // The product's condition is `progress < 100`, so an out-of-range value
    // from the stream still lands on success rather than flipping back.
    const { container } = render(
      <BackupProgress progress={101} progressMsg="Done" />,
    );
    expect(bar(container)?.className).toContain("ant-progress-status-success");
    expect(bar(container)?.className).not.toContain(
      "ant-progress-status-active",
    );
    expect(barEl(container)?.getAttribute("aria-valuenow")).toBe("101");
  });

  it("swaps the percent text for a check icon once it succeeds", () => {
    const { container } = render(
      <BackupProgress progress={100} progressMsg="Done" />,
    );
    // Probed: textContent is the empty string at 100 and a check icon appears,
    // while aria-valuenow still carries the number for assistive tech.
    expect(percentText(container)).toBe("");
    expect(container.querySelector(".anticon-check-circle")).not.toBeNull();
    expect(barEl(container)?.getAttribute("aria-valuenow")).toBe("100");
  });

  it("still shows percent text while active", () => {
    const { container } = render(
      <BackupProgress progress={7} progressMsg="Streaming agents" />,
    );
    expect(percentText(container)).toBe("7%");
    expect(container.querySelector(".anticon-check-circle")).toBeNull();
  });
});

describe("BackupProgress - the status message", () => {
  it("renders the message verbatim as secondary text", () => {
    const { container } = render(
      <BackupProgress progress={31} progressMsg="Streaming agents" />,
    );
    const msg = messageEl(container);
    expect(msg).not.toBeNull();
    expect(msg?.tagName).toBe("SPAN");
    expect(msg?.textContent).toBe("Streaming agents");
    expect(msg?.className).toContain("ant-typography-secondary");
  });

  it("survives an empty message", () => {
    // `useBackupRunner` initialises progressMsg to "" (`:31`), so the first
    // render of a backup has no message yet and must not break.
    const { container } = render(
      <BackupProgress progress={0} progressMsg="" />,
    );
    expect(messageEl(container)?.textContent).toBe("");
    expect(barEl(container)?.getAttribute("aria-valuenow")).toBe("0");
  });

  it("renders a long message without truncating it here", () => {
    const long =
      "Snapshotting agent configuration, secrets and the skill pool before restore";
    const { container } = render(
      <BackupProgress progress={55} progressMsg={long} />,
    );
    expect(messageEl(container)?.textContent).toBe(long);
  });

  it("renders the bar and the message together", () => {
    const { container } = render(
      <BackupProgress progress={55} progressMsg="Halfway" />,
    );
    // Whole-element text, so the two parts cannot be silently dropped: the
    // readable percent comes first, then the message.
    expect(container.textContent).toBe("55%Halfway");
    expect(container.children.length).toBe(1);
  });
});

describe("BackupProgress - following the parent", () => {
  it("moves the bar and the message when new values arrive", () => {
    const { container, rerender } = render(
      <BackupProgress progress={10} progressMsg="Starting" />,
    );
    expect(barEl(container)?.getAttribute("aria-valuenow")).toBe("10");
    expect(percentText(container)).toBe("10%");
    expect(messageEl(container)?.textContent).toBe("Starting");

    rerender(<BackupProgress progress={80} progressMsg="Uploading archive" />);
    expect(barEl(container)?.getAttribute("aria-valuenow")).toBe("80");
    expect(percentText(container)).toBe("80%");
    expect(messageEl(container)?.textContent).toBe("Uploading archive");

    rerender(<BackupProgress progress={100} progressMsg="Finished" />);
    expect(bar(container)?.className).toContain("ant-progress-status-success");
    expect(barEl(container)?.getAttribute("aria-valuenow")).toBe("100");
    expect(messageEl(container)?.textContent).toBe("Finished");
  });

  it("updates the message alone without touching the number", () => {
    const { container, rerender } = render(
      <BackupProgress progress={64} progressMsg="Stage one" />,
    );
    rerender(<BackupProgress progress={64} progressMsg="Stage two" />);
    expect(barEl(container)?.getAttribute("aria-valuenow")).toBe("64");
    expect(messageEl(container)?.textContent).toBe("Stage two");
  });
});
