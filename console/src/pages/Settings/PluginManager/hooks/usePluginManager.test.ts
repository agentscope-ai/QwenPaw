import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import type { PluginInfo } from "@/api/modules/plugin";

const hoisted = vi.hoisted(() => ({
  messageMock: {
    success: vi.fn(),
    error: vi.fn(),
  },
  stableT: (k: string) => k,
  fetchPluginsMock: vi.fn(),
  fetchPluginCatalogMock: vi.fn(),
  fetchMarketPluginsMock: vi.fn(),
  installPluginMock: vi.fn(),
  uninstallPluginMock: vi.fn(),
  // Captured Modal.confirm options; initialized per-test in beforeEach.
  modalConfirmMock: vi.fn(),
  refreshMock: vi.fn(),
  pluginsData: [] as PluginInfo[],
}));

vi.mock("@/hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: hoisted.messageMock }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: hoisted.stableT }),
}));

vi.mock("@/api/modules/plugin", () => ({
  fetchPlugins: hoisted.fetchPluginsMock,
  fetchPluginCatalog: hoisted.fetchPluginCatalogMock,
  installPlugin: hoisted.installPluginMock,
  uninstallPlugin: hoisted.uninstallPluginMock,
}));

vi.mock("@/api/modules/pluginMarket", () => ({
  fetchMarketPlugins: hoisted.fetchMarketPluginsMock,
  buildMarketDownloadUrl: vi.fn(() => "https://example.com/plugin.zip"),
}));

vi.mock("ahooks", () => ({
  useRequest: (
    fn: unknown,
    opts: { onError?: () => void } & Record<string, unknown>,
  ) => {
    void fn;
    void opts;
    return {
      data: hoisted.pluginsData,
      loading: false,
      refresh: hoisted.refreshMock,
    };
  },
}));

vi.mock("antd", () => ({
  Modal: {
    confirm: hoisted.modalConfirmMock,
  },
}));

import { usePluginManager } from "./usePluginManager";

const { messageMock, modalConfirmMock, refreshMock, uninstallPluginMock } =
  hoisted;

function makePlugin(): PluginInfo {
  return {
    id: "p1",
    name: "demo",
  } as unknown as PluginInfo;
}

