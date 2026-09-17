import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { agentsApi } from "@/api";
import { useAgentStore } from "@/stores/agentStore";
import { useReMeRuntimeStatus } from "./useReMeRuntimeStatus";

const runtime = {
  worker: {
    status: "idle" as const,
    queue_pending: 0,
    tasks_running: 0,
  },
  auto_memory: {
    enabled: true,
    interval: 5,
    active_sessions: 0,
    sessions_with_pending: 0,
    pending_turns: 0,
  },
  recent: {
    last_completed_at: null,
    last_failed_at: null,
    last_error: null,
  },
  reindexing: false,
};

afterEach(() => {
  vi.restoreAllMocks();
  useAgentStore.setState({ selectedAgent: "default" });
});

describe("useReMeRuntimeStatus", () => {
  it("polls the explicit governance target with its request context", async () => {
    useAgentStore.setState({ selectedAgent: "sidebar-agent" });
    const getRuntimeStatus = vi
      .spyOn(agentsApi, "getMemoryRuntimeStatus")
      .mockResolvedValue(runtime);
    const requestContext = {
      agentId: "governed-agent",
      governance: true,
    } as const;

    const { unmount } = renderHook(() =>
      useReMeRuntimeStatus(true, requestContext),
    );

    await waitFor(() =>
      expect(getRuntimeStatus).toHaveBeenCalledWith(
        "governed-agent",
        expect.any(AbortSignal),
        requestContext,
      ),
    );
    unmount();
  });
});
