/* eslint-disable @typescript-eslint/no-explicit-any */
/**
 * PreviewModal - the read-only detail dialog for one tool-guard rule: the
 * early return while there is no rule to show, the dialog props handed to
 * Modal (title, open, width, footer), the six labelled fields with their two
 * empty-list fallbacks, the severity tag colour including the unknown-severity
 * fallback, the description that prefers the catalogue entry over the rule's
 * own text, the patterns block and the exclude-patterns block that only
 * appears when there is at least one, the newline join inside both blocks, and
 * the dark-theme style the product computes for those two blocks.
 *
 * Stub notes, each one measured against the real modules before writing:
 * - The global design stub exports Modal, Button and Tag (measured: all three
 *   true), but `@agentscope-ai/design` is still overridden here so that
 *   `onCancel` and the footer action are reachable through explicit driver
 *   buttons: a stub Modal has no DOM event of its own for `onCancel`, and no
 *   assertion reads the driver buttons themselves. Overriding is authorised by
 *   src/test/design-mock.ts:4.
 * - No icon library is imported by this component, so none is mocked.
 * - `useTheme` is mocked after the established pattern of the sibling tests
 *   (pages/Login/index.test.tsx:33), and `isDark` is switchable so that both
 *   arms of the computed block style really execute.
 * - Expected colours are the jsdom-normalised forms, measured by probe rather
 *   than copied from the source literals: the light arm reports
 *   "rgb(245, 245, 245)" / "rgb(51, 51, 51)" / "1px solid rgb(232, 232, 232)",
 *   the dark arm keeps the two var() tokens and reports the rgba with spaces
 *   ("1px solid rgba(255, 255, 255, 0.12)"). Numeric lengths come back with
 *   their unit ("12px", "6px", "13px").
 * - The severity colour table is asserted through the colour the product maps
 *   to, which the stub Tag mirrors as a data attribute, so the assertion is on
 *   the product's mapping and not on the stub.
 * - Translation is a switchable stub: keys listed in `tMissing` answer with the
 *   caller's defaultValue, every other key answers with itself. That is what
 *   makes both arms of the description fallback reachable.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import React from "react";
import type { ToolGuardRule } from "../../../../api/modules/security";
import { PreviewModal } from "./PreviewModal";

const h = vi.hoisted(() => ({
  isDark: false,
  tMissing: new Set<string>(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { defaultValue?: string }) =>
      h.tMissing.has(key) ? opts?.defaultValue ?? "" : key,
    i18n: {
      language: "en",
      resolvedLanguage: "en",
      changeLanguage: vi.fn(),
    },
  }),
}));

vi.mock("../../../../contexts/ThemeContext", () => ({
  useTheme: () => ({ isDark: h.isDark }),
}));

vi.mock("@agentscope-ai/design", () => {
  const Modal = ({ children, title, open, onCancel, footer, width }: any) =>
    open
      ? React.createElement(
          "div",
          {
            "data-testid": "modal",
            "data-title": title,
            "data-width": String(width),
          },
          // The product's own onCancel and footer are surfaced through explicit
          // driver buttons because a stub has no dialog chrome to click.
          React.createElement("button", {
            type: "button",
            "data-testid": "driver-cancel",
            onClick: onCancel,
          }),
          React.createElement("div", { "data-testid": "modal-footer" }, footer),
          children,
        )
      : null;
  const Button = ({ children, onClick }: any) =>
    React.createElement(
      "button",
      { type: "button", "data-testid": "modal-button", onClick },
      children,
    );
  const Tag = ({ children, color }: any) =>
    React.createElement(
      "span",
      { "data-testid": "tag", "data-color": color },
      children,
    );
  return { Modal, Button, Tag };
});

const makeRule = (overrides: Partial<ToolGuardRule> = {}): ToolGuardRule => ({
  id: "rm_guard",
  severity: "HIGH",
  description: "Guard recursive removal",
  tools: ["shell"],
  params: ["command"],
  patterns: ["\\brm\\b"],
  exclude_patterns: [],
  category: "shell",
  // Required by the product type (api/modules/security.ts:12). PreviewModal
  // never renders it, so it only has to be present for the object to typecheck.
  remediation: "",
  ...overrides,
});

const tags = () => screen.queryAllByTestId("tag");
const tagByLabel = (label: string) => {
  const paragraph = screen.getByText(label).closest("p") as HTMLElement | null;
  expect(paragraph, `no paragraph for label ${label}`).not.toBeNull();
  return within(paragraph as HTMLElement).getByTestId("tag");
};
const preBlocks = () =>
  Array.from(document.querySelectorAll("pre")) as HTMLPreElement[];

describe("PreviewModal - closed state", () => {
  beforeEach(() => {
    h.tMissing.clear();
    h.isDark = false;
  });

  it("renders nothing at all while there is no rule", () => {
    const { container } = render(
      <PreviewModal rule={null} onClose={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByTestId("modal")).not.toBeInTheDocument();
  });

  it("does not call onClose by itself while there is no rule", () => {
    const onClose = vi.fn();
    render(<PreviewModal rule={null} onClose={onClose} />);
    expect(onClose).not.toHaveBeenCalled();
  });
});

describe("PreviewModal - dialog props", () => {
  beforeEach(() => {
    h.tMissing.clear();
    h.isDark = false;
  });

  it("opens the dialog with the preview title and a 640px width", () => {
    render(<PreviewModal rule={makeRule()} onClose={vi.fn()} />);
    const modal = screen.getByTestId("modal");
    expect(modal.getAttribute("data-title")).toBe(
      "security.rules.previewTitle",
    );
    expect(modal.getAttribute("data-width")).toBe("640");
  });

  it("puts a close button labelled with the common key into the footer", () => {
    render(<PreviewModal rule={makeRule()} onClose={vi.fn()} />);
    const footer = screen.getByTestId("modal-footer");
    const button = within(footer).getByTestId("modal-button");
    expect(button).toHaveTextContent("common.close");
  });

  it("calls onClose from the dialog cancel", () => {
    const onClose = vi.fn();
    render(<PreviewModal rule={makeRule()} onClose={onClose} />);
    fireEvent.click(screen.getByTestId("driver-cancel"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("calls onClose from the footer button as well", () => {
    const onClose = vi.fn();
    render(<PreviewModal rule={makeRule()} onClose={onClose} />);
    fireEvent.click(
      within(screen.getByTestId("modal-footer")).getByTestId("modal-button"),
    );
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe("PreviewModal - labelled fields", () => {
  beforeEach(() => {
    h.tMissing.clear();
    h.isDark = false;
  });

  it("shows the rule id next to its label", () => {
    render(
      <PreviewModal rule={makeRule({ id: "no_curl" })} onClose={vi.fn()} />,
    );
    expect(screen.getByText("security.rules.ruleId:")).toBeInTheDocument();
    expect(screen.getByText("no_curl")).toBeInTheDocument();
  });

  it("shows the severity both as text and as the mapped tag colour", () => {
    render(
      <PreviewModal
        rule={makeRule({ severity: "CRITICAL" })}
        onClose={vi.fn()}
      />,
    );
    const tag = tagByLabel("security.rules.severityLabel:");
    expect(tag).toHaveTextContent("CRITICAL");
    expect(tag.getAttribute("data-color")).toBe("red");
  });

  it.each([
    ["CRITICAL", "red"],
    ["HIGH", "orange"],
    ["MEDIUM", "gold"],
    ["LOW", "blue"],
    ["INFO", "default"],
  ] as Array<[string, string]>)(
    "maps severity %s to the colour %s",
    (severity, colour) => {
      render(
        <PreviewModal
          rule={makeRule({ severity: severity as ToolGuardRule["severity"] })}
          onClose={vi.fn()}
        />,
      );
      expect(
        tagByLabel("security.rules.severityLabel:").getAttribute("data-color"),
      ).toBe(colour);
    },
  );

  it("falls back to the default colour for a severity outside the table", () => {
    render(
      <PreviewModal
        rule={makeRule({ severity: "URGENT" as ToolGuardRule["severity"] })}
        onClose={vi.fn()}
      />,
    );
    const tag = tagByLabel("security.rules.severityLabel:");
    expect(tag.getAttribute("data-color")).toBe("default");
    expect(tag).toHaveTextContent("URGENT");
  });

  it("lists the tools joined by a comma and a space", () => {
    render(
      <PreviewModal
        rule={makeRule({ tools: ["shell", "browser", "file_write"] })}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByText("shell, browser, file_write")).toBeInTheDocument();
  });

  it("lists a single tool without any separator", () => {
    render(
      <PreviewModal rule={makeRule({ tools: ["shell"] })} onClose={vi.fn()} />,
    );
    expect(screen.getByText("shell")).toBeInTheDocument();
    expect(screen.queryByText(/, /)).not.toBeInTheDocument();
  });

  it("says all tools when the list is empty", () => {
    render(<PreviewModal rule={makeRule({ tools: [] })} onClose={vi.fn()} />);
    expect(screen.getByText("security.rules.allTools")).toBeInTheDocument();
  });

  it("lists the params joined by a comma and a space", () => {
    render(
      <PreviewModal
        rule={makeRule({ params: ["command", "path"] })}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByText("command, path")).toBeInTheDocument();
  });

  it("says all params when the list is empty", () => {
    render(<PreviewModal rule={makeRule({ params: [] })} onClose={vi.fn()} />);
    expect(screen.getByText("security.rules.allParams")).toBeInTheDocument();
  });

  it("always shows the approval action with its own orange tag", () => {
    render(
      <PreviewModal rule={makeRule({ severity: "LOW" })} onClose={vi.fn()} />,
    );
    const tag = tagByLabel("security.rules.actionLabel:");
    expect(tag).toHaveTextContent("security.rules.actionApproval");
    expect(tag.getAttribute("data-color")).toBe("orange");
    // The severity tag keeps its own colour, so the two are not confused.
    expect(
      tagByLabel("security.rules.severityLabel:").getAttribute("data-color"),
    ).toBe("blue");
    expect(tags()).toHaveLength(2);
  });
});

describe("PreviewModal - description fallback", () => {
  beforeEach(() => {
    h.tMissing.clear();
    h.isDark = false;
  });

  it("prefers the catalogue entry for this rule id", () => {
    render(
      <PreviewModal
        rule={makeRule({ id: "no_curl", description: "own text" })}
        onClose={vi.fn()}
      />,
    );
    expect(
      screen.getByText("security.rules.descriptions.no_curl"),
    ).toBeInTheDocument();
    expect(screen.queryByText("own text")).not.toBeInTheDocument();
  });

  it("falls back to the rule's own description when the catalogue is empty", () => {
    h.tMissing.add("security.rules.descriptions.no_curl");
    render(
      <PreviewModal
        rule={makeRule({ id: "no_curl", description: "own text" })}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByText("own text")).toBeInTheDocument();
    expect(
      screen.queryByText("security.rules.descriptions.no_curl"),
    ).not.toBeInTheDocument();
  });

  it("shows nothing for the description when both sources are empty", () => {
    h.tMissing.add("security.rules.descriptions.blank");
    const { container } = render(
      <PreviewModal
        rule={makeRule({ id: "blank", description: "" })}
        onClose={vi.fn()}
      />,
    );
    // The label is still rendered, so the paragraph exists but carries no text
    // beyond the label.
    const label = screen.getByText("security.rules.descriptionLabel:");
    const paragraph = label.closest("p") as HTMLElement;
    expect(within(paragraph).queryByText("blank")).not.toBeInTheDocument();
    expect(
      paragraph.textContent
        ?.replace("security.rules.descriptionLabel:", "")
        .trim(),
    ).toBe("");
    expect(container).not.toBeEmptyDOMElement();
  });
});

describe("PreviewModal - pattern blocks", () => {
  beforeEach(() => {
    h.tMissing.clear();
    h.isDark = false;
  });

  it("renders one patterns block and no exclude block when there is none", () => {
    render(
      <PreviewModal
        rule={makeRule({ patterns: ["\\brm\\b"], exclude_patterns: [] })}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByText("security.rules.patterns:")).toBeInTheDocument();
    expect(
      screen.queryByText("security.rules.excludePatterns:"),
    ).not.toBeInTheDocument();
    expect(preBlocks()).toHaveLength(1);
  });

  it("renders the exclude block once there is at least one exclude pattern", () => {
    render(
      <PreviewModal
        rule={makeRule({
          patterns: ["\\brm\\b"],
          exclude_patterns: ["--help"],
        })}
        onClose={vi.fn()}
      />,
    );
    expect(
      screen.getByText("security.rules.excludePatterns:"),
    ).toBeInTheDocument();
    expect(preBlocks()).toHaveLength(2);
  });

  it("joins several patterns with a newline", () => {
    render(
      <PreviewModal
        rule={makeRule({
          patterns: ["\\brm\\b", "\\bmv\\b", "--no-preserve-root"],
          exclude_patterns: ["--help", "--version"],
        })}
        onClose={vi.fn()}
      />,
    );
    const [patterns, excludes] = preBlocks();
    expect(patterns.textContent).toBe("\\brm\\b\n\\bmv\\b\n--no-preserve-root");
    expect(excludes.textContent).toBe("--help\n--version");
  });

  it("renders an empty patterns block when the list is empty", () => {
    render(
      <PreviewModal
        rule={makeRule({ patterns: [], exclude_patterns: [] })}
        onClose={vi.fn()}
      />,
    );
    const [patterns] = preBlocks();
    expect(patterns.textContent).toBe("");
    // The label is still there, so the block was not dropped with its content.
    expect(screen.getByText("security.rules.patterns:")).toBeInTheDocument();
  });

  it("keeps multi-line patterns apart from each other", () => {
    render(
      <PreviewModal
        rule={makeRule({ patterns: ["first\nsecond", "third"] })}
        onClose={vi.fn()}
      />,
    );
    expect(preBlocks()[0].textContent).toBe("first\nsecond\nthird");
  });
});

describe("PreviewModal - block style per theme", () => {
  beforeEach(() => {
    h.tMissing.clear();
    h.isDark = false;
  });

  it("uses the light palette when the theme is light", () => {
    h.isDark = false;
    render(<PreviewModal rule={makeRule()} onClose={vi.fn()} />);
    const block = preBlocks()[0].style as unknown as Record<string, string>;
    // Measured: jsdom normalises these source literals into rgb() with spaces.
    expect(block.background).toBe("rgb(245, 245, 245)");
    expect(block.color).toBe("rgb(51, 51, 51)");
    expect(block.border).toBe("1px solid rgb(232, 232, 232)");
    expect(block.padding).toBe("12px");
    expect(block.borderRadius).toBe("6px");
    expect(block.fontSize).toBe("13px");
  });

  it("uses the theme tokens when the theme is dark", () => {
    h.isDark = true;
    render(<PreviewModal rule={makeRule()} onClose={vi.fn()} />);
    const block = preBlocks()[0].style as unknown as Record<string, string>;
    expect(block.background).toBe("var(--app-surface-subtle)");
    expect(block.color).toBe("var(--app-text)");
    // Measured: jsdom keeps the rgba but inserts spaces after the commas.
    expect(block.border).toBe("1px solid rgba(255, 255, 255, 0.12)");
  });

  it("shares the geometry between the two theme arms", () => {
    const read = () => {
      const block = preBlocks()[0].style as unknown as Record<string, string>;
      return [block.padding, block.borderRadius, block.fontSize];
    };
    h.isDark = false;
    const { rerender } = render(
      <PreviewModal rule={makeRule()} onClose={vi.fn()} />,
    );
    const light = read();
    h.isDark = true;
    rerender(<PreviewModal rule={makeRule()} onClose={vi.fn()} />);
    expect(read()).toEqual(light);
    expect(light).toEqual(["12px", "6px", "13px"]);
  });

  it("applies the same style to the exclude block", () => {
    h.isDark = true;
    render(
      <PreviewModal
        rule={makeRule({ patterns: ["a"], exclude_patterns: ["b"] })}
        onClose={vi.fn()}
      />,
    );
    const [patterns, excludes] = preBlocks();
    expect(excludes.getAttribute("style")).toBe(patterns.getAttribute("style"));
  });

  it("marks the description paragraph as preformatted and wrapping", () => {
    render(<PreviewModal rule={makeRule()} onClose={vi.fn()} />);
    const label = screen.getByText("security.rules.descriptionLabel:");
    const paragraph = label.closest("p") as HTMLElement;
    expect(paragraph.style.whiteSpace).toBe("pre-wrap");
    expect(paragraph.style.wordBreak).toBe("break-word");
  });
});
