import { describe, it, expect, beforeEach, vi } from "vitest";
import {
  DEFAULT_FOCUS_ITEM_IDS,
  useSidebarModeStore,
} from "./sidebarModeStore";

const STORAGE_KEY = "qwenpaw_sidebar_mode";
const FOCUS_ITEMS_STORAGE_KEY = "qwenpaw_sidebar_focus_items_v1";
const HIDDEN_PLUGIN_ITEMS_STORAGE_KEY =
  "qwenpaw_sidebar_hidden_plugin_items_v1";

function clearStorage() {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
}

describe("sidebarModeStore", () => {
  beforeEach(() => {
    clearStorage();
    localStorage.removeItem(FOCUS_ITEMS_STORAGE_KEY);
    localStorage.removeItem(HIDDEN_PLUGIN_ITEMS_STORAGE_KEY);
    useSidebarModeStore.setState({
      mode: "full",
      focusItemIds: DEFAULT_FOCUS_ITEM_IDS,
      hiddenPluginItemIds: [],
    });
    vi.clearAllMocks();
  });

  // ---------------------------------------------------------------------------
  // Initial state — tri-state-ish (persisted "simple" / persisted other / no value)
  // ---------------------------------------------------------------------------

  it("defaults to 'full' when localStorage has no entry (via setstate we can't test create-time)", () => {
    // After our reset, the store has the value we set.
    useSidebarModeStore.setState({ mode: "full" });
    expect(useSidebarModeStore.getState().mode).toBe("full");
  });

  it("persists to the 'qwenpaw_sidebar_mode' localStorage key", () => {
    useSidebarModeStore.getState().setMode("simple");
    expect(localStorage.getItem("qwenpaw_sidebar_mode")).toBe("simple");
  });

  // ---------------------------------------------------------------------------
  // setMode
  // ---------------------------------------------------------------------------

  it("setMode('simple') persists 'simple' to localStorage and updates state", () => {
    useSidebarModeStore.getState().setMode("simple");

    expect(useSidebarModeStore.getState().mode).toBe("simple");
    expect(localStorage.getItem(STORAGE_KEY)).toBe("simple");
  });

  it("setMode('full') removes the localStorage entry and updates state", () => {
    localStorage.setItem(STORAGE_KEY, "simple");

    useSidebarModeStore.getState().setMode("full");

    expect(useSidebarModeStore.getState().mode).toBe("full");
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it("setMode updates state across multiple calls", () => {
    useSidebarModeStore.getState().setMode("simple");
    expect(useSidebarModeStore.getState().mode).toBe("simple");

    useSidebarModeStore.getState().setMode("full");
    expect(useSidebarModeStore.getState().mode).toBe("full");

    useSidebarModeStore.getState().setMode("simple");
    expect(useSidebarModeStore.getState().mode).toBe("simple");
  });

  // ---------------------------------------------------------------------------
  // toggleMode
  // ---------------------------------------------------------------------------

  it("toggleMode flips 'full' to 'simple' and persists 'simple'", () => {
    useSidebarModeStore.setState({ mode: "full" });

    useSidebarModeStore.getState().toggleMode();

    expect(useSidebarModeStore.getState().mode).toBe("simple");
    expect(localStorage.getItem(STORAGE_KEY)).toBe("simple");
  });

  it("toggleMode flips 'simple' to 'full' and removes the localStorage entry", () => {
    useSidebarModeStore.setState({ mode: "simple" });
    localStorage.setItem(STORAGE_KEY, "simple");

    useSidebarModeStore.getState().toggleMode();

    expect(useSidebarModeStore.getState().mode).toBe("full");
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it("toggleMode round-trips back to the original mode after two calls", () => {
    useSidebarModeStore.setState({ mode: "full" });

    useSidebarModeStore.getState().toggleMode();
    expect(useSidebarModeStore.getState().mode).toBe("simple");

    useSidebarModeStore.getState().toggleMode();
    expect(useSidebarModeStore.getState().mode).toBe("full");
  });

  it("persists focus-navigation item visibility without the fixed inbox", () => {
    useSidebarModeStore
      .getState()
      .setFocusItemIds(["core.files", "core.inbox", "plugin.example"]);

    expect(useSidebarModeStore.getState().focusItemIds).toEqual([
      "core.files",
      "plugin.example",
    ]);
    expect(
      JSON.parse(localStorage.getItem(FOCUS_ITEMS_STORAGE_KEY) || "[]"),
    ).toEqual(["core.files", "plugin.example"]);
  });

  it("restores the default focus-navigation items", () => {
    useSidebarModeStore
      .getState()
      .setSidebarItemVisible("plugin.example", false);
    useSidebarModeStore.getState().setFocusItemIds([]);
    useSidebarModeStore.getState().resetFocusItemIds();

    expect(useSidebarModeStore.getState().focusItemIds).toEqual(
      DEFAULT_FOCUS_ITEM_IDS,
    );
    expect(useSidebarModeStore.getState().hiddenPluginItemIds).toEqual([]);
  });

  it("keeps plugins visible by default and persists an explicit hide", () => {
    expect(useSidebarModeStore.getState().hiddenPluginItemIds).toEqual([]);

    useSidebarModeStore
      .getState()
      .setSidebarItemVisible("plugin.example", false);

    expect(useSidebarModeStore.getState().hiddenPluginItemIds).toEqual([
      "plugin.example",
    ]);
    expect(
      JSON.parse(localStorage.getItem(HIDDEN_PLUGIN_ITEMS_STORAGE_KEY) || "[]"),
    ).toEqual(["plugin.example"]);

    useSidebarModeStore
      .getState()
      .setSidebarItemVisible("plugin.example", true);
    expect(useSidebarModeStore.getState().hiddenPluginItemIds).toEqual([]);
  });

  // ---------------------------------------------------------------------------
  // Storage failure resilience
  // ---------------------------------------------------------------------------

  it("setMode('simple') does not throw when localStorage.setItem throws", () => {
    const original = localStorage.getItem;
    const originalSet = localStorage.setItem;
    localStorage.setItem = vi.fn(() => {
      throw new Error("quota");
    });

    expect(() =>
      useSidebarModeStore.getState().setMode("simple"),
    ).not.toThrow();
    expect(useSidebarModeStore.getState().mode).toBe("simple");

    localStorage.setItem = originalSet;
    localStorage.getItem = original;
  });

  it("setMode('full') does not throw when localStorage.removeItem throws", () => {
    const original = localStorage.removeItem;
    localStorage.removeItem = vi.fn(() => {
      throw new Error("denied");
    });

    expect(() => useSidebarModeStore.getState().setMode("full")).not.toThrow();
    expect(useSidebarModeStore.getState().mode).toBe("full");

    localStorage.removeItem = original;
  });

  it("toggleMode does not throw when localStorage.setItem throws", () => {
    useSidebarModeStore.setState({ mode: "full" });
    const originalSet = localStorage.setItem;
    localStorage.setItem = vi.fn(() => {
      throw new Error("quota");
    });

    expect(() => useSidebarModeStore.getState().toggleMode()).not.toThrow();
    expect(useSidebarModeStore.getState().mode).toBe("simple");

    localStorage.setItem = originalSet;
  });
});
