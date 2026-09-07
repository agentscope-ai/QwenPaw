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

const {
  messageMock,
  modalConfirmMock,
  refreshMock,
  uninstallPluginMock,
  pluginsData,
} = hoisted;

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
    pluginsData.length = 0;
    pluginsData.push(makePlugin());
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
    pluginsData.splice(0, pluginsData.length, plugin);
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

  it("detects community updates by package ID and author", async () => {
    const plugin = {
      ...makePlugin(),
      id: "qwenpaw-thinking-collapse",
      author: "erickcharles",
      version: "2.8.0",
    };
    pluginsData.splice(0, pluginsData.length, plugin);
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

  it("refreshes after a partial update failure", async () => {
    const first = { ...makePlugin(), id: "first", version: "1.0.0" };
    const second = { ...makePlugin(), id: "second", version: "1.0.0" };
    pluginsData.splice(0, pluginsData.length, first, second);
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
      .mockResolvedValueOnce({ name: "first" })
      .mockRejectedValueOnce(new Error("second failed"));

    const { result } = renderHook(() => usePluginManager());
    await waitFor(() => expect(result.current.updates.size).toBe(2));
    await act(async () => {
      await result.current.updateAll();
    });

    expect(hoisted.installPluginMock).toHaveBeenCalledTimes(2);
    expect(refreshMock).toHaveBeenCalledTimes(1);
    expect(result.current.updates.has("first")).toBe(false);
  });
});
