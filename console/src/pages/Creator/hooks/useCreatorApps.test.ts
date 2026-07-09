import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useCreatorApps } from "./useCreatorApps";
import * as pluginApi from "@/api/modules/plugin";

vi.mock("@/api/modules/plugin", async () => {
  const actual = await vi.importActual<typeof pluginApi>(
    "@/api/modules/plugin",
  );
  return {
    ...actual,
    fetchPluginCatalog: vi.fn(),
  };
});

function makeCatalogEntry(
  name: string,
  kind: string,
): pluginApi.OfficialPluginCatalogEntry {
  return {
    id: name.toLowerCase(),
    plugin_id: name.toLowerCase(),
    name,
    description: `${name} description`,
    version: "1.0.0",
    author: "dev",
    kind,
    size: "",
    sha256: "",
    install_url: `https://example.com/${name.toLowerCase()}.zip`,
    installed: false,
    upgrade_available: false,
  };
}

describe("useCreatorApps", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("fetches catalog and returns only kind=app plugins", async () => {
    vi.mocked(pluginApi.fetchPluginCatalog).mockResolvedValueOnce({
      updated_at: null,
      plugins: [
        makeCatalogEntry("TeamChat", "app"),
        makeCatalogEntry("Other", "tool"),
      ],
    });

    const { result } = renderHook(() => useCreatorApps());
    expect(result.current.loading).toBe(true);

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.apps).toHaveLength(1);
    expect(result.current.apps[0].name).toBe("TeamChat");
    expect(result.current.apps[0].kind).toBe("app");
    expect(result.current.error).toBeNull();
  });

  it("returns an empty list when no kind=app plugins exist", async () => {
    vi.mocked(pluginApi.fetchPluginCatalog).mockResolvedValueOnce({
      updated_at: null,
      plugins: [makeCatalogEntry("Other", "tool")],
    });

    const { result } = renderHook(() => useCreatorApps());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.apps).toHaveLength(0);
    expect(result.current.error).toBeNull();
  });

  it("surfaces network errors", async () => {
    vi.mocked(pluginApi.fetchPluginCatalog).mockRejectedValueOnce(
      new Error("network down"),
    );

    const { result } = renderHook(() => useCreatorApps());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBe("network down");
    expect(result.current.apps).toHaveLength(0);
  });
});
