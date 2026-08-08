import { describe, it, expect, beforeEach } from "vitest";
import { renderHook } from "@testing-library/react";
import {
  AGENT_FILES_TABS_STORAGE_KEY,
  SESSION_FILES_TABS_STORAGE_KEY,
  useCodingTabsStore,
  useTabsForScope,
  ORIGINAL_DIFF_SIZE_LIMIT,
} from "./codingTabsStore";

const TAB_FOO = { path: "foo.ts", content: "", dirty: false };

describe("codingTabsStore", () => {
  beforeEach(() => {
    localStorage.clear();
    useCodingTabsStore.setState({
      tabsByAgent: {},
      activeTabByAgent: {},
      diffsByAgent: {},
    });
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

  it("keeps the display path separate from the internal tab key", () => {
    useCodingTabsStore.getState().openTab("a1", {
      path: "attachment::hello.txt",
      displayPath: "/workspace/hello.txt",
      content: "hello",
      dirty: false,
    });

    const tab = useCodingTabsStore.getState().tabsByAgent["a1"]?.[0];

    expect(tab?.path).toBe("attachment::hello.txt");
    expect(tab?.displayPath).toBe("/workspace/hello.txt");
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

  it("setTabEtag updates the in-memory disk version", () => {
    useCodingTabsStore.getState().openTab("a1", {
      ...TAB_FOO,
      etag: "v1",
    });

    useCodingTabsStore.getState().setTabEtag("a1", "foo.ts", "v2");

    expect(useCodingTabsStore.getState().tabsByAgent["a1"][0].etag).toBe("v2");
  });

  it("setTabDirty updates the dirty flag of an open tab", () => {
    useCodingTabsStore.getState().openTab("a1", TAB_FOO);
    useCodingTabsStore.getState().setTabDirty("a1", "foo.ts", true);
    const tab = useCodingTabsStore
      .getState()
      .tabsByAgent["a1"].find((t) => t.path === "foo.ts");
    expect(tab?.dirty).toBe(true);
  });

  it("resolveDiff updates content and removes the diff atomically", () => {
    useCodingTabsStore.getState().openTab("a1", {
      path: "foo.ts",
      content: "old",
      dirty: true,
    });
    useCodingTabsStore
      .getState()
      .setDiff("a1", "foo.ts", { original: "old", modified: "new" });

    useCodingTabsStore.getState().resolveDiff("a1", "foo.ts", "new");

    const state = useCodingTabsStore.getState();
    expect(state.tabsByAgent["a1"][0]).toMatchObject({
      content: "new",
      dirty: false,
    });
    expect(state.diffsByAgent["a1"]).not.toHaveProperty("foo.ts");
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
  // Selector: useTabsForScope
  // ---------------------------------------------------------------------------

  it("useTabsForScope returns tabs for the requested scope", () => {
    useCodingTabsStore.setState({
      tabsByAgent: {
        "agent-x": [{ path: "x.ts", content: "", dirty: false }],
      },
      activeTabByAgent: {},
      diffsByAgent: {},
    });

    const { result } = renderHook(() => useTabsForScope("agent-x"));
    expect(result.current).toHaveLength(1);
    expect(result.current[0].path).toBe("x.ts");
  });

  it("keeps Agent and Session tabs with the same path isolated", () => {
    const store = useCodingTabsStore.getState();
    store.openTab("agent:a1", { ...TAB_FOO, content: "agent" });
    store.openTab("session:a1:s1", { ...TAB_FOO, content: "session" });

    expect(
      useCodingTabsStore.getState().tabsByAgent["agent:a1"][0].content,
    ).toBe("agent");
    expect(
      useCodingTabsStore.getState().tabsByAgent["session:a1:s1"][0].content,
    ).toBe("session");
  });

  it("opening a Chat preview workspace tab never opens an Agent tab", () => {
    useCodingTabsStore
      .getState()
      .openTab("session:a1:s1", { ...TAB_FOO, content: "session" });

    const state = useCodingTabsStore.getState();
    expect(state.tabsByAgent["session:a1:s1"]).toHaveLength(1);
    expect(state.tabsByAgent["agent:a1"]).toBeUndefined();
  });

  it("persists Agent and Session tabs in separate containers", () => {
    const store = useCodingTabsStore.getState();
    store.openTab("agent:a1", { ...TAB_FOO, content: "agent" });
    store.openTab("session:a1:s1", { ...TAB_FOO, content: "session" });

    const agentEnvelope = JSON.parse(
      localStorage.getItem(AGENT_FILES_TABS_STORAGE_KEY) ?? "{}",
    );
    const sessionEnvelope = JSON.parse(
      localStorage.getItem(SESSION_FILES_TABS_STORAGE_KEY) ?? "{}",
    );

    expect(agentEnvelope.state.tabsByAgent["agent:a1"]).toHaveLength(1);
    expect(agentEnvelope.state.tabsByAgent["session:a1:s1"]).toBeUndefined();
    expect(sessionEnvelope.state.tabsByAgent["session:a1:s1"]).toHaveLength(1);
    expect(sessionEnvelope.state.tabsByAgent["agent:a1"]).toBeUndefined();
    expect(localStorage.getItem("qwenpaw-files-workbench")).toBeNull();
  });

  it("migrates a temporary Session scope to its backend id", () => {
    const store = useCodingTabsStore.getState();
    store.openTab("session:a1:new", TAB_FOO);
    store.setActiveTab("session:a1:new", TAB_FOO.path);
    store.setDiff("session:a1:new", TAB_FOO.path, {
      original: "old",
      modified: "new",
    });

    store.migrateScope("session:a1:new", "session:a1:uuid");

    const state = useCodingTabsStore.getState();
    expect(state.tabsByAgent["session:a1:new"]).toBeUndefined();
    expect(state.tabsByAgent["session:a1:uuid"]).toHaveLength(1);
    expect(state.activeTabByAgent["session:a1:uuid"]).toBe(TAB_FOO.path);
    expect(state.diffsByAgent["session:a1:uuid"]).toHaveProperty(TAB_FOO.path);
  });

  it("clears only project-root tabs when the directory changes", () => {
    const store = useCodingTabsStore.getState();
    store.openTab("agent:a1", {
      ...TAB_FOO,
      workspaceRoot: "project",
      source: "workspace",
    });
    store.openTab("agent:a1", {
      path: "profile::AGENTS.md",
      content: "",
      dirty: false,
      source: "profile",
      workspaceRoot: "workspace",
    });

    store.clearProjectTabs("agent:a1");

    expect(useCodingTabsStore.getState().tabsByAgent["agent:a1"]).toEqual([
      expect.objectContaining({ path: "profile::AGENTS.md" }),
    ]);
  });
});
