import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const h = vi.hoisted(() => ({
  t: (key: string) => key,
  message: { success: vi.fn(), error: vi.fn() },
  fetchPluginCatalog: vi.fn(),
  installPlugin: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: h.t }),
}));

vi.mock("@/hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: h.message }),
}));

vi.mock("@/api/modules/plugin", () => ({
  fetchPluginCatalog: h.fetchPluginCatalog,
  installPlugin: h.installPlugin,
}));

import { useOfficialPlugins } from "./useOfficialPlugins";

const ENTRY = {
  id: "e1",
  plugin_id: "p1",
  name: "Demo",
  description: "d",
  version: "1.0.0",
  author: "a",
  kind: "tool",
  size: "1kb",
  sha256: "abc",
  install_url: "https://example.invalid/demo.zip",
  installed: false,
  upgrade_available: false,
};

const CATALOG = { updated_at: null, plugins: [ENTRY] };
const RESULT = {
  id: "e1",
  name: "Demo",
  version: "1.0.0",
  description: "d",
  loaded: true,
  message: "ok",
};

beforeEach(() => {
  vi.clearAllMocks();
  h.fetchPluginCatalog.mockResolvedValue(CATALOG);
  h.installPlugin.mockResolvedValue(RESULT);
});

describe("useOfficialPlugins catalog load", () => {
  it("starts loading and then exposes the catalog", async () => {
    const { result } = renderHook(() =>
      useOfficialPlugins({ onInstalled: vi.fn() }),
    );
    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.plugins).toEqual([ENTRY]);
    expect(result.current.catalogError).toBeNull();
    expect(result.current.installingId).toBeNull();
  });

  it("loads the catalog once on mount", async () => {
    renderHook(() => useOfficialPlugins({ onInstalled: vi.fn() }));
    await waitFor(() => expect(h.fetchPluginCatalog).toHaveBeenCalledTimes(1));
  });

  it("treats a missing plugins array as empty", async () => {
    h.fetchPluginCatalog.mockResolvedValue({ updated_at: null });
    const { result } = renderHook(() =>
      useOfficialPlugins({ onInstalled: vi.fn() }),
    );
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.plugins).toEqual([]);
    expect(result.current.catalogError).toBeNull();
  });

  it("surfaces a catalog error payload and empties the list", async () => {
    h.fetchPluginCatalog.mockResolvedValue({
      updated_at: null,
      plugins: [ENTRY],
      error: "backend unavailable",
    });
    const { result } = renderHook(() =>
      useOfficialPlugins({ onInstalled: vi.fn() }),
    );
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.catalogError).toBe("backend unavailable");
    expect(result.current.plugins).toEqual([]);
  });

  it("clears a previously loaded list when a reload returns an error payload", async () => {
    // First load succeeds with one entry; the reload then carries an `error`.
    // Without the `setPlugins([])` in the error branch the stale entry would
    // survive, which a fresh-mount test cannot detect (plugins starts as []).
    const { result } = renderHook(() =>
      useOfficialPlugins({ onInstalled: vi.fn() }),
    );
    await waitFor(() => expect(result.current.plugins).toEqual([ENTRY]));
    h.fetchPluginCatalog.mockResolvedValue({
      updated_at: null,
      plugins: [ENTRY],
      error: "now broken",
    });
    await act(async () => {
      await result.current.loadCatalog();
    });
    expect(result.current.catalogError).toBe("now broken");
    expect(result.current.plugins).toEqual([]);
  });

  it("uses the Error message when the catalog request throws", async () => {
    h.fetchPluginCatalog.mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() =>
      useOfficialPlugins({ onInstalled: vi.fn() }),
    );
    await waitFor(() => expect(result.current.catalogError).toBe("boom"));
    expect(result.current.plugins).toEqual([]);
    expect(result.current.loading).toBe(false);
  });

  it("falls back to the i18n key for a non-Error rejection", async () => {
    h.fetchPluginCatalog.mockRejectedValue("plain failure");
    const { result } = renderHook(() =>
      useOfficialPlugins({ onInstalled: vi.fn() }),
    );
    await waitFor(() =>
      expect(result.current.catalogError).toBe(
        "pluginManager.catalogLoadFailed",
      ),
    );
  });

  it("clears a previous error when a later reload succeeds", async () => {
    h.fetchPluginCatalog.mockRejectedValueOnce(new Error("transient"));
    const { result } = renderHook(() =>
      useOfficialPlugins({ onInstalled: vi.fn() }),
    );
    await waitFor(() => expect(result.current.catalogError).toBe("transient"));
    h.fetchPluginCatalog.mockResolvedValue(CATALOG);
    await act(async () => {
      await result.current.loadCatalog();
    });
    expect(result.current.catalogError).toBeNull();
    expect(result.current.plugins).toEqual([ENTRY]);
  });

  it("sets loading again while reloading", async () => {
    const { result } = renderHook(() =>
      useOfficialPlugins({ onInstalled: vi.fn() }),
    );
    await waitFor(() => expect(result.current.loading).toBe(false));
    let pending!: Promise<void>;
    act(() => {
      pending = result.current.loadCatalog();
    });
    expect(result.current.loading).toBe(true);
    await act(async () => {
      await pending;
    });
    expect(result.current.loading).toBe(false);
  });
});

