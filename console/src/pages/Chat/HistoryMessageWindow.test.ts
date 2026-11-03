import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render } from "@testing-library/react";
import { createElement } from "react";
import type { ReactNode } from "react";
import {
  HistoryMessageWindowCard,
  HistoryNavigationDirectory,
} from "./HistoryMessageWindow";
import { ChatUserMessageNavigation } from "./ChatUserMessageNavigation";
import {
  createHistoryMessageWindowCard,
  HISTORY_MESSAGE_WINDOW_CARD,
  historyMessageWindow,
  splitHistoryMessagesIntoTurnRows,
} from "./historyMessageWindowStore";
import sessionApi, { mergeHistoryMessages } from "./sessionApi";

vi.mock("@agentscope-ai/chat", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@agentscope-ai/chat")>()),
  Bubble: ({ id, role }: { id: string; role: string }) =>
    createElement("div", { id, "data-role": role }),
}));

vi.mock("./HostBubbles", () => ({
  DeferredHistoryContent: ({ children }: { children: ReactNode }) => children,
  EagerHistoryContent: ({ children }: { children: ReactNode }) => children,
  HostRequestCard: () => null,
  HostResponseCard: () => null,
}));

function rect(top: number, height = 40): DOMRect {
  return {
    bottom: top + height,
    height,
    left: 0,
    right: 100,
    top,
    width: 100,
    x: 0,
    y: top,
    toJSON: () => ({}),
  };
}

it("bounds directory rows and loads older indexes only after scrolling", () => {
  const items = Array.from({ length: 1000 }, (_, i) => ({
    messageId: `index-${i}`,
    preview: `Input ${i}`,
    createdAt: "",
    anchor: `a-${i}`,
  }));
  const loadOlder = vi.fn();
  const { container } = render(
    createElement(HistoryNavigationDirectory, {
      items,
      total: 2000,
      activeMessageId: "index-999",
      openVersion: 0,
      onSelect: vi.fn(),
      hasMore: true,
      onLoadOlder: loadOlder,
    }),
  );
  expect(container.querySelectorAll("time").length).toBeLessThanOrEqual(20);
  expect(loadOlder).not.toHaveBeenCalled();
  const list = container.querySelector<HTMLElement>(
    '[style*="overflow: auto"]',
  )!;
  Object.defineProperties(list, {
    clientHeight: { value: 360 },
    scrollHeight: { value: 33000 },
  });
  fireEvent.scroll(list, { target: { scrollTop: 0 } });
  expect(loadOlder).toHaveBeenCalledOnce();
  expect(container.querySelectorAll("time").length).toBeLessThanOrEqual(20);
});

function renderWithNavigation() {
  const current = historyMessageWindow.getSnapshot()!;
  vi.spyOn(sessionApi, "loadUserMessageIndexPage").mockResolvedValue({
    items: current.userMessages,
    total: current.userMessages.length,
    before: undefined,
  });
  return render(
    createElement(
      "div",
      {
        className:
          "qwenpaw-chat-anywhere-layout-right qwenpaw-chat-anywhere-message-list",
      },
      createElement(HistoryMessageWindowCard),
      createElement(ChatUserMessageNavigation, {
        sessionId: current.sessionId,
        onNavigate: (item) => current.onNavigateToUserMessage(item, "replace"),
        onCancel: current.onCancelPending,
      }),
    ),
  );
}

