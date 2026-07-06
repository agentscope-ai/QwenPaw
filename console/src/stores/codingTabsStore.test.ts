import { describe, it, expect, beforeEach } from "vitest";
import { renderHook } from "@testing-library/react";
import { useAgentStore } from "./agentStore";
import {
  useCodingTabsStore,
  useCurrentTabs,
  ORIGINAL_DIFF_SIZE_LIMIT,
} from "./codingTabsStore";

const TAB_FOO = { path: "foo.ts", content: "", dirty: false };

describe("codingTabsStore", () => {
  beforeEach(() => {
    useCodingTabsStore.setState({
      tabsByAgent: {},
      activeTabByAgent: {},
      diffsByAgent: {},
    });
    useAgentStore.setState({ selectedAgent: "default", agents: [] });
  });

  // ---------------------------------------------------------------------------
  // Initial state
  // ---------------------------------------------------------------------------

  it("all three maps start empty", () => {
    const state = useCodingTabsStore.getState();
    expect(state.tabsByAgent).toEqual({});
    expect(state.activeTabByAgent).toEqual({});
    expect(state.diffsByAgent).toEqual({});
  });

  // ---------------------------------------------------------------------------
  // openTab
  // ---------------------------------------------------------------------------

  it("openTab adds a tab for the agent", () => {
    useCodingTabsStore.getState().openTab("a1", TAB_FOO);
    const tabs = useCodingTabsStore.getState().tabsByAgent["a1"];
    expect(tabs).toHaveLength(1);
    expect(tabs[0].path).toBe("foo.ts");
  });

  it("openTab is a no-op when the same path is opened twice", () => {
    useCodingTabsStore.getState().openTab("a1", TAB_FOO);
    useCodingTabsStore.getState().openTab("a1", TAB_FOO);
    expect(useCodingTabsStore.getState().tabsByAgent["a1"]).toHaveLength(1);
  });

  // ---------------------------------------------------------------------------
  // closeTab
  // ---------------------------------------------------------------------------

  it("closeTab removes the tab from the list", () => {
    useCodingTabsStore.getState().openTab("a1", TAB_FOO);
    useCodingTabsStore.getState().closeTab("a1", "foo.ts");
    expect(useCodingTabsStore.getState().tabsByAgent["a1"]).toHaveLength(0);
  });

  it("closeTab also removes the diff for that path", () => {
    useCodingTabsStore.getState().openTab("a1", TAB_FOO);
    useCodingTabsStore
      .getState()
      .setDiff("a1", "foo.ts", { original: "old", modified: "new" });
    useCodingTabsStore.getState().closeTab("a1", "foo.ts");
    const diffs = useCodingTabsStore.getState().diffsByAgent["a1"];
    expect(diffs).not.toHaveProperty("foo.ts");
  });

  // ---------------------------------------------------------------------------
  // setActiveTab
  // ---------------------------------------------------------------------------

  it("setActiveTab sets activeTabByAgent for the agent", () => {
    useCodingTabsStore.getState().setActiveTab("a1", "foo.ts");
    expect(useCodingTabsStore.getState().activeTabByAgent["a1"]).toBe("foo.ts");
  });

  // ---------------------------------------------------------------------------
  // setTabContent + setTabDirty
  // ---------------------------------------------------------------------------

  it("setTabContent updates the content of an open tab", () => {
    useCodingTabsStore.getState().openTab("a1", TAB_FOO);
    useCodingTabsStore.getState().setTabContent("a1", "foo.ts", "hello");
    const tab = useCodingTabsStore
      .getState()
      .tabsByAgent["a1"].find((t) => t.path === "foo.ts");
    expect(tab?.content).toBe("hello");
  });

  it("setTabDirty updates the dirty flag of an open tab", () => {
    useCodingTabsStore.getState().openTab("a1", TAB_FOO);
    useCodingTabsStore.getState().setTabDirty("a1", "foo.ts", true);
    const tab = useCodingTabsStore
      .getState()
      .tabsByAgent["a1"].find((t) => t.path === "foo.ts");
    expect(tab?.dirty).toBe(true);
  });

  // ---------------------------------------------------------------------------
  // clearAgent
  // ---------------------------------------------------------------------------

  it("clearAgent resets tabs, activeTab, and diffs for the agent", () => {
    useCodingTabsStore.getState().openTab("a1", TAB_FOO);
    useCodingTabsStore.getState().setActiveTab("a1", "foo.ts");
    useCodingTabsStore
      .getState()
      .setDiff("a1", "foo.ts", { original: "old", modified: "new" });

    useCodingTabsStore.getState().clearAgent("a1");

    const state = useCodingTabsStore.getState();
    expect(state.tabsByAgent["a1"]).toEqual([]);
    expect(state.activeTabByAgent["a1"]).toBe("");
    expect(state.diffsByAgent["a1"]).toEqual({});
  });

  // ---------------------------------------------------------------------------
  // setDiff / removeDiff / updateDiffModified / updateDiffOriginal
  // ---------------------------------------------------------------------------

  it("setDiff stores a diff for the given agent and path", () => {
    useCodingTabsStore
      .getState()
      .setDiff("a1", "foo.ts", { original: "old", modified: "new" });
    const diff = useCodingTabsStore.getState().diffsByAgent["a1"]["foo.ts"];
    expect(diff).toEqual({ original: "old", modified: "new" });
  });

  it("removeDiff removes the diff for the given path", () => {
    useCodingTabsStore
      .getState()
      .setDiff("a1", "foo.ts", { original: "old", modified: "new" });
    useCodingTabsStore.getState().removeDiff("a1", "foo.ts");
    expect(useCodingTabsStore.getState().diffsByAgent["a1"]).not.toHaveProperty(
      "foo.ts",
    );
  });

  it("updateDiffModified updates the modified field of an existing diff", () => {
    useCodingTabsStore
      .getState()
      .setDiff("a1", "foo.ts", { original: "old", modified: "new" });
    useCodingTabsStore.getState().updateDiffModified("a1", "foo.ts", "updated");
    const diff = useCodingTabsStore.getState().diffsByAgent["a1"]["foo.ts"];
    expect(diff.modified).toBe("updated");
    expect(diff.original).toBe("old");
  });

  it("updateDiffOriginal updates the original field of an existing diff", () => {
    useCodingTabsStore
      .getState()
      .setDiff("a1", "foo.ts", { original: "old", modified: "new" });
    useCodingTabsStore
      .getState()
      .updateDiffOriginal("a1", "foo.ts", "new-orig");
    const diff = useCodingTabsStore.getState().diffsByAgent["a1"]["foo.ts"];
    expect(diff.original).toBe("new-orig");
    expect(diff.modified).toBe("new");
  });

  // ---------------------------------------------------------------------------
  // ORIGINAL_DIFF_SIZE_LIMIT
  // ---------------------------------------------------------------------------

  it("ORIGINAL_DIFF_SIZE_LIMIT equals 256 * 1024 (262144)", () => {
    expect(ORIGINAL_DIFF_SIZE_LIMIT).toBe(262144);
  });

  // ---------------------------------------------------------------------------
  // Selector: useCurrentTabs
  // ---------------------------------------------------------------------------

  it("useCurrentTabs returns tabs for the currently selected agent", () => {
    useAgentStore.setState({ selectedAgent: "agent-x", agents: [] });
    useCodingTabsStore.setState({
      tabsByAgent: {
        "agent-x": [{ path: "x.ts", content: "", dirty: false }],
      },
      activeTabByAgent: {},
      diffsByAgent: {},
    });

    const { result } = renderHook(() => useCurrentTabs());
    expect(result.current).toHaveLength(1);
    expect(result.current[0].path).toBe("x.ts");
  });
});
