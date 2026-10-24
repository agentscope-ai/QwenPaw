import { describe, it, expect, vi } from "vitest";
import { createRecordingApi } from "../src/api";

const mocks = vi.hoisted(() => ({ fetch: vi.fn() }));
vi.mock("../src/host", () => ({ host: mocks }));

describe("recording API workspace binding", () => {
  it("keeps an existing Learn request on its captured agent", async () => {
    mocks.fetch.mockResolvedValue({ ok: true, json: async () => ({}) });
    const original = createRecordingApi("agent-a");
    const later = createRecordingApi("agent-b");
    await later.getStatus();
    await original.generateDraft("consent-a");
    expect(mocks.fetch.mock.calls[0][1].headers["X-Agent-Id"]).toBe("agent-b");
    expect(mocks.fetch.mock.calls[1][1].headers["X-Agent-Id"]).toBe("agent-a");
  });
  it("does not retry an uncertain mutation", async () => {
    mocks.fetch.mockReset().mockRejectedValue(new Error("connection lost"));
    await expect(createRecordingApi("agent-a").start()).rejects.toThrow(
      "connection lost",
    );
    expect(mocks.fetch).toHaveBeenCalledTimes(1);
  });
});
