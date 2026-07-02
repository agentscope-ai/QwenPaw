import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("../config", () => ({
  getApiUrl: vi.fn((p: string) => "http://test" + p),
}));
vi.mock("../authHeaders", () => ({
  buildAuthHeaders: vi.fn(() => ({})),
}));

import {
  fetchPlugins,
  fetchPluginCatalog,
  installPlugin,
  uploadPlugin,
  uninstallPlugin,
  fetchPluginStatus,
} from "./plugin";
import { getApiUrl } from "../config";
import { buildAuthHeaders } from "../authHeaders";

interface MockResponseOptions {
  ok: boolean;
  status: number;
  json?: unknown;
  text?: string;
}

function mockResponse({
  ok,
  status,
  json,
  text,
}: MockResponseOptions): Response {
  return {
    ok,
    status,
    json: async () => json,
    text: async () => text ?? "",
  } as unknown as Response;
}

describe("plugin module", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("fetchPlugins returns parsed list on success", async () => {
    const plugins = [{ id: "p1", name: "Plugin One" }];
    global.fetch = vi
      .fn()
      .mockResolvedValue(
        mockResponse({ ok: true, status: 200, json: plugins }),
      );

    const result = await fetchPlugins();

    expect(result).toEqual(plugins);
    expect(fetch).toHaveBeenCalledWith("http://test/plugins", {
      headers: {},
    });
  });

  it("fetchPlugins returns empty array on failure and does not throw", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    global.fetch = vi
      .fn()
      .mockResolvedValue(mockResponse({ ok: false, status: 500, json: {} }));

    const result = await fetchPlugins();

    expect(result).toEqual([]);
    expect(warnSpy).toHaveBeenCalledWith(
      "[plugin] Failed to fetch plugin list:",
      500,
    );
  });

  it("fetchPluginCatalog returns parsed catalog on success", async () => {
    const catalog = { updated_at: null, plugins: [] };
    global.fetch = vi
      .fn()
      .mockResolvedValue(
        mockResponse({ ok: true, status: 200, json: catalog }),
      );

    const result = await fetchPluginCatalog();

    expect(result).toEqual(catalog);
    expect(getApiUrl).toHaveBeenCalledWith("/plugins/catalog");
  });

  it("fetchPluginCatalog throws with body.detail on failure", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      mockResponse({
        ok: false,
        status: 502,
        json: { detail: "Upstream down" },
      }),
    );

    await expect(fetchPluginCatalog()).rejects.toThrow("Upstream down");
  });

  it("fetchPluginCatalog throws fallback message when body has no detail", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValue(mockResponse({ ok: false, status: 503, json: {} }));

    await expect(fetchPluginCatalog()).rejects.toThrow(
      "Failed to load plugin catalog (503)",
    );
  });

  it("installPlugin posts JSON with force defaulting to false", async () => {
    const res = { id: "p1", name: "n", message: "ok" };
    global.fetch = vi
      .fn()
      .mockResolvedValue(mockResponse({ ok: true, status: 200, json: res }));

    const result = await installPlugin("/local/path");

    expect(result).toEqual(res);
    expect(fetch).toHaveBeenCalledWith("http://test/plugins/install", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source: "/local/path", force: false }),
    });
  });

  it("installPlugin forwards force when provided and throws detail on failure", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      mockResponse({
        ok: false,
        status: 400,
        json: { detail: "Already installed" },
      }),
    );

    await expect(installPlugin("http://x/y", { force: true })).rejects.toThrow(
      "Already installed",
    );
    const [, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [
      string,
      RequestInit,
    ];
    expect(JSON.parse(init.body as string)).toEqual({
      source: "http://x/y",
      force: true,
    });
  });

  it("uploadPlugin posts FormData and returns json on success", async () => {
    const res = { id: "p1", name: "n" };
    global.fetch = vi
      .fn()
      .mockResolvedValue(mockResponse({ ok: true, status: 200, json: res }));

    const file = new File(["zip"], "p.zip", { type: "application/zip" });
    const result = await uploadPlugin(file);

    expect(result).toEqual(res);
    expect(buildAuthHeaders).toHaveBeenCalled();
    const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [
      string,
      RequestInit,
    ];
    expect(url).toBe("http://test/plugins/upload");
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
    expect((init.body as FormData).get("file")).toBe(file);
  });

  it("uninstallPlugin resolves void on success and DELETEs by id", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValue(mockResponse({ ok: true, status: 204, json: null }));

    await expect(uninstallPlugin("p1")).resolves.toBeUndefined();
    expect(fetch).toHaveBeenCalledWith("http://test/plugins/p1", {
      method: "DELETE",
      headers: {},
    });
  });

  it("uninstallPlugin throws fallback message on failure", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValue(mockResponse({ ok: false, status: 500, json: {} }));

    await expect(uninstallPlugin("p1")).rejects.toThrow(
      "Uninstall failed (500)",
    );
  });

  it("fetchPluginStatus throws Status fetch failed on non-ok", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValue(mockResponse({ ok: false, status: 404, json: {} }));

    await expect(fetchPluginStatus("missing")).rejects.toThrow(
      "Status fetch failed (404)",
    );
    expect(getApiUrl).toHaveBeenCalledWith("/plugins/missing/status");
  });
});
