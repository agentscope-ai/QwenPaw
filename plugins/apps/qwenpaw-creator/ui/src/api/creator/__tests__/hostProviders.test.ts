import { afterEach, describe, expect, it, vi } from "vitest";
import { getHostProviders } from "../models";

afterEach(() => vi.unstubAllGlobals());

describe("host provider catalog", () => {
  it("uses the host base path and keeps the returned providers", async () => {
    const providers = [{ id: "local", name: "Local" }];
    const fetch = vi.fn().mockResolvedValue(Response.json(providers));
    vi.stubGlobal("fetch", fetch);
    vi.stubGlobal("QwenPaw", {
      host: { getApiUrl: (p: string) => `/app/api${p}` },
    });
    await expect(getHostProviders()).resolves.toEqual(providers);
    expect(fetch.mock.calls[0][0]).toBe("/app/api/models");
  });

  it("distinguishes a failed lookup from a successful empty catalog on retry", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(new Response(null, { status: 404 }))
      .mockResolvedValueOnce(Response.json([]));
    vi.stubGlobal("fetch", fetch);
    await expect(getHostProviders()).rejects.toMatchObject({ status: 404 });
    await expect(getHostProviders()).resolves.toEqual([]);
    expect(fetch.mock.calls[1][0]).toBe("/api/models");
  });
});
