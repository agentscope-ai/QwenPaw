import { beforeEach, describe, expect, it, vi } from "vitest";
const state = vi.hoisted(() => ({ token: "user-a", mode: "hub" }));
vi.mock("../../api/config", () => ({
  getApiToken: () => state.token,
  getApiUrl: (path: string) => `/api${path}`,
  updateBrowserSession: (operation: () => Promise<unknown>) => operation(),
}));
vi.mock("../../auth/gate", () => ({
  resolveBackendMode: async () => state.mode,
}));
beforeEach(() => {
  vi.resetModules();
  state.token = "user-a";
  state.mode = "hub";
});
describe("PawApp browser sessions", () => {
  it("deduplicates pending grants and prepares again after account changes", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue({ ok: true, json: async () => ({ expires_in: 900 }) });
    vi.stubGlobal("fetch", fetcher);
    const sdk = await import("./browserSession");
    await Promise.all([
      sdk.prepareBrowserSession("creator"),
      sdk.prepareBrowserSession("creator"),
    ]);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher.mock.calls[0][1].headers.Authorization).toBe(
      "Bearer user-a",
    );
    expect(sdk.usesBrowserSession("creator")).toBe(true);
    state.token = "user-b";
    expect(sdk.usesBrowserSession("creator")).toBe(true);
    await sdk.prepareBrowserSession("creator");
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
  it("does not call Hub endpoints in standalone mode", async () => {
    state.mode = "standard";
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    const sdk = await import("./browserSession");
    expect(await sdk.prepareBrowserSession("creator")).toBeNull();
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("fails closed on rejected sessions", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 401 }),
    );
    const sdk = await import("./browserSession");
    await expect(sdk.prepareBrowserSession("creator")).rejects.toThrow("401");
    expect(sdk.usesBrowserSession("creator")).toBe(true);
  });
});
