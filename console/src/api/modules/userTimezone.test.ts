/**
 * Tests for api/modules/userTimezone.ts
 *
 * Contract-guard style: verify return pass-through and that the
 * updated timezone is reflected in the resolved value.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("../request", () => ({
  request: vi.fn(),
}));

import { userTimezoneApi } from "./userTimezone";
import { request } from "../request";

describe("userTimezoneApi", () => {
  beforeEach(() => {
    vi.mocked(request).mockReset();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("getUserTimezone returns the stored timezone config", async () => {
    vi.mocked(request).mockResolvedValue({ timezone: "Asia/Shanghai" });
    await expect(userTimezoneApi.getUserTimezone()).resolves.toEqual({
      timezone: "Asia/Shanghai",
    });
  });

  it("updateUserTimezone returns the persisted config", async () => {
    vi.mocked(request).mockResolvedValue({ timezone: "Europe/London" });
    await expect(
      userTimezoneApi.updateUserTimezone("Europe/London"),
    ).resolves.toEqual({ timezone: "Europe/London" });
  });

  it("propagates request errors", async () => {
    vi.mocked(request).mockRejectedValue(new Error("forbidden"));
    await expect(userTimezoneApi.getUserTimezone()).rejects.toThrow(
      "forbidden",
    );
  });
});
