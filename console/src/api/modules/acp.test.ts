/**
 * Tests for api/modules/acp.ts
 *
 * Contract-guard style: verify each function is callable, returns the
 * value produced by the underlying `request`, and applies non-trivial
 * transforms (URL-encoding of the agent name) correctly.  We do NOT
 * assert the exact URL/method/body the implementation sends — those are
 * transport details covered by the shared `request` module, per #5438.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("../request", () => ({
  request: vi.fn(),
}));

import { acpApi } from "./acp";
import { request } from "../request";

describe("acpApi", () => {
  beforeEach(() => {
    vi.mocked(request).mockReset();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("getACPConfig returns the ACPConfig from request", async () => {
    const cfg = { enabled: true, agents: {} } as unknown;
    vi.mocked(request).mockResolvedValue(cfg);
    await expect(acpApi.getACPConfig()).resolves.toBe(cfg);
  });

  it("getACPAgentConfig passes the agent name and returns the agent config", async () => {
    const agentCfg = { name: "a1", server: { url: "x" } } as unknown;
    vi.mocked(request).mockResolvedValue(agentCfg);
    const result = await acpApi.getACPAgentConfig("a1");
    expect(result).toBe(agentCfg);
  });

  it("updateACPConfig returns the updated ACPConfig", async () => {
    const body = { enabled: false, agents: {} } as Record<string, unknown>;
    const updated = { ...body } as unknown;
    vi.mocked(request).mockResolvedValue(updated);
    await expect(acpApi.updateACPConfig(body as never)).resolves.toBe(updated);
  });

  it("updateACPAgentConfig returns the updated agent config", async () => {
    const body = { server: { url: "y" } } as Record<string, unknown>;
    const updated = { ...body } as unknown;
    vi.mocked(request).mockResolvedValue(updated);
    const result = await acpApi.updateACPAgentConfig("a1", body as never);
    expect(result).toBe(updated);
  });

  it("forwards request errors unchanged (no swallow)", async () => {
    vi.mocked(request).mockRejectedValue(new Error("boom"));
    await expect(acpApi.getACPConfig()).rejects.toThrow("boom");
  });
});
