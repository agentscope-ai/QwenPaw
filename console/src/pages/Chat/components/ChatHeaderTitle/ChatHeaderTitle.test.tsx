import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/common_setup";
import ChatHeaderTitle from "./index";
import styles from "./index.module.less";
import { useAgentStore } from "@/stores/agentStore";
import { useAdvisorModeStore } from "@/stores/advisorModeStore";

const { mockUseChatAnywhereSessionsState } = vi.hoisted(() => ({
  mockUseChatAnywhereSessionsState: vi.fn(),
}));

vi.mock("@agentscope-ai/chat", () => ({
  useChatAnywhereSessionsState: mockUseChatAnywhereSessionsState,
}));

describe("ChatHeaderTitle", () => {
  it("displays the current session name", () => {
    mockUseChatAnywhereSessionsState.mockReturnValue({
      sessions: [{ id: "sess-1", name: "My Chat" }],
      currentSessionId: "sess-1",
    });
    renderWithProviders(<ChatHeaderTitle />);
    expect(screen.getAllByText("My Chat")[0]).toBeInTheDocument();
  });

  it('displays "New Chat" when session name is empty', () => {
    mockUseChatAnywhereSessionsState.mockReturnValue({
      sessions: [{ id: "sess-1", name: "" }],
      currentSessionId: "sess-1",
    });
    renderWithProviders(<ChatHeaderTitle />);
    expect(screen.getAllByText("New Chat")[0]).toBeInTheDocument();
  });

  it('displays "New Chat" when no matching session exists', () => {
    mockUseChatAnywhereSessionsState.mockReturnValue({
      sessions: [],
      currentSessionId: null,
    });
    renderWithProviders(<ChatHeaderTitle />);
    expect(screen.getAllByText("New Chat")[0]).toBeInTheDocument();
  });

  it("displays the correct session name after switching currentSessionId", () => {
    mockUseChatAnywhereSessionsState.mockReturnValue({
      sessions: [
        { id: "sess-1", name: "Chat A" },
        { id: "sess-2", name: "Chat B" },
      ],
      currentSessionId: "sess-2",
    });
    renderWithProviders(<ChatHeaderTitle />);
    expect(screen.getAllByText("Chat B")[0]).toBeInTheDocument();
    expect(screen.queryByText("Chat A")).not.toBeInTheDocument();
  });

  it("keeps a long session list inside the bounded dropdown", async () => {
    const user = userEvent.setup();
    mockUseChatAnywhereSessionsState.mockReturnValue({
      sessions: Array.from({ length: 30 }, (_, index) => ({
        id: `sess-${index}`,
        name: `Chat ${index}`,
      })),
      currentSessionId: "sess-0",
      setCurrentSessionId: vi.fn(),
    });

    renderWithProviders(<ChatHeaderTitle />);
    const trigger = screen.getByRole("button", { name: "Chat 0" });
    await user.click(trigger);

    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(
      (await screen.findByRole("menu")).closest(
        ".qwenpaw-dropdown, .ant-dropdown",
      ),
    ).toHaveClass(styles.sessionDropdown);
  });

  it("shows the Advisor badge when Advisor Mode is on for the agent", () => {
    mockUseChatAnywhereSessionsState.mockReturnValue({
      sessions: [{ id: "sess-1", name: "My Chat" }],
      currentSessionId: "sess-1",
    });
    useAgentStore.setState({ selectedAgent: "a1", agents: [] });
    useAdvisorModeStore.getState().setAdvisorMode("a1", {
      enabled: true,
      plan_enabled: true,
      followup_enabled: true,
      on_demand_enabled: true,
      teacher_model: null,
      student_model: null,
    });
    renderWithProviders(<ChatHeaderTitle />);
    expect(screen.getByTestId("advisor-mode-badge")).toBeInTheDocument();
  });

  it("hides the Advisor badge when Advisor Mode is off", () => {
    mockUseChatAnywhereSessionsState.mockReturnValue({
      sessions: [{ id: "sess-1", name: "My Chat" }],
      currentSessionId: "sess-1",
    });
    useAgentStore.setState({ selectedAgent: "a1", agents: [] });
    useAdvisorModeStore.getState().setAdvisorMode("a1", {
      enabled: false,
      plan_enabled: true,
      followup_enabled: true,
      on_demand_enabled: true,
      teacher_model: null,
      student_model: null,
    });
    renderWithProviders(<ChatHeaderTitle />);
    expect(screen.queryByTestId("advisor-mode-badge")).toBeNull();
  });
});