describe("usePluginManager", () => {
  beforeEach(() => {
    messageMock.success.mockReset();
    messageMock.error.mockReset();
    modalConfirmMock.mockReset();
    refreshMock.mockReset();
    hoisted.installPluginMock.mockReset();
    uninstallPluginMock.mockReset();
    hoisted.fetchPluginCatalogMock
      .mockReset()
      .mockResolvedValue({ plugins: [] });
    hoisted.fetchMarketPluginsMock.mockReset().mockResolvedValue({
      plugins: [],
      total: 0,
    });
    hoisted.pluginsData = [makePlugin()];
  });

  it("initializes plugins from useRequest", () => {
    const { result } = renderHook(() => usePluginManager());

    expect(result.current.plugins).toEqual([makePlugin()]);
    expect(result.current.loading).toBe(false);
  });

  it("handleUninstall opens Modal.confirm with okType 'danger'", () => {
    const { result } = renderHook(() => usePluginManager());

    act(() => {
      result.current.handleUninstall(makePlugin());
    });

    expect(modalConfirmMock).toHaveBeenCalledTimes(1);
    const opts = modalConfirmMock.mock.calls[0][0] as {
      title: string;
      okType: string;
    };
    expect(opts.title).toBe("pluginManager.confirmTitle");
    expect(opts.okType).toBe("danger");
  });

  it("Modal.confirm onOk success calls uninstallPlugin, success message, and refresh", async () => {
    uninstallPluginMock.mockResolvedValue(undefined);
    const { result } = renderHook(() => usePluginManager());

    act(() => {
      result.current.handleUninstall(makePlugin());
    });

    const opts = modalConfirmMock.mock.calls[0][0] as {
      onOk: () => Promise<void>;
    };

    await act(async () => {
      await opts.onOk();
    });

    expect(uninstallPluginMock).toHaveBeenCalledWith("p1");
    expect(messageMock.success).toHaveBeenCalledWith(
      "pluginManager.uninstallSuccess",
    );
    expect(refreshMock).toHaveBeenCalled();
  });

  it("detects official updates and updates one plugin without reloading", async () => {
    const plugin = { ...makePlugin(), version: "1.0.0" };
    hoisted.pluginsData = [plugin];
    hoisted.fetchPluginCatalogMock.mockResolvedValue({
      plugins: [
        {
          plugin_id: "p1",
          name: "demo",
          version: "2.0.0",
          install_url: "https://example.com/demo.zip",
          upgrade_available: true,
        },
      ],
    });
    hoisted.installPluginMock.mockResolvedValue({ name: "demo" });

    const { result } = renderHook(() => usePluginManager());
    await waitFor(() => expect(result.current.updates.size).toBe(1));

    await act(async () => {
      await result.current.updateOne(plugin);
    });

    expect(hoisted.installPluginMock).toHaveBeenCalledWith(
      "https://example.com/demo.zip",
      { force: true },
    );
    expect(refreshMock).toHaveBeenCalled();
  });

  it("selects the latest official update from an unordered catalog", async () => {
    const plugin = { ...makePlugin(), version: "0.9.0" };
    hoisted.pluginsData = [plugin];
    hoisted.fetchPluginCatalogMock.mockResolvedValue({
      plugins: [
        {
          plugin_id: "p1",
          name: "demo",
          version: "1.0.0",
          install_url: "https://example.com/demo-1.0.0.zip",
          upgrade_available: true,
        },
        {
          plugin_id: "p1",
          name: "demo",
          version: "1.2.0",
          install_url: "https://example.com/demo-1.2.0.zip",
          upgrade_available: true,
        },
        {
          plugin_id: "p1",
          name: "demo",
          version: "1.1.0",
          install_url: "https://example.com/demo-1.1.0.zip",
          upgrade_available: true,
        },
      ],
    });
    hoisted.fetchMarketPluginsMock.mockResolvedValue({
      plugins: [
        {
          id: "p1",
          display_name: "demo",
          developer: "owner",
          owner: "owner",
          version: "1.1.5",
          logo_url: null,
          downloads: 0,
          view_count: 0,
          details_url: null,
          locales: {},
        },
      ],
      total: 1,
    });

    const { result } = renderHook(() => usePluginManager());

    await waitFor(() => expect(result.current.updates.size).toBe(1));
    expect(result.current.updates.get("p1")).toMatchObject({
      version: "1.2.0",
      source: "https://example.com/demo-1.2.0.zip",
    });
  });

  it("detects community updates by package ID and author", async () => {
    const plugin = {
      ...makePlugin(),
      id: "qwenpaw-thinking-collapse",
      author: "erickcharles",
      version: "2.8.0",
    };
    hoisted.pluginsData = [plugin];
    hoisted.fetchMarketPluginsMock.mockResolvedValue({
      plugins: [
        {
          id: "@erickcharles/qwenpaw-thinking-collapse",
          display_name: "Thinking Collapse",
          developer: "erickcharles",
          owner: "erickcharles",
          version: "2.9.0",
          logo_url: null,
          downloads: 0,
          view_count: 0,
          details_url: null,
          locales: {},
        },
      ],
      total: 1,
    });

    const { result } = renderHook(() => usePluginManager());
    await waitFor(() => expect(result.current.updates.size).toBe(1));
    expect(result.current.updates.get(plugin.id)?.version).toBe("2.9.0");
  });

  it("stops checking market updates after an empty page", async () => {
    hoisted.fetchMarketPluginsMock.mockResolvedValue({
      plugins: [],
      total: 100,
    });

    const { result } = renderHook(() => usePluginManager());

    await waitFor(() =>
      expect(hoisted.fetchMarketPluginsMock).toHaveBeenCalledTimes(1),
    );
    await waitFor(() => expect(result.current.updatesLoading).toBe(false));
  });

  it("stops checking market updates when a page has no new plugins", async () => {
    const entry = {
      id: "@owner/other-plugin",
      display_name: "Other Plugin",
      developer: "owner",
      owner: "owner",
      version: "1.0.0",
      logo_url: null,
      downloads: 0,
      view_count: 0,
      details_url: null,
      locales: {},
    };
    hoisted.fetchMarketPluginsMock.mockResolvedValue({
      plugins: [entry],
      total: 100,
    });

    const { result } = renderHook(() => usePluginManager());

    await waitFor(() =>
      expect(hoisted.fetchMarketPluginsMock).toHaveBeenCalledTimes(2),
    );
    await waitFor(() => expect(result.current.updatesLoading).toBe(false));
  });

  it("limits market update checks to twenty pages", async () => {
    hoisted.fetchMarketPluginsMock.mockImplementation(({ page_number }) =>
      Promise.resolve({
        plugins: [
          {
            id: `@owner/plugin-${page_number}`,
            display_name: `Plugin ${page_number}`,
            developer: "owner",
            owner: "owner",
            version: "1.0.0",
            logo_url: null,
            downloads: 0,
            view_count: 0,
            details_url: null,
            locales: {},
          },
        ],
        total: 10_000,
      }),
    );

    const { result } = renderHook(() => usePluginManager());

    await waitFor(() =>
      expect(hoisted.fetchMarketPluginsMock).toHaveBeenCalledTimes(20),
    );
    await waitFor(() => expect(result.current.updatesLoading).toBe(false));
  });

  it("reuses market results until updates are manually refreshed", async () => {
    const { result, rerender } = renderHook(() => usePluginManager());
    await waitFor(() =>
      expect(hoisted.fetchMarketPluginsMock).toHaveBeenCalledTimes(1),
    );

    hoisted.pluginsData = [{ ...makePlugin(), version: "1.0.1" }];
    rerender();
    await waitFor(() =>
      expect(hoisted.fetchPluginCatalogMock).toHaveBeenCalledTimes(2),
    );
    expect(hoisted.fetchMarketPluginsMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      await result.current.refreshUpdates();
    });
    hoisted.pluginsData = [{ ...makePlugin(), version: "1.0.2" }];
    rerender();
    await waitFor(() =>
      expect(hoisted.fetchMarketPluginsMock).toHaveBeenCalledTimes(2),
    );
  });

  it("continues updating after a plugin fails", async () => {
    const first = { ...makePlugin(), id: "first", version: "1.0.0" };
    const second = { ...makePlugin(), id: "second", version: "1.0.0" };
    hoisted.pluginsData = [first, second];
    hoisted.fetchPluginCatalogMock.mockResolvedValue({
      plugins: [
        {
          plugin_id: "first",
          name: "first",
          version: "2.0.0",
          install_url: "https://example.com/first.zip",
          upgrade_available: true,
        },
        {
          plugin_id: "second",
          name: "second",
          version: "2.0.0",
          install_url: "https://example.com/second.zip",
          upgrade_available: true,
        },
      ],
    });
    hoisted.installPluginMock
      .mockRejectedValueOnce(new Error("first failed"))
      .mockResolvedValueOnce({ name: "second" });

    const { result } = renderHook(() => usePluginManager());
    await waitFor(() => expect(result.current.updates.size).toBe(2));
    await act(async () => {
      await result.current.updateAll();
    });

    expect(hoisted.installPluginMock).toHaveBeenCalledTimes(2);
    expect(hoisted.installPluginMock).toHaveBeenLastCalledWith(
      "https://example.com/second.zip",
      { force: true },
    );
    expect(refreshMock).toHaveBeenCalledTimes(1);
    expect(result.current.updates.has("first")).toBe(true);
    expect(result.current.updates.has("second")).toBe(false);
    expect(messageMock.error).toHaveBeenCalledWith(
      "pluginManager.updateAllResult",
    );
  });
});