describe("history message window store", () => {
  afterEach(() => act(() => historyMessageWindow.end()));

  it("returns to the retained live stream without loading an anchor", () => {
    const onReturnToLatest = vi.fn();
    const onNavigateToUserMessage = vi.fn();
    historyMessageWindow.begin({
      sessionId: "chat-live",
      turnRows: [[{ id: "old-user", role: "user" }] as never[]],
      canLoadOlder: false,
      onLoadOlder: vi.fn(),
      onFillOlder: vi.fn(),
      onNavigateToUserMessage,
      onReturnToLatest,
    });
    const view = renderWithNavigation();
    fireEvent.click(view.getByRole("button", { name: "Scroll to bottom" }));
    expect(onReturnToLatest).toHaveBeenCalledOnce();
    expect(onNavigateToUserMessage).not.toHaveBeenCalled();
  });

  it("updates one isolated snapshot without changing its callbacks", () => {
    const listener = vi.fn();
    const unsubscribe = historyMessageWindow.subscribe(listener);
    const onLoadOlder = vi.fn();
    const onFillOlder = vi.fn();
    const first = [{ id: "first", role: "user" }] as never[];
    const second = [{ id: "second", role: "assistant" }] as never[];

    historyMessageWindow.begin({
      sessionId: "chat-1",
      turnRows: [first],
      canLoadOlder: true,
      onLoadOlder,
      onFillOlder,
    });
    historyMessageWindow.setTurnRows("chat-1", [second], false);
    historyMessageWindow.setLoading("chat-1", false);

    expect(historyMessageWindow.getSnapshot()).toEqual({
      sessionId: "chat-1",
      turnRows: [second],
      loading: false,
      canLoadOlder: false,
      onLoadOlder,
      onFillOlder,
      userMessages: [],
      onNavigateToUserMessage: expect.any(Function),
      onCancelPending: expect.any(Function),
    });
    expect(listener).toHaveBeenCalledTimes(3);
    unsubscribe();
  });

  it("creates one runtime boundary card for the active session", () => {
    const card = createHistoryMessageWindowCard("chat-1");

    expect(card).toMatchObject({
      id: "qwenpaw-history-window-chat-1",
      role: "assistant",
      history: true,
      cards: [{ code: HISTORY_MESSAGE_WINDOW_CARD }],
    });
  });

  it("groups accumulated history into stable virtual turn rows", () => {
    const messages = Array.from({ length: 12 }, (_, index) => [
      { id: `user-${index + 1}`, role: "user" },
      { id: `assistant-${index + 1}`, role: "assistant" },
    ]).flat() as never[];

    const turnRows = splitHistoryMessagesIntoTurnRows(messages);

    expect(turnRows).toHaveLength(12);
    expect(turnRows.map((turn) => turn.length)).toEqual(
      Array.from({ length: 12 }, () => 2),
    );
    expect(turnRows.map((turn) => turn[0].id)).toEqual(
      Array.from({ length: 12 }, (_, index) => `user-${index + 1}`),
    );
  });

  it("virtualizes a partial turn prefix by materialized message", () => {
    const messages = [
      { id: "assistant-fragment-1", role: "assistant" },
      { id: "assistant-fragment-2", role: "assistant" },
      { id: "user-2", role: "user" },
      { id: "assistant-2", role: "assistant" },
    ] as never[];

    const turnRows = splitHistoryMessagesIntoTurnRows(messages);

    expect(turnRows.map((turn) => turn.map((message) => message.id))).toEqual([
      ["assistant-fragment-1"],
      ["assistant-fragment-2"],
      ["user-2", "assistant-2"],
    ]);
  });

  it("prepends one page without duplicating its boundary message", () => {
    const current = Array.from({ length: 5 }, (_, index) => [
      { id: `user-${index + 6}`, role: "user" },
      { id: `assistant-${index + 6}`, role: "assistant" },
    ]).flat() as never[];
    const older = [
      ...Array.from({ length: 5 }, (_, index) => [
        { id: `user-${index + 1}`, role: "user" },
        { id: `assistant-${index + 1}`, role: "assistant" },
      ]).flat(),
      current[0],
    ] as never[];

    const turnRows = splitHistoryMessagesIntoTurnRows(
      mergeHistoryMessages(older, current),
    );
    const ids = turnRows.flat().map((message) => message.id);

    expect(turnRows).toHaveLength(10);
    expect(ids).toHaveLength(new Set(ids).size);
    expect(ids).toEqual([
      "user-1",
      "assistant-1",
      "user-2",
      "assistant-2",
      "user-3",
      "assistant-3",
      "user-4",
      "assistant-4",
      "user-5",
      "assistant-5",
      "user-6",
      "assistant-6",
      "user-7",
      "assistant-7",
      "user-8",
      "assistant-8",
      "user-9",
      "assistant-9",
      "user-10",
      "assistant-10",
    ]);
  });

  it("ignores late updates from a previous session", () => {
    const messages = [{ id: "current", role: "assistant" }] as never[];
    historyMessageWindow.begin({
      sessionId: "chat-2",
      turnRows: [messages],
      canLoadOlder: true,
      onLoadOlder: vi.fn(),
      onFillOlder: vi.fn(),
    });

    historyMessageWindow.setLoading("chat-1", false);
    historyMessageWindow.setTurnRows("chat-1", [], false);
    historyMessageWindow.end("chat-1");

    expect(historyMessageWindow.getSnapshot()).toMatchObject({
      sessionId: "chat-2",
      turnRows: [messages],
      loading: true,
      canLoadOlder: true,
    });
  });

  it("loads again after the preceding page request finishes", () => {
    vi.useFakeTimers();
    const onLoadOlder = vi.fn(() =>
      historyMessageWindow.setLoading("chat-1", true),
    );
    historyMessageWindow.begin({
      sessionId: "chat-1",
      turnRows: [],
      canLoadOlder: true,
      onLoadOlder,
      onFillOlder: vi.fn(),
    });
    historyMessageWindow.setLoading("chat-1", false);
    const { container } = render(
      createElement(
        "div",
        { className: "qwenpaw-chat-anywhere-message-list" },
        createElement(HistoryMessageWindowCard),
      ),
    );
    const window = container.querySelector<HTMLElement>(
      "[data-history-message-window]",
    );
    expect(window).not.toBeNull();

    act(() => fireEvent.wheel(window!, { deltaY: -10 }));
    act(() => fireEvent.wheel(window!, { deltaY: -10 }));
    expect(onLoadOlder).toHaveBeenCalledTimes(1);

    act(() => historyMessageWindow.setLoading("chat-1", false));
    act(() => fireEvent.wheel(window!, { deltaY: -10 }));
    expect(onLoadOlder).toHaveBeenCalledTimes(1);

    act(() => vi.advanceTimersByTime(161));
    act(() => fireEvent.wheel(window!, { deltaY: -10 }));
    expect(onLoadOlder).toHaveBeenCalledTimes(2);
    act(() => vi.runOnlyPendingTimers());
    vi.useRealTimers();
  });

  it("keeps the previous top message fixed while older turns are prepended", () => {
    vi.useFakeTimers();
    const clientHeight = vi
      .spyOn(HTMLElement.prototype, "clientHeight", "get")
      .mockReturnValue(500);
    const scrollHeight = vi
      .spyOn(HTMLElement.prototype, "scrollHeight", "get")
      .mockReturnValue(3000);
    let scrollTarget: HTMLElement | null = null;
    const bounds = vi
      .spyOn(HTMLElement.prototype, "getBoundingClientRect")
      .mockImplementation(function getBounds(this: HTMLElement) {
        if (this.id === "user-6") {
          const itemTop = document.getElementById("user-1") ? 270 : 70;
          return rect(itemTop - (scrollTarget?.scrollTop ?? 0));
        }
        return rect(0);
      });
    const current = Array.from({ length: 5 }, (_, index) => [
      { id: `user-${index + 6}`, role: "user" },
      { id: `assistant-${index + 6}`, role: "assistant" },
    ]) as never[][];
    const older = Array.from({ length: 5 }, (_, index) => [
      { id: `user-${index + 1}`, role: "user" },
      { id: `assistant-${index + 1}`, role: "assistant" },
    ]) as never[][];
    const onLoadOlder = vi.fn(() =>
      historyMessageWindow.setLoading("chat-1", true),
    );
    historyMessageWindow.begin({
      sessionId: "chat-1",
      turnRows: current,
      canLoadOlder: true,
      onLoadOlder,
      onFillOlder: vi.fn(),
    });
    historyMessageWindow.setLoading("chat-1", false);
    const { container } = render(
      createElement(
        "div",
        { className: "qwenpaw-chat-anywhere-message-list" },
        createElement(HistoryMessageWindowCard),
      ),
    );
    scrollTarget = container.querySelector<HTMLElement>(
      "[data-history-message-window]",
    );
    expect(scrollTarget).not.toBeNull();
    act(() => vi.runAllTimers());
    scrollTarget!.scrollTop = 0;
    act(() => {
      fireEvent.scroll(scrollTarget!);
      vi.runAllTimers();
    });
    expect(document.getElementById("user-6")).not.toBeNull();

    act(() => fireEvent.wheel(scrollTarget!, { deltaY: -10 }));
    expect(onLoadOlder).toHaveBeenCalledOnce();

    act(() => {
      historyMessageWindow.setTurnRows("chat-1", [...older, ...current], false);
      historyMessageWindow.setLoading("chat-1", false);
      vi.runAllTimers();
    });
    act(() => vi.runAllTimers());

    const anchor = document.getElementById("user-6");
    expect(anchor).not.toBeNull();
    expect(
      anchor!.getBoundingClientRect().top -
        scrollTarget!.getBoundingClientRect().top,
    ).toBe(70);

    bounds.mockRestore();
    clientHeight.mockRestore();
    scrollHeight.mockRestore();
    vi.useRealTimers();
  });

  it("fills another page when the history viewport is not scrollable", () => {
    vi.useFakeTimers();
    const clientHeight = vi
      .spyOn(HTMLElement.prototype, "clientHeight", "get")
      .mockReturnValue(800);
    const scrollHeight = vi
      .spyOn(HTMLElement.prototype, "scrollHeight", "get")
      .mockReturnValue(800);
    const onFillOlder = vi.fn();
    historyMessageWindow.begin({
      sessionId: "chat-1",
      turnRows: [],
      canLoadOlder: true,
      onLoadOlder: vi.fn(),
      onFillOlder,
    });
    historyMessageWindow.setLoading("chat-1", false);

    render(
      createElement(
        "div",
        { className: "qwenpaw-chat-anywhere-message-list" },
        createElement(HistoryMessageWindowCard),
      ),
    );
    act(() => vi.runAllTimers());

    expect(onFillOlder).toHaveBeenCalledTimes(1);
    clientHeight.mockRestore();
    scrollHeight.mockRestore();
    vi.useRealTimers();
  });

  it("appends the next five turns when scrolling past a navigated page", () => {
    const onNavigateToUserMessage = vi.fn();
    const userMessages = Array.from({ length: 7 }, (_, index) => ({
      messageId: `user-${index + 1}`,
      preview: `message ${index + 1}`,
      createdAt: `2026-10-23T0${index + 1}:00:00Z`,
      anchor: `opaque-anchor-${index + 1}`,
    }));
    historyMessageWindow.begin({
      sessionId: "chat-1",
      turnRows: [
        [
          { id: "user-2", role: "user", cards: [] },
          { id: "assistant-2", role: "assistant", cards: [] },
        ],
      ] as never[][],
      canLoadOlder: true,
      userMessages: userMessages.slice(-1),
      onLoadOlder: vi.fn(),
      onFillOlder: vi.fn(),
      onNavigateToUserMessage,
    });
    historyMessageWindow.setLoading("chat-1", false);
    const { container } = render(
      createElement(
        "div",
        { className: "qwenpaw-chat-anywhere-message-list" },
        createElement(HistoryMessageWindowCard),
      ),
    );
    const window = container.querySelector<HTMLElement>(
      "[data-history-message-window]",
    );

    act(() => fireEvent.wheel(window!, { deltaY: 10 }));

    expect(onNavigateToUserMessage).toHaveBeenCalledExactlyOnceWith(
      expect.objectContaining({ messageId: "user-2" }),
      "append-newer",
    );
  });

  it("returns to the live card at the edge without querying its optimistic id", () => {
    const navigate = vi.fn();
    const latest = vi.fn();
    historyMessageWindow.begin({
      sessionId: "chat-1",
      turnRows: [[{ id: "sdk-live-user", role: "user", cards: [] }]],
      canLoadOlder: false,
      onLoadOlder: vi.fn(),
      onFillOlder: vi.fn(),
      onNavigateToUserMessage: navigate,
      onReturnToLatest: latest,
    });
    historyMessageWindow.setLoading("chat-1", false);
    const { container } = render(
      createElement(
        "div",
        {
          className: "qwenpaw-chat-anywhere-message-list",
        },
        createElement(HistoryMessageWindowCard),
      ),
    );
    const scroll = container.querySelector<HTMLElement>(
      "[data-history-message-window]",
    )!;
    Object.defineProperties(scroll, {
      clientHeight: { value: 500 },
      scrollHeight: { value: 3000 },
    });
    scroll.scrollTop = 2000;
    fireEvent.wheel(scroll, { deltaY: 20 });
    expect(navigate).not.toHaveBeenCalled();
    expect(latest).not.toHaveBeenCalled();
    scroll.scrollTop = 2500;
    fireEvent.wheel(scroll, { deltaY: 20 });
    expect(navigate).not.toHaveBeenCalled();
    expect(latest).toHaveBeenCalledOnce();
  });

  it("blocks automatic forward retries after a failed page", () => {
    const navigate = vi.fn();
    historyMessageWindow.begin({
      sessionId: "chat-1",
      turnRows: [[{ id: "durable-user", role: "user", cards: [] }]],
      canLoadOlder: false,
      newerLoadFailed: true,
      onLoadOlder: vi.fn(),
      onFillOlder: vi.fn(),
      onNavigateToUserMessage: navigate,
    });
    historyMessageWindow.setLoading("chat-1", false);
    const { container } = render(
      createElement(
        "div",
        {
          className: "qwenpaw-chat-anywhere-message-list",
        },
        createElement(HistoryMessageWindowCard),
      ),
    );
    const scroll = container.querySelector<HTMLElement>(
      "[data-history-message-window]",
    )!;
    Object.defineProperties(scroll, {
      clientHeight: { value: 500 },
      scrollHeight: { value: 3000 },
    });
    scroll.scrollTop = 2500;
    for (let i = 0; i < 5; i++) fireEvent.wheel(scroll, { deltaY: 20 });
    expect(navigate).not.toHaveBeenCalled();
  });

  it.each(["older", "newer"])(
    "prefetches %s history on scroll before reaching the boundary",
    (direction) => {
      const load = vi.fn(() => historyMessageWindow.setLoading("chat-1", true));
      const userMessages = Array.from({ length: 8 }, (_, index) => ({
        messageId: `user-${index + 1}`,
        preview: "message",
        createdAt: "",
        anchor: `anchor-${index + 1}`,
      }));
      historyMessageWindow.begin({
        sessionId: "chat-1",
        turnRows: [[{ id: "user-2", role: "user" }]] as never[][],
        canLoadOlder: true,
        userMessages,
        onLoadOlder: load,
        onFillOlder: vi.fn(),
        onNavigateToUserMessage: load,
      });
      historyMessageWindow.setLoading("chat-1", false);
      const { container } = render(
        createElement(
          "div",
          { className: "qwenpaw-chat-anywhere-message-list" },
          createElement(HistoryMessageWindowCard),
        ),
      );
      const scroll = container.querySelector<HTMLElement>(
        "[data-history-message-window]",
      )!;
      Object.defineProperties(scroll, {
        clientHeight: { value: 500 },
        scrollHeight: { value: 3000 },
      });
      scroll.scrollTop = 1250;
      fireEvent.pointerDown(scroll);
      scroll.scrollTop = direction === "older" ? 900 : 1600;
      const position = scroll.scrollTop;
      act(() => {
        fireEvent.scroll(scroll);
        fireEvent.scroll(scroll);
      });
      expect(load).toHaveBeenCalledOnce();
      expect(scroll.scrollTop).toBe(position);
      if (direction === "newer") {
        expect(load).toHaveBeenCalledWith(
          expect.objectContaining({ messageId: "user-2" }),
          "append-newer",
        );
      } else {
        expect(load).toHaveBeenCalledWith(scroll);
      }
    },
  );

  it("fills newer turns at the start without requiring a wheel gesture", () => {
    vi.useFakeTimers();
    const clientHeight = vi
      .spyOn(HTMLElement.prototype, "clientHeight", "get")
      .mockReturnValue(800);
    const scrollHeight = vi
      .spyOn(HTMLElement.prototype, "scrollHeight", "get")
      .mockReturnValue(800);
    const onNavigateToUserMessage = vi.fn();
    const userMessages = Array.from({ length: 6 }, (_, index) => ({
      messageId: `user-${index + 1}`,
      preview: `message ${index + 1}`,
      createdAt: "2026-10-24T00:00:00Z",
      anchor: `anchor-${index + 1}`,
    }));
    historyMessageWindow.begin({
      sessionId: "chat-1",
      turnRows: [[{ id: "user-1", role: "user" }]] as never[][],
      canLoadOlder: false,
      userMessages,
      onLoadOlder: vi.fn(),
      onFillOlder: vi.fn(),
      onNavigateToUserMessage,
    });
    historyMessageWindow.setLoading("chat-1", false);
    render(
      createElement(
        "div",
        { className: "qwenpaw-chat-anywhere-message-list" },
        createElement(HistoryMessageWindowCard),
      ),
    );
    act(() => vi.runAllTimers());
    expect(onNavigateToUserMessage).toHaveBeenCalledExactlyOnceWith(
      expect.objectContaining({ messageId: "user-1" }),
      "append-newer",
    );
    act(() => {
      historyMessageWindow.setCanLoadNewer("chat-1", false);
      historyMessageWindow.setTurnRows(
        "chat-1",
        [[{ id: "user-6", role: "user" }]] as never[][],
        false,
      );
      vi.runAllTimers();
    });
    act(() => vi.runAllTimers());
    expect(onNavigateToUserMessage).toHaveBeenCalledTimes(1);
    clientHeight.mockRestore();
    scrollHeight.mockRestore();
    vi.useRealTimers();
  });

  it("fills following context after a directory jump, not the nearby older edge", () => {
    const older = vi.fn();
    const newer = vi.fn(() => historyMessageWindow.setLoading("chat-1", true));
    historyMessageWindow.begin({
      sessionId: "chat-1",
      turnRows: [[{ id: "user-2", role: "user" }]] as never[][],
      canLoadOlder: true,
      onLoadOlder: older,
      onFillOlder: older,
      onNavigateToUserMessage: newer,
    });
    historyMessageWindow.setLoading("chat-1", false);
    const { container } = render(
      createElement(
        "div",
        { className: "qwenpaw-chat-anywhere-message-list" },
        createElement(HistoryMessageWindowCard),
      ),
    );
    const scroll = container.querySelector<HTMLElement>(
      "[data-history-message-window]",
    )!;
    Object.defineProperties(scroll, {
      clientHeight: { value: 800 },
      scrollHeight: { value: 1000 },
    });
    act(() => scroll.dispatchEvent(new Event("chat-history-navigated")));
    expect(older).not.toHaveBeenCalled();
    expect(newer).toHaveBeenCalledExactlyOnceWith(
      expect.objectContaining({ messageId: "user-2" }),
      "append-newer",
    );
  });

  it("loads an unloaded target with following context through an opaque anchor", async () => {
    const onNavigateToUserMessage = vi.fn();
    const onCancelPending = vi.fn();
    historyMessageWindow.begin({
      sessionId: "chat-1",
      turnRows: [
        [
          { id: "user-2", role: "user", cards: [] },
          { id: "assistant-2", role: "assistant", cards: [] },
        ],
      ] as never[][],
      canLoadOlder: true,
      userMessages: [
        {
          messageId: "user-0",
          preview: "earlier message",
          createdAt: "2026-10-23T00:00:00Z",
          anchor: "opaque-anchor-0",
        },
        {
          messageId: "user-1",
          preview: "first message",
          createdAt: "2026-10-23T01:00:00Z",
          anchor: "opaque-anchor-1",
        },
        {
          messageId: "user-2",
          preview: "second message",
          createdAt: "2026-10-23T02:00:00Z",
          anchor: "opaque-anchor-2",
        },
      ],
      onLoadOlder: vi.fn(),
      onFillOlder: vi.fn(),
      onNavigateToUserMessage,
      onCancelPending,
    });
    historyMessageWindow.setLoading("chat-1", false);

    const { getByLabelText } = renderWithNavigation();
    await act(async () => {});
    act(() => fireEvent.click(getByLabelText("Previous user message")));

    expect(onNavigateToUserMessage).toHaveBeenCalledExactlyOnceWith(
      expect.objectContaining({
        messageId: "user-1",
        anchor: "opaque-anchor-1",
      }),
      "replace",
    );
    expect(onCancelPending).toHaveBeenCalledOnce();
  });

  it("lets a new wheel intent cancel an unfinished navigation", async () => {
    const onCancelPending = vi.fn();
    historyMessageWindow.begin({
      sessionId: "chat-1",
      turnRows: [
        [
          { id: "user-2", role: "user", cards: [] },
          { id: "assistant-2", role: "assistant", cards: [] },
        ],
      ] as never[][],
      canLoadOlder: true,
      userMessages: [
        {
          messageId: "user-0",
          preview: "earlier message",
          createdAt: "2026-10-23T00:00:00Z",
          anchor: "opaque-anchor-0",
        },
        {
          messageId: "user-1",
          preview: "first message",
          createdAt: "2026-10-23T01:00:00Z",
          anchor: "opaque-anchor-1",
        },
        {
          messageId: "user-2",
          preview: "second message",
          createdAt: "2026-10-23T02:00:00Z",
          anchor: "opaque-anchor-2",
        },
      ],
      onLoadOlder: vi.fn(),
      onFillOlder: vi.fn(),
      onNavigateToUserMessage: vi.fn(),
      onCancelPending,
    });
    historyMessageWindow.setLoading("chat-1", false);

    const { container, getByLabelText } = renderWithNavigation();
    await act(async () => {});
    const window = container.querySelector<HTMLElement>(
      "[data-history-message-window]",
    );
    act(() => fireEvent.click(getByLabelText("Previous user message")));
    act(() => fireEvent.wheel(window!, { deltaY: 10 }));

    expect(onCancelPending).toHaveBeenCalledTimes(2);
  });
});
