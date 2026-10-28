import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { agentsApi } from "../../api/modules/agents";
import type { AgentProfileConfig } from "../../api/types/agents";
import { useMemoryTagSupport } from "./useMemoryTagSupport";

const config = (backend: string): AgentProfileConfig => ({
  id: "agent",
  name: "Agent",
  running: { memory_manager_backend: backend },
});

describe("memory tag support", () => {
  afterEach(() => vi.restoreAllMocks());

  it("ignores a late capability response after changing agents", async () => {
    let resolveOld!: (value: AgentProfileConfig) => void;
    const getAgent = vi
      .spyOn(agentsApi, "getAgent")
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveOld = resolve;
          }),
      )
      .mockResolvedValue(config("powercontext"));
    const { result, rerender } = renderHook(
      ({ agentId }) => useMemoryTagSupport(agentId),
      { initialProps: { agentId: "first" } },
    );
    expect(result.current).toBe(false);
    rerender({ agentId: "second" });
    await act(async () => resolveOld(config("remelight")));
    expect(getAgent.mock.calls[0][1]?.aborted).toBe(true);
    expect(result.current).toBe(false);
  });

  it("refreshes backend support on focus and recovers after a failed config read", async () => {
    vi.spyOn(agentsApi, "getAgent")
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(config("remelight"))
      .mockResolvedValueOnce(config("adbpg"));
    const { result } = renderHook(() => useMemoryTagSupport("agent"));
    await act(async () => {});
    expect(result.current).toBe(false);
    act(() => window.dispatchEvent(new Event("focus")));
    await waitFor(() => expect(result.current).toBe(true));
    act(() => window.dispatchEvent(new Event("focus")));
    await waitFor(() => expect(result.current).toBe(false));
  });
});
