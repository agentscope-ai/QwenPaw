import { afterEach, describe, expect, it, vi } from "vitest";
import {
  getFrontendBuildId,
  isChunkLoadError,
  reloadAfterChunkError,
} from "./chunkRecovery";

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

describe("bounded document recovery", () => {
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
    expect(reloadAfterChunkError()).toBe(true);
    expect(reloadAfterChunkError()).toBe(false);
    expect(reloadAfterChunkError()).toBe(false);
    expect(reload).toHaveBeenCalledTimes(2);
  });

  it("allows recovery when the guard belongs to an earlier build", () => {
    const { values, reload } = browser();
    reloadAfterChunkError();
    for (const key of values.keys()) values.set(key, "previous-build");
    expect(reloadAfterChunkError()).toBe(true);
    expect(reloadAfterChunkError()).toBe(true);
    expect(reloadAfterChunkError()).toBe(false);
    expect(reload).toHaveBeenCalledTimes(3);
  });

  it("publishes every decision and persists the budget before navigation", () => {
    const { reload } = browser();
    const persist = vi.fn();
    reload.mockImplementation(() => {
      expect(persist.mock.lastCall?.[0].reason).toBe("reload");
    });
    expect(reloadAfterChunkError(persist)).toBe(true);
    expect(reloadAfterChunkError(persist)).toBe(true);
    expect(reloadAfterChunkError(persist)).toBe(false);
    expect(persist.mock.calls.map(([decision]) => decision)).toEqual([
      { reason: "reload", attempts: 1, maxAttempts: 2 },
      { reason: "reload", attempts: 2, maxAttempts: 2 },
      { reason: "limit-reached", attempts: 2, maxAttempts: 2 },
    ]);
  });

  it("allows one remaining refresh for the legacy one-shot guard", () => {
    const { values, reload } = browser();
    values.set("qwenpaw:chunk-reload-build", getFrontendBuildId());
    expect(reloadAfterChunkError()).toBe(true);
    expect(reloadAfterChunkError()).toBe(false);
    expect(reload).toHaveBeenCalledOnce();
  });

  it("does not reset a malformed counter for the current build", () => {
    const { values, reload } = browser();
    values.set(
      "qwenpaw:chunk-reload-build",
      JSON.stringify({ build: getFrontendBuildId(), attempts: "invalid" }),
    );
    const persist = vi.fn();
    expect(reloadAfterChunkError(persist)).toBe(false);
    expect(persist).toHaveBeenCalledWith({
      reason: "limit-reached",
      attempts: 2,
      maxAttempts: 2,
    });
    expect(reload).not.toHaveBeenCalled();
  });

  it("reports navigation failure without discarding the reload budget", () => {
    const { reload } = browser();
    reload.mockImplementation(() => {
      throw new Error("Navigation failed");
    });
    const persist = vi.fn();
    expect(reloadAfterChunkError(persist)).toBe(false);
    expect(persist).toHaveBeenLastCalledWith({
      reason: "reload-failed",
      attempts: 1,
      maxAttempts: 2,
    });
    expect(reloadAfterChunkError()).toBe(false);
    expect(reloadAfterChunkError()).toBe(false);
    expect(reload).toHaveBeenCalledTimes(2);
  });

  it("keeps the fallback while offline without consuming recovery", () => {
    const { navigator, storage, reload } = browser();
    navigator.onLine = false;
    const persist = vi.fn();
    expect(reloadAfterChunkError(persist)).toBe(false);
    expect(persist).toHaveBeenCalledWith({
      reason: "offline",
      attempts: null,
      maxAttempts: 2,
    });
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
      const persist = vi.fn();
      expect(reloadAfterChunkError(persist)).toBe(false);
      expect(persist).toHaveBeenCalledWith({
        reason: "storage-unavailable",
        attempts: null,
        maxAttempts: 2,
      });
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
