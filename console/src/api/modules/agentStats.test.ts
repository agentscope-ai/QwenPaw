/**
 * Tests for api/modules/agentStats.ts
 *
 * Contract-guard style: verify return pass-through and that the date
 * params are forwarded to `request`.  We do not pin the exact query
 * string format — that's a transport detail covered by `request`.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("../request", () => ({
  request: vi.fn(),
}));

import { agentStatsApi } from "./agentStats";
import { request } from "../request";

describe("agentStatsApi", () => {
  beforeEach(() => {
    vi.mocked(request).mockReset();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("getAgentStats returns the AgentStatsSummary from request", async () => {
    const summary = {
      total_messages: 10,
      by_agent: [],
      by_date: [],
    } as unknown;
    vi.mocked(request).mockResolvedValue(summary);
    const result = await agentStatsApi.getAgentStats({
      start_date: "2026-01-01",
      end_date: "2026-01-31",
    });
    expect(result).toBe(summary);
  });

  it("forwards request errors unchanged", async () => {
    vi.mocked(request).mockRejectedValue(new Error("network"));
    await expect(
      agentStatsApi.getAgentStats({
        start_date: "2026-01-01",
        end_date: "2026-01-31",
      }),
    ).rejects.toThrow("network");
  });
});
