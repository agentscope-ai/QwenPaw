import { beforeEach, describe, expect, it } from "vitest";

import { DEFAULT_FOCUS_ITEM_IDS, useSidebarStore } from "./sidebarStore";

const FOCUS_ITEMS_STORAGE_KEY = "qwenpaw_sidebar_focus_items_v1";
const HIDDEN_PLUGIN_ITEMS_STORAGE_KEY =
  "qwenpaw_sidebar_hidden_plugin_items_v1";

describe("sidebarStore", () => {
  beforeEach(() => {
    localStorage.removeItem(FOCUS_ITEMS_STORAGE_KEY);
    localStorage.removeItem(HIDDEN_PLUGIN_ITEMS_STORAGE_KEY);
    useSidebarStore.setState({
      focusItemIds: DEFAULT_FOCUS_ITEM_IDS,
      hiddenPluginItemIds: [],
    });
  });

  it("uses the requested default sidebar shortcuts in display order", () => {
    expect(DEFAULT_FOCUS_ITEM_IDS).toEqual([
      "core.cron-jobs",
      "core.files",
      "core.agent-config",
      "core.models",
    ]);
  });

  it("persists preferences without fixed sidebar entries", () => {
    useSidebarStore
      .getState()
      .setFocusItemIds([
        "core.files",
        "core.inbox",
        "core.marketplace",
        "plugin.example",
      ]);

    expect(useSidebarStore.getState().focusItemIds).toEqual([
      "core.files",
      "plugin.example",
    ]);
    expect(
      JSON.parse(localStorage.getItem(FOCUS_ITEMS_STORAGE_KEY) || "[]"),
    ).toEqual(["core.files", "plugin.example"]);
  });

  it("restores the default sidebar items", () => {
    useSidebarStore.getState().setSidebarItemVisible("plugin.example", false);
    useSidebarStore.getState().setFocusItemIds([]);
    useSidebarStore.getState().resetFocusItemIds();

    expect(useSidebarStore.getState().focusItemIds).toEqual(
      DEFAULT_FOCUS_ITEM_IDS,
    );
    expect(useSidebarStore.getState().hiddenPluginItemIds).toEqual([]);
  });

  it("does not expose the default array through mutable store state", () => {
    useSidebarStore.getState().resetFocusItemIds();

    expect(useSidebarStore.getState().focusItemIds).not.toBe(
      DEFAULT_FOCUS_ITEM_IDS,
    );
  });

  it("keeps plugins visible by default and persists an explicit hide", () => {
    expect(useSidebarStore.getState().hiddenPluginItemIds).toEqual([]);

    useSidebarStore.getState().setSidebarItemVisible("plugin.example", false);

    expect(useSidebarStore.getState().hiddenPluginItemIds).toEqual([
      "plugin.example",
    ]);
    expect(
      JSON.parse(localStorage.getItem(HIDDEN_PLUGIN_ITEMS_STORAGE_KEY) || "[]"),
    ).toEqual(["plugin.example"]);

    useSidebarStore.getState().setSidebarItemVisible("plugin.example", true);
    expect(useSidebarStore.getState().hiddenPluginItemIds).toEqual([]);
  });

  it("selects all built-in and plugin shortcuts in one update", () => {
    useSidebarStore.setState({
      focusItemIds: ["core.files"],
      hiddenPluginItemIds: ["plugin.example"],
    });

    useSidebarStore
      .getState()
      .setSidebarItemsVisible(
        ["core.inbox", "core.security", "plugin.example"],
        true,
      );

    expect(useSidebarStore.getState().focusItemIds).toEqual([
      "core.files",
      "core.security",
    ]);
    expect(useSidebarStore.getState().hiddenPluginItemIds).toEqual([]);
  });

  it("inverts shortcuts while ignoring fixed sidebar entries", () => {
    useSidebarStore.setState({
      focusItemIds: ["core.files", "core.security"],
      hiddenPluginItemIds: ["plugin.hidden"],
    });

    useSidebarStore
      .getState()
      .invertSidebarItems([
        "core.inbox",
        "core.marketplace",
        "core.security",
        "core.debug",
        "plugin.visible",
        "plugin.hidden",
      ]);

    expect(useSidebarStore.getState().focusItemIds).toEqual([
      "core.files",
      "core.debug",
    ]);
    expect(useSidebarStore.getState().hiddenPluginItemIds).toEqual([
      "plugin.visible",
    ]);
  });
});
