import { afterEach, describe, expect, it, vi } from "vitest";
import { isChunkLoadError, reloadAfterChunkError } from "./chunkRecovery";

describe("chunk-load error recognition", () => {
  it.each([
    "Failed to fetch dynamically imported module: /assets/page.js",
    "error loading dynamically imported module: /assets/page.js",
    "Importing a module script failed.",
    "Loading chunk 10 failed.",
    "Loading CSS chunk 10 failed.",
    "Unable to preload CSS for /assets/page.css",
  ])("recognizes %s", (message) => {
    expect(isChunkLoadError(new Error(message))).toBe(true);
  });

  it("recognizes a named ChunkLoadError", () => {
    const error = new Error("asset unavailable");
    error.name = "ChunkLoadError";
    expect(isChunkLoadError(error)).toBe(true);
  });

  it.each([new TypeError("Failed to fetch"), new Error("render failed"), null])(
    "does not classify unrelated errors as chunk failures",
    (error) => expect(isChunkLoadError(error)).toBe(false),
  );
});

describe("one-shot document recovery", () => {
  afterEach(() => vi.unstubAllGlobals());

  function browser() {
    const values = new Map<string, string>();
    const storage = {
      getItem: vi.fn((key: string) => values.get(key) ?? null),
      setItem: vi.fn((key: string, value: string) => values.set(key, value)),
    };
    const reload = vi.fn();
    const navigator = { onLine: true };
    vi.stubGlobal("window", {
      navigator,
      sessionStorage: storage,
      location: { reload },
    });
    return { values, storage, reload, navigator };
  }

  it("persists the guard before reloading and prevents repeated reloads", () => {
    const { values, reload } = browser();
    reload.mockImplementation(() => expect(values.size).toBe(1));
    expect(reloadAfterChunkError()).toBe(true);
    expect(reloadAfterChunkError()).toBe(false);
    expect(reloadAfterChunkError()).toBe(false);
    expect(reload).toHaveBeenCalledOnce();
  });

  it("allows recovery when the guard belongs to an earlier build", () => {
    const { values, reload } = browser();
    reloadAfterChunkError();
    for (const key of values.keys()) values.set(key, "previous-build");
    expect(reloadAfterChunkError()).toBe(true);
    expect(reloadAfterChunkError()).toBe(false);
    expect(reload).toHaveBeenCalledTimes(2);
  });

  it("runs diagnostic persistence before navigation and only once", () => {
    const { reload } = browser();
    const persist = vi.fn();
    reload.mockImplementation(() => expect(persist).toHaveBeenCalledOnce());
    expect(reloadAfterChunkError(persist)).toBe(true);
    expect(reloadAfterChunkError(persist)).toBe(false);
    expect(persist).toHaveBeenCalledOnce();
  });

  it("keeps the fallback while offline without consuming recovery", () => {
    const { navigator, storage, reload } = browser();
    navigator.onLine = false;
    expect(reloadAfterChunkError()).toBe(false);
    expect(storage.setItem).not.toHaveBeenCalled();
    expect(reload).not.toHaveBeenCalled();
    navigator.onLine = true;
    expect(reloadAfterChunkError()).toBe(true);
  });

  it.each(["getItem", "setItem"] as const)(
    "does not reload when storage %s is blocked",
    (method) => {
      const { storage, reload } = browser();
      storage[method].mockImplementation(() => {
        throw new DOMException("Storage blocked", "SecurityError");
      });
      expect(reloadAfterChunkError()).toBe(false);
      expect(reload).not.toHaveBeenCalled();
    },
  );

  it("does not reload when accessing session storage is blocked", () => {
    const { reload } = browser();
    Object.defineProperty(window, "sessionStorage", {
      get() {
        throw new DOMException("Storage blocked", "SecurityError");
      },
    });
    expect(reloadAfterChunkError()).toBe(false);
    expect(reload).not.toHaveBeenCalled();
  });
});
