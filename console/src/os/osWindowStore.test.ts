import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { useOsWindows } from "./osWindowStore";
import { routeRegistry } from "../plugins/registry/store";
import type { Disposable } from "../plugins/registry/types";

/** Reset the store to a pristine desktop between tests. */
function resetStore() {
  useOsWindows.setState({
    windows: {},
    order: [],
    activeId: null,
    zCounter: 100,
    launcherOpen: false,
    spaceId: "default",
    saved: {},
    missionControlOpen: false,
  });
}

const s = () => useOsWindows.getState();

/** Registered plugin routes to clean up after each test. */
let disposables: Disposable[] = [];

describe("osWindowStore", () => {
  beforeEach(() => {
    // Fixed desktop-sized viewport so open()'s viewport clamp stays inert.
    Object.defineProperty(window, "innerWidth", {
      value: 1920,
      configurable: true,
      writable: true,
    });
    Object.defineProperty(window, "innerHeight", {
      value: 1080,
      configurable: true,
      writable: true,
    });
    resetStore();
  });

  afterEach(() => {
    for (const d of disposables) d.dispose();
    disposables = [];
  });

  it("open creates a window with the given size and focuses it", () => {
    s().open("core.chat", { w: 880, h: 640 });
    const win = s().windows["core.chat"];
    expect(win).toMatchObject({ w: 880, h: 640, minimized: false });
    expect(s().order).toEqual(["core.chat"]);
    expect(s().activeId).toBe("core.chat");
  });

  it("open on an already-open app restores and focuses instead of duplicating", () => {
    s().open("core.chat");
    s().minimize("core.chat");
    s().open("core.chat");
    expect(s().order).toEqual(["core.chat"]);
    expect(s().windows["core.chat"].minimized).toBe(false);
    expect(s().activeId).toBe("core.chat");
  });

  it("close removes the window and refocuses the most recent one", () => {
    s().open("core.chat");
    s().open("core.inbox");
    s().close("core.inbox");
    expect(s().windows["core.inbox"]).toBeUndefined();
    expect(s().activeId).toBe("core.chat");
  });

  it("focus raises the z-order above other windows", () => {
    s().open("core.chat");
    s().open("core.inbox");
    s().focus("core.chat");
    expect(s().windows["core.chat"].z).toBeGreaterThan(
      s().windows["core.inbox"].z,
    );
    expect(s().activeId).toBe("core.chat");
  });

  it("toggleMaximize saves geometry and restores it on the second toggle", () => {
    s().open("core.chat", { w: 700, h: 500 });
    s().move("core.chat", 150, 120);
    s().toggleMaximize("core.chat");
    expect(s().windows["core.chat"].maximized).toBe(true);
    expect(s().windows["core.chat"].prev).toEqual({
      x: 150,
      y: 120,
      w: 700,
      h: 500,
    });
    s().toggleMaximize("core.chat");
    const win = s().windows["core.chat"];
    expect(win.maximized).toBe(false);
    expect({ x: win.x, y: win.y, w: win.w, h: win.h }).toEqual({
      x: 150,
      y: 120,
      w: 700,
      h: 500,
    });
  });

  it("snap keeps the pre-snap geometry in prev for later restore", () => {
    s().open("core.chat", { w: 700, h: 500 });
    s().move("core.chat", 200, 180);
    s().snap("core.chat", "left");
    const win = s().windows["core.chat"];
    expect(win.maximized).toBe(false);
    expect(win.prev).toEqual({ x: 200, y: 180, w: 700, h: 500 });
  });

  it("resize applies partial rects (edge resize moves x with w)", () => {
    s().open("core.chat", { w: 700, h: 500 });
    s().move("core.chat", 100, 100);
    s().resize("core.chat", { x: 60, w: 740 });
    const win = s().windows["core.chat"];
    expect(win).toMatchObject({ x: 60, y: 100, w: 740, h: 500 });
  });

  it("switchSpace saves the current layout and restores it when switching back", () => {
    s().open("core.chat");
    s().switchSpace("agent-b");
    expect(s().order).toEqual([]);
    expect(s().saved["default"].order).toEqual(["core.chat"]);

    s().open("core.inbox");
    s().switchSpace("default");
    expect(s().order).toEqual(["core.chat"]);
    expect(s().saved["agent-b"].order).toEqual(["core.inbox"]);
  });

  it("switchSpace to the current space only closes mission control", () => {
    s().setMissionControl(true);
    s().switchSpace("default");
    expect(s().missionControlOpen).toBe(false);
    expect(s().spaceId).toBe("default");
  });

  it("open clamps the initial size to the provided minimum", () => {
    s().open("os.settings", { w: 400, h: 300, minW: 960, minH: 560 });
    const win = s().windows["os.settings"];
    expect(win.w).toBeGreaterThanOrEqual(960);
    expect(win.h).toBeGreaterThanOrEqual(560);
  });

  it("open without minimums keeps the requested size", () => {
    s().open("core.chat", { w: 880, h: 640 });
    expect(s().windows["core.chat"]).toMatchObject({ w: 880, h: 640 });
  });

  it("open without an explicit size falls back to the app manifest", () => {
    // System Settings manifest: 1200x720, min 960x560 (osApps.ts).
    s().open("os.settings");
    expect(s().windows["os.settings"]).toMatchObject({ w: 1200, h: 720 });
  });

  it("open resolves dynamic plugin app sizes via the registry", () => {
    disposables.push(
      routeRegistry.add("office", {
        id: "plugin.office",
        path: "/apps/office",
        component: () => null,
      }),
    );
    s().open("plugin.office");
    expect(s().windows["plugin.office"]).toMatchObject({ w: 960, h: 680 });
  });

  it("purgeApps drops the given ids in active and saved spaces", () => {
    s().open("core.chat");
    s().open("core.inbox");
    s().switchSpace("agent-b");
    s().open("core.tools");
    s().open("core.mcp");

    s().purgeApps(new Set(["core.inbox", "core.mcp"]));

    // Active space: core.mcp is gone, core.tools survives.
    expect(s().windows["core.mcp"]).toBeUndefined();
    expect(s().order).toEqual(["core.tools"]);
    expect(s().activeId).toBe("core.tools");
    // Saved space: core.inbox is gone, core.chat survives.
    const savedDefault = s().saved["default"];
    expect(savedDefault.windows["core.inbox"]).toBeUndefined();
    expect(savedDefault.order).toEqual(["core.chat"]);
    expect(savedDefault.activeId).toBe("core.chat");
  });

  it("purgeApps is a no-op for ids that are not present", () => {
    s().open("core.chat");
    s().open("core.inbox");
    const before = s().windows;
    s().purgeApps(new Set(["gone.app"]));
    expect(s().windows).toBe(before);
    expect(s().order).toEqual(["core.chat", "core.inbox"]);
  });

  it("purgeSpace drops exactly the deleted agent's saved layout", () => {
    s().open("core.chat");
    s().switchSpace("agent-b"); // saves default
    s().open("core.inbox");
    s().switchSpace("agent-c"); // saves agent-b

    s().purgeSpace("agent-b");

    expect(s().saved["agent-b"]).toBeUndefined();
    expect(s().saved["default"]).toBeDefined();
  });

  it("purgeSpace clears the active layout when it is the displayed space", () => {
    s().open("core.chat");
    s().purgeSpace("default");
    expect(s().order).toEqual([]);
    expect(s().windows).toEqual({});
    expect(s().activeId).toBeNull();
    // The purged space cannot be resurrected by a later space switch.
    s().switchSpace("agent-b");
    expect(s().saved["default"]).toBeUndefined();
  });

  it("debounces localStorage writes during a drag burst", () => {
    // The test body stays fully synchronous, so only fake timers can
    // trigger the debounced flush inside this test.
    vi.useFakeTimers();
    try {
      s().open("core.chat", { w: 700, h: 500 });
      // Flush the open() write, then clear the stored value so the burst
      // below is observable in isolation.
      vi.advanceTimersByTime(300);
      window.localStorage.removeItem("qwenpaw-os-windows");
      for (let i = 0; i < 30; i += 1) {
        s().move("core.chat", 100 + i, 100);
      }
      // Mid-burst: no write per pointermove-driven update.
      expect(window.localStorage.getItem("qwenpaw-os-windows")).toBeNull();
      vi.advanceTimersByTime(300);
      // One write after the burst, carrying the final geometry.
      const stored = window.localStorage.getItem("qwenpaw-os-windows");
      expect(stored).toContain('"x":129');
    } finally {
      vi.useRealTimers();
    }
  });

  it("ignores a delayed flush after the window environment is gone", () => {
    vi.useFakeTimers();
    const originalWindow = globalThis.window;
    try {
      s().open("core.chat", { w: 700, h: 500 });
      vi.stubGlobal("window", undefined);
      expect(() => vi.advanceTimersByTime(300)).not.toThrow();
    } finally {
      vi.stubGlobal("window", originalWindow);
      vi.useRealTimers();
    }
  });

  it("clampToViewport pulls off-screen windows back into the work area", () => {
    s().open("core.chat", { w: 700, h: 500 });
    s().move("core.chat", 5000, -300);
    s().clampToViewport();
    const win = s().windows["core.chat"];
    expect(win.x).toBeLessThanOrEqual(1920 - 80);
    expect(win.y).toBeGreaterThanOrEqual(28);
  });

  it("clampToViewport shrinks oversized windows to the viewport", () => {
    s().open("core.chat", { w: 700, h: 500 });
    s().resize("core.chat", { w: 5000, h: 4000 });
    s().clampToViewport();
    const win = s().windows["core.chat"];
    expect(win.w).toBeLessThanOrEqual(1920 - 40);
    expect(win.h).toBeLessThanOrEqual(1080 - 140);
  });

  it("clampToViewport reclamps saved spaces and restore rects on shrink", () => {
    s().open("core.chat", { w: 700, h: 500 });
    s().move("core.chat", 1500, 900);
    s().toggleMaximize("core.chat"); // prev = { x:1500, y:900, ... }
    s().switchSpace("agent-b");

    // Viewport shrinks (smaller monitor / DPI change) before re-clamping.
    window.innerWidth = 800;
    window.innerHeight = 500;
    s().clampToViewport();

    const saved = s().saved["default"].windows["core.chat"];
    expect(saved.x).toBeLessThanOrEqual(800 - 80);
    expect(saved.y).toBeLessThanOrEqual(500 - 78 - 40);
    expect(saved.prev).toBeDefined();
    expect(saved.prev!.x).toBeLessThanOrEqual(800 - 80);
    expect(saved.prev!.y).toBeLessThanOrEqual(500 - 78 - 40);
    expect(saved.prev!.w).toBeLessThanOrEqual(800 - 40);
    expect(saved.prev!.h).toBeLessThanOrEqual(500 - 140);
  });
});
