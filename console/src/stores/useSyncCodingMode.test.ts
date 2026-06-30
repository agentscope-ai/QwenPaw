import { vi, describe, it, expect, beforeEach } from "vitest";

vi.mock("../api/modules/codingMode", () => ({
  codingModeApi: {
    get: vi.fn(),
  },
}));

import { renderHook, act, waitFor } from "@testing-library/react";
import { useAgentStore } from "./agentStore";
import { useCodingModeStore } from "./codingModeStore";
import { useSyncCodingMode } from "./useSyncCodingMode";
import { codingModeApi } from "../api/modules/codingMode";

beforeEach(() => {
  useAgentStore.setState({ selectedAgent: "agent-1", agents: [] });
  useCodingModeStore.setState({ codingModeByAgent: {}, projectDirByAgent: {} });
  vi.clearAllMocks();
});

describe("useSyncCodingMode", () => {
  // ---------------------------------------------------------------------------
  // Test 1: calls codingModeApi.get() once on mount with a selected agent
  // ---------------------------------------------------------------------------
  it("calls codingModeApi.get() once on mount when selectedAgent is set", async () => {
    vi.mocked(codingModeApi.get).mockResolvedValue({
      enabled: false,
      project_dir: null,
      agent_id: "agent-1",
    });

    renderHook(() => useSyncCodingMode());

    await waitFor(() => {
      expect(vi.mocked(codingModeApi.get)).toHaveBeenCalledTimes(1);
    });
  });

  // ---------------------------------------------------------------------------
  // Test 2: on success, sets codingModeByAgent[agent] to enabled value
  // ---------------------------------------------------------------------------
  it("sets codingModeByAgent[selectedAgent] to enabled value on success", async () => {
    vi.mocked(codingModeApi.get).mockResolvedValue({
      enabled: true,
      project_dir: "/my/project",
      agent_id: "agent-1",
    });

    renderHook(() => useSyncCodingMode());

    await waitFor(() => {
      expect(useCodingModeStore.getState().codingModeByAgent["agent-1"]).toBe(
        true,
      );
    });
  });

  // ---------------------------------------------------------------------------
  // Test 3: on success, sets projectDirByAgent[agent] to project_dir value
  // ---------------------------------------------------------------------------
  it("sets projectDirByAgent[selectedAgent] to project_dir on success", async () => {
    vi.mocked(codingModeApi.get).mockResolvedValue({
      enabled: true,
      project_dir: "/my/project",
      agent_id: "agent-1",
    });

    renderHook(() => useSyncCodingMode());

    await waitFor(() => {
      expect(useCodingModeStore.getState().projectDirByAgent["agent-1"]).toBe(
        "/my/project",
      );
    });
  });

  // ---------------------------------------------------------------------------
  // Test 4: on API failure, defaults codingMode to false and projectDir to null
  // ---------------------------------------------------------------------------
  it("defaults codingModeByAgent to false and projectDirByAgent to null on API failure", async () => {
    vi.mocked(codingModeApi.get).mockRejectedValue(new Error("network error"));

    renderHook(() => useSyncCodingMode());

    await waitFor(() => {
      expect(useCodingModeStore.getState().codingModeByAgent["agent-1"]).toBe(
        false,
      );
      expect(
        useCodingModeStore.getState().projectDirByAgent["agent-1"],
      ).toBeNull();
    });
  });

  // ---------------------------------------------------------------------------
  // Test 5: when selectedAgent changes, a new fetch fires for the new agent
  // ---------------------------------------------------------------------------
  it("fires a new fetch when selectedAgent changes", async () => {
    vi.mocked(codingModeApi.get)
      .mockResolvedValueOnce({
        enabled: false,
        project_dir: null,
        agent_id: "agent-1",
      })
      .mockResolvedValueOnce({
        enabled: true,
        project_dir: "/agent2/project",
        agent_id: "agent-2",
      });

    const { rerender } = renderHook(() => useSyncCodingMode());

    // Wait for the first fetch to complete
    await waitFor(() => {
      expect(vi.mocked(codingModeApi.get)).toHaveBeenCalledTimes(1);
    });

    // Change the selected agent — triggers cleanup + new effect
    act(() => {
      useAgentStore.setState({ selectedAgent: "agent-2", agents: [] });
    });

    rerender();

    // A second fetch should fire for agent-2
    await waitFor(() => {
      expect(vi.mocked(codingModeApi.get)).toHaveBeenCalledTimes(2);
    });

    // Final state should reflect agent-2's data
    await waitFor(() => {
      expect(useCodingModeStore.getState().codingModeByAgent["agent-2"]).toBe(
        true,
      );
      expect(useCodingModeStore.getState().projectDirByAgent["agent-2"]).toBe(
        "/agent2/project",
      );
    });
  });
});
