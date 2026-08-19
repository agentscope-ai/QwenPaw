import { describe, it, expect, afterEach, vi } from "vitest";
import { renderHook } from "@testing-library/react";
import { useOsApps, resolveAppDef, appsBySource } from "./osAppRegistry";
import { STORE_APP, SETTINGS_APP, findAppDef } from "./osApps";
import { routeRegistry } from "../plugins/registry/store";
import type { Disposable } from "../plugins/registry/types";

// Registry hooks feeding useOsApps: one catalog route + one plugin route.
vi.mock("../plugins/registry/hooks", () => ({
  useRoutes: () => [
    { id: "core.chat", path: "/chat/*", source: "core" },
    { id: "core.files", path: "/files", source: "core" },
    { id: "plugin.office", path: "/apps/office", source: "office" },
  ],
  useAllMenuItems: () => [],
}));

let disposables: Disposable[] = [];

function addPluginRoute(source: string, id: string, path: string): void {
  disposables.push(
    routeRegistry.add(source, { id, path, component: () => null }),
  );
}

afterEach(() => {
  for (const d of disposables) d.dispose();
  disposables = [];
});

describe("resolveAppDef", () => {
  it("exposes the shared Files workspace as an OS app", () => {
    expect(findAppDef("core.files")).toMatchObject({
      routeId: "core.files",
      labelKey: "nav.files",
      fallback: "Files",
      defaultW: 1180,
      defaultH: 720,
      minW: 760,
      minH: 480,
    });
  });

  it("resolves system and catalog apps statically", () => {
    expect(resolveAppDef("os.settings")).toBe(SETTINGS_APP);
    expect(resolveAppDef("os.store")).toBe(STORE_APP);
    expect(resolveAppDef("core.chat")?.defaultW).toBe(880);
  });

  it("returns undefined for unknown apps", () => {
    expect(resolveAppDef("nope")).toBeUndefined();
  });

  it("reflects registry changes in the same tick, without any mount", () => {
    expect(resolveAppDef("plugin.office")).toBeUndefined();

    addPluginRoute("office", "plugin.office", "/apps/office");
    // Registered -> resolvable immediately (no React render in between).
    expect(resolveAppDef("plugin.office")?.defaultW).toBe(960);

    disposables.pop()!.dispose();
    // Disposed -> gone immediately.
    expect(resolveAppDef("plugin.office")).toBeUndefined();
  });
});

describe("appsBySource", () => {
  it("maps a plugin source to its desktop app bundle", () => {
    addPluginRoute("office", "plugin.office", "/apps/office");
    const apps = appsBySource("office");
    expect(apps.map((a) => a.routeId)).toEqual(["plugin.office"]);
    expect(appsBySource("unknown")).toEqual([]);
  });
});

describe("useOsApps", () => {
  it("merges system, catalog and plugin apps into one registry", () => {
    const { result } = renderHook(() => useOsApps());
    const ids = result.current.apps.map((a) => a.routeId);

    expect(ids[0]).toBe(STORE_APP.routeId);
    expect(ids[ids.length - 1]).toBe(SETTINGS_APP.routeId);
    expect(ids).toContain("core.chat");
    expect(ids).toContain("core.files");
    expect(ids).toContain("plugin.office");
    // Catalog apps without a registered route are filtered out.
    expect(ids).not.toContain("core.tools");
    expect(result.current.appById.get("plugin.office")?.defaultW).toBe(960);
  });
});
