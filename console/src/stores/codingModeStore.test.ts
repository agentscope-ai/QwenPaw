import { describe, it, expect, beforeEach } from "vitest";
import { renderHook } from "@testing-library/react";
import {
  useCodingModeStore,
  useCodingMode,
  useProjectDir,
} from "./codingModeStore";
import { useAgentStore } from "./agentStore";

beforeEach(() => {
  useCodingModeStore.setState({ codingModeByAgent: {}, projectDirByAgent: {} });
  useAgentStore.setState({ selectedAgent: "test-agent", agents: [] });
});

describe("codingModeStore", () => {
  // ---------------------------------------------------------------------------
  // Initial state
  // ---------------------------------------------------------------------------

  it("both codingModeByAgent and projectDirByAgent start empty", () => {
    const { codingModeByAgent, projectDirByAgent } =
      useCodingModeStore.getState();
    expect(codingModeByAgent).toEqual({});
    expect(projectDirByAgent).toEqual({});
  });

  // ---------------------------------------------------------------------------
  // setCodingMode
  // ---------------------------------------------------------------------------

  it("setCodingMode(true) stores true for the given agent", () => {
    useCodingModeStore.getState().setCodingMode("a1", true);
    expect(useCodingModeStore.getState().codingModeByAgent["a1"]).toBe(true);
  });

  it("setCodingMode(false) stores false for the given agent", () => {
    useCodingModeStore.getState().setCodingMode("a1", false);
    expect(useCodingModeStore.getState().codingModeByAgent["a1"]).toBe(false);
  });

  // ---------------------------------------------------------------------------
  // setProjectDir
  // ---------------------------------------------------------------------------

  it("setProjectDir stores the path string correctly", () => {
    useCodingModeStore.getState().setProjectDir("a1", "/path/to/project");
    expect(useCodingModeStore.getState().projectDirByAgent["a1"]).toBe(
      "/path/to/project",
    );
  });

  it("setProjectDir(null) stores null (user chose default workspace)", () => {
    useCodingModeStore.getState().setProjectDir("a1", null);
    expect(useCodingModeStore.getState().projectDirByAgent["a1"]).toBeNull();
  });

  // ---------------------------------------------------------------------------
  // useCodingMode hook
  // ---------------------------------------------------------------------------

  it("useCodingMode: agent not in store → codingMode false, initialized false", () => {
    useAgentStore.setState({ selectedAgent: "unknown-agent", agents: [] });
    const { result } = renderHook(() => useCodingMode());
    expect(result.current.codingMode).toBe(false);
    expect(result.current.initialized).toBe(false);
  });

  it("useCodingMode: agent in store with false → codingMode false, initialized TRUE", () => {
    useAgentStore.setState({ selectedAgent: "a1", agents: [] });
    useCodingModeStore.setState({
      codingModeByAgent: { a1: false },
      projectDirByAgent: {},
    });
    const { result } = renderHook(() => useCodingMode());
    expect(result.current.codingMode).toBe(false);
    expect(result.current.initialized).toBe(true);
  });

  // ---------------------------------------------------------------------------
  // useProjectDir hook
  // ---------------------------------------------------------------------------

  it("useProjectDir: agent never set projectDir → projectDir is undefined", () => {
    useAgentStore.setState({ selectedAgent: "never-set", agents: [] });
    const { result } = renderHook(() => useProjectDir());
    expect(result.current.projectDir).toBeUndefined();
  });
});
