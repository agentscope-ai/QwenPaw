// @vitest-environment jsdom
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ mode: vi.fn(), token: vi.fn() }));
vi.mock("../../auth/gate", () => ({ resolveBackendMode: mocks.mode }));
vi.mock("../../api/config", () => ({
  getApiToken: mocks.token,
  getApiUrl: (path: string) => `/api${path}`,
  updateBrowserSession: (operation: () => Promise<unknown>) => operation(),
}));

describe("PawApp browser sessions", () => {
  beforeEach(() => {
    vi.resetModules();
    mocks.token.mockReturnValue("account-token");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ expires_in: 900 }),
      }),
    );
  });
  afterEach(() => vi.unstubAllGlobals());

  it("leaves standalone manifest IDs alone", async () => {
    mocks.mode.mockResolvedValue("standalone");
    const { prepareBrowserSession } = await import("./browserSession");
    expect(await prepareBrowserSession("my_app")).toBeNull();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("encodes the manifest ID and deduplicates pending requests", async () => {
    mocks.mode.mockResolvedValue("hub");
    const { prepareBrowserSession } = await import("./browserSession");
    const first = prepareBrowserSession("我的_App");
    expect(prepareBrowserSession("我的_App")).toBe(first);
    expect(await first).toBe(900);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch).toHaveBeenCalledWith(
      `/api/hub/pawapps/${encodeURIComponent("我的_App")}/session`,
      expect.objectContaining({ credentials: "same-origin" }),
    );
  });
});
