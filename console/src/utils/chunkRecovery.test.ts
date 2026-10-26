import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createForeignError } from "../test/foreignError";
import {
  blockChunkRecoveryHealth,
  getFrontendBuildId,
  isChunkLoadError,
  markChunkPageHealthy,
  reloadAfterChunkError,
} from "./chunkRecovery";

function browser() {
  const values = new Map<string, string>();
  const storage = {
    getItem: vi.fn((key: string) => values.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => values.set(key, value)),
    removeItem: vi.fn((key: string) => values.delete(key)),
  };
  const reload = vi.fn();
  const navigator = { onLine: true };
  const events = new EventTarget();
  vi.stubGlobal("window", {
    navigator,
    sessionStorage: storage,
    location: { reload },
    setTimeout,
    clearTimeout,
    addEventListener: events.addEventListener.bind(events),
    removeEventListener: events.removeEventListener.bind(events),
    dispatchEvent: events.dispatchEvent.bind(events),
  });
  return { values, storage, reload, navigator };
}

describe("chunk-load error recognition", () => {
  it("recognizes module failures from a different JavaScript realm", () => {
    const error = createForeignError(
      "Failed to fetch dynamically imported module: /assets/page.js",
    );
    expect(error).not.toBeInstanceOf(Error);
    expect(isChunkLoadError(error)).toBe(true);
  });

  it("recognizes serialized module errors without a local Error prototype", () => {
    expect(
      isChunkLoadError({
        name: "TypeError",
        message: "Importing a module script failed.",
      }),
    ).toBe(true);
  });

  it.each([
    createForeignError("Failed to fetch"),
    createForeignError("Cannot read properties of null", "Error"),
    { name: "TypeError", message: "Failed to fetch" },
    { name: "ChunkLoadError", message: null },
    { message: 42 },
    "Failed to fetch dynamically imported module: /assets/page.js",
  ])("does not misclassify malformed or unrelated foreign errors", (error) => {
    expect(isChunkLoadError(error)).toBe(false);
  });

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

describe("healthy recovery intervals", () => {
  const reloadKey = "qwenpaw:chunk-reload-build";
  let current: ReturnType<typeof browser>;
  let guard: string;
  let visibility: DocumentVisibilityState;
  let releases: (() => void)[];
  let addedScript: HTMLScriptElement | undefined;

  beforeEach(() => {
    vi.useFakeTimers();
    visibility = "visible";
    vi.spyOn(document, "visibilityState", "get").mockImplementation(
      () => visibility,
    );
    current = browser();
    guard = JSON.stringify({ build: getFrontendBuildId(), attempts: 2 });
    current.values.set(reloadKey, guard);
    releases = [];
  });

  afterEach(() => {
    for (const release of releases) release();
    addedScript?.remove();
    addedScript = undefined;
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  function healthyPage() {
    const release = markChunkPageHealthy();
    releases.push(release);
    return release;
  }

  function blockedPage() {
    const release = blockChunkRecoveryHealth();
    releases.push(release);
    return release;
  }

  function changeAvailability(kind: "offline" | "hidden", available: boolean) {
    if (kind === "offline") {
      current.navigator.onLine = available;
      window.dispatchEvent(new Event(available ? "online" : "offline"));
    } else {
      visibility = available ? "visible" : "hidden";
      document.dispatchEvent(new Event("visibilitychange"));
    }
  }

  it("grants exactly two new reloads after 60 healthy seconds", () => {
    expect(reloadAfterChunkError()).toBe(false);
    healthyPage();
    vi.advanceTimersByTime(59_999);
    expect(current.values.get(reloadKey)).toBe(guard);
    vi.advanceTimersByTime(1);
    expect(current.values.has(reloadKey)).toBe(false);

    expect(reloadAfterChunkError()).toBe(true);
    expect(reloadAfterChunkError()).toBe(true);
    expect(reloadAfterChunkError()).toBe(false);
    vi.advanceTimersByTime(120_000);
    expect(reloadAfterChunkError()).toBe(false);
    expect(current.reload).toHaveBeenCalledTimes(2);
  });

  it("keeps the original interval as healthy windows mount and unmount", () => {
    healthyPage();
    vi.advanceTimersByTime(20_000);
    const release = healthyPage();
    vi.advanceTimersByTime(20_000);
    release();
    vi.advanceTimersByTime(19_999);
    expect(current.values.get(reloadKey)).toBe(guard);
    vi.advanceTimersByTime(1);
    expect(current.values.has(reloadKey)).toBe(false);
  });

  it("cancels a pending reset as soon as another chunk fails", () => {
    guard = JSON.stringify({ build: getFrontendBuildId(), attempts: 1 });
    current.values.set(reloadKey, guard);
    healthyPage();
    vi.advanceTimersByTime(59_999);
    expect(reloadAfterChunkError()).toBe(true);
    const updated = current.values.get(reloadKey);
    expect(JSON.parse(updated!)).toMatchObject({ attempts: 2 });
    vi.advanceTimersByTime(60_000);
    expect(current.values.get(reloadKey)).toBe(updated);
  });

  it("keeps a healthy window blocked until every loading or error view is gone", () => {
    healthyPage();
    vi.advanceTimersByTime(40_000);
    const first = blockedPage();
    const second = blockedPage();
    vi.advanceTimersByTime(60_000);
    first();
    first();
    vi.advanceTimersByTime(60_000);
    expect(current.values.get(reloadKey)).toBe(guard);

    second();
    vi.advanceTimersByTime(59_999);
    expect(current.values.get(reloadKey)).toBe(guard);
    vi.advanceTimersByTime(1);
    expect(current.values.has(reloadKey)).toBe(false);
  });

  it.each(["offline", "hidden"] as const)(
    "requires a fresh minute after becoming %s during recovery",
    (kind) => {
      healthyPage();
      vi.advanceTimersByTime(40_000);
      changeAvailability(kind, false);
      vi.advanceTimersByTime(120_000);
      expect(current.values.get(reloadKey)).toBe(guard);

      changeAvailability(kind, true);
      vi.advanceTimersByTime(59_999);
      expect(current.values.get(reloadKey)).toBe(guard);
      vi.advanceTimersByTime(1);
      expect(current.values.has(reloadKey)).toBe(false);
    },
  );

  it.each(["offline", "hidden"] as const)(
    "does not start recovery while initially %s",
    (kind) => {
      changeAvailability(kind, false);
      healthyPage();
      vi.advanceTimersByTime(60_000);
      expect(current.values.get(reloadKey)).toBe(guard);
      changeAvailability(kind, true);
      vi.advanceTimersByTime(59_999);
      expect(current.values.get(reloadKey)).toBe(guard);
      vi.advanceTimersByTime(1);
      expect(current.values.has(reloadKey)).toBe(false);
    },
  );

  it("cancels recovery when the last healthy page unmounts", () => {
    const release = healthyPage();
    vi.advanceTimersByTime(30_000);
    release();
    release();
    vi.advanceTimersByTime(60_000);
    window.dispatchEvent(new Event("online"));
    vi.advanceTimersByTime(60_000);
    expect(current.values.get(reloadKey)).toBe(guard);
    healthyPage();
    vi.advanceTimersByTime(60_000);
    expect(current.values.has(reloadKey)).toBe(false);
  });

  it.each(["same", "other"])(
    "preserves a changed guard for the %s build",
    (build) => {
      healthyPage();
      vi.advanceTimersByTime(30_000);
      const replacement = JSON.stringify({
        build: build === "same" ? getFrontendBuildId() : "other-build",
        attempts: 1,
      });
      current.values.set(reloadKey, replacement);
      vi.advanceTimersByTime(30_000);
      expect(current.values.get(reloadKey)).toBe(replacement);
    },
  );

  it("preserves the guard if the frontend build changes during recovery", () => {
    healthyPage();
    vi.advanceTimersByTime(30_000);
    addedScript = document.createElement("script");
    addedScript.type = "module";
    addedScript.src = `${document.baseURI}assets/new-build.js`;
    document.head.append(addedScript);
    vi.advanceTimersByTime(30_000);
    expect(current.values.get(reloadKey)).toBe(guard);
  });

  it("restores recovery for a legacy marker of the current build", () => {
    current.values.set(reloadKey, getFrontendBuildId());
    healthyPage();
    vi.advanceTimersByTime(60_000);
    expect(current.values.has(reloadKey)).toBe(false);
  });

  it.each([
    "other-build",
    "invalid-json",
    JSON.stringify({ build: "other-build", attempts: 2 }),
    ...[-1, 0, 1.5, "2", null].map((attempts) =>
      JSON.stringify({ build: getFrontendBuildId(), attempts }),
    ),
  ])("preserves unrelated or malformed guards: %s", (stored) => {
    current.values.set(reloadKey, stored);
    healthyPage();
    vi.advanceTimersByTime(60_000);
    expect(current.values.get(reloadKey)).toBe(stored);
    expect(current.storage.removeItem).not.toHaveBeenCalled();
  });

  it("keeps the guard when storage is unreadable at registration", () => {
    current.storage.getItem.mockImplementation(() => {
      throw new DOMException("Storage blocked", "SecurityError");
    });
    expect(healthyPage).not.toThrow();
    vi.advanceTimersByTime(60_000);
    expect(current.values.get(reloadKey)).toBe(guard);
  });

  it.each(["getItem", "removeItem"] as const)(
    "keeps the guard when storage %s becomes blocked before reset",
    (method) => {
      healthyPage();
      current.storage[method].mockImplementation(() => {
        throw new DOMException("Storage blocked", "SecurityError");
      });
      expect(() => vi.advanceTimersByTime(60_000)).not.toThrow();
      expect(current.values.get(reloadKey)).toBe(guard);
    },
  );
});
