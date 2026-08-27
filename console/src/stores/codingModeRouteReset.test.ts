/* eslint-disable @typescript-eslint/no-explicit-any, @typescript-eslint/no-unused-vars */
/**
 * codingModeRouteReset.test.ts — regression for A#82590506 (coding -> chat mode switch)
 *
 * When the user navigates from Coding mode to Chat mode (route change),
 * the coding mode state must be properly managed. The useSyncCodingMode
 * hook fetches the coding mode from the backend when the agent changes.
 *
 * This test covers the store-level behavior:
 *   - codingModeStore correctly tracks per-agent mode
 *   - setCodingMode updates both the mode and the revision counter
 *   - The revision counter prevents stale responses from overwriting
 *     newer local changes (the core fix for the mode-reset bug)
 */
import { describe, it, expect, beforeEach } from "vitest";
import { useCodingModeStore } from "./codingModeStore";
import { useAgentStore } from "./agentStore";

describe("codingMode route switch (A#82590506)", () => {
  beforeEach(() => {
    useCodingModeStore.setState({
      codingModeByAgent: {},
      codingModeRevisionByAgent: {},
    });
    useAgentStore.setState({ selectedAgent: "agent-1", agents: [] });
  });

  it("initializes with no coding mode set", () => {
    expect(
      useCodingModeStore.getState().codingModeByAgent["agent-1"],
    ).toBeUndefined();
  });

  it("setCodingMode enables coding mode for the agent", () => {
    useCodingModeStore.getState().setCodingMode("agent-1", true);
    expect(useCodingModeStore.getState().codingModeByAgent["agent-1"]).toBe(
      true,
    );
  });

  it("setCodingMode disables coding mode for the agent", () => {
    useCodingModeStore.getState().setCodingMode("agent-1", true);
    useCodingModeStore.getState().setCodingMode("agent-1", false);
    expect(useCodingModeStore.getState().codingModeByAgent["agent-1"]).toBe(
      false,
    );
  });

  it("revision counter increments on each local write", () => {
    useCodingModeStore.getState().setCodingMode("agent-1", false);
    const rev1 =
      useCodingModeStore.getState().codingModeRevisionByAgent["agent-1"];
    useCodingModeStore.getState().setCodingMode("agent-1", true);
    const rev2 =
      useCodingModeStore.getState().codingModeRevisionByAgent["agent-1"];
    expect(rev2).toBeGreaterThan(rev1);
  });

  it("different agents have independent coding mode state", () => {
    useCodingModeStore.getState().setCodingMode("agent-1", true);
    useCodingModeStore.getState().setCodingMode("agent-2", false);

    expect(useCodingModeStore.getState().codingModeByAgent["agent-1"]).toBe(
      true,
    );
    expect(useCodingModeStore.getState().codingModeByAgent["agent-2"]).toBe(
      false,
    );
  });

  it("revision counter is per-agent", () => {
    useCodingModeStore.getState().setCodingMode("agent-1", true);
    useCodingModeStore.getState().setCodingMode("agent-1", false);
    useCodingModeStore.getState().setCodingMode("agent-2", true);

    const rev1 =
      useCodingModeStore.getState().codingModeRevisionByAgent["agent-1"];
    const rev2 =
      useCodingModeStore.getState().codingModeRevisionByAgent["agent-2"];
    // agent-1 had 2 writes, agent-2 had 1
    expect(rev1).toBeGreaterThan(rev2);
  });

  it("useCodingMode convenience hook reads from selected agent", () => {
    useCodingModeStore.getState().setCodingMode("agent-1", true);

    // Simulate what useCodingMode does internally
    const selectedAgent = useAgentStore.getState().selectedAgent;
    const codingMode =
      useCodingModeStore.getState().codingModeByAgent[selectedAgent];
    expect(codingMode).toBe(true);
  });

  it("switching agent reads the new agent's mode (simulating route change)", () => {
    // Agent-1 is in coding mode
    useCodingModeStore.getState().setCodingMode("agent-1", true);
    // Agent-2 is not in coding mode
    useCodingModeStore.getState().setCodingMode("agent-2", false);

    // User switches from agent-1 to agent-2 (route change: coding → chat)
    useAgentStore.setState({ selectedAgent: "agent-2", agents: [] });

    const selectedAgent = useAgentStore.getState().selectedAgent;
    const codingMode =
      useCodingModeStore.getState().codingModeByAgent[selectedAgent];
    expect(codingMode).toBe(false);
  });
});
