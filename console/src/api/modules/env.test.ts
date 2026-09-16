/**
 * Tests for api/modules/env.ts
 *
 * Contract guard for the write-only secret API.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("../request", () => ({
  request: vi.fn(),
}));

import { envApi } from "./env";
import { request } from "../request";

describe("envApi", () => {
  beforeEach(() => {
    vi.mocked(request).mockReset();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("listEnvs returns the EnvVar[] from request", async () => {
    const envs = [
      { key: "API_KEY", configured: true },
      { key: "DEBUG", configured: true },
    ];
    vi.mocked(request).mockResolvedValue(envs);
    const result = await envApi.listEnvs();
    expect(result).toEqual(envs);
  });

  it("updateEnvs sends explicit operations and returns masked state", async () => {
    const updated = [{ key: "K", configured: true }];
    const operations = [{ key: "K", action: "replace" as const, value: "V" }];
    vi.mocked(request).mockResolvedValue(updated);
    const result = await envApi.updateEnvs(operations);
    expect(result).toBe(updated);
    expect(request).toHaveBeenCalledWith("/envs", {
      method: "PUT",
      body: JSON.stringify({ operations }),
    });
  });

  it("propagates request errors", async () => {
    vi.mocked(request).mockRejectedValue(new Error("conflict"));
    await expect(envApi.updateEnvs([])).rejects.toThrow("conflict");
  });
});
