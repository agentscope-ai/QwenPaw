import { afterEach, describe, expect, it } from "vitest";
import {
  migrateWorkbenchPreferences,
  readStoredWorkbenchLayout,
  storeWorkbenchLayout,
  workbenchLayoutStorageKey,
  workbenchWidthStorageKey,
} from "./workbenchPreferences";

describe("workbenchPreferences", () => {
  afterEach(() => localStorage.clear());

  it("round-trips a dynamic tab layout", () => {
    const key = workbenchLayoutStorageKey("agent-a", "chat-1");
    storeWorkbenchLayout(key, {
      openTabs: ["terminal", "files"],
      activeTab: "terminal",
    });

    expect(readStoredWorkbenchLayout(key)).toEqual({
      openTabs: ["terminal", "files"],
      activeTab: "terminal",
    });
  });

  it("drops invalid and duplicate capabilities", () => {
    const key = workbenchLayoutStorageKey("agent-a", "chat-1");
    localStorage.setItem(
      key,
      JSON.stringify({
        openTabs: ["files", "unknown", "files"],
        activeTab: "unknown",
      }),
    );

    expect(readStoredWorkbenchLayout(key)).toEqual({
      openTabs: ["files"],
      activeTab: null,
    });
  });

  it("migrates temporary session preferences to the resolved session", () => {
    const sourceLayoutKey = workbenchLayoutStorageKey("agent-a", "new");
    storeWorkbenchLayout(sourceLayoutKey, {
      openTabs: ["terminal"],
      activeTab: "terminal",
    });
    localStorage.setItem(workbenchWidthStorageKey("agent-a", "new"), "720");

    migrateWorkbenchPreferences("agent-a", "new", "chat-1");

    expect(
      readStoredWorkbenchLayout(workbenchLayoutStorageKey("agent-a", "chat-1")),
    ).toEqual({ openTabs: ["terminal"], activeTab: "terminal" });
    expect(
      localStorage.getItem(workbenchWidthStorageKey("agent-a", "chat-1")),
    ).toBe("720");
    expect(localStorage.getItem(sourceLayoutKey)).toBeNull();
    expect(
      localStorage.getItem(workbenchWidthStorageKey("agent-a", "new")),
    ).toBeNull();
  });

  it("does not overwrite preferences already stored for the target", () => {
    const sourceKey = workbenchLayoutStorageKey("agent-a", "new");
    const targetKey = workbenchLayoutStorageKey("agent-a", "chat-1");
    storeWorkbenchLayout(sourceKey, {
      openTabs: ["tools"],
      activeTab: "tools",
    });
    storeWorkbenchLayout(targetKey, {
      openTabs: ["files"],
      activeTab: "files",
    });

    migrateWorkbenchPreferences("agent-a", "new", "chat-1");

    expect(readStoredWorkbenchLayout(targetKey)).toEqual({
      openTabs: ["files"],
      activeTab: "files",
    });
    expect(localStorage.getItem(sourceKey)).toBeNull();
  });
});
