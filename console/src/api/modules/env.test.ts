/**
 * Tests for api/modules/env.ts
 *
 * Contract-guard style: verify return pass-through.  `saveEnvs` is a
 * full-replacement batch op; `deleteEnv` removes one key.  We verify
 * shape and error propagation, not exact request body strings (#5438).
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
      { key: "API_KEY", value: "v1", is_secret: true },
      { key: "DEBUG", value: "false", is_secret: false },
    ];
    vi.mocked(request).mockResolvedValue(envs);
    const result = await envApi.listEnvs();
    expect(result).toEqual(envs);
  });

  it("saveEnvs returns the full updated EnvVar[] after batch save", async () => {
    const updated = [{ key: "K", value: "V", is_secret: false }];
    vi.mocked(request).mockResolvedValue(updated);
    const result = await envApi.saveEnvs({ K: "V" });
    expect(result).toBe(updated);
  });

  it("deleteEnv returns the remaining EnvVar[] after deletion", async () => {
    const remaining = [{ key: "OTHER", value: "x", is_secret: false }];
    vi.mocked(request).mockResolvedValue(remaining);
    const result = await envApi.deleteEnv("OLD_KEY");
    expect(result).toBe(remaining);
  });

  it("propagates request errors", async () => {
    vi.mocked(request).mockRejectedValue(new Error("conflict"));
    await expect(envApi.saveEnvs({})).rejects.toThrow("conflict");
  });
});
