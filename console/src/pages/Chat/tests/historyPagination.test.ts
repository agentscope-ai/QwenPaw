/**
 * Session history pagination: opening a chat requests a latest window,
 * load-earlier uses metadata.original_id, and partial windows are never
 * treated as the full canonical history.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import type { ChatHistory, Message } from "../../../api";
import api from "../../../api";
import sessionApi from "../sessionApi";
import { DEFAULT_HISTORY_PAGE_SIZE } from "../sessionApi/historyWindow";
import { setHistoryPageSize } from "../sessionApi/historyPageSize";

interface SessionApiTestAccess {
  sessionList: Array<Record<string, unknown>>;
  convertedSessionCache: Map<unknown, unknown>;
  sessionResultCache: Map<unknown, unknown>;
  sessionRequests: Map<unknown, unknown>;
  lastSelectedIds: Set<unknown>;
}

const testApi = sessionApi as unknown as SessionApiTestAccess;

function msg(originalId: string, text: string, role = "user"): Message {
  return {
    id: `uuid-${originalId}`,
    role,
    content: [{ type: "text", text }],
    metadata: { original_id: originalId, timestamp: "2026-08-01 10:00:00.000" },
  } as Message;
}

function history(
  messages: Message[],
  extras: {
    has_more?: boolean;
    total?: number;
    status?: "idle" | "running";
  } = {},
): ChatHistory {
  return {
    messages,
    status: extras.status ?? "idle",
    has_more: extras.has_more ?? false,
    total: extras.total ?? messages.length,
  };
}

function seedSession(id: string): void {
  testApi.sessionList = [
    { id, sessionId: id, userId: "u", channel: "console", name: "t" },
  ];
}

describe("SessionApi history pagination", () => {
  beforeEach(() => {
    sessionApi.resetForTests();
    sessionApi.setActiveAgent("agent-a");
    testApi.lastSelectedIds.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    sessionApi.resetForTests();
  });

  it("opens a chat with the latest N messages, not full history", async () => {
    seedSession("chat-page");
    const getChat = vi.spyOn(api, "getChat").mockResolvedValue(
      history([msg("m40", "a"), msg("m41", "b")], {
        has_more: true,
        total: 80,
      }),
    );

    const session = await sessionApi.getSession("chat-page");
    expect(getChat).toHaveBeenCalledWith("chat-page", {
      signal: undefined,
      include_app_owned: false,
      limit: DEFAULT_HISTORY_PAGE_SIZE,
    });
    expect(sessionApi.getHistoryPage("chat-page")).toMatchObject({
      hasMore: true,
      total: 80,
      oldestOriginalId: "m40",
    });
    expect((session as { hasMore?: boolean }).hasMore).toBe(true);
  });

  it("load earlier uses before = oldest original_id and prepends", async () => {
    seedSession("chat-page");
    vi.spyOn(api, "getChat")
      .mockResolvedValueOnce(
        history(
          [msg("m40", "recent-user"), msg("m41", "recent-asst", "assistant")],
          { has_more: true, total: 4 },
        ),
      )
      .mockResolvedValueOnce(
        history(
          [msg("m38", "older-user"), msg("m39", "older-asst", "assistant")],
          { has_more: false, total: 4 },
        ),
      );

    const first = await sessionApi.getSession("chat-page");
    const initialCount = (first.messages || []).length;
    expect(initialCount).toBeGreaterThan(0);

    const { prepended } = await sessionApi.loadEarlierMessages("chat-page");
    expect(api.getChat).toHaveBeenLastCalledWith("chat-page", {
      signal: undefined,
      include_app_owned: false,
      limit: DEFAULT_HISTORY_PAGE_SIZE,
      before: "m40",
    });
    expect(prepended.length).toBeGreaterThan(0);
    expect(sessionApi.getHistoryPage("chat-page").hasMore).toBe(false);

    const cached = await sessionApi.getSession("chat-page");
    expect((cached.messages || []).length).toBeGreaterThan(initialCount);
  });

  it("does not treat a partial window as full canonical history in the LRU cache", async () => {
    seedSession("chat-partial");
    const getChat = vi
      .spyOn(api, "getChat")
      .mockResolvedValue(
        history([msg("m90", "tail")], { has_more: true, total: 200 }),
      );

    await sessionApi.getSession("chat-partial");
    await sessionApi.getSession("chat-partial");
    expect(getChat).toHaveBeenCalledTimes(1);

    const page = sessionApi.getHistoryPage("chat-partial");
    expect(page.hasMore).toBe(true);
    expect(page.total).toBe(200);
  });

  it("stale-cursor overlap is not prepended and exhausts has_more", async () => {
    seedSession("chat-stale");
    vi.spyOn(api, "getChat")
      .mockResolvedValueOnce(
        history([msg("m2", "a"), msg("m3", "b")], {
          has_more: true,
          total: 4,
        }),
      )
      .mockResolvedValueOnce(
        history([msg("m2", "a"), msg("m3", "b")], {
          has_more: true,
          total: 4,
        }),
      );

    await sessionApi.getSession("chat-stale");
    const { prepended } = await sessionApi.loadEarlierMessages("chat-stale");
    expect(prepended).toEqual([]);
    expect(sessionApi.getHistoryPage("chat-stale").hasMore).toBe(false);
  });

  it("a stale owner epoch cannot apply a load-earlier result", async () => {
    seedSession("chat-owner");
    vi.spyOn(api, "getChat").mockResolvedValueOnce(
      history([msg("m2", "a")], { has_more: true, total: 3 }),
    );
    await sessionApi.getSession("chat-owner");

    let resolveChat: (value: ChatHistory) => void = () => undefined;
    vi.spyOn(api, "getChat").mockImplementationOnce(
      () =>
        new Promise<ChatHistory>((resolve) => {
          resolveChat = resolve;
        }),
    );

    const pending = sessionApi.loadEarlierMessages("chat-owner");
    sessionApi.setActiveAgent("agent-b");
    resolveChat(history([msg("m0", "old")], { has_more: false, total: 3 }));

    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
    expect(sessionApi.getHistoryPage("chat-owner").hasMore).toBe(false);
  });

  it("getHistoryPage returns the same object until the page is updated", async () => {
    seedSession("chat-stable");
    vi.spyOn(api, "getChat").mockResolvedValue(
      history([msg("m1", "a")], { has_more: true, total: 2 }),
    );
    await sessionApi.getSession("chat-stable");
    const first = sessionApi.getHistoryPage("chat-stable");
    const second = sessionApi.getHistoryPage("chat-stable");
    expect(first).toBe(second);
    expect(sessionApi.getHistoryPage(null)).toBe(
      sessionApi.getHistoryPage(undefined),
    );
  });

  it("opens a chat with the stored page size, not a hardcoded 50", async () => {
    seedSession("chat-n");
    setHistoryPageSize(20);
    const getChat = vi
      .spyOn(api, "getChat")
      .mockResolvedValue(
        history([msg("m1", "a")], { has_more: true, total: 40 }),
      );
    await sessionApi.getSession("chat-n");
    expect(getChat).toHaveBeenCalledWith("chat-n", {
      signal: undefined,
      include_app_owned: false,
      limit: 20,
    });
  });

  it("load earlier uses the stored page size", async () => {
    seedSession("chat-n");
    setHistoryPageSize(20);
    vi.spyOn(api, "getChat")
      .mockResolvedValueOnce(
        history([msg("m2", "a")], { has_more: true, total: 4 }),
      )
      .mockResolvedValueOnce(
        history([msg("m1", "older")], { has_more: false, total: 4 }),
      );
    await sessionApi.getSession("chat-n");
    await sessionApi.loadEarlierMessages("chat-n");
    expect(api.getChat).toHaveBeenLastCalledWith("chat-n", {
      signal: undefined,
      include_app_owned: false,
      limit: 20,
      before: "m2",
    });
  });

  it("changing N refetches the latest window with the new limit", async () => {
    seedSession("chat-n");
    vi.spyOn(api, "getChat")
      .mockResolvedValueOnce(
        history([msg("m50", "tail")], { has_more: true, total: 80 }),
      )
      .mockResolvedValueOnce(
        history([msg("m1", "older"), msg("m50", "tail")], {
          has_more: false,
          total: 80,
        }),
      );
    await sessionApi.getSession("chat-n");
    expect(sessionApi.getHistoryPage("chat-n").hasMore).toBe(true);

    setHistoryPageSize(200);
    await sessionApi.reloadAfterPageSizeChange("chat-n");
    expect(api.getChat).toHaveBeenLastCalledWith("chat-n", {
      signal: undefined,
      include_app_owned: false,
      limit: 200,
    });
    expect(sessionApi.getHistoryPage("chat-n").hasMore).toBe(false);
  });
});
