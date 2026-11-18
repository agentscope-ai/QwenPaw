/**
 * Contract tests for api/modules/pluginMarket.ts
 *
 * Scope: `fetchMarketPlugins` - query-string construction, auth header and
 * abort-signal pass-through, and the three error-mapping arms (HTTP failure
 * with `detail`, with `message`, and with an unusable body) plus the
 * `success: false` envelope arm.
 *
 * Assertions target the request contract the UI depends on (which params reach
 * the server, which error text surfaces to the user), not transport internals.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const mocks = vi.hoisted(() => ({
  getApiUrl: vi.fn((p: string) => `/api${p}`),
  buildAuthHeaders: vi.fn(() => ({
    Authorization: "Bearer tok",
    "X-Agent-Id": "agent-1",
  })),
}));

vi.mock("../config", () => ({ getApiUrl: mocks.getApiUrl }));
vi.mock("../authHeaders", () => ({ buildAuthHeaders: mocks.buildAuthHeaders }));

import {
  fetchMarketPlugins,
  type FetchMarketPluginsParams,
  type MarketPluginEntry,
} from "./pluginMarket";

const ORIGIN = "http://localhost:3000";

interface FetchInit {
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

/** Install a fetch stub and return helpers to inspect what it received. */
function stubFetch(response: Partial<Response>) {
  const fn = vi.fn().mockResolvedValue(response as Response);
  global.fetch = fn;
  return {
    fn,
    url: () => new URL(String(fn.mock.calls[0][0])),
    init: () => (fn.mock.calls[0][1] ?? {}) as FetchInit,
    rawUrl: () => String(fn.mock.calls[0][0]),
  };
}

function jsonResponse(payload: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  } as unknown as Response;
}

function baseParams(
  overrides: Partial<FetchMarketPluginsParams> = {},
): FetchMarketPluginsParams {
  return { page_number: 1, page_size: 20, ...overrides };
}

const entry: MarketPluginEntry = {
  id: "@acme/demo",
  display_name: "Demo",
  developer: "acme",
  owner: "acme",
  version: "1.0.0",
  logo_url: null,
  downloads: 3,
  view_count: 9,
  details_url: null,
  locales: { en: { description: "d", category: "app" } },
};

beforeEach(() => {
  mocks.getApiUrl.mockClear();
  mocks.buildAuthHeaders.mockClear();
});

