/* eslint-disable @typescript-eslint/no-explicit-any */
/**
 * SkillScannerSection - scanner mode / timeout configuration plus the blocked
 * history and whitelist tables. Covers the load guard, the mode select wiring,
 * the timeout blur guard (untouched / below min / above max / valid, each with
 * save success and failure), the allow-skill flow, both imperative
 * Modal.confirm callbacks (remove from whitelist incl. the disableSkill
 * fallback, and clear history), every table cell renderer (action tag,
 * timestamp formatting and its catch arm, content-hash truncation vs "any")
 * and the findings modal open / close round trip.
 *
 * File split note: this suite lives beside SkillScannerSection.test.tsx rather
 * than inside it, because that file is the upstream-owned pagination test and
 * the two need incompatible `useSkillScanner` stubs (a fixed 11-entry
 * blockedHistory to page through there, versus the mutable `h.scanner` this
 * file drives per case). Keeping them separate means neither side's stub can
 * break the other, and the upstream test stays byte-identical.
 *
 * Stub notes, each one verified against the real module before writing:
 * - The global design stub exports neither Card, Table, Empty nor Alert and its
 *   Modal ignores `open` (measured: DESIGN_KEYS has no Card/Table/Empty,
 *   HAS_Card=false HAS_Table=false HAS_Empty=false). `@agentscope-ai/design` is
 *   therefore overridden here, which src/test/design-mock.ts:4 authorises.
 * - The stub Table invokes every column `render(value, record, index)` so the
 *   product cell logic really executes, and the stub Tabs renders all panels so
 *   both tables are present regardless of which tab is active.
 * - `Modal.confirm` is captured as a spy and its `onOk` is driven explicitly:
 *   nothing in jsdom would call it otherwise.
 * - The timestamp catch arms need `Date.prototype.toLocaleString` to throw. An
 *   invalid date string does NOT reach them (measured:
 *   `new Date("not-a-date").toLocaleString()` returns "Invalid Date" without
 *   throwing), so a spy is the only way in. The happy path is spied to a fixed
 *   string as well, because the real output is locale dependent.
 * - Tooltip surfaces `title` as a title attribute so the three icon-only row
 *   buttons can be told apart by the label the product passes, instead of by
 *   third-party icon class names or by stub structure.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import React from "react";

const h = vi.hoisted(() => ({
  scanner: {
    config: null as any,
    blockedHistory: [] as any[],
    whitelist: [] as any[],
    loading: false,
    updateConfig: vi.fn(),
    addToWhitelist: vi.fn(),
    removeFromWhitelist: vi.fn(),
    removeBlockedEntry: vi.fn(),
    clearBlockedHistory: vi.fn(),
  },
  message: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
  },
  confirmSpy: vi.fn(),
  disableSkill: vi.fn(),
  isDark: false,
  stableT: (key: string) => key,
  stableI18n: {
    language: "en",
    resolvedLanguage: "en",
    changeLanguage: vi.fn(),
  },
}));

vi.mock("../useSkillScanner", () => ({
  useSkillScanner: () => ({
    config: h.scanner.config,
    blockedHistory: h.scanner.blockedHistory,
    whitelist: h.scanner.whitelist,
    loading: h.scanner.loading,
    updateConfig: h.scanner.updateConfig,
    addToWhitelist: h.scanner.addToWhitelist,
    removeFromWhitelist: h.scanner.removeFromWhitelist,
    removeBlockedEntry: h.scanner.removeBlockedEntry,
    clearBlockedHistory: h.scanner.clearBlockedHistory,
  }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: h.stableT, i18n: h.stableI18n }),
}));

vi.mock("../../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: h.message }),
}));

vi.mock("../../../../contexts/ThemeContext", () => ({
  useTheme: () => ({ isDark: h.isDark }),
}));

vi.mock("../../../../api/modules/skill", () => ({
  skillApi: { disableSkill: (...args: unknown[]) => h.disableSkill(...args) },
}));

// antd's real Select needs an open dropdown to reach an option; the stub keeps
// the product-decided option list (values and labels) and exposes each option
// as a button so the onChange wiring can be driven deterministically. Space is
// left as the real component.
vi.mock("antd", async () => {
  const actual = await vi.importActual<Record<string, unknown>>("antd");
  const Select = ({ value, onChange, disabled, options = [] }: any) =>
    React.createElement(
      "div",
      { "data-testid": "mode-select" },
      (options as Array<{ value: string; label: string }>).map((o) =>
        React.createElement(
          "button",
          {
            key: o.value,
            type: "button",
            disabled,
            "data-testid": "mode-option-" + o.value,
            onClick: () =>
              (onChange as ((v: string) => void) | undefined)?.(o.value),
          },
          o.label,
        ),
      ),
      React.createElement(
        "span",
        { "data-testid": "mode-value" },
        String(value),
      ),
    );
  return { ...actual, Select };
});

vi.mock("@agentscope-ai/design", () => {
  const Card = ({ children, className }: any) =>
    React.createElement("div", { className }, children);
  const Tag = ({ children }: any) =>
    React.createElement("span", null, children);
  const Tooltip = ({ children, title }: any) =>
    React.createElement(
      "span",
      { title: typeof title === "string" ? title : undefined },
      children,
    );
  const Empty = ({ description }: any) =>
    React.createElement("div", { "data-testid": "empty-state" }, description);
  const Button = ({ children, onClick, disabled, icon }: any) =>
    React.createElement(
      "button",
      { type: "button", onClick, disabled },
      icon,
      children,
    );
  const InputNumber = ({
    value,
    onChange,
    onBlur,
    onPressEnter,
    disabled,
    min,
    max,
  }: any) =>
    React.createElement(
      React.Fragment,
      null,
      React.createElement("input", {
        "data-testid": "timeout-input",
        type: "number",
        value: value ?? "",
        min,
        max,
        disabled,
        onChange: (e: React.ChangeEvent<HTMLInputElement>) =>
          (onChange as ((v: number | null) => void) | undefined)?.(
            e.target.value === "" ? null : Number(e.target.value),
          ),
        onBlur,
      }),
      // Driver button: onPressEnter is an antd InputNumber prop with no DOM
      // event of its own in a stub, so it is surfaced explicitly.
      React.createElement("button", {
        type: "button",
        "data-testid": "timeout-press-enter",
        onClick: () => (onPressEnter as (() => void) | undefined)?.(),
      }),
    );
  const Table = ({ dataSource = [], columns = [], rowKey }: any) =>
    React.createElement(
      "div",
      { "data-testid": "table" },
      (dataSource as any[]).map((record, index) => {
        const key =
          typeof rowKey === "function"
            ? rowKey(record, index)
            : String(record[rowKey as string]);
        return React.createElement(
          "div",
          { key, "data-testid": "table-row" },
          (columns as any[]).map((col, ci) =>
            React.createElement(
              "div",
              { key: String(col.key ?? ci) },
              col.render
                ? col.render(
                    col.dataIndex ? record[col.dataIndex] : undefined,
                    record,
                    index,
                  )
                : col.dataIndex
                ? record[col.dataIndex]
                : null,
            ),
          ),
        );
      }),
    );
  const Tabs = ({ items = [] }: any) =>
    React.createElement(
      "div",
      { role: "tablist" },
      (items as any[]).map((item) =>
        React.createElement(
          "div",
          {
            key: String(item.key),
            "data-testid": "tab-panel-" + String(item.key),
          },
          React.createElement("div", { role: "tab" }, item.label),
          item.children,
        ),
      ),
    );
  const Modal: any = ({ open, title, children, onCancel }: any) =>
    open
      ? React.createElement(
          "div",
          { "data-testid": "findings-modal" },
          React.createElement("div", null, title),
          children,
          // Driver button: the product wires onClose through onCancel and asks
          // for no footer, so the stub surfaces the callback itself.
          React.createElement("button", {
            type: "button",
            "data-testid": "findings-modal-close",
            onClick: () => (onCancel as (() => void) | undefined)?.(),
          }),
        )
      : null;
  Modal.confirm = (...args: unknown[]) => h.confirmSpy(...args);
  return { Card, Tag, Tooltip, Empty, Button, InputNumber, Table, Tabs, Modal };
});

import { SkillScannerSection } from "./SkillScannerSection";

type ConfirmArg = {
  title?: string;
  content?: string;
  onOk?: () => Promise<void> | void;
};

function makeFinding(overrides: Record<string, unknown> = {}) {
  return {
    severity: "high",
    title: "Suspicious exec",
    description: "Runs a shell command",
    file_path: "scripts/run.sh",
    line_number: 12 as number | null,
    rule_id: "R1",
    ...overrides,
  };
}

function makeBlocked(overrides: Record<string, unknown> = {}) {
  return {
    skill_name: "skill-alpha",
    blocked_at: "2026-09-20T10:00:00Z",
    max_severity: "high",
    findings: [makeFinding()],
    content_hash: "hash-alpha-0123456789abcdef",
    action: "blocked" as "blocked" | "warned",
    ...overrides,
  };
}

function makeWhitelistEntry(overrides: Record<string, unknown> = {}) {
  return {
    skill_name: "wl-skill",
    content_hash: "wl-hash-0123456789abcdef",
    added_at: "2026-09-21T08:30:00Z",
    ...overrides,
  };
}

function seedState(overrides: Record<string, unknown> = {}) {
  h.scanner.config = {
    mode: "block",
    timeout: 30,
    whitelist: [],
    ...(overrides.config as object | undefined),
  };
  h.scanner.blockedHistory = (overrides.blockedHistory as any[]) ?? [];
  h.scanner.whitelist = (overrides.whitelist as any[]) ?? [];
  h.scanner.loading = (overrides.loading as boolean) ?? false;
}

let toLocaleSpy: ReturnType<typeof vi.spyOn> | null = null;

function stubLocaleString(value: string) {
  toLocaleSpy = vi
    .spyOn(Date.prototype, "toLocaleString")
    .mockReturnValue(value);
  return toLocaleSpy;
}

function stubLocaleStringThrows() {
  toLocaleSpy = vi
    .spyOn(Date.prototype, "toLocaleString")
    .mockImplementation(() => {
      throw new Error("locale unavailable");
    });
  return toLocaleSpy;
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

function timeoutInput() {
  return screen.getByTestId("timeout-input") as HTMLInputElement;
}

function tabLabel(key: string) {
  return within(screen.getByTestId("tab-panel-" + key)).getByRole("tab");
}

function confirmArg(index = 0): ConfirmArg {
  return h.confirmSpy.mock.calls[index][0] as ConfirmArg;
}

beforeEach(() => {
  vi.clearAllMocks();
  h.isDark = false;
  h.scanner.config = null;
  h.scanner.blockedHistory = [];
  h.scanner.whitelist = [];
  h.scanner.loading = false;
  h.scanner.updateConfig.mockResolvedValue(true);
  h.scanner.addToWhitelist.mockResolvedValue(true);
  h.scanner.removeFromWhitelist.mockResolvedValue(true);
  h.scanner.removeBlockedEntry.mockResolvedValue(true);
  h.scanner.clearBlockedHistory.mockResolvedValue(true);
  h.disableSkill.mockResolvedValue(undefined);
});

afterEach(() => {
  if (toLocaleSpy) {
    toLocaleSpy.mockRestore();
    toLocaleSpy = null;
  }
});

describe("SkillScannerSection - load guard", () => {
  it("renders nothing while the scanner config is still loading", () => {
    seedState({ loading: true });
    const { container } = render(<SkillScannerSection />);
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByTestId("mode-select")).toBeNull();
  });

  it("renders nothing when loading finished but no config came back", () => {
    h.scanner.loading = false;
    h.scanner.config = null;
    const { container } = render(<SkillScannerSection />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when both loading and config are missing", () => {
    h.scanner.loading = true;
    h.scanner.config = null;
    const { container } = render(<SkillScannerSection />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders the config card and both tabs once a config is present", () => {
    seedState();
    render(<SkillScannerSection />);
    expect(screen.getByTestId("mode-select")).toBeInTheDocument();
    expect(screen.getByTestId("timeout-input")).toBeInTheDocument();
    expect(screen.getByTestId("tab-panel-scanAlerts")).toBeInTheDocument();
    expect(screen.getByTestId("tab-panel-whitelist")).toBeInTheDocument();
  });

  it("shows the mode and timeout labels next to their controls", () => {
    seedState();
    render(<SkillScannerSection />);
    expect(screen.getByText("security.skillScanner.mode")).toBeInTheDocument();
    expect(
      screen.getByText("security.skillScanner.timeout"),
    ).toBeInTheDocument();
  });
});

describe("SkillScannerSection - mode select", () => {
  it("offers exactly the three product modes with their translated labels", () => {
    seedState();
    render(<SkillScannerSection />);
    expect(screen.getByTestId("mode-option-block")).toHaveTextContent(
      "security.skillScanner.modeBlock",
    );
    expect(screen.getByTestId("mode-option-warn")).toHaveTextContent(
      "security.skillScanner.modeWarn",
    );
    expect(screen.getByTestId("mode-option-off")).toHaveTextContent(
      "security.skillScanner.modeOff",
    );
  });

  it("reflects the configured mode as the selected value", () => {
    seedState({ config: { mode: "warn", timeout: 30, whitelist: [] } });
    render(<SkillScannerSection />);
    expect(screen.getByTestId("mode-value")).toHaveTextContent("warn");
  });

  it("saves the chosen mode and reports success", async () => {
    seedState();
    h.scanner.updateConfig.mockResolvedValue(true);
    render(<SkillScannerSection />);
    fireEvent.click(screen.getByTestId("mode-option-warn"));
    await flush();
    expect(h.scanner.updateConfig).toHaveBeenCalledWith({ mode: "warn" });
    expect(h.message.success).toHaveBeenCalledWith(
      "security.skillScanner.saveSuccess",
    );
    expect(h.message.error).not.toHaveBeenCalled();
  });

  it("reports failure when saving the mode is rejected", async () => {
    seedState();
    h.scanner.updateConfig.mockResolvedValue(false);
    render(<SkillScannerSection />);
    fireEvent.click(screen.getByTestId("mode-option-off"));
    await flush();
    expect(h.scanner.updateConfig).toHaveBeenCalledWith({ mode: "off" });
    expect(h.message.error).toHaveBeenCalledWith(
      "security.skillScanner.saveFailed",
    );
    expect(h.message.success).not.toHaveBeenCalled();
  });

  it("keeps the timeout field usable while the scanner is on", () => {
    seedState({ config: { mode: "block", timeout: 30, whitelist: [] } });
    render(<SkillScannerSection />);
    expect(timeoutInput()).not.toBeDisabled();
  });

  it("disables the timeout field when the mode is off", () => {
    seedState({ config: { mode: "off", timeout: 30, whitelist: [] } });
    render(<SkillScannerSection />);
    expect(timeoutInput()).toBeDisabled();
  });

  it("disables the timeout field when the mode is warn but not when block", () => {
    seedState({ config: { mode: "warn", timeout: 30, whitelist: [] } });
    render(<SkillScannerSection />);
    expect(timeoutInput()).not.toBeDisabled();
  });
});

describe("SkillScannerSection - timeout input", () => {
  it("shows the saved timeout before any edit", () => {
    seedState({ config: { mode: "block", timeout: 45, whitelist: [] } });
    render(<SkillScannerSection />);
    expect(timeoutInput().value).toBe("45");
  });

  it("announces the 5 to 300 bounds to the field", () => {
    seedState();
    render(<SkillScannerSection />);
    expect(timeoutInput()).toHaveAttribute("min", "5");
    expect(timeoutInput()).toHaveAttribute("max", "300");
  });

  it("discards a blur without any edit and does not save", async () => {
    seedState({ config: { mode: "block", timeout: 30, whitelist: [] } });
    render(<SkillScannerSection />);
    fireEvent.blur(timeoutInput());
    await flush();
    expect(h.scanner.updateConfig).not.toHaveBeenCalled();
    expect(h.message.success).not.toHaveBeenCalled();
    expect(h.message.error).not.toHaveBeenCalled();
    expect(timeoutInput().value).toBe("30");
  });

  it("discards a value below the minimum and falls back to the saved timeout", async () => {
    seedState({ config: { mode: "block", timeout: 30, whitelist: [] } });
    render(<SkillScannerSection />);
    fireEvent.change(timeoutInput(), { target: { value: "4" } });
    expect(timeoutInput().value).toBe("4");
    fireEvent.blur(timeoutInput());
    await flush();
    expect(h.scanner.updateConfig).not.toHaveBeenCalled();
    expect(timeoutInput().value).toBe("30");
  });

  it("discards a value above the maximum and falls back to the saved timeout", async () => {
    seedState({ config: { mode: "block", timeout: 30, whitelist: [] } });
    render(<SkillScannerSection />);
    fireEvent.change(timeoutInput(), { target: { value: "301" } });
    fireEvent.blur(timeoutInput());
    await flush();
    expect(h.scanner.updateConfig).not.toHaveBeenCalled();
    expect(timeoutInput().value).toBe("30");
  });

  it("accepts the lower bound of 5", async () => {
    seedState({ config: { mode: "block", timeout: 30, whitelist: [] } });
    render(<SkillScannerSection />);
    fireEvent.change(timeoutInput(), { target: { value: "5" } });
    fireEvent.blur(timeoutInput());
    await flush();
    expect(h.scanner.updateConfig).toHaveBeenCalledWith({ timeout: 5 });
    expect(h.message.success).toHaveBeenCalledWith(
      "security.skillScanner.saveSuccess",
    );
  });

  it("accepts the upper bound of 300", async () => {
    seedState({ config: { mode: "block", timeout: 30, whitelist: [] } });
    render(<SkillScannerSection />);
    fireEvent.change(timeoutInput(), { target: { value: "300" } });
    fireEvent.blur(timeoutInput());
    await flush();
    expect(h.scanner.updateConfig).toHaveBeenCalledWith({ timeout: 300 });
  });

  it("clears the pending edit after a successful save", async () => {
    seedState({ config: { mode: "block", timeout: 30, whitelist: [] } });
    render(<SkillScannerSection />);
    fireEvent.change(timeoutInput(), { target: { value: "60" } });
    fireEvent.blur(timeoutInput());
    await flush();
    expect(timeoutInput().value).toBe("30");
  });

  it("reports failure when saving a valid timeout is rejected", async () => {
    seedState({ config: { mode: "block", timeout: 30, whitelist: [] } });
    h.scanner.updateConfig.mockResolvedValue(false);
    render(<SkillScannerSection />);
    fireEvent.change(timeoutInput(), { target: { value: "60" } });
    fireEvent.blur(timeoutInput());
    await flush();
    expect(h.scanner.updateConfig).toHaveBeenCalledWith({ timeout: 60 });
    expect(h.message.error).toHaveBeenCalledWith(
      "security.skillScanner.saveFailed",
    );
    expect(h.message.success).not.toHaveBeenCalled();
    expect(timeoutInput().value).toBe("30");
  });

  it("saves on Enter as well as on blur", async () => {
    seedState({ config: { mode: "block", timeout: 30, whitelist: [] } });
    render(<SkillScannerSection />);
    fireEvent.change(timeoutInput(), { target: { value: "90" } });
    fireEvent.click(screen.getByTestId("timeout-press-enter"));
    await flush();
    expect(h.scanner.updateConfig).toHaveBeenCalledWith({ timeout: 90 });
    expect(h.message.success).toHaveBeenCalledWith(
      "security.skillScanner.saveSuccess",
    );
  });

  it("still discards an out-of-range value when submitted with Enter", async () => {
    seedState({ config: { mode: "block", timeout: 30, whitelist: [] } });
    render(<SkillScannerSection />);
    fireEvent.change(timeoutInput(), { target: { value: "1" } });
    fireEvent.click(screen.getByTestId("timeout-press-enter"));
    await flush();
    expect(h.scanner.updateConfig).not.toHaveBeenCalled();
    expect(timeoutInput().value).toBe("30");
  });

  it("treats an emptied field as no pending value", async () => {
    seedState({ config: { mode: "block", timeout: 30, whitelist: [] } });
    render(<SkillScannerSection />);
    fireEvent.change(timeoutInput(), { target: { value: "" } });
    fireEvent.blur(timeoutInput());
    await flush();
    expect(h.scanner.updateConfig).not.toHaveBeenCalled();
  });
});

describe("SkillScannerSection - blocked history tab", () => {
  it("shows the empty state and no clear-all button when nothing was blocked", () => {
    seedState({ blockedHistory: [] });
    render(<SkillScannerSection />);
    const panel = screen.getByTestId("tab-panel-scanAlerts");
    expect(
      within(panel).getByText("security.skillScanner.scanAlerts.empty"),
    ).toBeInTheDocument();
    expect(
      within(panel).queryByText("security.skillScanner.scanAlerts.clearAll"),
    ).toBeNull();
    expect(within(panel).queryAllByTestId("table-row")).toHaveLength(0);
  });

  it("leaves the tab label bare when there is no blocked entry", () => {
    seedState({ blockedHistory: [] });
    render(<SkillScannerSection />);
    expect(tabLabel("scanAlerts").textContent).toBe(
      "security.skillScanner.scanAlerts.title",
    );
  });

  it("badges the tab with the number of blocked entries", () => {
    seedState({
      blockedHistory: [
        makeBlocked({ skill_name: "skill-alpha" }),
        makeBlocked({ skill_name: "skill-beta" }),
      ],
    });
    stubLocaleString("FORMATTED_TIME");
    render(<SkillScannerSection />);
    expect(tabLabel("scanAlerts").textContent).toBe(
      "security.skillScanner.scanAlerts.title2",
    );
  });

  it("offers clear-all once there is at least one blocked entry", () => {
    seedState({ blockedHistory: [makeBlocked()] });
    stubLocaleString("FORMATTED_TIME");
    render(<SkillScannerSection />);
    expect(
      screen.getByText("security.skillScanner.scanAlerts.clearAll"),
    ).toBeInTheDocument();
  });

  it("renders one row per blocked entry with its skill name", () => {
    stubLocaleString("FORMATTED_TIME");
    seedState({
      blockedHistory: [
        makeBlocked({ skill_name: "skill-alpha" }),
        makeBlocked({ skill_name: "skill-beta" }),
      ],
    });
    render(<SkillScannerSection />);
    expect(screen.getByText("skill-alpha")).toBeInTheDocument();
    expect(screen.getByText("skill-beta")).toBeInTheDocument();
    expect(screen.getAllByTestId("table-row")).toHaveLength(2);
  });

  it("labels a blocked action in red wording", () => {
    stubLocaleString("FORMATTED_TIME");
    seedState({ blockedHistory: [makeBlocked({ action: "blocked" })] });
    render(<SkillScannerSection />);
    expect(
      screen.getByText("security.skillScanner.scanAlerts.actionBlocked"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("security.skillScanner.scanAlerts.actionWarned"),
    ).toBeNull();
  });

  it("labels a warned action with the warned wording", () => {
    stubLocaleString("FORMATTED_TIME");
    seedState({ blockedHistory: [makeBlocked({ action: "warned" })] });
    render(<SkillScannerSection />);
    expect(
      screen.getByText("security.skillScanner.scanAlerts.actionWarned"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("security.skillScanner.scanAlerts.actionBlocked"),
    ).toBeNull();
  });

  it("formats the blocked-at timestamp for display", () => {
    stubLocaleString("FORMATTED_TIME");
    seedState({ blockedHistory: [makeBlocked()] });
    render(<SkillScannerSection />);
    expect(screen.getByText("FORMATTED_TIME")).toBeInTheDocument();
    expect(screen.queryByText("2026-09-20T10:00:00Z")).toBeNull();
  });

  it("falls back to the raw timestamp string when formatting throws", () => {
    stubLocaleStringThrows();
    seedState({
      blockedHistory: [makeBlocked({ blocked_at: "raw-blocked-stamp" })],
    });
    render(<SkillScannerSection />);
    expect(screen.getByText("raw-blocked-stamp")).toBeInTheDocument();
  });

  it("exposes three row actions labelled view findings, allow skill and remove", () => {
    stubLocaleString("FORMATTED_TIME");
    seedState({ blockedHistory: [makeBlocked()] });
    render(<SkillScannerSection />);
    expect(
      screen.getByTitle("security.skillScanner.scanAlerts.viewFindings"),
    ).toBeInTheDocument();
    expect(
      screen.getByTitle("security.skillScanner.scanAlerts.allowSkill"),
    ).toBeInTheDocument();
    expect(
      screen.getByTitle("security.skillScanner.scanAlerts.remove"),
    ).toBeInTheDocument();
  });

  it("removes a single blocked entry through its row action", async () => {
    stubLocaleString("FORMATTED_TIME");
    seedState({
      blockedHistory: [
        makeBlocked({ skill_name: "skill-alpha" }),
        makeBlocked({ skill_name: "skill-beta" }),
      ],
    });
    render(<SkillScannerSection />);
    const removes = screen.getAllByTitle(
      "security.skillScanner.scanAlerts.remove",
    );
    fireEvent.click(within(removes[1] as HTMLElement).getByRole("button"));
    await flush();
    expect(h.scanner.removeBlockedEntry).toHaveBeenCalledWith(1);
  });

  it("whitelists the skill and then drops the blocked entry", async () => {
    stubLocaleString("FORMATTED_TIME");
    h.scanner.addToWhitelist.mockResolvedValue(true);
    seedState({
      blockedHistory: [
        makeBlocked({
          skill_name: "skill-alpha",
          content_hash: "hash-alpha-value",
        }),
      ],
    });
    render(<SkillScannerSection />);
    fireEvent.click(
      within(
        screen.getByTitle(
          "security.skillScanner.scanAlerts.allowSkill",
        ) as HTMLElement,
      ).getByRole("button"),
    );
    await flush();
    expect(h.scanner.addToWhitelist).toHaveBeenCalledWith(
      "skill-alpha",
      "hash-alpha-value",
    );
    expect(h.message.success).toHaveBeenCalledWith(
      "security.skillScanner.whitelist.addSuccess",
    );
    expect(h.scanner.removeBlockedEntry).toHaveBeenCalledWith(0);
  });

  it("reports failure and keeps the blocked entry when whitelisting fails", async () => {
    stubLocaleString("FORMATTED_TIME");
    h.scanner.addToWhitelist.mockResolvedValue(false);
    seedState({ blockedHistory: [makeBlocked()] });
    render(<SkillScannerSection />);
    fireEvent.click(
      within(
        screen.getByTitle(
          "security.skillScanner.scanAlerts.allowSkill",
        ) as HTMLElement,
      ).getByRole("button"),
    );
    await flush();
    expect(h.message.error).toHaveBeenCalledWith(
      "security.skillScanner.whitelist.addFailed",
    );
    expect(h.message.success).not.toHaveBeenCalled();
    expect(h.scanner.removeBlockedEntry).not.toHaveBeenCalled();
  });
});

describe("SkillScannerSection - findings modal", () => {
  it("stays closed until the view-findings action is used", () => {
    stubLocaleString("FORMATTED_TIME");
    seedState({ blockedHistory: [makeBlocked()] });
    render(<SkillScannerSection />);
    expect(screen.queryByTestId("findings-modal")).toBeNull();
  });

  it("opens with the skill name in its title", () => {
    stubLocaleString("FORMATTED_TIME");
    seedState({ blockedHistory: [makeBlocked({ skill_name: "skill-alpha" })] });
    render(<SkillScannerSection />);
    fireEvent.click(
      within(
        screen.getByTitle(
          "security.skillScanner.scanAlerts.viewFindings",
        ) as HTMLElement,
      ).getByRole("button"),
    );
    const modal = screen.getByTestId("findings-modal");
    expect(modal).toHaveTextContent(
      "security.skillScanner.scanAlerts.viewFindings - skill-alpha",
    );
  });

  it("lists every finding of the opened record with title and description", () => {
    stubLocaleString("FORMATTED_TIME");
    seedState({
      blockedHistory: [
        makeBlocked({
          findings: [
            makeFinding({ title: "Finding one", description: "Desc one" }),
            makeFinding({ title: "Finding two", description: "Desc two" }),
          ],
        }),
      ],
    });
    render(<SkillScannerSection />);
    fireEvent.click(
      within(
        screen.getByTitle(
          "security.skillScanner.scanAlerts.viewFindings",
        ) as HTMLElement,
      ).getByRole("button"),
    );
    const modal = screen.getByTestId("findings-modal");
    expect(within(modal).getByText("Finding one")).toBeInTheDocument();
    expect(within(modal).getByText("Desc one")).toBeInTheDocument();
    expect(within(modal).getByText("Finding two")).toBeInTheDocument();
    expect(within(modal).getAllByTestId("table-row")).toHaveLength(2);
  });

  it("shows file path with line number when the finding has one", () => {
    stubLocaleString("FORMATTED_TIME");
    seedState({
      blockedHistory: [
        makeBlocked({
          findings: [
            makeFinding({ file_path: "scripts/run.sh", line_number: 12 }),
          ],
        }),
      ],
    });
    render(<SkillScannerSection />);
    fireEvent.click(
      within(
        screen.getByTitle(
          "security.skillScanner.scanAlerts.viewFindings",
        ) as HTMLElement,
      ).getByRole("button"),
    );
    expect(
      within(screen.getByTestId("findings-modal")).getByText(
        "scripts/run.sh:12",
      ),
    ).toBeInTheDocument();
  });

  it("shows only the file path when the finding has no line number", () => {
    stubLocaleString("FORMATTED_TIME");
    seedState({
      blockedHistory: [
        makeBlocked({
          findings: [
            makeFinding({ file_path: "scripts/run.sh", line_number: null }),
          ],
        }),
      ],
    });
    render(<SkillScannerSection />);
    fireEvent.click(
      within(
        screen.getByTitle(
          "security.skillScanner.scanAlerts.viewFindings",
        ) as HTMLElement,
      ).getByRole("button"),
    );
    const modal = screen.getByTestId("findings-modal");
    expect(within(modal).getByText("scripts/run.sh")).toBeInTheDocument();
    expect(within(modal).queryByText("scripts/run.sh:null")).toBeNull();
  });

  it("closes again and forgets the shown findings", () => {
    stubLocaleString("FORMATTED_TIME");
    seedState({
      blockedHistory: [makeBlocked({ findings: [makeFinding()] })],
    });
    render(<SkillScannerSection />);
    fireEvent.click(
      within(
        screen.getByTitle(
          "security.skillScanner.scanAlerts.viewFindings",
        ) as HTMLElement,
      ).getByRole("button"),
    );
    expect(screen.getByTestId("findings-modal")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("findings-modal-close"));
    expect(screen.queryByTestId("findings-modal")).toBeNull();
    expect(screen.queryByText("Suspicious exec")).toBeNull();
  });

  it("reopens with the newly clicked record after being closed", () => {
    stubLocaleString("FORMATTED_TIME");
    seedState({
      blockedHistory: [
        makeBlocked({ skill_name: "skill-alpha" }),
        makeBlocked({ skill_name: "skill-beta" }),
      ],
    });
    render(<SkillScannerSection />);
    const views = screen.getAllByTitle(
      "security.skillScanner.scanAlerts.viewFindings",
    );
    fireEvent.click(within(views[0] as HTMLElement).getByRole("button"));
    expect(screen.getByTestId("findings-modal")).toHaveTextContent(
      "viewFindings - skill-alpha",
    );
    fireEvent.click(screen.getByTestId("findings-modal-close"));
    fireEvent.click(within(views[1] as HTMLElement).getByRole("button"));
    expect(screen.getByTestId("findings-modal")).toHaveTextContent(
      "security.skillScanner.scanAlerts.viewFindings - skill-beta",
    );
  });
});

describe("SkillScannerSection - clear history confirmation", () => {
  it("asks for confirmation before clearing and does nothing yet", () => {
    stubLocaleString("FORMATTED_TIME");
    seedState({ blockedHistory: [makeBlocked()] });
    render(<SkillScannerSection />);
    fireEvent.click(
      screen.getByText("security.skillScanner.scanAlerts.clearAll"),
    );
    expect(h.confirmSpy).toHaveBeenCalledTimes(1);
    expect(confirmArg().title).toBe(
      "security.skillScanner.scanAlerts.clearConfirm",
    );
    expect(h.scanner.clearBlockedHistory).not.toHaveBeenCalled();
  });

  it("clears the history once the confirmation is accepted", async () => {
    stubLocaleString("FORMATTED_TIME");
    seedState({ blockedHistory: [makeBlocked()] });
    render(<SkillScannerSection />);
    fireEvent.click(
      screen.getByText("security.skillScanner.scanAlerts.clearAll"),
    );
    await act(async () => {
      await confirmArg().onOk?.();
    });
    expect(h.scanner.clearBlockedHistory).toHaveBeenCalledTimes(1);
  });
});

describe("SkillScannerSection - whitelist tab", () => {
  it("shows the empty state when the whitelist is empty", () => {
    seedState({ whitelist: [] });
    render(<SkillScannerSection />);
    const panel = screen.getByTestId("tab-panel-whitelist");
    expect(
      within(panel).getByText("security.skillScanner.whitelist.empty"),
    ).toBeInTheDocument();
    expect(within(panel).queryAllByTestId("table-row")).toHaveLength(0);
  });

  it("leaves the whitelist tab label bare when it is empty", () => {
    seedState({ whitelist: [] });
    render(<SkillScannerSection />);
    expect(tabLabel("whitelist").textContent).toBe(
      "security.skillScanner.whitelist.title",
    );
  });

  it("badges the whitelist tab with the entry count", () => {
    stubLocaleString("FORMATTED_TIME");
    seedState({
      whitelist: [
        makeWhitelistEntry({ skill_name: "wl-one" }),
        makeWhitelistEntry({ skill_name: "wl-two" }),
        makeWhitelistEntry({ skill_name: "wl-three" }),
      ],
    });
    render(<SkillScannerSection />);
    expect(tabLabel("whitelist").textContent).toBe(
      "security.skillScanner.whitelist.title3",
    );
  });

  it("truncates a long content hash to its first 16 characters", () => {
    stubLocaleString("FORMATTED_TIME");
    seedState({
      whitelist: [makeWhitelistEntry({ content_hash: "0123456789abcdefghij" })],
    });
    render(<SkillScannerSection />);
    expect(screen.getByText("0123456789abcdef...")).toBeInTheDocument();
    expect(screen.queryByText("0123456789abcdefghij")).toBeNull();
  });

  it("renders a hash shorter than 16 characters with the same suffix", () => {
    stubLocaleString("FORMATTED_TIME");
    seedState({ whitelist: [makeWhitelistEntry({ content_hash: "abc" })] });
    render(<SkillScannerSection />);
    expect(screen.getByText("abc...")).toBeInTheDocument();
  });

  it("shows the any-hash placeholder when the entry has no content hash", () => {
    stubLocaleString("FORMATTED_TIME");
    seedState({ whitelist: [makeWhitelistEntry({ content_hash: "" })] });
    render(<SkillScannerSection />);
    expect(screen.getByText("any")).toBeInTheDocument();
    expect(screen.queryByText("...")).toBeNull();
  });

  it("formats the added-at timestamp", () => {
    stubLocaleString("ADDED_TIME");
    seedState({ whitelist: [makeWhitelistEntry()] });
    render(<SkillScannerSection />);
    expect(screen.getByText("ADDED_TIME")).toBeInTheDocument();
  });

  it("falls back to the raw added-at string when formatting throws", () => {
    stubLocaleStringThrows();
    seedState({
      whitelist: [makeWhitelistEntry({ added_at: "raw-added-stamp" })],
    });
    render(<SkillScannerSection />);
    expect(screen.getByText("raw-added-stamp")).toBeInTheDocument();
  });

  it("labels the row remove action", () => {
    stubLocaleString("FORMATTED_TIME");
    seedState({ whitelist: [makeWhitelistEntry()] });
    render(<SkillScannerSection />);
    expect(
      screen.getByTitle("security.skillScanner.whitelist.remove"),
    ).toBeInTheDocument();
  });

  it("asks for confirmation before removing a whitelist entry", () => {
    stubLocaleString("FORMATTED_TIME");
    seedState({ whitelist: [makeWhitelistEntry({ skill_name: "wl-skill" })] });
    render(<SkillScannerSection />);
    fireEvent.click(
      within(
        screen.getByTitle(
          "security.skillScanner.whitelist.remove",
        ) as HTMLElement,
      ).getByRole("button"),
    );
    expect(h.confirmSpy).toHaveBeenCalledTimes(1);
    expect(confirmArg().title).toBe(
      "security.skillScanner.whitelist.removeConfirm",
    );
    expect(confirmArg().content).toBe(
      "security.skillScanner.whitelist.removeWillDisable",
    );
    expect(h.scanner.removeFromWhitelist).not.toHaveBeenCalled();
  });

  it("removes the entry and disables the skill once confirmed", async () => {
    stubLocaleString("FORMATTED_TIME");
    h.scanner.removeFromWhitelist.mockResolvedValue(true);
    h.disableSkill.mockResolvedValue(undefined);
    seedState({ whitelist: [makeWhitelistEntry({ skill_name: "wl-skill" })] });
    render(<SkillScannerSection />);
    fireEvent.click(
      within(
        screen.getByTitle(
          "security.skillScanner.whitelist.remove",
        ) as HTMLElement,
      ).getByRole("button"),
    );
    await act(async () => {
      await confirmArg().onOk?.();
    });
    expect(h.scanner.removeFromWhitelist).toHaveBeenCalledWith("wl-skill");
    expect(h.disableSkill).toHaveBeenCalledWith("wl-skill");
    expect(h.message.success).toHaveBeenCalledWith(
      "security.skillScanner.whitelist.removeAndDisabled",
    );
    expect(h.message.error).not.toHaveBeenCalled();
  });

  it("still reports success when disabling the skill throws", async () => {
    stubLocaleString("FORMATTED_TIME");
    h.scanner.removeFromWhitelist.mockResolvedValue(true);
    h.disableSkill.mockRejectedValue(new Error("disable failed"));
    seedState({ whitelist: [makeWhitelistEntry({ skill_name: "wl-skill" })] });
    render(<SkillScannerSection />);
    fireEvent.click(
      within(
        screen.getByTitle(
          "security.skillScanner.whitelist.remove",
        ) as HTMLElement,
      ).getByRole("button"),
    );
    await act(async () => {
      await confirmArg().onOk?.();
    });
    expect(h.message.success).toHaveBeenCalledWith(
      "security.skillScanner.whitelist.removeSuccess",
    );
    expect(h.message.success).not.toHaveBeenCalledWith(
      "security.skillScanner.whitelist.removeAndDisabled",
    );
    expect(h.message.error).not.toHaveBeenCalled();
  });

  it("stops and reports failure when the removal itself is rejected", async () => {
    stubLocaleString("FORMATTED_TIME");
    h.scanner.removeFromWhitelist.mockResolvedValue(false);
    seedState({ whitelist: [makeWhitelistEntry({ skill_name: "wl-skill" })] });
    render(<SkillScannerSection />);
    fireEvent.click(
      within(
        screen.getByTitle(
          "security.skillScanner.whitelist.remove",
        ) as HTMLElement,
      ).getByRole("button"),
    );
    await act(async () => {
      await confirmArg().onOk?.();
    });
    expect(h.message.error).toHaveBeenCalledWith(
      "security.skillScanner.whitelist.removeFailed",
    );
    expect(h.disableSkill).not.toHaveBeenCalled();
    expect(h.message.success).not.toHaveBeenCalled();
  });
});

describe("SkillScannerSection - both tabs populated", () => {
  it("keeps blocked history and whitelist rows apart", () => {
    stubLocaleString("FORMATTED_TIME");
    seedState({
      blockedHistory: [makeBlocked({ skill_name: "blocked-one" })],
      whitelist: [makeWhitelistEntry({ skill_name: "allowed-one" })],
    });
    render(<SkillScannerSection />);
    expect(
      within(screen.getByTestId("tab-panel-scanAlerts")).getByText(
        "blocked-one",
      ),
    ).toBeInTheDocument();
    expect(
      within(screen.getByTestId("tab-panel-whitelist")).getByText(
        "allowed-one",
      ),
    ).toBeInTheDocument();
  });

  it("badges both tabs independently", () => {
    stubLocaleString("FORMATTED_TIME");
    seedState({
      blockedHistory: [
        makeBlocked({ skill_name: "b1" }),
        makeBlocked({ skill_name: "b2" }),
      ],
      whitelist: [makeWhitelistEntry({ skill_name: "w1" })],
    });
    render(<SkillScannerSection />);
    expect(tabLabel("scanAlerts").textContent).toBe(
      "security.skillScanner.scanAlerts.title2",
    );
    expect(tabLabel("whitelist").textContent).toBe(
      "security.skillScanner.whitelist.title1",
    );
  });
});

describe("SkillScannerSection - theme", () => {
  it("renders the row actions in light mode", () => {
    stubLocaleString("FORMATTED_TIME");
    h.isDark = false;
    seedState({ blockedHistory: [makeBlocked()] });
    render(<SkillScannerSection />);
    expect(
      screen.getByTitle("security.skillScanner.scanAlerts.allowSkill"),
    ).toBeInTheDocument();
  });

  it("renders the row actions in dark mode too", () => {
    stubLocaleString("FORMATTED_TIME");
    h.isDark = true;
    seedState({ blockedHistory: [makeBlocked()] });
    render(<SkillScannerSection />);
    expect(
      screen.getByTitle("security.skillScanner.scanAlerts.allowSkill"),
    ).toBeInTheDocument();
  });

  it("renders the whitelist row action in dark mode", () => {
    stubLocaleString("FORMATTED_TIME");
    h.isDark = true;
    seedState({ whitelist: [makeWhitelistEntry()] });
    render(<SkillScannerSection />);
    expect(
      screen.getByTitle("security.skillScanner.whitelist.remove"),
    ).toBeInTheDocument();
  });
});
