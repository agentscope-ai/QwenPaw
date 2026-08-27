import { describe, it, expect, beforeEach } from "vitest";
import { act, renderHook } from "@testing-library/react";
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

  // ---------------------------------------------------------------------------
  // A#82590506 — codingMode resets to false when routing from coding to chat
  // ---------------------------------------------------------------------------
  describe("coding → chat route reset (#82590506)", () => {
    it("setCodingMode(agent, false) resets codingMode from true to false", () => {
      useAgentStore.setState({ selectedAgent: "a1", agents: [] });
      // Simulate coding mode active
      useCodingModeStore.getState().setCodingMode("a1", true);
      expect(useCodingModeStore.getState().codingModeByAgent["a1"]).toBe(true);

      // Navigate from coding to chat → backend returns enabled: false
      useCodingModeStore.getState().setCodingMode("a1", false);
      expect(useCodingModeStore.getState().codingModeByAgent["a1"]).toBe(false);
    });

    it("useCodingMode hook reflects reset after coding → chat navigation", () => {
      useAgentStore.setState({ selectedAgent: "a1", agents: [] });
      // Start in coding mode
      useCodingModeStore.getState().setCodingMode("a1", true);

      const { result, rerender } = renderHook(() => useCodingMode());
      expect(result.current.codingMode).toBe(true);

      // Simulate route change: useSyncCodingMode fetches backend → enabled: false
      act(() => {
        useCodingModeStore.getState().setCodingMode("a1", false);
      });
      rerender();

      expect(result.current.codingMode).toBe(false);
      expect(result.current.initialized).toBe(true);
    });

    it("revision increments on each setCodingMode call to prevent stale sync", () => {
      useCodingModeStore.getState().setCodingMode("a1", true);
      const rev1 =
        useCodingModeStore.getState().codingModeRevisionByAgent["a1"];

      useCodingModeStore.getState().setCodingMode("a1", false);
      const rev2 =
        useCodingModeStore.getState().codingModeRevisionByAgent["a1"];

      expect(rev2!).toBeGreaterThan(rev1!);
    });

    it("different agents maintain independent coding mode state during route switch", () => {
      // Agent a1 in coding mode, agent a2 not
      useCodingModeStore.getState().setCodingMode("a1", true);
      useCodingModeStore.getState().setCodingMode("a2", false);

      // Navigate a1 from coding to chat
      useCodingModeStore.getState().setCodingMode("a1", false);

      expect(useCodingModeStore.getState().codingModeByAgent["a1"]).toBe(false);
      // a2 unaffected
      expect(useCodingModeStore.getState().codingModeByAgent["a2"]).toBe(false);
    });
  });
});