afterEach(() => {
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

describe("fetchMarketPlugins request contract", () => {
  it("always sends pagination params even when no filter is given", async () => {
    const f = stubFetch(
      jsonResponse({
        success: true,
        message: "",
        data: { total: 0, plugins: [] },
      }),
    );
    await fetchMarketPlugins(baseParams({ page_number: 3, page_size: 50 }));

    const url = f.url();
    expect(url.origin + url.pathname).toBe(
      `${ORIGIN}/api/plugins/market/search`,
    );
    expect(url.searchParams.get("page_number")).toBe("3");
    expect(url.searchParams.get("page_size")).toBe("50");
  });

  it("omits every optional filter when the params are absent", async () => {
    const f = stubFetch(
      jsonResponse({
        success: true,
        message: "",
        data: { total: 0, plugins: [] },
      }),
    );
    await fetchMarketPlugins(baseParams());

    for (const key of [
      "search",
      "category",
      "sort_by",
      "is_featured",
      "is_trending",
    ]) {
      expect(f.url().searchParams.has(key)).toBe(false);
    }
  });

  it("omits optional filters that are present but falsy", async () => {
    const f = stubFetch(
      jsonResponse({
        success: true,
        message: "",
        data: { total: 0, plugins: [] },
      }),
    );
    await fetchMarketPlugins(
      baseParams({
        search: "",
        category: "",
        is_featured: false,
        is_trending: false,
      }),
    );

    for (const key of ["search", "category", "is_featured", "is_trending"]) {
      expect(f.url().searchParams.has(key)).toBe(false);
    }
  });

  it("forwards search, category and sort_by verbatim", async () => {
    const f = stubFetch(
      jsonResponse({
        success: true,
        message: "",
        data: { total: 0, plugins: [] },
      }),
    );
    await fetchMarketPlugins(
      baseParams({ search: "pdf 工具", category: "App", sort_by: "fauvarate" }),
    );

    const p = f.url().searchParams;
    expect(p.get("search")).toBe("pdf 工具");
    expect(p.get("category")).toBe("App");
    expect(p.get("sort_by")).toBe("fauvarate");
  });

  it("serialises the two boolean filters as the literal string true", async () => {
    const f = stubFetch(
      jsonResponse({
        success: true,
        message: "",
        data: { total: 0, plugins: [] },
      }),
    );
    await fetchMarketPlugins(
      baseParams({ is_featured: true, is_trending: true }),
    );

    expect(f.url().searchParams.get("is_featured")).toBe("true");
    expect(f.url().searchParams.get("is_trending")).toBe("true");
  });

  it("sends the auth headers built for the current agent", async () => {
    const f = stubFetch(
      jsonResponse({
        success: true,
        message: "",
        data: { total: 0, plugins: [] },
      }),
    );
    await fetchMarketPlugins(baseParams());

    expect(mocks.buildAuthHeaders).toHaveBeenCalledTimes(1);
    expect(f.init().headers).toEqual({
      Authorization: "Bearer tok",
      "X-Agent-Id": "agent-1",
    });
  });

  it("passes the caller abort signal through to fetch", async () => {
    const f = stubFetch(
      jsonResponse({
        success: true,
        message: "",
        data: { total: 0, plugins: [] },
      }),
    );
    const controller = new AbortController();
    await fetchMarketPlugins(baseParams(), { signal: controller.signal });

    expect(f.init().signal).toBe(controller.signal);
  });

  it("leaves the signal undefined when the caller passes no options", async () => {
    const f = stubFetch(
      jsonResponse({
        success: true,
        message: "",
        data: { total: 0, plugins: [] },
      }),
    );
    await fetchMarketPlugins(baseParams());

    expect(f.init().signal).toBeUndefined();
  });
});

describe("fetchMarketPlugins success envelope", () => {
  it("returns the data payload without the envelope", async () => {
    stubFetch(
      jsonResponse({
        success: true,
        message: "ok",
        data: { total: 1, plugins: [entry] },
      }),
    );
    const result = await fetchMarketPlugins(baseParams());

    expect(result).toEqual({ total: 1, plugins: [entry] });
  });

  it("keeps an empty plugin list as-is rather than substituting a default", async () => {
    stubFetch(
      jsonResponse({
        success: true,
        message: "",
        data: { total: 0, plugins: [] },
      }),
    );
    const result = await fetchMarketPlugins(baseParams());

    expect(result.plugins).toEqual([]);
    expect(result.total).toBe(0);
  });
});

describe("fetchMarketPlugins failure mapping", () => {
  it("throws with the server detail when the HTTP call fails", async () => {
    stubFetch(jsonResponse({ detail: "rate limited" }, 429));

    await expect(fetchMarketPlugins(baseParams())).rejects.toThrow(
      "rate limited",
    );
  });

  it("falls back to the server message when there is no detail", async () => {
    stubFetch(jsonResponse({ message: "bad gateway" }, 502));

    await expect(fetchMarketPlugins(baseParams())).rejects.toThrow(
      "bad gateway",
    );
  });

  it("prefers detail over message when the server sends both", async () => {
    stubFetch(
      jsonResponse({ detail: "from detail", message: "from message" }, 500),
    );

    await expect(fetchMarketPlugins(baseParams())).rejects.toThrow(
      "from detail",
    );
  });

  it("builds a status-bearing message when the body carries neither field", async () => {
    stubFetch(jsonResponse({}, 503));

    await expect(fetchMarketPlugins(baseParams())).rejects.toThrow(
      "Failed to fetch market plugins (503)",
    );
  });

  it("builds a status-bearing message when the error body is not JSON", async () => {
    const f = stubFetch({
      ok: false,
      status: 500,
      json: async () => {
        throw new SyntaxError("Unexpected token < in JSON");
      },
    } as unknown as Response);

    await expect(fetchMarketPlugins(baseParams())).rejects.toThrow(
      "Failed to fetch market plugins (500)",
    );
    expect(f.fn).toHaveBeenCalledTimes(1);
  });

  it("treats a null detail as absent and falls through to the status message", async () => {
    stubFetch(jsonResponse({ detail: null }, 404));

    await expect(fetchMarketPlugins(baseParams())).rejects.toThrow(
      "Failed to fetch market plugins (404)",
    );
  });

  it("throws the envelope message when success is false", async () => {
    stubFetch(
      jsonResponse({ success: false, message: "quota exhausted", data: null }),
    );

    await expect(fetchMarketPlugins(baseParams())).rejects.toThrow(
      "quota exhausted",
    );
  });

  it("throws the generic text when success is false with an empty message", async () => {
    stubFetch(jsonResponse({ success: false, message: "", data: null }));

    await expect(fetchMarketPlugins(baseParams())).rejects.toThrow(
      "Failed to fetch market plugins",
    );
  });

  it("does not return data when success is false", async () => {
    stubFetch(
      jsonResponse({
        success: false,
        message: "nope",
        data: { total: 5, plugins: [entry] },
      }),
    );

    await expect(fetchMarketPlugins(baseParams())).rejects.toThrow("nope");
  });

  it("propagates a network rejection from fetch unchanged", async () => {
    global.fetch = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));

    await expect(fetchMarketPlugins(baseParams())).rejects.toThrow(
      "Failed to fetch",
    );
  });
});
