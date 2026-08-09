// @vitest-environment jsdom
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { MarketPluginEntry } from "@/api/modules/pluginMarket";
import { useOsAppMarket } from "./useOsAppMarket";

const hoisted = vi.hoisted(() => ({
  fetchMarketPlugins: vi.fn(),
  installPlugin: vi.fn(),
  message: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@/hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: hoisted.message }),
}));

vi.mock("@/api/modules/pluginMarket", async () => {
  const actual = await vi.importActual<
    typeof import("@/api/modules/pluginMarket")
  >("@/api/modules/pluginMarket");
  return {
    ...actual,
    fetchMarketPlugins: hoisted.fetchMarketPlugins,
  };
});

vi.mock("@/api/modules/plugin", () => ({
  installPlugin: hoisted.installPlugin,
}));

function makeEntry(id: string, category = "app"): MarketPluginEntry {
  return {
    id,
    display_name: id,
    developer: "dev",
    owner: "owner",
    version: "1.0.0",
    logo_url: null,
    downloads: 1,
    view_count: 1,
    details_url: null,
    locales: { en: { description: id, category } },
  };
}

describe("useOsAppMarket", () => {
  beforeEach(() => {
    hoisted.fetchMarketPlugins.mockReset();
    hoisted.installPlugin.mockReset();
    hoisted.message.success.mockReset();
    hoisted.message.error.mockReset();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: vi.fn().mockResolvedValue({ version: "2.1.0" }),
      }),
    );
  });

  it("loads every server page and paginates filtered apps", async () => {
    const firstPage = [
      ...Array.from({ length: 99 }, (_, index) => makeEntry(`app-${index}`)),
      makeEntry("not-an-app", "provider"),
    ];
    hoisted.fetchMarketPlugins.mockImplementation(({ page_number }) =>
      Promise.resolve(
        page_number === 1
          ? { plugins: firstPage, total: 101 }
          : { plugins: [makeEntry("app-99")], total: 101 },
      ),
    );

    const { result } = renderHook(() =>
      useOsAppMarket({ onInstalled: vi.fn() }),
    );

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(hoisted.fetchMarketPlugins).toHaveBeenCalledTimes(2);
    expect(hoisted.fetchMarketPlugins).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({
        category: "app",
        page_number: 1,
        page_size: 100,
        sort_by: "downloads",
      }),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(result.current.total).toBe(100);
    expect(result.current.plugins).toHaveLength(20);
    expect(
      result.current.plugins.some((entry) => entry.id === "not-an-app"),
    ).toBe(false);

    act(() => result.current.handlePageChange(5));

    expect(result.current.plugins).toHaveLength(20);
    expect(result.current.plugins[result.current.plugins.length - 1]?.id).toBe(
      "app-99",
    );
  });

  it("resets pagination when searching", async () => {
    hoisted.fetchMarketPlugins.mockResolvedValue({
      plugins: Array.from({ length: 21 }, (_, index) =>
        makeEntry(`app-${index}`),
      ),
      total: 21,
    });

    const { result } = renderHook(() =>
      useOsAppMarket({ onInstalled: vi.fn() }),
    );
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => result.current.handlePageChange(2));
    expect(result.current.page).toBe(2);

    act(() => result.current.handleSearch("kanban"));

    expect(result.current.page).toBe(1);
    await waitFor(() =>
      expect(hoisted.fetchMarketPlugins).toHaveBeenLastCalledWith(
        expect.objectContaining({ search: "kanban" }),
        expect.objectContaining({ signal: expect.any(AbortSignal) }),
      ),
    );
  });
});
