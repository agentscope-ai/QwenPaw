/**
 * queryChatStatus is the single-shot status probe used by both queue send
 * paths — the foreground watchdog (scheduleNextSend) and the background
 * sender (waitForChatIdle). It must distinguish a *confirmed* state
 * ("running"/"idle") from an *undetermined* one ("unknown"): a transient
 * network failure must never be taken as proof that the chat is idle, or
 * the next queued message could be sent while the previous turn is still
 * running on the backend (out-of-order send).
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

  it("does not release the queue while the status is unknown", async () => {
    // A transient network failure must not release the background sender:
    // the prior turn could still be running, and sending now would break
    // ordering. waitForChatIdle keeps polling with its backoff instead.
    (fetch as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error("backend gone"),
    );
    const ctrl = new AbortController();
    const waiting = waitForChatIdle("chat-1", ctrl.signal);
    const outcome = await Promise.race([
      waiting.then(() => "released"),
      new Promise<string>((resolve) =>
        setTimeout(() => resolve("still-waiting"), 20),
      ),
    ]);
    expect(outcome).toBe("still-waiting");
    ctrl.abort();
    await expect(waiting).resolves.toBe(false);
  });

  it("releases on 404 — a non-existent chat is confirmed idle", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      jsonResponse({ detail: "not found" }, 404),
    );
    const ctrl = new AbortController();
    await expect(waitForChatIdle("missing", ctrl.signal)).resolves.toBe(true);
  });
});
