// @vitest-environment jsdom
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { IAgentScopeRuntimeWebUIMessage } from "@agentscope-ai/chat";

const state = vi.hoisted(() => ({
  messages: [] as IAgentScopeRuntimeWebUIMessage[],
  load: vi.fn(),
}));
vi.mock("use-context-selector", () => ({
  useContextSelector: (
    _context: unknown,
    select: (value: unknown) => unknown,
  ) => select({ messages: state.messages }),
}));
vi.mock(
  "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/Context/ChatAnywhereMessagesContext",
  () => ({
    ChatAnywhereMessagesContext: {},
  }),
);
vi.mock("./sessionApi", () => ({
  default: {
    loadUserMessageIndexPage: async (...args: unknown[]) => {
      const result = await state.load(...args);
      return Array.isArray(result)
        ? { items: result, total: result.length }
        : result;
    },
  },
}));
vi.mock("./HistoryMessageWindow", () => ({
  HistoryNavigationDirectory: ({
    activeMessageId,
    items,
  }: {
    activeMessageId?: string;
    items: Array<{ messageId: string }>;
  }) => (
    <>
      <output data-testid="active-user">{activeMessageId}</output>
      <output data-testid="directory-ids">
        {items.map((item) => item.messageId).join(",")}
      </output>
    </>
  ),
}));
vi.mock("antd", () => ({
  Tooltip: ({ children }: { children: React.ReactNode }) => children,
  Popover: ({
    children,
    content,
  }: {
    children: React.ReactNode;
    content: React.ReactNode;
  }) => (
    <>
      {children}
      {content}
    </>
  ),
}));
import { ChatUserMessageNavigation } from "./ChatUserMessageNavigation";
import { historyMessageWindow } from "./historyMessageWindowStore";

afterEach(() => {
  cleanup();
  historyMessageWindow.end();
  state.load.mockReset();
  state.messages = [];
});

