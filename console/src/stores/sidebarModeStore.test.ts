import { beforeEach, describe, expect, it } from "vitest";

import {
  DEFAULT_FOCUS_ITEM_IDS,
  useSidebarModeStore,
} from "./sidebarModeStore";

const FOCUS_ITEMS_STORAGE_KEY = "qwenpaw_sidebar_focus_items_v1";
const HIDDEN_PLUGIN_ITEMS_STORAGE_KEY =
  "qwenpaw_sidebar_hidden_plugin_items_v1";

describe("sidebarModeStore", () => {
  beforeEach(() => {
    localStorage.removeItem(FOCUS_ITEMS_STORAGE_KEY);
    localStorage.removeItem(HIDDEN_PLUGIN_ITEMS_STORAGE_KEY);
    useSidebarModeStore.setState({
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
    useSidebarModeStore
      .getState()
      .setFocusItemIds([
        "core.files",
        "core.inbox",
        "core.marketplace",
        "plugin.example",
      ]);

    expect(useSidebarModeStore.getState().focusItemIds).toEqual([
      "core.files",
      "plugin.example",
    ]);
    expect(
      JSON.parse(localStorage.getItem(FOCUS_ITEMS_STORAGE_KEY) || "[]"),
    ).toEqual(["core.files", "plugin.example"]);
  });

  it("restores the default sidebar items", () => {
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

  it("selects all built-in and plugin shortcuts in one update", () => {
    useSidebarModeStore.setState({
      focusItemIds: ["core.files"],
      hiddenPluginItemIds: ["plugin.example"],
    });

    useSidebarModeStore
      .getState()
      .setSidebarItemsVisible(
        ["core.inbox", "core.security", "plugin.example"],
        true,
      );

    expect(useSidebarModeStore.getState().focusItemIds).toEqual([
      "core.files",
      "core.security",
    ]);
    expect(useSidebarModeStore.getState().hiddenPluginItemIds).toEqual([]);
  });

  it("inverts shortcuts while ignoring fixed sidebar entries", () => {
    useSidebarModeStore.setState({
      focusItemIds: ["core.files", "core.security"],
      hiddenPluginItemIds: ["plugin.hidden"],
    });

    useSidebarModeStore
      .getState()
      .invertSidebarItems([
        "core.inbox",
        "core.marketplace",
        "core.security",
        "core.debug",
        "plugin.visible",
        "plugin.hidden",
      ]);

    expect(useSidebarModeStore.getState().focusItemIds).toEqual([
      "core.files",
      "core.debug",
    ]);
    expect(useSidebarModeStore.getState().hiddenPluginItemIds).toEqual([
      "plugin.visible",
    ]);
  });
});
