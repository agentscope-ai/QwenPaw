// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { routeRegistry } from "./registry/store";
import { harnessRegistry } from "./harnesses";
import { loadHostUiDependencies } from "./hostUiDependencies";
import {
  fetchFrontendPlugins,
  loadAllPlugins,
  loadPawApp,
  reloadFrontendPlugin,
  reloadPawApp,
  resetPawAppLoaderForTests,
} from "./usePluginLoader";
import {
  clearPluginSdkDeclarations,
  getPluginSdkDeclaration,
} from "./registry/pluginSdk";

vi.mock("./hostUiDependencies", () => ({
  loadHostUiDependencies: vi.fn(async () => undefined),
}));

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
    clearPluginSdkDeclarations();
    localStorage.removeItem("qwenpaw_auth_token");
    vi.restoreAllMocks();
    vi.mocked(loadHostUiDependencies).mockReset().mockResolvedValue(undefined);
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
    expect(loadHostUiDependencies).toHaveBeenCalledTimes(2);
  });

  it("waits for shared UI dependencies before evaluating a plugin", async () => {
    let ready!: () => void;
    vi.mocked(loadHostUiDependencies).mockReturnValueOnce(
      new Promise<void>((resolve) => {
        ready = resolve;
      }),
    );
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse([plugin("tools", "frontend")]))
      .mockResolvedValueOnce(jsonResponse({ backends: [] }))
      .mockResolvedValueOnce(new Response("export default true"));

    const loading = loadAllPlugins();
    await vi.waitFor(() => expect(loadHostUiDependencies).toHaveBeenCalled());
    expect(URL.createObjectURL).not.toHaveBeenCalled();
    ready();
    await expect(loading).resolves.toEqual({ loaded: 1, failed: [] });
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
  });

  it("reports preparation failures without evaluating the plugin", async () => {
    vi.mocked(loadHostUiDependencies).mockRejectedValueOnce(
      new Error("UI chunk unavailable"),
    );
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse([plugin("tools", "frontend")]))
      .mockResolvedValueOnce(jsonResponse({ backends: [] }))
      .mockResolvedValueOnce(new Response("export default true"));

    const summary = await loadAllPlugins();
    expect(summary.loaded).toBe(0);
    expect(summary.failed).toEqual(["tools: Error: UI chunk unavailable"]);
    expect(URL.createObjectURL).not.toHaveBeenCalled();
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
    expect(loadHostUiDependencies).toHaveBeenCalledTimes(1);
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
    expect(loadHostUiDependencies).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(routeRegistry.snapshot()[0].Component).toBe(newComponent);
    expect(routeRegistry.snapshot()[0].Component).not.toBe(oldComponent);
  });

  it("keeps the newest SDK declaration when an older list arrives late", async () => {
    let releaseStaleList!: (response: Response) => void;
    const staleList = new Promise<Response>((resolve) => {
      releaseStaleList = resolve;
    });
    const fetchMock = vi.spyOn(globalThis, "fetch");
    fetchMock
      .mockImplementationOnce(() => staleList)
      .mockImplementationOnce(async () =>
        jsonResponse([
          {
            ...plugin("fresh", "frontend"),
            sdk_version: "1.2.0",
            sdk_capabilities: ["themeTokens"],
          },
        ]),
      );

    const staleRequest = fetchFrontendPlugins();
    await fetchFrontendPlugins();
    expect(getPluginSdkDeclaration("fresh")?.capabilities).toEqual([
      "themeTokens",
    ]);

    releaseStaleList(jsonResponse([plugin("other", "frontend")]));
    const stale = await staleRequest;
    // The late response is still returned to its caller, marked so the caller
    // can tell it is not allowed to install anything.
    expect(stale.stale).toBe(true);
    expect(stale.plugins.map((item) => item.id)).toEqual(["other"]);

    expect(getPluginSdkDeclaration("fresh")?.capabilities).toEqual([
      "themeTokens",
    ]);
    expect(getPluginSdkDeclaration("other")).toBeUndefined();
  });

  it("keeps a hot reload when the startup list arrives late", async () => {
    // The reviewer held the startup list, started a hot reload that declared
    // 1.2.0 + themeTokens, then released the startup response carrying the
    // same plugin id at 1.1.0 without the capability. `loadAllPlugins` used to
    // hand that stale record to `executePluginScript`, which wrote it back over
    // the newer declaration and broke the reload.
    let releaseStartup!: (response: Response) => void;
    const startupList = new Promise<Response>((resolve) => {
      releaseStartup = resolve;
    });
    let listCalls = 0;
    const fetchMock = vi.spyOn(globalThis, "fetch");
    fetchMock.mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/frontend_plugin")) {
        listCalls += 1;
        if (listCalls === 1) return startupList;
        return jsonResponse([
          {
            ...plugin("p1", "frontend"),
            sdk_version: "1.2.0",
            sdk_capabilities: ["themeTokens"],
          },
        ]);
      }
      if (url.includes("/harness")) return jsonResponse([]);
      return new Response("export default 1", { status: 200 });
    });

    const startupLoad = loadAllPlugins();
    expect(await reloadFrontendPlugin("p1")).toBe(true);
    expect(getPluginSdkDeclaration("p1")?.capabilities).toEqual([
      "themeTokens",
    ]);

    releaseStartup(
      jsonResponse([
        {
          ...plugin("p1", "frontend"),
          sdk_version: "1.1.0",
          sdk_capabilities: [],
        },
      ]),
    );
    const summary = await startupLoad;

    // The superseded list installs nothing, and the reload's declaration is
    // still the one in force.
    expect(summary.loaded).toBe(0);
    expect(getPluginSdkDeclaration("p1")?.capabilities).toEqual([
      "themeTokens",
    ]);
  });

  it("still loads the other plugins when a hot reload supersedes the startup list", async () => {
    // Reviewer repro: both lists carry A and B. A is hot reloaded while the
    // startup list is still in flight. The startup response is then marked
    // stale, and `loadAllPlugins` used to return { loaded: 0 } without ever
    // requesting B's entry script. A must not run twice, B must still load.
    let releaseStartup!: (response: Response) => void;
    const startupList = new Promise<Response>((resolve) => {
      releaseStartup = resolve;
    });
    const entryRequests: string[] = [];
    let listCalls = 0;
    const fetchMock = vi.spyOn(globalThis, "fetch");
    fetchMock.mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/files/")) {
        entryRequests.push(url);
        return new Response("export default true", { status: 200 });
      }
      if (url.includes("/frontend_plugin")) {
        listCalls += 1;
        if (listCalls === 1) return startupList;
        return jsonResponse([plugin("A", "frontend"), plugin("B", "frontend")]);
      }
      if (url.includes("/harness")) return jsonResponse([]);
      return new Response("export default true", { status: 200 });
    });

    const startupLoad = loadAllPlugins();
    // Hot reload A from the newer list while the startup list is still held.
    expect(await reloadFrontendPlugin("A")).toBe(true);
    const requestsBeforeRelease = entryRequests.length;

    releaseStartup(
      jsonResponse([plugin("A", "frontend"), plugin("B", "frontend")]),
    );
    const summary = await startupLoad;

    // B must have been fetched even though the startup list was superseded.
    expect(entryRequests.length).toBeGreaterThan(requestsBeforeRelease);
    const fetchedIds = entryRequests.map((url) =>
      url.includes("/A/") ? "A" : "B",
    );
    expect(fetchedIds).toContain("B");
    // A was already installed by the reload; the startup load must not re-run it.
    expect(summary.failed).toEqual([]);
    expect(summary.loaded).toBe(1);
  });

  it("discards a late entry-script response instead of overwriting a newer declaration", async () => {
    // Reviewer repro: the old list arrives first and only its entry-script
    // response is delayed. The new entry starts, then the old response is
    // released. `executePluginScript` wrote the old declaration back before
    // checking the revision, replacing 1.2.0 + themeTokens with 1.1.0.
    let releaseOldEntry!: (response: Response) => void;
    const oldEntry = new Promise<Response>((resolve) => {
      releaseOldEntry = resolve;
    });
    let listCalls = 0;
    let entryCalls = 0;
    const fetchMock = vi.spyOn(globalThis, "fetch");
    fetchMock.mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/files/")) {
        entryCalls += 1;
        if (entryCalls === 1) return oldEntry;
        return new Response("export default true", { status: 200 });
      }
      if (url.includes("/frontend_plugin")) {
        listCalls += 1;
        if (listCalls === 1) {
          return jsonResponse([
            {
              ...plugin("A", "frontend"),
              sdk_version: "1.1.0",
              sdk_capabilities: [],
            },
          ]);
        }
        return jsonResponse([
          {
            ...plugin("A", "frontend"),
            sdk_version: "1.2.0",
            sdk_capabilities: ["themeTokens"],
          },
        ]);
      }
      if (url.includes("/harness")) return jsonResponse([]);
      return new Response("export default true", { status: 200 });
    });

    // Start the old load, which blocks on the delayed entry script.
    const oldLoad = loadAllPlugins();
    // Let the startup load issue its entry request first, so the delayed
    // response belongs to it rather than to the reload.
    await new Promise((resolve) => setTimeout(resolve, 0));
    // A hot reload from the newer list installs 1.2.0 + themeTokens.
    expect(await reloadFrontendPlugin("A")).toBe(true);
    expect(getPluginSdkDeclaration("A")?.version).toBe("1.2.0");

    // Now release the stale entry response.
    releaseOldEntry(new Response("export default true", { status: 200 }));
    await oldLoad.catch(() => undefined);

    // The stale load must not have written 1.1.0 back over the newer record.
    expect(getPluginSdkDeclaration("A")?.version).toBe("1.2.0");
    expect(getPluginSdkDeclaration("A")?.capabilities).toEqual(["themeTokens"]);
  });

  it("joins a hot reload that is still in flight instead of running it twice", async () => {
    // Reviewer repro: hold the new entry at an `await`, then release an older
    // startup list carrying the same plugin id. The reload had not finished, so
    // the id was not in `executedPluginIds` and `loadAllPlugins` executed the
    // plugin a second time from the stale 1.1.0 record, overwriting the
    // declaration the reload had registered and failing `overrideTokens()`.
    let releaseStartup!: (response: Response) => void;
    const startupList = new Promise<Response>((resolve) => {
      releaseStartup = resolve;
    });
    let releaseEntry!: (response: Response) => void;
    const heldEntry = new Promise<Response>((resolve) => {
      releaseEntry = resolve;
    });
    const entryRequests: string[] = [];
    let listCalls = 0;
    const fetchMock = vi.spyOn(globalThis, "fetch");
    fetchMock.mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/files/")) {
        entryRequests.push(url);
        const firstP1 =
          url.includes("/p1/") &&
          entryRequests.filter((item) => item.includes("/p1/")).length === 1;
        if (firstP1) return heldEntry;
        return new Response("export default true", { status: 200 });
      }
      if (url.includes("/frontend_plugin")) {
        listCalls += 1;
        if (listCalls === 1) return startupList;
        return jsonResponse([
          {
            ...plugin("p1", "frontend"),
            sdk_version: "1.2.0",
            sdk_capabilities: ["themeTokens"],
          },
        ]);
      }
      if (url.includes("/harness")) return jsonResponse([]);
      return new Response("export default true", { status: 200 });
    });

    const startupLoad = loadAllPlugins();
    const reload = reloadFrontendPlugin("p1");
    // Let the reload issue its own list + entry requests first.
    await new Promise((resolve) => setTimeout(resolve, 0));

    // The old startup list lands while the reload is still blocked on its entry.
    releaseStartup(
      jsonResponse([
        {
          ...plugin("p1", "frontend"),
          sdk_version: "1.1.0",
          sdk_capabilities: [],
        },
      ]),
    );
    await new Promise((resolve) => setTimeout(resolve, 0));

    // Startup must join the in-flight reload rather than fetch the entry again.
    expect(entryRequests.filter((url) => url.includes("/p1/"))).toHaveLength(1);

    releaseEntry(new Response("export default true", { status: 200 }));
    await reload;
    await startupLoad;

    expect(entryRequests.filter((url) => url.includes("/p1/"))).toHaveLength(1);
    expect(getPluginSdkDeclaration("p1")?.version).toBe("1.2.0");
    expect(getPluginSdkDeclaration("p1")?.capabilities).toEqual([
      "themeTokens",
    ]);
  });

  it("does not install a superseded record when nothing is reloading it", async () => {
    // The catalog generation is the second line of defence. The in-flight join
    // covers a plugin that is being reloaded, but a list can also be superseded
    // by a fetch that only refreshes the registry and executes nothing. If such
    // a record is still executed, its generation says it is older than the
    // newest catalog, so it must not write its declaration over the newer one.
    let releaseStartup!: (response: Response) => void;
    const startupList = new Promise<Response>((resolve) => {
      releaseStartup = resolve;
    });
    let listCalls = 0;
    const fetchMock = vi.spyOn(globalThis, "fetch");
    fetchMock.mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/files/")) {
        return new Response("export default true", { status: 200 });
      }
      if (url.includes("/frontend_plugin")) {
        listCalls += 1;
        if (listCalls === 1) return startupList;
        return jsonResponse([
          {
            ...plugin("p1", "frontend"),
            sdk_version: "1.2.0",
            sdk_capabilities: ["themeTokens"],
          },
        ]);
      }
      if (url.includes("/harness")) return jsonResponse([]);
      return new Response("export default true", { status: 200 });
    });

    const startupLoad = loadAllPlugins();
    // A newer list refreshes the registry without executing any plugin.
    await fetchFrontendPlugins();
    expect(getPluginSdkDeclaration("p1")?.version).toBe("1.2.0");

    // The older startup list lands afterwards, carrying the same id at 1.1.0.
    releaseStartup(
      jsonResponse([
        {
          ...plugin("p1", "frontend"),
          sdk_version: "1.1.0",
          sdk_capabilities: [],
        },
      ]),
    );
    await startupLoad;

    expect(getPluginSdkDeclaration("p1")?.version).toBe("1.2.0");
    expect(getPluginSdkDeclaration("p1")?.capabilities).toEqual([
      "themeTokens",
    ]);
  });

  it("never imports an entry script whose record went stale", async () => {
    // Reviewer repro: the old list arrives first and only its entry-script
    // response is delayed. A newer list refreshes the registry while that
    // response is in flight. The generation check used to protect the SDK
    // declaration only — the old script was still imported afterwards, so the
    // plugin ended up running an old entry that nothing replaced.
    let releaseStaleEntry!: (response: Response) => void;
    const staleEntry = new Promise<Response>((resolve) => {
      releaseStaleEntry = resolve;
    });
    let listCalls = 0;
    let entryCalls = 0;
    const fetchMock = vi.spyOn(globalThis, "fetch");
    fetchMock.mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/files/")) {
        entryCalls += 1;
        // The first entry request belongs to the list that is about to go
        // stale; every later one is served from the newest list.
        if (entryCalls === 1) return staleEntry;
        return new Response("export default true", { status: 200 });
      }
      if (url.includes("/frontend_plugin")) {
        listCalls += 1;
        if (listCalls === 1) {
          return jsonResponse([
            {
              ...plugin("p1", "frontend"),
              sdk_version: "1.1.0",
              sdk_capabilities: [],
            },
          ]);
        }
        return jsonResponse([
          {
            ...plugin("p1", "frontend"),
            sdk_version: "1.2.0",
            sdk_capabilities: ["themeTokens"],
          },
        ]);
      }
      if (url.includes("/agents/backends"))
        return jsonResponse({ backends: [] });
      return new Response("export default true", { status: 200 });
    });

    // The stale script is one byte long and throws if it is ever evaluated;
    // the fresh one is a valid module.
    URL.createObjectURL = vi.fn(
      (blob: Blob) =>
        `data:text/javascript,${encodeURIComponent(
          blob.size === 1
            ? "throw new Error('stale entry ran')"
            : "export default true",
        )}`,
    );

    const startupLoad = loadAllPlugins();
    await new Promise((resolve) => setTimeout(resolve, 0));

    // A newer list refreshes the registry without executing anything.
    await fetchFrontendPlugins();

    releaseStaleEntry(new Response("0", { status: 200 }));
    const summary = await startupLoad;

    // The stale script must never have reached `import()`.
    expect(summary.failed).toEqual([]);
    expect(summary.loaded).toBe(1);
  });

  it("runs the new entry once when a change event supersedes an in-flight load", async () => {
    // Reviewer repro: the startup load is waiting on the old entry script when
    // a hot reload installs the new one and a plugin-change event bumps the
    // revision. The old load then fetched the current record and evaluated it
    // recursively without joining the reload, so Chromium saw the new entry
    // script run twice.
    let releaseStaleEntry!: (response: Response) => void;
    const staleEntry = new Promise<Response>((resolve) => {
      releaseStaleEntry = resolve;
    });
    const runtime = globalThis as typeof globalThis & { __freshRuns?: number };
    delete runtime.__freshRuns;
    // Each evaluation needs a distinct data URL: the module cache is keyed by
    // URL, so a repeated URL would swallow a second run.
    let objectUrls = 0;
    URL.createObjectURL = vi.fn(
      () =>
        `data:text/javascript,${encodeURIComponent(
          `globalThis.__freshRuns=(globalThis.__freshRuns||0)+1;//${++objectUrls}`,
        )}`,
    );

    let listCalls = 0;
    let entryCalls = 0;
    const fetchMock = vi.spyOn(globalThis, "fetch");
    fetchMock.mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/files/")) {
        entryCalls += 1;
        if (entryCalls === 1) return staleEntry;
        return new Response("export default true", { status: 200 });
      }
      if (url.includes("/frontend_plugin")) {
        listCalls += 1;
        if (listCalls === 1) {
          return jsonResponse([
            {
              ...plugin("p1", "frontend"),
              sdk_version: "1.1.0",
              sdk_capabilities: [],
            },
          ]);
        }
        return jsonResponse([
          {
            ...plugin("p1", "frontend"),
            sdk_version: "1.2.0",
            sdk_capabilities: ["themeTokens"],
          },
        ]);
      }
      if (url.includes("/agents/backends"))
        return jsonResponse({ backends: [] });
      return new Response("export default true", { status: 200 });
    });

    const startupLoad = loadAllPlugins();
    await new Promise((resolve) => setTimeout(resolve, 0));

    // A hot reload installs the new entry (run #1).
    await expect(reloadFrontendPlugin("p1")).resolves.toBe(true);
    expect(runtime.__freshRuns).toBe(1);

    // A plugin-change event supersedes the startup load while its entry script
    // is still in flight.
    window.dispatchEvent(new Event("qwenpaw:plugins-changed"));
    await new Promise((resolve) => setTimeout(resolve, 0));

    releaseStaleEntry(new Response("export default true", { status: 200 }));
    await startupLoad;

    // The stale load must not evaluate the new entry a second time.
    expect(runtime.__freshRuns).toBe(1);
  });

  it("keeps both plugins when two reloads overlap", async () => {
    // Reviewer repro: A and B are loaded, A is force-reloaded and its entry
    // script held, B is then force-reloaded to completion, and only then is A's
    // response released. The catalog request issued for B used to make A look
    // stale: A was rejected after its runtime had already been removed by the
    // forced reload, so it never came back.
    const runtime = globalThis as typeof globalThis & {
      __registerRoute?: (source: string) => void;
    };
    runtime.__registerRoute = (source: string) => {
      routeRegistry.add(source, {
        id: `${source}.page`,
        path: `/apps/${source}`,
        component: () => null,
      });
    };

    let created = 0;
    URL.createObjectURL = vi.fn(() => {
      created += 1;
      // Evaluation order: A(startup), B(startup), B(reload), A(reload).
      const source = created === 1 || created === 4 ? "A" : "B";
      return `data:text/javascript,${encodeURIComponent(
        `globalThis.__registerRoute(${JSON.stringify(source)})//${created}`,
      )}`;
    });

    let releaseA!: (response: Response) => void;
    const heldA = new Promise<Response>((resolve) => {
      releaseA = resolve;
    });
    let entryA = 0;
    const fetchMock = vi.spyOn(globalThis, "fetch");
    fetchMock.mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/files/")) {
        if (url.includes("/A/")) {
          entryA += 1;
          // Hold the reload's entry script; the startup one goes through.
          if (entryA === 2) return heldA;
        }
        return new Response("export default true", { status: 200 });
      }
      if (url.includes("/frontend_plugin")) {
        return jsonResponse([plugin("A", "app"), plugin("B", "app")]);
      }
      if (url.includes("/agents/backends"))
        return jsonResponse({ backends: [] });
      return new Response("export default true", { status: 200 });
    });

    await expect(loadAllPlugins()).resolves.toEqual({
      loaded: 2,
      failed: [],
    });
    expect(
      routeRegistry
        .snapshot()
        .map((row) => row.source)
        .sort(),
    ).toEqual(["A", "B"]);

    const reloadA = reloadPawApp("A");
    await new Promise((resolve) => setTimeout(resolve, 0));
    await expect(reloadPawApp("B")).resolves.toBeUndefined();

    releaseA(new Response("export default true", { status: 200 }));
    await expect(reloadA).resolves.toBeUndefined();

    // Both new entry scripts ran exactly once and both routes are back.
    expect(created).toBe(4);
    expect(
      routeRegistry
        .snapshot()
        .map((row) => row.source)
        .sort(),
    ).toEqual(["A", "B"]);
  });
});
