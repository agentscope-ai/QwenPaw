import { describe, it, expect, afterEach, vi } from "vitest";
import { renderHook } from "@testing-library/react";
import { useOsApps, resolveAppDef, syncDynamicApps } from "./osAppRegistry";
import { STORE_APP, SETTINGS_APP } from "./osApps";

// Registry hooks feeding useOsApps: one catalog route + one plugin route.
vi.mock("../plugins/registry/hooks", () => ({
  useRoutes: () => [
    { id: "core.chat", path: "/chat/*", source: "core" },
    { id: "plugin.office", path: "/apps/office", source: "office" },
  ],
  useAllMenuItems: () => [],
}));

afterEach(() => {
  syncDynamicApps([]);
});

describe("resolveAppDef", () => {
  it("resolves system and catalog apps statically", () => {
    expect(resolveAppDef("os.settings")).toBe(SETTINGS_APP);
    expect(resolveAppDef("os.store")).toBe(STORE_APP);
    expect(resolveAppDef("core.chat")?.defaultW).toBe(880);
  });

  it("returns undefined for unknown apps", () => {
    expect(resolveAppDef("nope")).toBeUndefined();
  });

  it("resolves dynamic apps after syncDynamicApps", () => {
    expect(resolveAppDef("plugin.office")).toBeUndefined();
    syncDynamicApps([
      {
        routeId: "plugin.office",
        labelKey: "Office",
        fallback: "Office",
        Icon: STORE_APP.Icon,
        accent: "#6366f1",
        defaultW: 960,
        defaultH: 680,
        source: "office",
      },
    ]);
    expect(resolveAppDef("plugin.office")?.defaultW).toBe(960);
  });
});

describe("useOsApps", () => {
  it("merges system, catalog and plugin apps into one registry", () => {
    const { result } = renderHook(() => useOsApps());
    const ids = result.current.apps.map((a) => a.routeId);

    expect(ids[0]).toBe(STORE_APP.routeId);
    expect(ids[ids.length - 1]).toBe(SETTINGS_APP.routeId);
    expect(ids).toContain("core.chat");
    expect(ids).toContain("plugin.office");
    // Catalog apps without a registered route are filtered out.
    expect(ids).not.toContain("core.tools");
    expect(result.current.appById.get("plugin.office")?.defaultW).toBe(960);
  });

  it("syncs dynamic apps so resolveAppDef covers plugin apps", () => {
    renderHook(() => useOsApps());
    expect(resolveAppDef("plugin.office")?.defaultH).toBe(680);
  });
});
