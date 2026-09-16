import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./modules/auth", () => ({
  authApi: { refresh: vi.fn() },
}));

vi.mock("./config", () => ({
  getApiAuthMode: vi.fn(() => "multi_user"),
  setAuthToken: vi.fn(),
  clearAuthToken: vi.fn(),
}));

import { setAuthToken } from "./config";
import { authApi } from "./modules/auth";
import {
  adoptAccessSession,
  clearAccessSession,
  ensureAccessSessionFresh,
  refreshAccessSession,
} from "./authSession";

describe("authSession", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    clearAccessSession();
  });

  it("coalesces concurrent refresh requests", async () => {
    let resolveRefresh: (value: {
      token: string;
      username: string;
      access_expires_at: string;
    }) => void = () => undefined;
    vi.mocked(authApi.refresh).mockReturnValue(
      new Promise((resolve) => {
        resolveRefresh = resolve;
      }),
    );

    const first = refreshAccessSession();
    const second = refreshAccessSession();
    resolveRefresh({
      token: "renewed",
      username: "admin",
      access_expires_at: new Date(Date.now() + 15 * 60_000).toISOString(),
    });

    await expect(Promise.all([first, second])).resolves.toEqual([true, true]);
    expect(authApi.refresh).toHaveBeenCalledOnce();
    expect(setAuthToken).toHaveBeenCalledWith("renewed");
  });

  it("refreshes before a known access token expires", async () => {
    adoptAccessSession({
      token: "short-lived",
      username: "admin",
      access_expires_at: new Date(Date.now() + 20_000).toISOString(),
    });
    vi.mocked(authApi.refresh).mockResolvedValue({
      token: "renewed",
      username: "admin",
      access_expires_at: new Date(Date.now() + 15 * 60_000).toISOString(),
    });

    await expect(ensureAccessSessionFresh()).resolves.toBe(true);
    expect(authApi.refresh).toHaveBeenCalledOnce();
  });
});
