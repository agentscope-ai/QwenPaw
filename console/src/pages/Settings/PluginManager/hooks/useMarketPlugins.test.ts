// @vitest-environment jsdom
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MarketPluginEntry } from "@/api/modules/pluginMarket";

const hoisted = vi.hoisted(() => ({
  fetchMarketPlugins: vi.fn(),
  installPlugin: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@/hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: { success: vi.fn(), error: vi.fn() },
  }),
}));

vi.mock("@/api/modules/pluginMarket", () => ({
  fetchMarketPlugins: hoisted.fetchMarketPlugins,
  buildMarketDownloadUrl: vi.fn(() => "https://example.com/plugin.zip"),
}));

vi.mock("@/api/modules/plugin", () => ({
  installPlugin: hoisted.installPlugin,
}));

import { useMarketPlugins } from "./useMarketPlugins";

function makeEntry(id: string): MarketPluginEntry {
  return {
    id,
    display_name: id,
    developer: "developer",
    owner: "owner",
    version: "1.0.0",
    logo_url: null,
    downloads: 1,
    view_count: 1,
    details_url: null,
    locales: { en: { description: id, category: "general" } },
  };
}

describe("useMarketPlugins", () => {
  beforeEach(() => {
    hoisted.fetchMarketPlugins.mockReset();
    hoisted.installPlugin.mockReset();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ version: "2.0.0" }),
      }),
    );
  });

  it("loads 20 plugins initially and appends page two", async () => {
    const firstPage = Array.from({ length: 20 }, (_, index) =>
      makeEntry(`plugin-${index}`),
    );
    hoisted.fetchMarketPlugins.mockImplementation(({ page_number }) =>
      Promise.resolve(
        page_number === 1
          ? { plugins: firstPage, total: 21 }
          : { plugins: [makeEntry("plugin-20")], total: 21 },
      ),
    );

    const { result } = renderHook(() =>
      useMarketPlugins({ onInstalled: vi.fn() }),
    );

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(hoisted.fetchMarketPlugins).toHaveBeenCalledWith(
      expect.objectContaining({ page_number: 1, page_size: 20 }),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(result.current.plugins).toHaveLength(20);
    expect(result.current.hasMore).toBe(true);

    act(() => result.current.handleLoadMore());

    await waitFor(() => expect(result.current.plugins).toHaveLength(21));
    expect(hoisted.fetchMarketPlugins).toHaveBeenLastCalledWith(
      expect.objectContaining({ page_number: 2, page_size: 20 }),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(result.current.hasMore).toBe(false);
  });

  it("resets to page one when the category changes", async () => {
    hoisted.fetchMarketPlugins.mockResolvedValue({ plugins: [], total: 0 });
    const { result } = renderHook(() =>
      useMarketPlugins({ onInstalled: vi.fn() }),
    );
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => result.current.handleCategoryChange("agent-tool"));

    await waitFor(() =>
      expect(hoisted.fetchMarketPlugins).toHaveBeenCalledTimes(2),
    );
    expect(hoisted.fetchMarketPlugins).toHaveBeenLastCalledWith(
      expect.objectContaining({
        category: "agent-tool",
        page_number: 1,
        page_size: 20,
      }),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it("uses the application market parameters for featured and trending", async () => {
    hoisted.fetchMarketPlugins.mockResolvedValue({ plugins: [], total: 0 });
    const { result } = renderHook(() =>
      useMarketPlugins({ onInstalled: vi.fn() }),
    );
    await waitFor(() => expect(result.current.loading).toBe(false));

    const initialParams = hoisted.fetchMarketPlugins.mock.calls[0]?.[0];
    expect(initialParams).not.toHaveProperty("is_featured");
    expect(initialParams).not.toHaveProperty("is_trending");

    act(() => result.current.handleHighlightFilterChange("featured"));
    await waitFor(() =>
      expect(hoisted.fetchMarketPlugins).toHaveBeenLastCalledWith(
        expect.objectContaining({
          is_featured: true,
          page_number: 1,
          page_size: 20,
        }),
        expect.objectContaining({ signal: expect.any(AbortSignal) }),
      ),
    );
    expect(
      hoisted.fetchMarketPlugins.mock.calls[
        hoisted.fetchMarketPlugins.mock.calls.length - 1
      ]?.[0],
    ).not.toHaveProperty("is_trending");

    act(() => result.current.handleHighlightFilterChange("trending"));
    await waitFor(() =>
      expect(hoisted.fetchMarketPlugins).toHaveBeenLastCalledWith(
        expect.objectContaining({
          is_trending: true,
          page_number: 1,
          page_size: 20,
        }),
        expect.objectContaining({ signal: expect.any(AbortSignal) }),
      ),
    );
    expect(
      hoisted.fetchMarketPlugins.mock.calls[
        hoisted.fetchMarketPlugins.mock.calls.length - 1
      ]?.[0],
    ).not.toHaveProperty("is_featured");
  });

  it("keeps featured and category filters mutually exclusive", async () => {
    hoisted.fetchMarketPlugins.mockResolvedValue({ plugins: [], total: 0 });
    const { result } = renderHook(() =>
      useMarketPlugins({ onInstalled: vi.fn() }),
    );
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => result.current.handleHighlightFilterChange("featured"));
    await waitFor(() =>
      expect(result.current.highlightFilter).toBe("featured"),
    );
    expect(result.current.category).toBeUndefined();

    act(() => result.current.handleCategoryChange("agent-tool"));
    await waitFor(() => expect(result.current.category).toBe("agent-tool"));
    expect(result.current.highlightFilter).toBeUndefined();
  });
});
