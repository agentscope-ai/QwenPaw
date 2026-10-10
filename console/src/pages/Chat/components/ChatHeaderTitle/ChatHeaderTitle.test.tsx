import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/common_setup";
import ChatHeaderTitle from "./index";
import styles from "./index.module.less";

const {
  mockUseChatAnywhereSessionsState,
  updateChat,
  getSessionList,
  syncSessions,
} = vi.hoisted(() => ({
  updateChat: vi.fn(),
  getSessionList: vi.fn(),
  syncSessions: vi.fn(),
  mockUseChatAnywhereSessionsState: vi.fn(),
}));

vi.mock("@agentscope-ai/chat", () => ({
  useChatAnywhereSessionsState: mockUseChatAnywhereSessionsState,
}));

vi.mock("../../../../api/modules/chat", () => ({ chatApi: { updateChat } }));
vi.mock("../../sessionApi", () => ({
  default: {
    getActiveOwner: () => "default",
    isActiveOwner: () => true,
    getSessionList,
    getEffectiveSessionId: (id: string) => id,
  },
}));
vi.mock("../../../../stores/sessionListStore", () => ({
  syncSessionsGlobal: syncSessions,
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
    const trigger = screen.getByRole("button", { name: "chat.switchSession" });
    await user.click(trigger);

    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(
      (await screen.findByRole("menu")).closest(
        ".qwenpaw-dropdown, .ant-dropdown",
      ),
    ).toHaveClass(styles.sessionDropdown);
  });
});

describe("Conversation title editing", () => {
  it("saves a trimmed title to the backend and synchronizes the sidebar", async () => {
    const user = userEvent.setup();
    const list = [{ id: "chat-rename", name: "New title" }];
    updateChat.mockResolvedValue({});
    getSessionList.mockResolvedValue(list);
    mockUseChatAnywhereSessionsState.mockReturnValue({
      sessions: [
        {
          id: "chat-rename",
          name: "Old title",
          updatedAt: "2026-09-22T08:00:00Z",
        },
      ],
      currentSessionId: "chat-rename",
    });
    renderWithProviders(<ChatHeaderTitle />);
    await user.click(screen.getByRole("button", { name: "Old title" }));
    const input = screen.getByRole("textbox", {
      name: "chat.contextMenu.rename",
    });
    await user.clear(input);
    await user.type(input, " New title {Enter}");
    expect(updateChat).toHaveBeenCalledWith("chat-rename", {
      name: "New title",
    });
    expect(syncSessions).toHaveBeenCalledWith(list);
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });
  it("cancels with Escape without saving", async () => {
    const user = userEvent.setup();
    updateChat.mockClear();
    mockUseChatAnywhereSessionsState.mockReturnValue({
      sessions: [{ id: "chat-cancel", name: "Keep name" }],
      currentSessionId: "chat-cancel",
    });
    renderWithProviders(<ChatHeaderTitle />);
    await user.click(screen.getByRole("button", { name: "Keep name" }));
    await user.type(screen.getByRole("textbox"), "changed{Escape}");
    expect(updateChat).not.toHaveBeenCalled();
    expect(
      screen.getByRole("button", { name: "Keep name" }),
    ).toBeInTheDocument();
  });
});

it("distinguishes duplicate titles with activity time and channel", async () => {
  mockUseChatAnywhereSessionsState.mockReturnValue({
    sessions: [
      {
        id: "sess-1",
        name: "Hi",
        updatedAt: "2026-09-21T10:15:00Z",
        channel: "console",
      },
      {
        id: "sess-2",
        name: "Hi",
        updatedAt: "2026-09-22T11:30:00Z",
        channel: "telegram",
      },
    ],
    currentSessionId: "sess-1",
  });
  renderWithProviders(<ChatHeaderTitle />);
  await userEvent.click(
    screen.getByRole("button", { name: "chat.switchSession" }),
  );
  const menu = await screen.findByRole("menu");
  expect(
    [...menu.querySelectorAll("time")].map((time) => time.dateTime),
  ).toEqual(["2026-09-21T10:15:00.000Z", "2026-09-22T11:30:00.000Z"]);
  expect(menu).toHaveTextContent("console");
  expect(menu).toHaveTextContent("telegram");
});
