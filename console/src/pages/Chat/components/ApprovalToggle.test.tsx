import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { message } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { migrateChatSessionPreferences } from "../chatSessionPreferences";
import { renderWithProviders } from "@/test/common_setup";
import ApprovalLevelToggle from "./ApprovalLevelToggle";
import HarnessApprovalToggle from "./HarnessApprovalToggle";

const { mockUseIsMobile, mockGetApprovalLevel, mockSetApprovalLevel } =
  vi.hoisted(() => ({
    mockUseIsMobile: vi.fn(() => false),
    mockGetApprovalLevel: vi.fn(
      async () =>
        ({
          chat_id: "",
          approval_level: null as string | null,
        }) as { chat_id: string; approval_level: string | null },
    ),
    mockSetApprovalLevel: vi.fn(
      async () =>
        ({
          chat_id: "",
          approval_level: null as string | null,
        }) as { chat_id: string; approval_level: string | null },
    ),
  }));

vi.mock("../../../hooks/useIsMobile", () => ({
  useIsMobile: mockUseIsMobile,
}));

vi.mock("../../../api/modules/chat", () => ({
  chatApi: {
    getApprovalLevel: mockGetApprovalLevel,
    setApprovalLevel: mockSetApprovalLevel,
  },
}));

describe("compact approval controls", () => {
  beforeEach(() => {
    localStorage.clear();
    mockUseIsMobile.mockReturnValue(false);
    mockGetApprovalLevel
      .mockReset()
      .mockResolvedValue({ chat_id: "", approval_level: null });
    mockSetApprovalLevel
      .mockReset()
      .mockResolvedValue({ chat_id: "", approval_level: null });
  });

  it("keeps draft preferences isolated when navigating to another Agent or existing Chat", () => {
    const changed = vi.fn();
    localStorage.setItem("approval_level-draft:a", "OFF");
    localStorage.setItem(
      "approval_level-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
      "STRICT",
    );
    const props = {
      runningConfigApprovalLevel: "AUTO" as const,
      onChange: changed,
    };
    const view = renderWithProviders(
      <ApprovalLevelToggle {...props} sessionId="draft:a" />,
    );
    expect(changed).toHaveBeenLastCalledWith("OFF");
    view.rerender(
      <ApprovalLevelToggle
        {...props}
        sessionId="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
      />,
    );
    expect(changed).toHaveBeenLastCalledWith("STRICT");
    expect(localStorage.getItem("approval_level-draft:a")).toBe("OFF");
    view.rerender(<ApprovalLevelToggle {...props} sessionId="draft:b" />);
    expect(changed).toHaveBeenLastCalledWith(null);
  });

  it("prefers the server-stored level over the local cache", async () => {
    const realChat = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb";
    localStorage.setItem(`approval_level-${realChat}`, "SMART");
    mockGetApprovalLevel.mockResolvedValueOnce({
      chat_id: realChat,
      approval_level: "OFF",
    });
    renderWithProviders(
      <ApprovalLevelToggle
        runningConfigApprovalLevel="AUTO"
        onChange={vi.fn()}
        sessionId={realChat}
      />,
    );
    // The test i18n bundle lacks the level-name keys, so t() falls back
    // to the level value passed as default.
    await waitFor(() =>
      expect(
        screen.getByRole("button", {
          name: "agentConfig.toolExecutionLevelTitle",
        }),
      ).toHaveTextContent("OFF"),
    );
    expect(mockSetApprovalLevel).not.toHaveBeenCalled();
  });

  it("adopts a local preference when the server has no persisted level", async () => {
    const realChat = "cccccccc-cccc-cccc-cccc-cccccccccccc";
    localStorage.setItem(`approval_level-${realChat}`, "STRICT");
    mockGetApprovalLevel.mockResolvedValueOnce({
      chat_id: realChat,
      approval_level: null,
    });
    const changed = vi.fn();
    renderWithProviders(
      <ApprovalLevelToggle
        runningConfigApprovalLevel="AUTO"
        onChange={changed}
        sessionId={realChat}
      />,
    );
    await waitFor(() =>
      expect(mockSetApprovalLevel).toHaveBeenCalledWith(
        realChat,
        "STRICT",
        undefined,
      ),
    );
    // The adopted level stays displayed instead of snapping to the default.
    expect(changed).toHaveBeenLastCalledWith("STRICT");
    expect(
      screen.getByRole("button", {
        name: "agentConfig.toolExecutionLevelTitle",
      }),
    ).toHaveTextContent("STRICT");
  });

  it("rolls back and alerts when the server rejects a level change", async () => {
    const realChat = "dddddddd-dddd-dddd-dddd-dddddddddddd";
    const messageSpy = vi
      .spyOn(message, "error")
      .mockImplementation(() => undefined as never);
    mockGetApprovalLevel.mockResolvedValueOnce({
      chat_id: realChat,
      approval_level: null,
    });
    // Hold the PUT open so the optimistic flip is observable, then reject.
    let rejectPut: (error: Error) => void = () => {};
    mockSetApprovalLevel.mockImplementationOnce(
      () =>
        new Promise((_resolve, reject) => {
          rejectPut = reject;
        }),
    );
    const user = userEvent.setup();
    renderWithProviders(
      <ApprovalLevelToggle
        runningConfigApprovalLevel="AUTO"
        onChange={vi.fn()}
        sessionId={realChat}
      />,
    );
    const trigger = screen.getByRole("button", {
      name: "agentConfig.toolExecutionLevelTitle",
    });
    await user.click(trigger);
    await user.click(await screen.findByText("STRICT"));

    // Optimistic flip while the write is in flight...
    await waitFor(() => expect(trigger).toHaveTextContent("STRICT"));
    expect(mockSetApprovalLevel).toHaveBeenCalledWith(
      realChat,
      "STRICT",
      undefined,
    );
    // ...and the rejected write must roll the UI back to the agent
    // default with an error toast, not silently keep an unsaved level.
    rejectPut(new Error("boom"));
    await waitFor(() => expect(messageSpy).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(trigger).toHaveTextContent("AUTO"));
    expect(messageSpy).toHaveBeenCalledWith(
      "Failed to save the approval level; reverted to the previous one.",
    );
    messageSpy.mockRestore();
  });

  it("moves both approval settings only on confirmed creation and preserves destination overrides", () => {
    localStorage.setItem("approval_level-draft:a", "SMART");
    localStorage.setItem("approval_level-draft:b", "STRICT");
    localStorage.setItem("harness-approval-codex-draft:a", "manual");
    migrateChatSessionPreferences("draft:a", "created-chat", "codex");
    expect(localStorage.getItem("approval_level-created-chat")).toBe("SMART");
    expect(localStorage.getItem("harness-approval-codex-created-chat")).toBe(
      "manual",
    );
    expect(localStorage.getItem("approval_level-draft:a")).toBeNull();
    expect(localStorage.getItem("approval_level-draft:b")).toBe("STRICT");
    localStorage.setItem("approval_level-draft:a", "OFF");
    migrateChatSessionPreferences("draft:a", "created-chat", "codex");
    expect(localStorage.getItem("approval_level-created-chat")).toBe("SMART");
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
