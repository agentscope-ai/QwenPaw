import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("../request", () => ({
  request: vi.fn(),
}));

import { consoleApi } from "./console";
import { request } from "../request";

describe("consoleApi", () => {
  beforeEach(() => {
    vi.mocked(request).mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("getPushMessages without sessionId calls GET /console/push-messages", async () => {
    const data = { messages: [], pending_approvals: [] };
    vi.mocked(request).mockResolvedValue(data);
    const result = await consoleApi.getPushMessages();
    expect(request).toHaveBeenCalledWith("/console/push-messages");
    expect(result).toEqual(data);
  });

  it("getPushMessages with sessionId appends session_id query", async () => {
    const data = { messages: [], pending_approvals: [] };
    vi.mocked(request).mockResolvedValue(data);
    const result = await consoleApi.getPushMessages("sess-1");
    expect(request).toHaveBeenCalledWith(
      "/console/push-messages?session_id=sess-1",
    );
    expect(result).toEqual(data);
  });

  it("getInboxEvents builds ordered query string with multiple params", async () => {
    const data = { events: [] };
    vi.mocked(request).mockResolvedValue(data);
    const result = await consoleApi.getInboxEvents({
      limit: 200,
      offset: 10,
      source_type: "cron",
      unread_only: true,
    });
    expect(request).toHaveBeenCalledWith(
      "/console/inbox/events?limit=200&offset=10&source_type=cron&unread_only=true",
    );
    expect(result).toEqual(data);
  });

  it("getInboxEvents without params calls GET without query", async () => {
    const data = { events: [] };
    vi.mocked(request).mockResolvedValue(data);
    await consoleApi.getInboxEvents();
    expect(request).toHaveBeenCalledWith("/console/inbox/events");
  });

  it("markInboxRead posts payload body (event_ids and all variants)", async () => {
    // event_ids variant
    const resp1 = { updated: 1 };
    vi.mocked(request).mockResolvedValue(resp1);
    const r1 = await consoleApi.markInboxRead({ event_ids: ["e1", "e2"] });
    expect(request).toHaveBeenCalledWith("/console/inbox/read", {
      method: "POST",
      body: JSON.stringify({ event_ids: ["e1", "e2"] }),
    });
    expect(r1).toEqual(resp1);

    // all variant
    const resp2 = { updated: 5 };
    vi.mocked(request).mockResolvedValue(resp2);
    const r2 = await consoleApi.markInboxRead({ all: true });
    expect(request).toHaveBeenCalledWith("/console/inbox/read", {
      method: "POST",
      body: JSON.stringify({ all: true }),
    });
    expect(r2).toEqual(resp2);
  });

  it("deleteInboxEvent URL-encodes eventId (slash handled)", async () => {
    const resp = { deleted: true, trace_deleted: false, run_id: null };
    vi.mocked(request).mockResolvedValue(resp);
    const result = await consoleApi.deleteInboxEvent("a/b");
    expect(request).toHaveBeenCalledWith("/console/inbox/events/a%2Fb", {
      method: "DELETE",
    });
    expect(result).toEqual(resp);
  });

  it("getInboxTrace URL-encodes runId", async () => {
    const trace = {
      run_id: "r/1",
      created_at: 0,
      completed_at: null,
      status: "ok",
      meta: {},
      events: [],
    };
    vi.mocked(request).mockResolvedValue(trace);
    const result = await consoleApi.getInboxTrace("r/1");
    expect(request).toHaveBeenCalledWith("/console/inbox/traces/r%2F1");
    expect(result).toEqual(trace);
  });
});