describe("useOfficialPlugins handleInstall", () => {
  it("installs without force for a fresh plugin, then notifies and reloads", async () => {
    const onInstalled = vi.fn();
    const { result } = renderHook(() => useOfficialPlugins({ onInstalled }));
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      await result.current.handleInstall(ENTRY);
    });
    expect(h.installPlugin).toHaveBeenCalledWith(ENTRY.install_url, {
      force: false,
    });
    expect(onInstalled).toHaveBeenCalledWith(RESULT);
    expect(h.message.success).toHaveBeenCalledWith(
      "pluginManager.installSuccess: Demo",
    );
    // initial load + the reload after a successful install
    expect(h.fetchPluginCatalog).toHaveBeenCalledTimes(2);
    expect(result.current.installingId).toBeNull();
  });

  it("forces the install when the plugin is already installed", async () => {
    const { result } = renderHook(() =>
      useOfficialPlugins({ onInstalled: vi.fn() }),
    );
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      await result.current.handleInstall({ ...ENTRY, installed: true });
    });
    expect(h.installPlugin).toHaveBeenCalledWith(ENTRY.install_url, {
      force: true,
    });
  });

  it("forces the install when an upgrade is available", async () => {
    const { result } = renderHook(() =>
      useOfficialPlugins({ onInstalled: vi.fn() }),
    );
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      await result.current.handleInstall({ ...ENTRY, upgrade_available: true });
    });
    expect(h.installPlugin).toHaveBeenCalledWith(ENTRY.install_url, {
      force: true,
    });
  });

  it("marks the entry as installing while the request is in flight", async () => {
    let release!: () => void;
    h.installPlugin.mockReturnValue(
      new Promise((resolve) => {
        release = () => resolve(RESULT);
      }),
    );
    const { result } = renderHook(() =>
      useOfficialPlugins({ onInstalled: vi.fn() }),
    );
    await waitFor(() => expect(result.current.loading).toBe(false));
    let pending!: Promise<void>;
    act(() => {
      pending = result.current.handleInstall(ENTRY);
    });
    expect(result.current.installingId).toBe("e1");
    await act(async () => {
      release();
      await pending;
    });
    expect(result.current.installingId).toBeNull();
  });

  it("awaits an async onInstalled callback before reloading", async () => {
    const order: string[] = [];
    const onInstalled = vi.fn(async () => {
      await Promise.resolve();
      order.push("onInstalled");
    });
    h.fetchPluginCatalog.mockImplementation(async () => {
      order.push("reload");
      return CATALOG;
    });
    const { result } = renderHook(() => useOfficialPlugins({ onInstalled }));
    await waitFor(() => expect(result.current.loading).toBe(false));
    order.length = 0;
    await act(async () => {
      await result.current.handleInstall(ENTRY);
    });
    expect(order).toEqual(["onInstalled", "reload"]);
  });

  it("reports an Error message when the install fails and does not reload", async () => {
    h.installPlugin.mockRejectedValue(new Error("install exploded"));
    const onInstalled = vi.fn();
    const { result } = renderHook(() => useOfficialPlugins({ onInstalled }));
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      await result.current.handleInstall(ENTRY);
    });
    expect(h.message.error).toHaveBeenCalledWith("install exploded");
    expect(h.message.success).not.toHaveBeenCalled();
    expect(onInstalled).not.toHaveBeenCalled();
    expect(h.fetchPluginCatalog).toHaveBeenCalledTimes(1);
    expect(result.current.installingId).toBeNull();
  });

  it("falls back to the i18n key for a non-Error install failure", async () => {
    h.installPlugin.mockRejectedValue(42);
    const { result } = renderHook(() =>
      useOfficialPlugins({ onInstalled: vi.fn() }),
    );
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      await result.current.handleInstall(ENTRY);
    });
    expect(h.message.error).toHaveBeenCalledWith("pluginManager.installFailed");
  });

  it("reports a failure thrown by the onInstalled callback", async () => {
    const onInstalled = vi.fn(async () => {
      throw new Error("callback blew up");
    });
    const { result } = renderHook(() => useOfficialPlugins({ onInstalled }));
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      await result.current.handleInstall(ENTRY);
    });
    expect(h.message.error).toHaveBeenCalledWith("callback blew up");
    expect(h.message.success).toHaveBeenCalledWith(
      "pluginManager.installSuccess: Demo",
    );
  });
});

describe("useOfficialPlugins state surface", () => {
  it("exposes every documented member", async () => {
    const { result } = renderHook(() =>
      useOfficialPlugins({ onInstalled: vi.fn() }),
    );
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(Object.keys(result.current).sort()).toEqual([
      "catalogError",
      "handleInstall",
      "installingId",
      "loadCatalog",
      "loading",
      "plugins",
    ]);
  });
});
