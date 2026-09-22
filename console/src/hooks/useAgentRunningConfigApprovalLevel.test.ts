import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const h = vi.hoisted(() => ({
  selectedAgent: { id: "a1" } as unknown,
  getAgentRunningConfig: vi.fn(),
}));

vi.mock("../stores/agentStore", () => {
  const useAgentStore = Object.assign(
    () => ({ selectedAgent: h.selectedAgent }),
    { getState: () => ({ selectedAgent: h.selectedAgent }) },
  );
  return { useAgentStore };
});

vi.mock("../api/modules/agent", () => ({
  agentApi: { getAgentRunningConfig: h.getAgentRunningConfig },
}));

// utils/approval is deliberately NOT mocked so normalizeLevel runs for real.

import { useAgentRunningConfigApprovalLevel } from "./useAgentRunningConfigApprovalLevel";

beforeEach(() => {
  vi.clearAllMocks();
  h.selectedAgent = { id: "a1" };
});

describe("useAgentRunningConfigApprovalLevel", () => {
  it("starts at AUTO before the config resolves", () => {
    h.getAgentRunningConfig.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useAgentRunningConfigApprovalLevel());
    expect(result.current).toBe("AUTO");
  });

  it("normalises a valid level from the running config", async () => {
    h.getAgentRunningConfig.mockResolvedValue({ approval_level: "strict" });
    const { result } = renderHook(() => useAgentRunningConfigApprovalLevel());
    await waitFor(() => expect(result.current).toBe("STRICT"));
  });

  it("upper-cases a mixed-case level through the real normalizeLevel", async () => {
    h.getAgentRunningConfig.mockResolvedValue({ approval_level: "sMaRt" });
    const { result } = renderHook(() => useAgentRunningConfigApprovalLevel());
    await waitFor(() => expect(result.current).toBe("SMART"));
  });

  it("falls back to AUTO for an unknown level", async () => {
    h.getAgentRunningConfig.mockResolvedValue({ approval_level: "WHATEVER" });
    const { result } = renderHook(() => useAgentRunningConfigApprovalLevel());
    await waitFor(() => expect(result.current).toBe("AUTO"));
  });

  it("falls back to AUTO when the level is absent", async () => {
    h.getAgentRunningConfig.mockResolvedValue({});
    const { result } = renderHook(() => useAgentRunningConfigApprovalLevel());
    await waitFor(() => expect(result.current).toBe("AUTO"));
  });

  it("falls back to AUTO when the request rejects", async () => {
    h.getAgentRunningConfig.mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() => useAgentRunningConfigApprovalLevel());
    // initial AUTO, stays AUTO after the rejection is swallowed
    await waitFor(() => expect(result.current).toBe("AUTO"));
    expect(h.getAgentRunningConfig).toHaveBeenCalled();
  });

  it("passes OFF through instead of coercing it to AUTO", async () => {
    h.getAgentRunningConfig.mockResolvedValue({ approval_level: "off" });
    const { result } = renderHook(() => useAgentRunningConfigApprovalLevel());
    await waitFor(() => expect(result.current).toBe("OFF"));
  });
});