describe("unified navigation across history and live rendering", () => {
  it("drops a superseded user after the index refreshes", async () => {
    const entry = (messageId: string) => ({
      messageId,
      preview: "input",
      createdAt: "",
      anchor: messageId,
    });
    state.load
      .mockResolvedValueOnce({
        items: [entry("old-0"), entry("old-1"), entry("old-2"), entry("old-3")],
        total: 4,
      })
      .mockResolvedValueOnce({
        items: [entry("old-1"), entry("old-2"), entry("new-3")],
        total: 4,
      });
    const props = { sessionId: "chat", onNavigate: vi.fn(), onCancel: vi.fn() };
    const view = () => (
      <div className="qwenpaw-chat-anywhere-layout-right">
        <ChatUserMessageNavigation {...props} />
      </div>
    );
    const { rerender } = render(view());
    await waitFor(() =>
      expect(screen.getByTestId("directory-ids").textContent).toBe(
        "old-0,old-1,old-2,old-3",
      ),
    );
    state.messages = [{ id: "new-3", role: "user", cards: [] }];
    rerender(view());
    await waitFor(() =>
      expect(screen.getByTestId("directory-ids").textContent).toBe(
        "old-0,old-1,old-2,new-3",
      ),
    );
  });

  it("tracks mounted history users outside the index page without fetching gaps", async () => {
    state.load.mockResolvedValue({
      items: [
        {
          messageId: "user-99",
          preview: "latest",
          createdAt: "",
          anchor: "a99",
        },
      ],
      total: 100,
      before: "older-index",
    });
    historyMessageWindow.begin({
      sessionId: "chat",
      turnRows: [[{ id: "user-2", role: "user", cards: [] }]],
      canLoadOlder: true,
      onLoadOlder: vi.fn(),
      onFillOlder: vi.fn(),
    });
    const view = (id: string) => (
      <div className="qwenpaw-chat-anywhere-layout-right">
        <div data-history-message-window>
          <div id={id} data-role="user" />
        </div>
        <ChatUserMessageNavigation
          sessionId="chat"
          onNavigate={vi.fn()}
          onCancel={vi.fn()}
        />
      </div>
    );
    const { rerender } = render(view("user-2"));
    await waitFor(() =>
      expect(screen.getByTestId("active-user").textContent).toBe("user-2"),
    );
    act(() =>
      historyMessageWindow.setTurnRows(
        "chat",
        [
          [{ id: "user-1", role: "user", cards: [] }],
          [{ id: "user-2", role: "user", cards: [] }],
        ],
        false,
      ),
    );
    rerender(view("user-1"));
    await waitFor(() =>
      expect(screen.getByTestId("active-user").textContent).toBe("user-1"),
    );
    expect(state.load).toHaveBeenCalledOnce();
  });
  it("keeps an adjacent target visible until manual scrolling", async () => {
    state.load.mockResolvedValue(
      [0, 1, 2].map((i) => ({
        messageId: `user-${i}`,
        preview: "input",
        createdAt: "",
        anchor: `cursor-${i}`,
      })),
    );
    const { container } = render(
      <div className="qwenpaw-chat-anywhere-layout-right">
        <div data-history-message-window>
          <div id="user-1" />
        </div>
        <ChatUserMessageNavigation
          sessionId="chat"
          onNavigate={vi.fn()}
          onCancel={vi.fn()}
        />
      </div>,
    );
    const scroll = container.querySelector<HTMLElement>(
      "[data-history-message-window]",
    )!;
    const user = container.querySelector<HTMLElement>("#user-1")!;
    let offset = 500;
    vi.spyOn(user, "getBoundingClientRect").mockImplementation(
      () => ({ top: offset - scroll.scrollTop }) as DOMRect,
    );
    const previous = await screen.findByRole("button", {
      name: "Previous user message",
    });
    user.dataset.role = "user";
    fireEvent.click(previous);
    expect(scroll.scrollTop).toBe(476);
    offset += 300;
    fireEvent(
      container.firstElementChild!,
      new Event("chat-message-window-rendered"),
    );
    expect(user.getBoundingClientRect().top).toBe(24);
    fireEvent.wheel(scroll, { deltaY: 100 });
    scroll.scrollTop += 100;
    fireEvent.scroll(scroll);
    expect(user.getBoundingClientRect().top).toBe(-76);
  });

  it.each([0, 1, 2, 3])(
    "shows navigation only with at least three users (%i)",
    async (count) => {
      state.load.mockResolvedValue(
        Array.from({ length: count }, (_, i) => ({
          messageId: `u-${i}`,
          preview: "input",
          createdAt: "",
          anchor: `a-${i}`,
        })),
      );
      render(
        <div className="qwenpaw-chat-anywhere-layout-right">
          <ChatUserMessageNavigation
            sessionId="chat"
            onNavigate={vi.fn()}
            onCancel={vi.fn()}
          />
        </div>,
      );
      await waitFor(() => expect(state.load).toHaveBeenCalledOnce());
      await act(async () => {});
      expect(Boolean(screen.queryByRole("navigation"))).toBe(count >= 3);
    },
  );

  it("loads the preceding index page only when crossing its boundary", async () => {
    const entry = (i: number) => ({
      messageId: `u-${i}`,
      preview: "input",
      createdAt: "",
      anchor: `a-${i}`,
    });
    state.load
      .mockResolvedValueOnce({
        items: [entry(99)],
        total: 100,
        before: "older",
      })
      .mockResolvedValueOnce({ items: [entry(97), entry(98)], total: 100 });
    const onNavigate = vi.fn();
    render(
      <div className="qwenpaw-chat-anywhere-layout-right">
        <ChatUserMessageNavigation
          sessionId="chat"
          onNavigate={onNavigate}
          onCancel={vi.fn()}
        />
      </div>,
    );
    const previous = await screen.findByRole("button", {
      name: "Previous user message",
    });
    expect(state.load).toHaveBeenCalledOnce();
    expect(
      screen.getByRole("button", { name: "User message directory" })
        .textContent,
    ).toBe("99+");
    fireEvent.click(previous);
    await waitFor(() =>
      expect(onNavigate).toHaveBeenCalledWith({ ...entry(98), anchor: "a-99" }),
    );
    expect(state.load.mock.calls[1][1]).toBe("older");
  });
  it("renders a new chat before a session identity exists", () => {
    render(
      <ChatUserMessageNavigation onNavigate={vi.fn()} onCancel={vi.fn()} />,
    );
    expect(screen.queryByRole("navigation")).toBeNull();
    expect(state.load).not.toHaveBeenCalled();
  });

  it("loads following context without changing the navigation target", async () => {
    const entries = Array.from({ length: 5 }, (_, i) => ({
      messageId: `user-${i}`,
      preview: "input",
      createdAt: "",
      anchor: `cursor-${i}`,
    }));
    state.load.mockResolvedValue(entries);
    const onNavigate = vi.fn();
    render(
      <div className="qwenpaw-chat-anywhere-layout-right">
        <ChatUserMessageNavigation
          sessionId="chat"
          onNavigate={onNavigate}
          onCancel={vi.fn()}
        />
      </div>,
    );
    const previous = await screen.findByRole("button", {
      name: "Previous user message",
    });
    fireEvent.click(previous);
    expect(onNavigate).toHaveBeenCalledWith({
      ...entries[3],
      anchor: "cursor-4",
    });
  });

  it("retains the full count, adds live input, and does not refetch on assistant deltas", async () => {
    const entries = Array.from({ length: 17 }, (_, i) => ({
      messageId: `user-${i}`,
      preview: "input",
      createdAt: "",
      anchor: `cursor-${i}`,
    }));
    state.load.mockResolvedValue(entries);
    const props = { sessionId: "chat", onNavigate: vi.fn(), onCancel: vi.fn() };
    const view = () => (
      <div className="qwenpaw-chat-anywhere-layout-right">
        <ChatUserMessageNavigation {...props} />
      </div>
    );
    const { rerender } = render(view());
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "User message directory" })
          .textContent,
      ).toBe("17"),
    );
    state.messages = [{ id: "live-user", role: "user", cards: [] }];
    rerender(view());
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "User message directory" })
          .textContent,
      ).toBe("18"),
    );
    const calls = state.load.mock.calls.length;
    state.messages = [
      ...state.messages,
      { id: "assistant", role: "assistant", cards: [] },
    ];
    rerender(view());
    expect(state.load).toHaveBeenCalledTimes(calls);
    expect(screen.getAllByRole("navigation")).toHaveLength(1);
    act(() => historyMessageWindow.end("chat"));
    expect(
      screen.getByRole("button", { name: "User message directory" })
        .textContent,
    ).toBe("18");
  });
});
