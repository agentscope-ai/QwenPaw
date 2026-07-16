import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AgentSummary } from "@/api/types/agents";
import { useAgentStatusPolling } from "./useAgentStatusPolling";

const agent = (startup_status: AgentSummary["startup_status"]) => ({
  id: "agent",
  name: "Agent",
  description: "",
  workspace_dir: "",
  enabled: startup_status !== "disabled",
  startup_status,
});

describe("useAgentStatusPolling", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("refreshes while an agent is starting", async () => {
    vi.useFakeTimers();
    const refresh = vi.fn().mockResolvedValue(undefined);
    renderHook(() => useAgentStatusPolling([agent("starting")], refresh));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500);
    });

    expect(refresh).toHaveBeenCalledOnce();
  });

  it("does not refresh terminal statuses", async () => {
    vi.useFakeTimers();
    const refresh = vi.fn().mockResolvedValue(undefined);
    renderHook(() => useAgentStatusPolling([agent("running")], refresh));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });

    expect(refresh).not.toHaveBeenCalled();
  });
});
