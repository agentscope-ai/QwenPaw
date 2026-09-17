/**
 * Tests for api/modules/heartbeat.ts
 *
 * Contract-guard style: verify return pass-through and that the three
 * operations (get / update / run-now) are independently callable.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("../request", () => ({
  request: vi.fn(),
}));

import { heartbeatApi } from "./heartbeat";
import { request } from "../request";

describe("heartbeatApi", () => {
  beforeEach(() => {
    vi.mocked(request).mockReset();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("getHeartbeatConfig returns the config object", async () => {
    const cfg = {
      enabled: true,
      interval_seconds: 60,
      agents: [],
      prompt: "ping",
    } as unknown;
    vi.mocked(request).mockResolvedValue(cfg);
    const result = await heartbeatApi.getHeartbeatConfig();
    expect(result).toBe(cfg);
  });

  it("updateHeartbeatConfig returns the persisted config", async () => {
    const body = {
      enabled: true,
      interval_seconds: 120,
      agents: [],
      prompt: "ping",
    } as unknown;
    vi.mocked(request).mockResolvedValue(body);
    const result = await heartbeatApi.updateHeartbeatConfig(body as never);
    expect(result).toBe(body);
  });

  it("runHeartbeatNow returns { started: true } when the backend accepts the trigger", async () => {
    vi.mocked(request).mockResolvedValue({ started: true });
    await expect(heartbeatApi.runHeartbeatNow()).resolves.toEqual({
      started: true,
    });
  });

  it("runHeartbeatNow returns { started: false } when a run is already in-flight", async () => {
    vi.mocked(request).mockResolvedValue({ started: false });
    await expect(heartbeatApi.runHeartbeatNow()).resolves.toEqual({
      started: false,
    });
  });

  it("propagates request errors", async () => {
    vi.mocked(request).mockRejectedValue(new Error("busy"));
    await expect(heartbeatApi.runHeartbeatNow()).rejects.toThrow("busy");
  });
});
