import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/common_setup";
import "@/i18n";
import ChatHeaderTitle from "./index";
import styles from "./index.module.less";

const { mockUseChatAnywhereSessionsState } = vi.hoisted(() => ({
  mockUseChatAnywhereSessionsState: vi.fn(),
}));

vi.mock("@agentscope-ai/chat", () => ({
  useChatAnywhereSessionsState: mockUseChatAnywhereSessionsState,
}));

describe("ChatHeaderTitle", () => {
  it("keeps the new-chat title when SDK selection still points to old history", () => {
    mockUseChatAnywhereSessionsState.mockReturnValue({
      sessions: [{ id: "old", name: "Voice Chat" }],
      currentSessionId: "old",
    });
    renderWithProviders(<ChatHeaderTitle />, { initialEntries: ["/chat"] });
    expect(screen.queryAllByText("Voice Chat")).toHaveLength(0);
    expect(screen.getAllByText("New Chat")[0]).toBeInTheDocument();
  });

  it("does not call a routed Chat new while the session list is pending", () => {
    mockUseChatAnywhereSessionsState.mockReturnValue({
      sessions: [],
      currentSessionId: null,
    });
    renderWithProviders(<ChatHeaderTitle />, {
      initialEntries: ["/chat/existing"],
    });
    expect(screen.queryAllByText("New Chat")).toHaveLength(0);
    expect(screen.getAllByText("Loading...")[0]).toBeInTheDocument();
  });

  it("uses the routed session title before SDK selection catches up", () => {
    mockUseChatAnywhereSessionsState.mockReturnValue({
      sessions: [
        { id: "old", name: "Previous" },
        { id: "local", realId: "target", name: "Target Chat" },
      ],
      currentSessionId: "old",
    });
    renderWithProviders(<ChatHeaderTitle />, {
      initialEntries: ["/chat/target"],
    });
    expect(screen.getAllByText("Target Chat")[0]).toBeInTheDocument();
    expect(screen.queryByText("Previous")).not.toBeInTheDocument();
  });

  it("displays the current session name", () => {
    mockUseChatAnywhereSessionsState.mockReturnValue({
      sessions: [{ id: "sess-1", name: "My Chat" }],
      currentSessionId: "sess-1",
    });
    renderWithProviders(<ChatHeaderTitle />, {
      initialEntries: ["/chat/sess-1"],
    });
    expect(screen.getAllByText("My Chat")[0]).toBeInTheDocument();
  });

  it('displays "New Chat" when session name is empty', () => {
    mockUseChatAnywhereSessionsState.mockReturnValue({
      sessions: [{ id: "sess-1", name: "" }],
      currentSessionId: "sess-1",
    });
    renderWithProviders(<ChatHeaderTitle />, {
      initialEntries: ["/chat/sess-1"],
    });
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

  it("displays the correct session name after switching the route", () => {
    mockUseChatAnywhereSessionsState.mockReturnValue({
      sessions: [
        { id: "sess-1", name: "Chat A" },
        { id: "sess-2", name: "Chat B" },
      ],
      currentSessionId: "sess-2",
    });
    renderWithProviders(<ChatHeaderTitle />, {
      initialEntries: ["/chat/sess-2"],
    });
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
