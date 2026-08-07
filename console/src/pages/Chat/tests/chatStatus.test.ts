/**
 * queryChatStatus is the single-shot status probe used by the queue
 * watchdog and waitForChatIdle. It must distinguish a *confirmed* state
 * ("running"/"idle") from an *undetermined* one ("unknown"): a transient
 * network failure must never be taken as proof that the chat is idle,
 * otherwise the watchdog could clear loading and send the next queued
 * message while the previous turn is still running (out-of-order send).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../api/config", () => ({
  getApiUrl: (p: string) => `http://api.test${p}`,
}));
vi.mock("../../../api/authHeaders", () => ({
  buildAuthHeaders: () => ({ Authorization: "test" }),
}));

import {
  queryChatStatus,
  shouldResetStuckLoading,
  waitForChatIdle,
} from "../chatStatus";

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
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

  it('returns "running" when the backend reports running', async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      jsonResponse({ status: "running" }),
    );
    await expect(queryChatStatus("chat-1")).resolves.toBe("running");
    expect(fetch).toHaveBeenCalledWith(
      "http://api.test/chats/chat-1",
      expect.objectContaining({ headers: { Authorization: "test" } }),
    );
  });

  it('returns "idle" when the backend reports a non-running status', async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      jsonResponse({ status: "idle" }),
    );
    await expect(queryChatStatus("chat-1")).resolves.toBe("idle");
  });

  it('returns "idle" on 404 — a non-existent chat cannot be running', async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      jsonResponse({ detail: "not found" }, 404),
    );
    await expect(queryChatStatus("missing")).resolves.toBe("idle");
  });

  it('returns "unknown" on a non-404 HTTP error (e.g. 500)', async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      jsonResponse({ detail: "boom" }, 500),
    );
    await expect(queryChatStatus("chat-1")).resolves.toBe("unknown");
  });

  it('returns "unknown" when fetch rejects (network error)', async () => {
    (fetch as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error("boom"),
    );
    await expect(queryChatStatus("chat-1")).resolves.toBe("unknown");
  });

  it('returns "unknown" when the body has no usable status', async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      jsonResponse({ status: 42 }),
    );
    await expect(queryChatStatus("chat-1")).resolves.toBe("unknown");
  });

  it('returns "unknown" without fetching for an empty chat id', async () => {
    await expect(queryChatStatus("")).resolves.toBe("unknown");
    expect(fetch).not.toHaveBeenCalled();
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
});

describe("shouldResetStuckLoading", () => {
  it("resets only on a confirmed idle backend state", () => {
    expect(shouldResetStuckLoading("idle")).toBe(true);
    expect(shouldResetStuckLoading("running")).toBe(false);
  });

  it("does NOT reset when the status is unknown (previous turn may still run)", () => {
    // Regression for the review finding: a transient network failure must
    // not be treated as idle, or the next queued message could send while
    // the previous turn is still generating.
    expect(shouldResetStuckLoading("unknown")).toBe(false);
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

  it("returns true when the status probe fails (does not block the queue)", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error("backend gone"),
    );
    const ctrl = new AbortController();
    await expect(waitForChatIdle("chat-1", ctrl.signal)).resolves.toBe(true);
  });
});
