import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/common_setup";
import ApprovalLevelToggle from "./ApprovalLevelToggle";
import HarnessApprovalToggle from "./HarnessApprovalToggle";

const { mockUseIsMobile } = vi.hoisted(() => ({
  mockUseIsMobile: vi.fn(() => false),
}));

vi.mock("../../../hooks/useIsMobile", () => ({
  useIsMobile: mockUseIsMobile,
}));

describe("compact approval controls", () => {
  beforeEach(() => {
    localStorage.clear();
    mockUseIsMobile.mockReturnValue(false);
  });

  it("renders only the QwenPaw approval icon", () => {
    const { container } = renderWithProviders(
      <ApprovalLevelToggle
        compact
        onChange={vi.fn()}
        runningConfigApprovalLevel="AUTO"
        sessionId="compact-test"
      />,
    );

    const trigger = container.querySelector<HTMLElement>("[aria-label]");
    expect(trigger).not.toBeNull();
    expect(trigger?.textContent).toBe("");
    expect(trigger?.querySelectorAll("svg")).toHaveLength(1);
  });

  it("renders only the harness approval icon", () => {
    const { container } = renderWithProviders(
      <HarnessApprovalToggle
        backend="codex"
        compact
        onChange={vi.fn()}
        presets={[
          {
            id: "auto",
            name: "Automatic",
            description: "Automatic approval",
            settings: {},
          },
        ]}
        sessionId="compact-test"
      />,
    );

    const trigger = container.querySelector<HTMLElement>("[aria-label]");
    expect(trigger).not.toBeNull();
    expect(trigger?.textContent).toBe("");
    expect(trigger?.querySelectorAll("svg")).toHaveLength(1);
  });

  it("uses a bottom drawer for QwenPaw approval on mobile", async () => {
    mockUseIsMobile.mockReturnValue(true);
    const user = userEvent.setup();
    renderWithProviders(
      <ApprovalLevelToggle
        compact
        onChange={vi.fn()}
        runningConfigApprovalLevel="AUTO"
        sessionId="mobile-test"
      />,
    );

    const trigger = screen.getByRole("button", {
      name: "agentConfig.toolExecutionLevelTitle",
    });
    await user.click(trigger);

    expect(
      await screen.findByRole("dialog", {
        name: "agentConfig.toolExecutionLevelTitle",
      }),
    ).toBeInTheDocument();
    expect(document.querySelector(".ant-dropdown")).not.toBeInTheDocument();

    const offOption = document.querySelector<HTMLElement>('[data-level="OFF"]');
    expect(offOption).not.toBeNull();
    await user.click(offOption!);

    expect(localStorage.getItem("approval_level-mobile-test")).toBe("OFF");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("shows only the approval mode title in the tooltip", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <ApprovalLevelToggle
        onChange={vi.fn()}
        runningConfigApprovalLevel="AUTO"
        sessionId="tooltip-test"
      />,
    );

    const trigger = screen.getByRole("button", {
      name: "agentConfig.toolExecutionLevelTitle",
    });
    await user.hover(trigger);

    expect(
      await screen.findByText("agentConfig.toolExecutionLevelTooltip"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("agentConfig.toolExecutionLevelTitle"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("agentConfig.toolExecutionLevel.autoDesc"),
    ).not.toBeInTheDocument();
  });

  it("uses a bottom drawer for harness approval on mobile", async () => {
    mockUseIsMobile.mockReturnValue(true);
    const user = userEvent.setup();
    renderWithProviders(
      <HarnessApprovalToggle
        backend="codex"
        compact
        onChange={vi.fn()}
        presets={[
          {
            id: "auto",
            name: "Automatic",
            description: "Automatic approval",
            settings: {},
          },
          {
            id: "manual",
            name: "Manual",
            description: "Ask before running tools",
            settings: { ask: true },
          },
        ]}
        sessionId="mobile-test"
      />,
    );

    const trigger = screen.getByRole("button", {
      name: "agent.backend.approvalMode",
    });
    await user.click(trigger);

    expect(
      await screen.findByRole("dialog", {
        name: "agent.backend.approvalMode",
      }),
    ).toBeInTheDocument();
    expect(document.querySelector(".ant-dropdown")).not.toBeInTheDocument();

    const manualOption = document.querySelector<HTMLElement>(
      '[data-preset-id="manual"]',
    );
    expect(manualOption).not.toBeNull();
    await user.click(manualOption!);

    expect(localStorage.getItem("harness-approval-codex-mobile-test")).toBe(
      "manual",
    );
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });
});
