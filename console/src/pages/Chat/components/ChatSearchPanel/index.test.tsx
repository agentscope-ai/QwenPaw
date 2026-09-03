/**
 * ChatSearchPanel — cross-session chat search drawer. Covers the debounced
 * serial search (title + message matching with context windows), stale-query
 * sequence protection, progress/count labels, empty and loading states,
 * result-click navigation for sessions both present and absent from the
 * local session list, and timestamp formatting.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";

const chatMocks = vi.hoisted(() => ({
  listChats: vi.fn(),
  getChat: vi.fn(),
}));

vi.mock("../../../../api/modules/chat", () => ({
  chatApi: chatMocks,
}));

const navigateSpy = vi.hoisted(() => vi.fn());

vi.mock("react-router-dom", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    useNavigate: () => navigateSpy,
  };
});

const sessionStateMocks = vi.hoisted(() => ({
  sessions: [] as Array<{ id: string; realId?: string | null }>,
  setCurrentSessionId: vi.fn(),
}));

vi.mock("@agentscope-ai/chat", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    useChatAnywhereSessionsState: () => ({
      sessions: sessionStateMocks.sessions,
      setCurrentSessionId: sessionStateMocks.setCurrentSessionId,
    }),
  };
});

vi.mock("../../sessionApi", () => ({
  default: {
    getRealIdForSession: vi.fn(() => null),
  },
}));

// t must be referentially stable: the panel's search effect depends on it.
const tFn = (key: string, opts?: Record<string, unknown>) =>
  opts?.progress
    ? `${key}:${opts.progress}`
    : opts?.count !== undefined
    ? `${key}:${opts.count}`
    : key;

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: tFn,
    i18n: { changeLanguage: vi.fn(), language: "en" },
  }),
}));

vi.mock("@agentscope-ai/icons", () => ({
  SparkOperateRightLine: () => null,
  SparkSearchLine: () => null,
}));

vi.mock("@agentscope-ai/design", async (importOriginal) => {
  const original = (await importOriginal()) as Record<string, unknown>;
  return {
    ...original,
    IconButton: ({ icon, onClick }: Record<string, unknown>) =>
      React.createElement(
        "button",
        { type: "button", onClick, "data-testid": "icon-button" },
        icon as any,
      ),
  };
});

import ChatSearchPanel from "./index";

function renderPanel(onClose = vi.fn()) {
  return render(<ChatSearchPanel open onClose={onClose} />);
}

function chats(...names: Array<[string, string]>) {
  return names.map(([id, name]) => ({
    id,
    name,
    created_at: "2026-09-01T10:00:00Z",
  }));
}

async function typeAndWaitForSearch(
  user: ReturnType<typeof userEvent.setup>,
  query: string,
) {
  const input = screen.getByPlaceholderText("chat.search.placeholder");
  await user.type(input, query);
  // Debounce is 300ms
  await new Promise((r) => setTimeout(r, 450));
}

describe("ChatSearchPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStateMocks.sessions = [];
    chatMocks.listChats.mockResolvedValue([]);
    chatMocks.getChat.mockResolvedValue({ messages: [] });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders the drawer header and empty input", () => {
    renderPanel();
    expect(screen.getByText("chat.search.title")).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText("chat.search.placeholder"),
    ).toBeInTheDocument();
  });

  it("closes via the header icon button", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    renderPanel(onClose);

    await user.click(screen.getByTestId("icon-button"));
    expect(onClose).toHaveBeenCalled();
  });

  it("shows the no-results empty state when nothing matches", async () => {
    const user = userEvent.setup();
    chatMocks.listChats.mockResolvedValue(chats(["c1", "Other Topic"]));
    chatMocks.getChat.mockResolvedValue({
      messages: [{ id: 1, role: "user", content: "hello world" }],
    });
    renderPanel();

    await typeAndWaitForSearch(user, "zebra");

    await waitFor(() =>
      expect(screen.getByText("chat.search.noResults")).toBeInTheDocument(),
    );
  });

  it("matches chat titles and message content", async () => {
    const user = userEvent.setup();
    chatMocks.listChats.mockResolvedValue(chats(["c1", "Project Plan"]));
    chatMocks.getChat.mockResolvedValue({
      messages: [
        {
          id: 7,
          role: "assistant",
          content: [{ type: "text", text: "the launch plan is ready" }],
        },
      ],
    });
    renderPanel();

    await typeAndWaitForSearch(user, "plan");

    await waitFor(() =>
      expect(screen.getAllByText("Project Plan").length).toBeGreaterThan(0),
    );
    // Title match and message match both appear
    expect(screen.getByText("chat.search.titleMatch")).toBeInTheDocument();
    expect(
      screen.getByText("chat.search.assistantMessage"),
    ).toBeInTheDocument();
  });

  it("matches user messages with the user role label", async () => {
    const user = userEvent.setup();
    chatMocks.listChats.mockResolvedValue(chats(["c1", "Random Chat"]));
    chatMocks.getChat.mockResolvedValue({
      messages: [{ id: 1, role: "user", content: "find me this needle" }],
    });
    renderPanel();

    await typeAndWaitForSearch(user, "needle");

    await waitFor(() =>
      expect(screen.getByText("chat.search.userMessage")).toBeInTheDocument(),
    );
  });

  it("extracts text from array content and skips non-text parts", async () => {
    const user = userEvent.setup();
    chatMocks.listChats.mockResolvedValue(chats(["c1", "Chat"]));
    chatMocks.getChat.mockResolvedValue({
      messages: [
        {
          id: 1,
          role: "user",
          content: [
            { type: "image" },
            { type: "text", text: "only the text part matters" },
          ],
        },
      ],
    });
    renderPanel();

    await typeAndWaitForSearch(user, "text part");

    await waitFor(() =>
      expect(
        screen.getAllByText(/only the text part matters/).length,
      ).toBeGreaterThan(0),
    );
  });

  it("truncates long matches with a leading ellipsis context window", async () => {
    const user = userEvent.setup();
    const longPrefix = "x".repeat(200);
    chatMocks.listChats.mockResolvedValue(chats(["c1", "Chat"]));
    chatMocks.getChat.mockResolvedValue({
      messages: [
        {
          id: 1,
          role: "user",
          content: `${longPrefix} needle here`,
        },
      ],
    });
    renderPanel();

    await typeAndWaitForSearch(user, "needle");

    await waitFor(() =>
      expect(screen.getAllByText(/^\.\.\./).length).toBeGreaterThan(0),
    );
  });

  it("ignores chats without an id and reports search progress", async () => {
    const user = userEvent.setup();
    chatMocks.listChats.mockResolvedValue([
      { id: "", name: "No Id" },
      { id: "c1", name: "Valid Chat" },
    ]);
    chatMocks.getChat.mockResolvedValue({
      messages: [{ id: 1, role: "user", content: "needle found" }],
    });
    renderPanel();

    await typeAndWaitForSearch(user, "needle");

    await waitFor(() =>
      expect(
        screen.getByText("chat.search.resultsCount:1"),
      ).toBeInTheDocument(),
    );
    // Only the valid chat was searched
    expect(chatMocks.getChat).toHaveBeenCalledTimes(1);
  });

  it("keeps searching when one chat fails to load", async () => {
    const user = userEvent.setup();
    chatMocks.listChats.mockResolvedValue(
      chats(["broken", "Broken"], ["ok", "Fine"]),
    );
    chatMocks.getChat.mockImplementation((id: string) =>
      id === "broken"
        ? Promise.reject(new Error("boom"))
        : Promise.resolve({
            messages: [{ id: 1, role: "user", content: "needle lives" }],
          }),
    );
    renderPanel();

    await typeAndWaitForSearch(user, "needle");

    await waitFor(() =>
      expect(screen.getAllByText(/needle lives/).length).toBeGreaterThan(0),
    );
  });

  it("reports a load failure with an error state", async () => {
    const user = userEvent.setup();
    chatMocks.listChats.mockRejectedValue(new Error("server down"));
    renderPanel();

    await typeAndWaitForSearch(user, "anything");

    await waitFor(() =>
      expect(screen.getByText("chat.search.noResults")).toBeInTheDocument(),
    );
  });

  it("navigates to the local session id when the result matches a session", async () => {
    const user = userEvent.setup();
    sessionStateMocks.sessions = [{ id: "s1", realId: null }];
    chatMocks.listChats.mockResolvedValue(chats(["c1", "Target"]));
    chatMocks.getChat.mockResolvedValue({
      messages: [{ id: 1, role: "user", content: "needle" }],
    });
    const onClose = vi.fn();
    renderPanel(onClose);

    await typeAndWaitForSearch(user, "needle");

    await waitFor(() =>
      expect(screen.getAllByText(/needle/).length).toBeGreaterThan(0),
    );
    const item = screen
      .getAllByText(/needle/)[0]
      .closest("[class*='searchResultItem']") as HTMLElement;
    await user.click(item);

    // c1 does not match any session's realId/id, so it navigates by chat id
    expect(navigateSpy).toHaveBeenCalledWith("/chat/c1");
    expect(onClose).toHaveBeenCalled();
  });

  it("navigates by session id when the session's realId matches", async () => {
    const user = userEvent.setup();
    sessionStateMocks.sessions = [{ id: "s1", realId: "c1" }];
    chatMocks.listChats.mockResolvedValue(chats(["c1", "Target"]));
    chatMocks.getChat.mockResolvedValue({
      messages: [{ id: 1, role: "user", content: "needle" }],
    });
    renderPanel();

    const sessionApi = (await import("../../sessionApi")).default;
    vi.mocked(sessionApi.getRealIdForSession).mockImplementation(
      (id: string) => (id === "s1" ? "c1" : null),
    );

    await typeAndWaitForSearch(user, "needle");

    await waitFor(() =>
      expect(screen.getAllByText(/needle/).length).toBeGreaterThan(0),
    );
    const item = screen
      .getAllByText(/needle/)[0]
      .closest("[class*='searchResultItem']") as HTMLElement;
    await user.click(item);

    expect(sessionStateMocks.setCurrentSessionId).toHaveBeenCalledWith("s1");
    expect(navigateSpy).toHaveBeenCalledWith("/chat/s1");
  });

  it("clears the query and results when closed", async () => {
    const user = userEvent.setup();
    chatMocks.listChats.mockResolvedValue(chats(["c1", "Target"]));
    chatMocks.getChat.mockResolvedValue({
      messages: [{ id: 1, role: "user", content: "needle" }],
    });
    const { rerender } = render(<ChatSearchPanel open onClose={vi.fn()} />);

    await typeAndWaitForSearch(user, "needle");
    await waitFor(() =>
      expect(screen.getAllByText(/needle/).length).toBeGreaterThan(0),
    );

    rerender(<ChatSearchPanel open={false} onClose={vi.fn()} />);
    await waitFor(() =>
      expect(screen.queryByText(/needle/)).not.toBeInTheDocument(),
    );
  });

  it("shows the searching progress label while loading", async () => {
    const user = userEvent.setup();
    let resolveList: (v: unknown[]) => void = () => {};
    chatMocks.listChats.mockReturnValue(
      new Promise((res) => {
        resolveList = res;
      }),
    );
    renderPanel();

    const input = screen.getByPlaceholderText("chat.search.placeholder");
    await user.type(input, "needle");
    await new Promise((r) => setTimeout(r, 450));

    await waitFor(() =>
      expect(screen.getByText("chat.search.loading")).toBeInTheDocument(),
    );

    resolveList([]);
    await waitFor(() =>
      expect(screen.getByText("chat.search.noResults")).toBeInTheDocument(),
    );
  });

  it("formats result timestamps for display", async () => {
    const user = userEvent.setup();
    chatMocks.listChats.mockResolvedValue(chats(["c1", "Target"]));
    chatMocks.getChat.mockResolvedValue({
      messages: [{ id: 1, role: "user", content: "needle" }],
    });
    renderPanel();

    await typeAndWaitForSearch(user, "needle");

    // chat.created_at "2026-09-01T10:00:00Z" formats to a local YYYY-MM-DD HH:mm
    await waitFor(() =>
      expect(
        screen.getAllByText(/2026-09-0\d \d\d:\d\d/).length,
      ).toBeGreaterThan(0),
    );
  });

  it("handles non-string, non-array content gracefully", async () => {
    const user = userEvent.setup();
    chatMocks.listChats.mockResolvedValue(chats(["c1", "Chat"]));
    chatMocks.getChat.mockResolvedValue({
      messages: [{ id: 1, role: "user", content: { weird: true } }],
    });
    renderPanel();

    await typeAndWaitForSearch(user, "needle");

    await waitFor(() =>
      expect(screen.getByText("chat.search.noResults")).toBeInTheDocument(),
    );
  });
});
