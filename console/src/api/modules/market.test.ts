/**
 * Tests for api/modules/market.ts
 *
 * Contract-guard style: verify return pass-through for the three endpoint
 * wrappers and the search-result shape that the UI depends on (results,
 * errors, by_provider pagination info).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("../request", () => ({
  request: vi.fn(),
}));

import { marketApi } from "./market";
import { request } from "../request";

describe("marketApi", () => {
  beforeEach(() => {
    vi.mocked(request).mockReset();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("listMarketProviders resolves to MarketProviderInfo[]", async () => {
    const providers = [
      {
        key: "hub",
        label: "Hub",
        available: true,
        reason: null,
        supports_browse: true,
      },
      {
        key: "claw",
        label: "ClawHub",
        available: false,
        reason: "not configured",
        supports_browse: false,
      },
    ];
    vi.mocked(request).mockResolvedValue(providers);
    const result = await marketApi.listMarketProviders();
    expect(result).toEqual(providers);
  });

  it("listMarketCategories resolves to MarketCategory[]", async () => {
    const cats = [
      { id: "agent", label: "Agents" },
      { id: "tool", label: "Tools" },
    ];
    vi.mocked(request).mockResolvedValue(cats);
    const result = await marketApi.listMarketCategories("en");
    expect(result).toEqual(cats);
  });

  it("searchMarket returns a MarketSearchResponse with results, errors, by_provider", async () => {
    const payload = {
      results: [
        {
          source: "hub",
          slug: "qwen-agent",
          name: "Qwen Agent",
          description: "an agent",
          source_url: "https://x",
          version: "1.0.0",
          author: "team",
          icon_url: null,
          stats: null,
        },
      ],
      errors: [{ provider: "claw", message: "unavailable" }],
      by_provider: { hub: { has_more: false, total: 1 } },
    };
    vi.mocked(request).mockResolvedValue(payload);
    const r = await marketApi.searchMarket({
      query: "qwen",
      provider_pages: { hub: 1 },
    });
    expect(r).toEqual(payload);
  });

  it("searchMarket tolerates an empty results array (UI shows 'no matches')", async () => {
    const payload = {
      results: [],
      errors: [],
      by_provider: {},
    };
    vi.mocked(request).mockResolvedValue(payload);
    const r = await marketApi.searchMarket({
      query: "zzz",
      provider_pages: {},
    });
    expect(r.results).toEqual([]);
  });

  it("propagates request errors", async () => {
    vi.mocked(request).mockRejectedValue(new Error("timeout"));
    await expect(marketApi.listMarketProviders()).rejects.toThrow("timeout");
  });
});
