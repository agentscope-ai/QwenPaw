import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./modules/auth", () => ({
  authApi: { refresh: vi.fn() },
}));

vi.mock("./config", () => ({
  getApiAuthMode: vi.fn(() => "multi_user"),
  getApiToken: vi.fn(() => ""),
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
  restoreAccessSession,
} from "./authSession";

describe("authSession", () => {
  afterEach(() => vi.unstubAllGlobals());
  beforeEach(() => {
    vi.clearAllMocks();
    clearAccessSession();
  });

  it("ignores a delayed cross-tab logout for a different device", async () => {
    vi.resetModules();
    const session = await import("./authSession");
    let receive!: (message: MessageEvent) => void;
    vi.stubGlobal(
      "BroadcastChannel",
      class {
        set onmessage(handler: (message: MessageEvent) => void) {
          receive = handler;
        }
        postMessage() {}
      },
    );
    session.adoptAccessSession({
      token: "bravo",
      username: "bravo",
      session: { id: "device-b", client_info: {} },
    });
    receive(
      new MessageEvent("message", {
        data: { type: "cleared", sessionId: "device-a" },
      }),
    );
    expect(session.getDeviceSessionId()).toBe("device-b");
    receive(
      new MessageEvent("message", {
        data: { type: "cleared", sessionId: "device-b" },
      }),
    );
    expect(session.getDeviceSessionId()).toBe("");
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

  it("keeps cross-tab refresh blocked until bootstrap identity verification completes", async () => {
    let queue = Promise.resolve();
    vi.stubGlobal("navigator", {
      locks: {
        request: (_name: string, callback: () => Promise<unknown>) => {
          const result = queue.then(callback);
          queue = result.then(
            () => undefined,
            () => undefined,
          );
          return result;
        },
      },
    });
    vi.mocked(authApi.refresh).mockResolvedValue({
      token: "fresh",
      username: "admin",
      access_expires_at: new Date(Date.now() + 900_000).toISOString(),
    });
    let finishIdentity: (value: string) => void = () => undefined;
    const identity = vi.fn(
      () =>
        new Promise<string>((resolve) => {
          finishIdentity = resolve;
        }),
    );
    const restoring = restoreAccessSession(identity);
    await vi.waitFor(() => expect(identity).toHaveBeenCalledOnce());
    const refreshing = refreshAccessSession();
    await Promise.resolve();
    expect(authApi.refresh).toHaveBeenCalledOnce();
    finishIdentity("verified");
    expect((await restoring).identity).toBe("verified");
    expect(await refreshing).toBe(true);
    expect(authApi.refresh).toHaveBeenCalledTimes(2);
  });

  it("does not restore identity after logout during account verification", async () => {
    vi.mocked(authApi.refresh).mockResolvedValue({
      token: "fresh",
      username: "admin",
    });
    let finish!: (value: string) => void;
    const identify = vi.fn(
      () =>
        new Promise<string>((resolve) => {
          finish = resolve;
        }),
    );
    const restoring = restoreAccessSession(identify);
    await vi.waitFor(() => expect(identify).toHaveBeenCalledOnce());
    clearAccessSession();
    finish("stale identity");
    await expect(restoring).rejects.toThrow("Authentication context changed");
  });
});
