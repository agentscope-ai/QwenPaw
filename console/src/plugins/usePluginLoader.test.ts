// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { routeRegistry } from "./registry/store";
import { removePluginAppState } from "../os/osCleanup";
import {
  loadEagerFrontendPlugins,
  loadPawApp,
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
    version: "1.0.0",
    plugin_type: type,
    frontend_entry: "dist/index.js",
  };
}

describe("frontend plugin loader", () => {
  beforeEach(() => {
    resetPawAppLoaderForTests();
    routeRegistry.__resetForTests();
    vi.restoreAllMocks();
    URL.createObjectURL = vi.fn(
      () => `data:text/javascript,${encodeURIComponent("export default true")}`,
    );
    URL.revokeObjectURL = vi.fn();
  });

  afterEach(() => {
    URL.createObjectURL = originalCreateObjectUrl;
    URL.revokeObjectURL = originalRevokeObjectUrl;
  });

  it("loads global plugins eagerly and skips PawApps", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse([
          plugin("global-tools", "frontend"),
          plugin("notes", "app"),
        ]),
      )
      .mockResolvedValueOnce(new Response("export default true"));

    await expect(loadEagerFrontendPlugins()).resolves.toEqual({
      loaded: 1,
      failed: [],
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1][0]).toContain("global-tools");
  });

  it("loads one PawApp once and verifies its registered entry page", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    fetchMock
      .mockResolvedValueOnce(jsonResponse([plugin("notes", "app")]))
      .mockImplementationOnce(async () => {
        routeRegistry.add("notes", {
          id: "notes.page",
          path: "/apps/notes",
          component: () => null,
        });
        return new Response("export default true");
      });

    await expect(loadPawApp("notes", "/apps/notes")).resolves.toBeUndefined();
    fetchMock.mockClear();
    fetchMock.mockResolvedValueOnce(jsonResponse([plugin("notes", "app")]));

    await expect(loadPawApp("notes", "/apps/notes")).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("deduplicates concurrent loads and permits a real retry after failure", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    fetchMock
      .mockResolvedValueOnce(jsonResponse([plugin("notes", "app")]))
      .mockResolvedValueOnce(new Response("missing", { status: 503 }));

    const first = loadPawApp("notes", "/apps/notes");
    const concurrent = loadPawApp("notes", "/apps/notes");
    expect(concurrent).toBe(first);
    await expect(first).rejects.toThrow("HTTP 503");

    fetchMock
      .mockResolvedValueOnce(jsonResponse([plugin("notes", "app")]))
      .mockImplementationOnce(async () => {
        routeRegistry.add("notes", {
          id: "notes.page",
          path: "/apps/notes",
          component: () => null,
        });
        return new Response("export default true");
      });

    await expect(loadPawApp("notes", "/apps/notes")).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it("hot-replaces an already loaded PawApp when its version changes", async () => {
    const OldPage = () => null;
    const NewPage = () => null;
    routeRegistry.add("notes", {
      id: "notes.page",
      path: "/apps/notes",
      component: OldPage,
    });
    const fetchMock = vi.spyOn(globalThis, "fetch");
    fetchMock.mockResolvedValueOnce(jsonResponse([plugin("notes", "app")]));
    await loadPawApp("notes", "/apps/notes");

    fetchMock
      .mockResolvedValueOnce(
        jsonResponse([{ ...plugin("notes", "app"), version: "2.0.0" }]),
      )
      .mockImplementationOnce(async () => {
        routeRegistry.add("notes", {
          id: "notes.page",
          path: "/apps/notes",
          component: NewPage,
        });
        return new Response("export default true");
      });

    await expect(loadPawApp("notes", "/apps/notes")).resolves.toBeUndefined();
    expect(routeRegistry.snapshot()[0].Component).toBe(NewPage);
    expect(fetchMock.mock.calls[2][0]).toContain("version=2.0.0");
  });

  it("restores the previous route when a hot replacement fails", async () => {
    const OldPage = () => null;
    routeRegistry.add("notes", {
      id: "notes.page",
      path: "/apps/notes",
      component: OldPage,
    });
    const fetchMock = vi.spyOn(globalThis, "fetch");
    fetchMock.mockResolvedValueOnce(jsonResponse([plugin("notes", "app")]));
    await loadPawApp("notes", "/apps/notes");

    fetchMock
      .mockResolvedValueOnce(
        jsonResponse([{ ...plugin("notes", "app"), version: "2.0.0" }]),
      )
      .mockResolvedValueOnce(new Response("missing", { status: 503 }));

    await expect(loadPawApp("notes", "/apps/notes")).rejects.toThrow(
      "HTTP 503",
    );
    expect(routeRegistry.snapshot()[0].Component).toBe(OldPage);
  });

  it("removes partial routes before restoring a failed hot replacement", async () => {
    const OldPage = () => null;
    const BrokenPage = () => null;
    routeRegistry.add("notes", {
      id: "notes.page",
      path: "/apps/notes",
      component: OldPage,
    });
    const fetchMock = vi.spyOn(globalThis, "fetch");
    fetchMock.mockResolvedValueOnce(jsonResponse([plugin("notes", "app")]));
    await loadPawApp("notes", "/apps/notes");

    URL.createObjectURL = vi.fn(
      () =>
        `data:text/javascript,${encodeURIComponent(
          "throw new Error('bundle crashed')",
        )}`,
    );
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse([{ ...plugin("notes", "app"), version: "2.0.0" }]),
      )
      .mockImplementationOnce(async () => {
        routeRegistry.add("notes", {
          id: "notes.page",
          path: "/apps/notes",
          component: BrokenPage,
        });
        return new Response("throw new Error('bundle crashed')");
      });

    await expect(loadPawApp("notes", "/apps/notes")).rejects.toThrow(
      "bundle crashed",
    );
    expect(routeRegistry.snapshot()).toHaveLength(1);
    expect(routeRegistry.snapshot()[0].Component).toBe(OldPage);
  });

  it("does not revive a PawApp when uninstall wins against an in-flight load", async () => {
    let resolveEntry!: (response: Response) => void;
    const entryResponse = new Promise<Response>((resolve) => {
      resolveEntry = resolve;
    });
    const fetchMock = vi.spyOn(globalThis, "fetch");
    fetchMock
      .mockResolvedValueOnce(jsonResponse([plugin("notes", "app")]))
      .mockReturnValueOnce(entryResponse);
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

    const loading = loadPawApp("notes", "/apps/notes");
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    removePluginAppState("notes");
    resolveEntry(new Response("globalThis.__registerNotes()"));
    await loading.catch(() => {});

    expect(routeRegistry.snapshot()).toEqual([]);
    delete runtimeGlobal.__registerNotes;
  });

  it("recognizes a PawApp base route while another plugin overrides it", async () => {
    const BasePage = () => null;
    const OverridePage = () => null;
    routeRegistry.add("notes", {
      id: "notes.page",
      path: "/apps/notes",
      component: BasePage,
    });
    const fetchMock = vi.spyOn(globalThis, "fetch");
    fetchMock.mockResolvedValueOnce(jsonResponse([plugin("notes", "app")]));
    await loadPawApp("notes", "/apps/notes");
    routeRegistry.replace("theme", "notes.page", OverridePage);
    fetchMock
      .mockResolvedValueOnce(jsonResponse([plugin("notes", "app")]))
      .mockImplementationOnce(async () => {
        routeRegistry.add("notes", {
          id: "notes.page",
          path: "/apps/notes",
          component: BasePage,
        });
        return new Response("export default true");
      });

    await expect(loadPawApp("notes", "/apps/notes")).resolves.toBeUndefined();

    expect(routeRegistry.snapshot()).toMatchObject([
      {
        id: "notes.page",
        path: "/apps/notes",
        baseSource: "notes",
        source: "theme",
        Component: OverridePage,
      },
    ]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
