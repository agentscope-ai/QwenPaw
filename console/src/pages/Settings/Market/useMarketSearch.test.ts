/**
 * useMarketSearch orchestrates provider selection, debounced search,
 * cursor-based pagination and error blocking for the skill market.
 * Regression family: settings round-trip (provider selection survives
 * refresh, #6242/#3824 config-loss family) + endless auto-retry loops
 * when a provider keeps failing.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ i18n: { language: "en" } }),
}));

const mocks = vi.hoisted(() => ({
  listMarketProviders: vi.fn(),
  listMarketCategories: vi.fn(),
  searchMarket: vi.fn(),
}));

vi.mock("../../../api/modules/market", () => ({
  marketApi: {
    listMarketProviders: mocks.listMarketProviders,
    listMarketCategories: mocks.listMarketCategories,
    searchMarket: mocks.searchMarket,
  },
}));

import { useMarketSearch } from "./useMarketSearch";

const PROVIDERS_KEY = "qwenpaw-market-providers";

const emptyResponse = { by_provider: {}, results: [], errors: [] };

const qwenpaw = { key: "qwenpaw", name: "QwenPaw", available: true };
const github = { key: "github", name: "GitHub", available: true };

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

async function mount() {
  const utils = renderHook(() => useMarketSearch());
  await flush();
  return utils;
}

describe("useMarketSearch", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    localStorage.clear();
    mocks.listMarketProviders.mockReset().mockResolvedValue([qwenpaw, github]);
    mocks.listMarketCategories.mockReset().mockResolvedValue([]);
    mocks.searchMarket.mockReset().mockResolvedValue(emptyResponse);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("loads providers on mount and falls back to qwenpaw selection", async () => {
    const { result } = await mount();
    expect(result.current.providers).toEqual([qwenpaw, github]);
    expect([...result.current.selectedProviderKeys]).toEqual(["qwenpaw"]);
  });

  it("keeps previously selected providers restored from localStorage", async () => {
    localStorage.setItem(PROVIDERS_KEY, JSON.stringify(["github"]));
    const { result } = await mount();
    expect([...result.current.selectedProviderKeys]).toEqual(["github"]);
  });

  it("drops restored providers that are no longer available", async () => {
    localStorage.setItem(PROVIDERS_KEY, JSON.stringify(["stale-key"]));
    const { result } = await mount();
    // stale-key not enabled → fallback to qwenpaw
    expect([...result.current.selectedProviderKeys]).toEqual(["qwenpaw"]);
  });

  it("falls back to the first enabled provider when qwenpaw is unavailable", async () => {
    mocks.listMarketProviders.mockResolvedValue([
      { key: "aliyun", name: "Aliyun", available: true },
      { key: "qwenpaw", name: "QwenPaw", available: false },
    ]);
    const { result } = await mount();
    expect([...result.current.selectedProviderKeys]).toEqual(["aliyun"]);
  });

  it("reports a global error and clears providers when the fetch fails", async () => {
    mocks.listMarketProviders.mockRejectedValue(new Error("backend down"));
    const { result } = await mount();
    expect(result.current.providers).toEqual([]);
    expect(result.current.globalError).toBe("backend down");
  });

  it("persists the provider selection to localStorage", async () => {
    const { result } = await mount();
    act(() => {
      result.current.setSelectedProviders(["github"]);
    });
    await flush();
    expect(JSON.parse(localStorage.getItem(PROVIDERS_KEY)!)).toEqual([
      "github",
    ]);
  });

  it("ignores corrupted localStorage selection gracefully", async () => {
    localStorage.setItem(PROVIDERS_KEY, "{not json");
    const { result } = await mount();
    // Falls back to qwenpaw without throwing
    expect([...result.current.selectedProviderKeys]).toEqual(["qwenpaw"]);
  });

  it("loads categories for the current language", async () => {
    mocks.listMarketCategories.mockResolvedValue([
      { id: "tools", name: "Tools" },
    ]);
    const { result } = await mount();
    expect(mocks.listMarketCategories).toHaveBeenCalledWith("en");
    expect(result.current.categories).toEqual([{ id: "tools", name: "Tools" }]);
  });

  it("runs the initial browse search once providers are selected", async () => {
    await mount();
    expect(mocks.searchMarket).toHaveBeenCalledWith(
      expect.objectContaining({
        query: "",
        provider_pages: { qwenpaw: 1 },
        limit: 10,
        lang: "en",
        category: undefined,
      }),
    );
  });

  it("debounces the query by 350ms and trims it", async () => {
    const { result } = await mount();
    mocks.searchMarket.mockClear();

    act(() => {
      result.current.setQuery("  web  ");
    });
    // Before the debounce window closes nothing fires
    expect(mocks.searchMarket).not.toHaveBeenCalled();

    await act(async () => {
      vi.advanceTimersByTime(349);
    });
    expect(mocks.searchMarket).not.toHaveBeenCalled();

    await act(async () => {
      vi.advanceTimersByTime(1);
    });
    await flush();
    expect(mocks.searchMarket).toHaveBeenCalledWith(
      expect.objectContaining({ query: "web" }),
    );
  });

  it("replaces results on a new search and sums provider totals", async () => {
    mocks.listMarketProviders.mockResolvedValue([qwenpaw, github]);
    localStorage.setItem(PROVIDERS_KEY, JSON.stringify(["qwenpaw", "github"]));
    mocks.searchMarket.mockResolvedValue({
      by_provider: {
        qwenpaw: { has_more: true, total: 25 },
        github: { has_more: false, total: 10 },
      },
      results: [{ id: "r1" }],
      errors: [],
    });
    const { result } = await mount();
    await flush();
    expect(result.current.results).toEqual([{ id: "r1" }]);
    expect(result.current.totalCount).toBe(35);
    expect(result.current.hasMore).toBe(true);
  });

  it("appends results on loadMore and exhausts when has_more is false", async () => {
    mocks.searchMarket
      .mockResolvedValueOnce({
        by_provider: { qwenpaw: { has_more: true, total: 20 } },
        results: [{ id: "page1" }],
        errors: [],
      })
      .mockResolvedValueOnce({
        by_provider: { qwenpaw: { has_more: false, total: 20 } },
        results: [{ id: "page2" }],
        errors: [],
      });
    const { result } = await mount();
    await flush();
    expect(result.current.results).toEqual([{ id: "page1" }]);

    act(() => {
      result.current.loadMore();
    });
    await flush();
    expect(result.current.results).toEqual([{ id: "page1" }, { id: "page2" }]);
    // Second request asks for page 2
    expect(mocks.searchMarket).toHaveBeenLastCalledWith(
      expect.objectContaining({ provider_pages: { qwenpaw: 2 } }),
    );
    expect(result.current.hasMore).toBe(false);
  });

  it("blocks auto-loading after a batch with provider errors", async () => {
    mocks.searchMarket.mockResolvedValue({
      by_provider: { qwenpaw: { has_more: true, total: 5 } },
      results: [{ id: "r1" }],
      errors: [{ provider: "qwenpaw", error: "timeout" }],
    });
    const { result } = await mount();
    await flush();
    expect(result.current.autoLoadBlocked).toBe(true);
    expect(result.current.errors).toHaveLength(1);

    const callsBefore = mocks.searchMarket.mock.calls.length;
    act(() => {
      result.current.autoLoadMore();
    });
    await flush();
    // Blocked: no retry storm
    expect(mocks.searchMarket.mock.calls.length).toBe(callsBefore);
  });

  it("autoLoadMore is a no-op once cursors are exhausted", async () => {
    // Real timers here: waitFor polls via real timers and deadlocks under fake timers.
    vi.useRealTimers();
    mocks.searchMarket.mockResolvedValue({
      by_provider: { qwenpaw: { has_more: false, total: 0 } },
      results: [],
      errors: [],
    });
    const { result } = await mount();
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });
    // has_more:false nulls the cursor, so there is no next page to fetch
    expect(result.current.hasMore).toBe(false);
    mocks.searchMarket.mockClear();
    act(() => {
      result.current.autoLoadMore();
    });
    await flush();
    expect(mocks.searchMarket).not.toHaveBeenCalled();
  });

  it("manual loadMore re-arms auto-loading after an error block", async () => {
    mocks.searchMarket
      .mockResolvedValueOnce({
        by_provider: { qwenpaw: { has_more: true, total: 9 } },
        results: [],
        errors: [{ provider: "qwenpaw", error: "x" }],
      })
      .mockResolvedValueOnce({
        by_provider: { qwenpaw: { has_more: false, total: 9 } },
        results: [{ id: "recovered" }],
        errors: [],
      });
    const { result } = await mount();
    await flush();
    expect(result.current.autoLoadBlocked).toBe(true);

    act(() => {
      result.current.loadMore();
    });
    await flush();
    expect(result.current.autoLoadBlocked).toBe(false);
  });

  it("sets a global error and blocks auto-load when the search rejects", async () => {
    mocks.searchMarket.mockRejectedValue(new Error("search exploded"));
    const { result } = await mount();
    await flush();
    expect(result.current.globalError).toBe("search exploded");
    expect(result.current.autoLoadBlocked).toBe(true);
    expect(result.current.results).toEqual([]);
    expect(result.current.hasMore).toBe(false);
  });

  it("typing a query clears the active category", async () => {
    const { result } = await mount();
    act(() => {
      result.current.setCategory("tools");
    });
    await flush();
    expect(result.current.category).toBe("tools");

    act(() => {
      result.current.setQuery("agent");
    });
    await act(async () => {
      vi.advanceTimersByTime(350);
    });
    await flush();
    expect(result.current.category).toBe("");
  });

  it("sends the category with the search request when set", async () => {
    const { result } = await mount();
    mocks.searchMarket.mockClear();
    act(() => {
      result.current.setCategory("tools");
    });
    await flush();
    expect(mocks.searchMarket).toHaveBeenCalledWith(
      expect.objectContaining({ category: "tools" }),
    );
  });

  it("clears results when there is nothing to query", async () => {
    mocks.listMarketProviders.mockResolvedValue([]);
    const { result } = await mount();
    await flush();
    expect(result.current.results).toEqual([]);
    expect(result.current.hasMore).toBe(false);
    expect(mocks.searchMarket).not.toHaveBeenCalled();
  });

  it("retry refetches providers when none were loaded", async () => {
    mocks.listMarketProviders
      .mockRejectedValueOnce(new Error("down"))
      .mockResolvedValueOnce([qwenpaw]);
    const { result } = await mount();
    await flush();
    expect(result.current.globalError).toBe("down");

    act(() => {
      result.current.retry();
    });
    await flush();
    expect(mocks.listMarketProviders).toHaveBeenCalledTimes(2);
    expect(result.current.providers).toEqual([qwenpaw]);
  });

  it("refresh resets cursors and refetches from page 1", async () => {
    const { result } = await mount();
    await flush();
    mocks.searchMarket.mockClear();

    act(() => {
      result.current.refresh();
    });
    await flush();
    expect(mocks.searchMarket).toHaveBeenCalledWith(
      expect.objectContaining({ provider_pages: { qwenpaw: 1 } }),
    );
  });
});
