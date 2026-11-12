// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { routeRegistry } from "./registry/store";
import { harnessRegistry } from "./harnesses";
import {
  loadAllPlugins,
  loadPawApp,
  reloadPawApp,
  resetPawAppLoaderForTests,
} from "./usePluginLoader";

const originalCreateObjectUrl = URL.createObjectURL;
const originalRevokeObjectUrl = URL.revokeObjectURL;

function jsonResponse(value: unknown): Response {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function plugin(id: string, type: string) {
  return {
    id,
    name: id,
    plugin_type: type,
    frontend_entry: "dist/index.js",
  };
}

describe("frontend plugin loader", () => {
  beforeEach(() => {
    resetPawAppLoaderForTests();
    routeRegistry.__resetForTests();
    harnessRegistry.syncCatalog([]);
    localStorage.removeItem("qwenpaw_auth_token");
    vi.restoreAllMocks();
    URL.createObjectURL = vi.fn(
      () => `data:text/javascript,${encodeURIComponent("export default true")}`,
    );
    URL.revokeObjectURL = vi.fn();
  });

  afterEach(() => {
    URL.createObjectURL = originalCreateObjectUrl;
    URL.revokeObjectURL = originalRevokeObjectUrl;
    delete (globalThis as typeof globalThis & { __registerNotes?: () => void })
      .__registerNotes;
  });

  it("loads every installed frontend plugin during startup", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse([
          plugin("global-tools", "frontend"),
          plugin("notes", "app"),
        ]),
      )
      .mockResolvedValueOnce(jsonResponse({ backends: [] }))
      .mockImplementation(async () => new Response("export default true"));

    await expect(loadAllPlugins()).resolves.toEqual({
      loaded: 2,
      failed: [],
    });
    expect(fetchMock).toHaveBeenCalledTimes(4);
    expect(fetchMock.mock.calls[1][0]).toContain("/agents/backends");
  });

  it("loads an enabled Harness and skips a disabled Harness", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (url) => {
        const path = String(url);
        if (path.endsWith("/frontend_plugin")) {
          return jsonResponse([
            {
              ...plugin("active-harness", "general"),
              harnesses: ["active"],
              enabled: true,
              status: "active",
            },
            {
              ...plugin("disabled-harness", "general"),
              harnesses: ["disabled"],
              enabled: false,
              status: "disabled",
            },
          ]);
        }
        if (path.includes("/agents/backends")) {
          return jsonResponse({
            backends: [
              {
                id: "active",
                plugin_id: "active-harness",
                status: "available",
              },
              {
                id: "disabled",
                plugin_id: "disabled-harness",
                status: "disabled",
              },
            ],
          });
        }
        return new Response("export default true");
      });

    await expect(loadAllPlugins()).resolves.toEqual({ loaded: 1, failed: [] });
    const scripts = fetchMock.mock.calls
      .map(([url]) => String(url))
      .filter((url) => url.includes("/files/"));
    expect(scripts).toHaveLength(1);
    expect(scripts[0]).toContain("active-harness/files/");
  });

  it("loads a newly installed PawApp and exposes its route immediately", async () => {
    const runtimeGlobal = globalThis as typeof globalThis & {
      __registerNotes?: () => void;
    };
    runtimeGlobal.__registerNotes = () => {
      routeRegistry.add("notes", {
        id: "notes.page",
        path: "/apps/notes",
        component: () => null,
      });
    };
    URL.createObjectURL = vi.fn(
      () =>
        `data:text/javascript,${encodeURIComponent(
          "globalThis.__registerNotes()",
        )}`,
    );
    const fetchMock = vi.spyOn(globalThis, "fetch");
    fetchMock
      .mockResolvedValueOnce(jsonResponse([plugin("notes", "app")]))
      .mockResolvedValueOnce(jsonResponse({ backends: [] }))
      .mockResolvedValueOnce(new Response("globalThis.__registerNotes()"));

    await expect(loadPawApp("notes")).resolves.toBeUndefined();
    expect(routeRegistry.snapshot()).toMatchObject([
      { id: "notes.page", path: "/apps/notes", source: "notes" },
    ]);
  });

  it("deduplicates concurrent loads and allows retry after failure", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    fetchMock
      .mockResolvedValueOnce(jsonResponse([plugin("notes", "app")]))
      .mockResolvedValueOnce(jsonResponse({ backends: [] }))
      .mockResolvedValueOnce(new Response("missing", { status: 503 }));

    const first = loadPawApp("notes");
    expect(loadPawApp("notes")).toBe(first);
    await expect(first).rejects.toThrow("HTTP 503");

    fetchMock
      .mockResolvedValueOnce(jsonResponse([plugin("notes", "app")]))
      .mockResolvedValueOnce(jsonResponse({ backends: [] }))
      .mockImplementationOnce(async () => {
        routeRegistry.add("notes", {
          id: "notes.page",
          path: "/apps/notes",
          component: () => null,
        });
        return new Response("export default true");
      });

    await expect(loadPawApp("notes")).resolves.toBeUndefined();
  });

  it("force reloads an already registered PawApp route", async () => {
    const oldComponent = () => null;
    const newComponent = () => null;
    routeRegistry.add("notes", {
      id: "notes.page",
      path: "/apps/notes",
      component: oldComponent,
    });
    const runtimeGlobal = globalThis as typeof globalThis & {
      __registerUpdatedNotes?: () => void;
    };
    runtimeGlobal.__registerUpdatedNotes = () => {
      routeRegistry.add("notes", {
        id: "notes.page",
        path: "/apps/notes",
        component: newComponent,
      });
    };
    URL.createObjectURL = vi.fn(
      () =>
        `data:text/javascript,${encodeURIComponent(
          "globalThis.__registerUpdatedNotes()",
        )}`,
    );
    const fetchMock = vi.spyOn(globalThis, "fetch");
    fetchMock
      .mockResolvedValueOnce(jsonResponse([plugin("notes", "app")]))
      .mockResolvedValueOnce(jsonResponse({ backends: [] }))
      .mockResolvedValueOnce(new Response("updated"));

    await expect(reloadPawApp("notes")).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(routeRegistry.snapshot()[0].Component).toBe(newComponent);
    expect(routeRegistry.snapshot()[0].Component).not.toBe(oldComponent);
  });
});
