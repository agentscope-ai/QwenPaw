import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "@/test/common_setup";
import ChatHeaderTitle from "./index";

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
    expect(screen.getByText("My Chat")).toBeInTheDocument();
  });

  it('displays "New Chat" when session name is empty', () => {
    mockUseChatAnywhereSessionsState.mockReturnValue({
      sessions: [{ id: "sess-1", name: "" }],
      currentSessionId: "sess-1",
    });
    renderWithProviders(<ChatHeaderTitle />);
    expect(screen.getByText("New Chat")).toBeInTheDocument();
  });

  it('displays "New Chat" when no matching session exists', () => {
    mockUseChatAnywhereSessionsState.mockReturnValue({
      sessions: [],
      currentSessionId: null,
    });
    renderWithProviders(<ChatHeaderTitle />);
    expect(screen.getByText("New Chat")).toBeInTheDocument();
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
    expect(screen.getByText("Chat B")).toBeInTheDocument();
    expect(screen.queryByText("Chat A")).not.toBeInTheDocument();
  });
});
