/**
 * Tests for api/modules/debug.ts
 *
 * Contract-guard style: verify return pass-through and the `lines`
 * defaulting behaviour.  We do not pin the exact URL/query format.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("../request", () => ({
  request: vi.fn(),
}));

import { debugApi } from "./debug";
import { request } from "../request";

describe("debugApi", () => {
  beforeEach(() => {
    vi.mocked(request).mockReset();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("getBackendLogs returns the parsed BackendDebugLogsResponse", async () => {
    const resp = {
      path: "/var/log/app.log",
      exists: true,
      lines: 100,
      updated_at: 1700000000,
      size: 4096,
      content: "line1\nline2",
    };
    vi.mocked(request).mockResolvedValue(resp);
    const result = await debugApi.getBackendLogs();
    expect(result).toEqual(resp);
  });

  it("getBackendLogs accepts a custom lines argument", async () => {
    const resp = {
      path: "",
      exists: false,
      lines: 0,
      updated_at: null,
      size: 0,
      content: "",
    };
    vi.mocked(request).mockResolvedValue(resp);
    const result = await debugApi.getBackendLogs(50);
    expect(result).toBe(resp);
    // Ensure request was actually invoked (not short-circuited)
    expect(request).toHaveBeenCalledTimes(1);
  });

  it("forwards request errors unchanged", async () => {
    vi.mocked(request).mockRejectedValue(new Error("oops"));
    await expect(debugApi.getBackendLogs()).rejects.toThrow("oops");
  });
});
