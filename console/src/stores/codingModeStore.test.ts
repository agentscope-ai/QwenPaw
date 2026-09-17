import { describe, it, expect, beforeEach } from "vitest";
import { renderHook } from "@testing-library/react";
import { useCodingModeStore, useCodingMode } from "./codingModeStore";
import { useAgentStore } from "./agentStore";

beforeEach(() => {
  useCodingModeStore.setState({
    codingModeByAgent: {},
    codingModeRevisionByAgent: {},
  });
  useAgentStore.setState({ selectedAgent: "test-agent", agents: [] });
});

describe("codingModeStore", () => {
  // ---------------------------------------------------------------------------
  // Initial state
  // ---------------------------------------------------------------------------

  it("codingModeByAgent starts empty", () => {
    const { codingModeByAgent } = useCodingModeStore.getState();
    expect(codingModeByAgent).toEqual({});
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
      codingModeRevisionByAgent: {},
    });
    const { result } = renderHook(() => useCodingMode());
    expect(result.current.codingMode).toBe(false);
    expect(result.current.initialized).toBe(true);
  });
});
