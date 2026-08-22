import { vi, describe, it, expect, beforeEach } from "vitest";

vi.mock("../api/modules/advisorMode", () => ({
  advisorModeApi: {
    get: vi.fn(),
  },
}));

import { renderHook, waitFor } from "@testing-library/react";
import { useAgentStore } from "./agentStore";
import { useAdvisorModeStore } from "./advisorModeStore";
import { useSyncAdvisorMode } from "./useSyncAdvisorMode";
import { advisorModeApi } from "../api/modules/advisorMode";

const ON = {
  enabled: true,
  plan_enabled: true,
  followup_enabled: false,
  on_demand_enabled: true,
  agent_id: "agent-1",
  teacher_model: { provider_id: "dash", model: "qwen3-max" },
  student_model: null,
};

beforeEach(() => {
  useAgentStore.setState({ selectedAgent: "agent-1", agents: [] });
  useAdvisorModeStore.setState({
    advisorModeByAgent: {},
    advisorModeRevisionByAgent: {},
  });
  vi.clearAllMocks();
});

describe("useSyncAdvisorMode", () => {
  it("fetches once on mount for the selected agent", async () => {
    vi.mocked(advisorModeApi.get).mockResolvedValue(ON);
    renderHook(() => useSyncAdvisorMode());
    await waitFor(() => {
      expect(vi.mocked(advisorModeApi.get)).toHaveBeenCalledTimes(1);
    });
  });

  it("stores the backend state for the selected agent", async () => {
    vi.mocked(advisorModeApi.get).mockResolvedValue(ON);
    renderHook(() => useSyncAdvisorMode());
    await waitFor(() => {
      expect(
        useAdvisorModeStore.getState().advisorModeByAgent["agent-1"],
      ).toEqual(ON);
    });
  });

  it("falls back to a disabled snapshot when the fetch fails", async () => {
    vi.mocked(advisorModeApi.get).mockRejectedValue(new Error("boom"));
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    renderHook(() => useSyncAdvisorMode());
    await waitFor(() => {
      expect(
        useAdvisorModeStore.getState().advisorModeByAgent["agent-1"]?.enabled,
      ).toBe(false);
    });
    warn.mockRestore();
  });

  it("does not overwrite a local write that raced the fetch", async () => {
    let resolve: (value: typeof ON) => void = () => {};
    vi.mocked(advisorModeApi.get).mockReturnValue(
      new Promise((r) => {
        resolve = r;
      }),
    );
    renderHook(() => useSyncAdvisorMode());
    // A local toggle lands while the GET is still in flight.
    useAdvisorModeStore
      .getState()
      .setAdvisorMode("agent-1", { ...ON, enabled: false });
    resolve(ON);
    await new Promise((r) => setTimeout(r, 0));
    expect(
      useAdvisorModeStore.getState().advisorModeByAgent["agent-1"].enabled,
    ).toBe(false);
  });

  it("does nothing without a selected agent", async () => {
    useAgentStore.setState({ selectedAgent: "", agents: [] });
    renderHook(() => useSyncAdvisorMode());
    await new Promise((r) => setTimeout(r, 0));
    expect(vi.mocked(advisorModeApi.get)).not.toHaveBeenCalled();
  });
});
