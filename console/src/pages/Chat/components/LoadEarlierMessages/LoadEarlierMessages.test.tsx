import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/common_setup";
import LoadEarlierMessages, {
  applyPrependedMessages,
  applyReplacedMessages,
} from "./index";
import { resetHistoryPageSizeForTests } from "../../sessionApi/historyPageSize";

const {
  mockSubscribe,
  mockGetHistoryPage,
  mockLoadEarlier,
  mockUseSessions,
  mockSubscribeReplaced,
  mockReloadAfterPageSizeChange,
  mockSubscribeLoadEarlier,
  mockRequestLoadEarlier,
} = vi.hoisted(() => {
  let loadEarlierListener: (() => void) | null = null;
  return {
    mockSubscribe: vi.fn((cb: () => void) => {
      void cb;
      return () => undefined;
    }),
    mockGetHistoryPage: vi.fn(),
    mockLoadEarlier: vi.fn(),
    mockUseSessions: vi.fn(),
    mockSubscribeReplaced: vi.fn(() => () => undefined),
    mockReloadAfterPageSizeChange: vi.fn(),
    mockSubscribeLoadEarlier: vi.fn((cb: () => void) => {
      loadEarlierListener = cb;
      return () => {
        loadEarlierListener = null;
      };
    }),
    mockRequestLoadEarlier: vi.fn(() => {
      loadEarlierListener?.();
    }),
  };
});

vi.mock("@agentscope-ai/chat", () => ({
  useChatAnywhereSessionsState: mockUseSessions,
}));

vi.mock("../../sessionApi", () => ({
  default: {
    subscribeHistoryPage: mockSubscribe,
    getHistoryPage: mockGetHistoryPage,
    loadEarlierMessages: mockLoadEarlier,
    subscribeHistoryReplaced: mockSubscribeReplaced,
    reloadAfterPageSizeChange: mockReloadAfterPageSizeChange,
    subscribeLoadEarlierRequest: mockSubscribeLoadEarlier,
    requestLoadEarlier: mockRequestLoadEarlier,
  },
}));

vi.mock("../../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: { error: vi.fn(), success: vi.fn() },
  }),
}));

describe("applyPrependedMessages", () => {
  it("uses setMessages when available", () => {
    const setMessages = vi.fn();
    applyPrependedMessages(
      {
        getMessages: () => [{ id: "new" }],
        setMessages,
      },
      [{ id: "old" }],
    );
    expect(setMessages).toHaveBeenCalledWith([{ id: "old" }, { id: "new" }]);
  });

  it("rebuilds via removeAll + addMessage", () => {
    const addMessage = vi.fn();
    const removeAllMessages = vi.fn();
    applyPrependedMessages(
      {
        getMessages: () => [{ id: "new" }],
        addMessage,
        removeAllMessages,
      },
      [{ id: "old" }],
    );
    expect(removeAllMessages).toHaveBeenCalledTimes(1);
    expect(addMessage).toHaveBeenCalledTimes(2);
    expect(addMessage.mock.calls[0][0]).toEqual({ id: "old" });
  });
});

describe("applyReplacedMessages", () => {
  it("replaces via setMessages", () => {
    const setMessages = vi.fn();
    applyReplacedMessages({ getMessages: () => [{ id: "old" }], setMessages }, [
      { id: "new" },
    ]);
    expect(setMessages).toHaveBeenCalledWith([{ id: "new" }]);
  });
});

describe("LoadEarlierMessages", () => {
  beforeEach(() => {
    mockUseSessions.mockReturnValue({ currentSessionId: "chat-1" });
    mockGetHistoryPage.mockReturnValue({
      hasMore: true,
      loading: false,
      total: 80,
      oldestOriginalId: "msg-30",
      loadedOriginalIds: ["msg-30"],
    });
    mockLoadEarlier.mockResolvedValue({ prepended: [{ id: "older" }] });
  });

  afterEach(() => {
    vi.clearAllMocks();
    resetHistoryPageSizeForTests();
  });

  it("is hidden when there is no current session", () => {
    mockUseSessions.mockReturnValue({ currentSessionId: null });
    mockGetHistoryPage.mockReturnValue({
      hasMore: true,
      loading: false,
      total: 80,
      oldestOriginalId: "msg-30",
      loadedOriginalIds: ["msg-30"],
    });
    renderWithProviders(
      <LoadEarlierMessages
        chatRef={{ current: null }}
        rootRef={{ current: null }}
      />,
    );
    expect(screen.queryByTestId("load-earlier-messages")).toBeNull();
    expect(screen.queryByTestId("history-page-size")).toBeNull();
  });

  it("hides Load earlier when there is no earlier history but keeps the page size input", () => {
    mockGetHistoryPage.mockReturnValue({
      hasMore: false,
      loading: false,
      total: 10,
      oldestOriginalId: "msg-0",
      loadedOriginalIds: ["msg-0"],
    });
    renderWithProviders(
      <LoadEarlierMessages
        chatRef={{ current: null }}
        rootRef={{ current: null }}
      />,
    );
    expect(screen.queryByTestId("load-earlier-messages")).toBeNull();
    expect(screen.getByTestId("history-page-size")).toBeTruthy();
  });

  it("loads earlier messages and prepends them", async () => {
    const user = userEvent.setup();
    const setMessages = vi.fn();
    renderWithProviders(
      <LoadEarlierMessages
        chatRef={{
          current: {
            messages: {
              getMessages: () => [{ id: "latest" }],
              setMessages,
            },
          } as never,
        }}
        rootRef={{ current: null }}
      />,
    );

    await user.click(screen.getByTestId("load-earlier-messages"));
    expect(mockLoadEarlier).toHaveBeenCalledWith("chat-1");
    expect(setMessages).toHaveBeenCalledWith([
      { id: "older" },
      { id: "latest" },
    ]);
  });

  it("changing the compact page size reloads the latest window", async () => {
    const user = userEvent.setup();
    mockReloadAfterPageSizeChange.mockResolvedValue({ messages: [] });
    renderWithProviders(
      <LoadEarlierMessages
        chatRef={{ current: null }}
        rootRef={{ current: null }}
      />,
    );
    const input = screen.getByRole("spinbutton");
    await user.clear(input!);
    await user.type(input!, "120");
    input!.blur();
    await waitFor(() =>
      expect(mockReloadAfterPageSizeChange).toHaveBeenCalledWith("chat-1"),
    );
  });

  it("loads earlier messages when the transcript is scrolled to the top", async () => {
    const root = document.createElement("div");
    const scroller = document.createElement("div");
    scroller.className =
      "qwenpaw-chat-anywhere-message-list-bubble-scroll " +
      "qwenpaw-bubble-list-order-desc";
    Object.defineProperties(scroller, {
      scrollHeight: { configurable: true, value: 2000 },
      clientHeight: { configurable: true, value: 400 },
    });
    root.append(scroller);
    document.body.append(root);

    mockLoadEarlier.mockResolvedValue({ prepended: [{ id: "older" }] });
    const setMessages = vi.fn();
    renderWithProviders(
      <LoadEarlierMessages
        chatRef={{
          current: {
            messages: {
              getMessages: () => [{ id: "latest" }],
              setMessages,
            },
          } as never,
        }}
        rootRef={{ current: root }}
      />,
    );

    await screen.findByTestId("load-earlier-messages");
    scroller.scrollTop = -1580;
    fireEvent.scroll(scroller);
    await waitFor(() => expect(mockLoadEarlier).toHaveBeenCalledWith("chat-1"));

    root.remove();
  });
});
