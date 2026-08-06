/**
 * queryChatStatus is the single-shot status probe used by the queue
 * watchdog and waitForChatIdle. Unknown/failed lookups must yield null
 * (treated as idle by callers) so the queue is never blocked forever.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../api/config", () => ({
  getApiUrl: (p: string) => `http://api.test${p}`,
}));
vi.mock("../../../api/authHeaders", () => ({
  buildAuthHeaders: () => ({ Authorization: "test" }),
}));

import { queryChatStatus, waitForChatIdle } from "../chatStatus";

function jsonResponse(body: unknown, ok = true): Response {
  return {
    ok,
    status: ok ? 200 : 404,
    json: async () => body,
  } as unknown as Response;
}

describe("queryChatStatus", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns the status string on a 200 response", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      jsonResponse({ status: "running" }),
    );
    await expect(queryChatStatus("chat-1")).resolves.toBe("running");
    expect(fetch).toHaveBeenCalledWith(
      "http://api.test/chats/chat-1",
      expect.objectContaining({ headers: { Authorization: "test" } }),
    );
  });

  it("sends the X-Agent-Id header when an agentId is provided", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      jsonResponse({ status: "idle" }),
    );
    await queryChatStatus("chat-1", "agent-9");
    expect(fetch).toHaveBeenCalledWith(
      "http://api.test/chats/chat-1",
      expect.objectContaining({
        headers: { Authorization: "test", "X-Agent-Id": "agent-9" },
      }),
    );
  });

  it("returns null on a non-2xx response (404)", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      jsonResponse({ detail: "not found" }, false),
    );
    await expect(queryChatStatus("missing")).resolves.toBeNull();
  });

  it("returns null when fetch rejects (network error)", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error("boom"),
    );
    await expect(queryChatStatus("chat-1")).resolves.toBeNull();
  });

  it("returns null when the body has no usable status", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      jsonResponse({ status: 42 }),
    );
    await expect(queryChatStatus("chat-1")).resolves.toBeNull();
  });

  it("returns null without fetching for an empty chat id", async () => {
    await expect(queryChatStatus("")).resolves.toBeNull();
    expect(fetch).not.toHaveBeenCalled();
  });
});

describe("waitForChatIdle", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns true immediately when the chat is idle", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      jsonResponse({ status: "idle" }),
    );
    const ctrl = new AbortController();
    await expect(waitForChatIdle("chat-1", ctrl.signal)).resolves.toBe(true);
  });

  it("returns true without fetching for an empty chat id", async () => {
    const ctrl = new AbortController();
    await expect(waitForChatIdle("", ctrl.signal)).resolves.toBe(true);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("returns false when already aborted", async () => {
    const ctrl = new AbortController();
    ctrl.abort();
    await expect(waitForChatIdle("chat-1", ctrl.signal)).resolves.toBe(false);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("treats an unknown status (null) as idle", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error("backend gone"),
    );
    const ctrl = new AbortController();
    await expect(waitForChatIdle("chat-1", ctrl.signal)).resolves.toBe(true);
  });
});
