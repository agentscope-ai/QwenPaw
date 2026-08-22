import { describe, it, expect, beforeEach } from "vitest";
import { renderHook } from "@testing-library/react";
import { useAdvisorModeStore, useAdvisorMode } from "./advisorModeStore";
import { useAgentStore } from "./agentStore";

const ON = {
  enabled: true,
  plan_enabled: true,
  followup_enabled: true,
  on_demand_enabled: true,
  teacher_model: { provider_id: "dash", model: "qwen3-max" },
  student_model: { provider_id: "dash", model: "qwen3-8b" },
};

beforeEach(() => {
  useAdvisorModeStore.setState({
    advisorModeByAgent: {},
    advisorModeRevisionByAgent: {},
  });
  useAgentStore.setState({ selectedAgent: "test-agent", agents: [] });
});

describe("advisorModeStore", () => {
  it("starts empty", () => {
    expect(useAdvisorModeStore.getState().advisorModeByAgent).toEqual({});
  });

  it("setAdvisorMode stores the snapshot and bumps the revision", () => {
    useAdvisorModeStore.getState().setAdvisorMode("a1", ON);
    const state = useAdvisorModeStore.getState();
    expect(state.advisorModeByAgent["a1"]).toEqual(ON);
    expect(state.advisorModeRevisionByAgent["a1"]).toBe(1);
    useAdvisorModeStore
      .getState()
      .setAdvisorMode("a1", { ...ON, enabled: false });
    expect(
      useAdvisorModeStore.getState().advisorModeRevisionByAgent["a1"],
    ).toBe(2);
  });

  it("useAdvisorMode: unknown agent → disabled, not initialized", () => {
    useAgentStore.setState({ selectedAgent: "unknown", agents: [] });
    const { result } = renderHook(() => useAdvisorMode());
    expect(result.current.advisorMode).toBe(false);
    expect(result.current.initialized).toBe(false);
    expect(result.current.state.student_model).toBeNull();
  });

  it("useAdvisorMode: reflects the selected agent's snapshot", () => {
    useAgentStore.setState({ selectedAgent: "a1", agents: [] });
    useAdvisorModeStore.getState().setAdvisorMode("a1", ON);
    const { result } = renderHook(() => useAdvisorMode());
    expect(result.current.advisorMode).toBe(true);
    expect(result.current.initialized).toBe(true);
    expect(result.current.state.teacher_model?.model).toBe("qwen3-max");
  });

  it("useAdvisorMode.setAdvisorMode writes to the selected agent", () => {
    useAgentStore.setState({ selectedAgent: "a2", agents: [] });
    const { result } = renderHook(() => useAdvisorMode());
    result.current.setAdvisorMode(ON);
    expect(useAdvisorModeStore.getState().advisorModeByAgent["a2"]).toEqual(ON);
  });
});
