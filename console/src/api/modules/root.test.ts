/**
 * Tests for api/modules/root.ts
 *
 * Contract-guard style: verify return pass-through only.  Both methods
 * are thin wrappers; per #5438 we do not assert the URL they send.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("../request", () => ({
  request: vi.fn(),
}));

import { rootApi } from "./root";
import { request } from "../request";

describe("rootApi", () => {
  beforeEach(() => {
    vi.mocked(request).mockReset();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("readRoot returns whatever request resolves to", async () => {
    vi.mocked(request).mockResolvedValue({ ok: true });
    await expect(rootApi.readRoot()).resolves.toEqual({ ok: true });
  });

  it("getVersion returns the { version } payload", async () => {
    vi.mocked(request).mockResolvedValue({ version: "1.2.3" });
    await expect(rootApi.getVersion()).resolves.toEqual({ version: "1.2.3" });
  });

  it("propagates request errors", async () => {
    vi.mocked(request).mockRejectedValue(new Error("500"));
    await expect(rootApi.getVersion()).rejects.toThrow("500");
  });
});
