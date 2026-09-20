import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/common_setup";
import ChatHeaderTitle from "./index";
import styles from "./index.module.less";

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
});
