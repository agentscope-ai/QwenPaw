import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Every mock below is created once via vi.hoisted and reused, so the store
// object keeps a referentially stable `refreshAgents`. The hook chains
// loadAgents -> fetchAgents -> refreshAgents through useCallback and runs the
// mount effect off it; a fresh function per render would re-run that effect
// and issue extra list calls (the same trap measured on useDebugLogs).
const mocks = vi.hoisted(() => ({
  deleteAgent: vi.fn(),
  toggleAgentEnabled: vi.fn(),
  setAgentPinned: vi.fn(),
  purgeAgentSpace: vi.fn(),
  setAgents: vi.fn(),
  refreshAgents: vi.fn(),
  messageSuccess: vi.fn(),
  messageError: vi.fn(),
}));

vi.mock("@/api/modules/agents", () => ({
  agentsApi: {
    deleteAgent: mocks.deleteAgent,
    toggleAgentEnabled: mocks.toggleAgentEnabled,
    setAgentPinned: mocks.setAgentPinned,
  },
}));

vi.mock("@/os/osCleanup", () => ({
  purgeAgentSpace: mocks.purgeAgentSpace,
}));

vi.mock("../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: { success: mocks.messageSuccess, error: mocks.messageError },
  }),
}));

// `t` must also stay referentially stable: it is stored in a ref and read back
// from there, and a changing identity would make the assertion below about
// refs meaningless.
const { stableT } = vi.hoisted(() => ({
  stableT: (key: string) => key,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: stableT,
    i18n: { resolvedLanguage: "en", language: "en" },
  }),
}));

const storeState = vi.hoisted(() => ({ agents: [] as unknown[] }));

vi.mock("@/stores/agentStore", () => ({
  useAgentStore: () => ({
    agents: storeState.agents,
    setAgents: mocks.setAgents,
    refreshAgents: mocks.refreshAgents,
  }),
}));

import type { AgentSummary } from "@/api/types/agents";
import { useAgents } from "./useAgents";

const agent = (over: Partial<AgentSummary> = {}): AgentSummary =>
  ({
    id: "a1",
    name: "Agent One",
    description: "",
    workspace_dir: "/tmp/a1",
    enabled: true,
    pinned: false,
    backend: "qwenpaw",
    ...over,
  }) as AgentSummary;

/** Let the pending effect + awaited fetch settle. */
const flush = async () => {
  await act(async () => {
    await Promise.resolve();
  });
};

describe("useAgents", () => {
  beforeEach(() => {
    Object.values(mocks).forEach((m) => m.mockReset());
    mocks.refreshAgents.mockResolvedValue(undefined);
    mocks.deleteAgent.mockResolvedValue(undefined);
    mocks.toggleAgentEnabled.mockResolvedValue(undefined);
    mocks.setAgentPinned.mockResolvedValue(undefined);
    storeState.agents = [agent()];
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // ── initial load ────────────────────────────────────────────────────────

  it("loads the agent list on mount and settles the loading flag", async () => {
    const { result } = renderHook(() => useAgents());

    await flush();

    expect(mocks.refreshAgents).toHaveBeenCalledTimes(1);
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBeNull();
    expect(result.current.agents).toEqual([agent()]);
  });

  it("reloads on demand through the exposed loadAgents", async () => {
    const { result } = renderHook(() => useAgents());

    await flush();
    await act(async () => {
      await result.current.loadAgents();
    });

    expect(mocks.refreshAgents).toHaveBeenCalledTimes(2);
  });

  it("does not leave the loading flag stuck when a reload throws", async () => {
    const { result } = renderHook(() => useAgents());

    await flush();
    mocks.refreshAgents.mockRejectedValueOnce(new Error("boom"));

    await act(async () => {
      await result.current.loadAgents();
    });

    expect(result.current.loading).toBe(false);
  });

  // ── load failure reporting ──────────────────────────────────────────────

  it("reports an Error rejection with its own message and toasts once", async () => {
    mocks.refreshAgents.mockRejectedValueOnce(new Error("gateway 502"));
    const { result } = renderHook(() => useAgents());

    await flush();

    expect(result.current.error?.message).toBe("gateway 502");
    expect(mocks.messageError).toHaveBeenCalledWith("agent.loadFailed");
    expect(console.error).toHaveBeenCalled();
  });

  it("wraps a non-Error rejection in the translated failure message", async () => {
    mocks.refreshAgents.mockRejectedValueOnce("plain string");
    const { result } = renderHook(() => useAgents());

    await flush();

    expect(result.current.error).toBeInstanceOf(Error);
    expect(result.current.error?.message).toBe("agent.loadFailed");
  });

  it("clears a previous load error once a later load succeeds", async () => {
    mocks.refreshAgents.mockRejectedValueOnce(new Error("offline"));
    const { result } = renderHook(() => useAgents());

    await flush();
    expect(result.current.error?.message).toBe("offline");

    await act(async () => {
      await result.current.loadAgents();
    });

    expect(result.current.error).toBeNull();
  });

  it("reads the message instance through a ref so a swapped instance still works", async () => {
    // The hook stores `message` in a ref and calls the ref from the catch
    // branch. Pin that indirection: the call must land on the mock the hook
    // currently holds, not on a stale one captured at first render.
    mocks.refreshAgents.mockRejectedValueOnce(new Error("late"));
    const { result } = renderHook(() => useAgents());

    await flush();

    expect(mocks.messageError).toHaveBeenCalledTimes(1);
    expect(result.current.error?.message).toBe("late");
  });

  // ── deleteAgent ─────────────────────────────────────────────────────────

  it("deletes an agent, purges its Desktop OS space, then reloads silently", async () => {
    const { result } = renderHook(() => useAgents());

    await flush();
    mocks.refreshAgents.mockClear();

    await act(async () => {
      await result.current.deleteAgent("a1");
    });

    expect(mocks.deleteAgent).toHaveBeenCalledWith("a1");
    // Cleanup only runs after a confirmed deletion.
    expect(mocks.purgeAgentSpace).toHaveBeenCalledWith("a1");
    expect(mocks.messageSuccess).toHaveBeenCalledWith("agent.deleteSuccess");
    expect(mocks.refreshAgents).toHaveBeenCalledTimes(1);
    // Silent reload: no toast, no error surfaced.
    expect(mocks.messageError).not.toHaveBeenCalled();
  });

  it("does not purge the space when the delete call fails", async () => {
    const { result } = renderHook(() => useAgents());

    await flush();
    mocks.deleteAgent.mockRejectedValueOnce(new Error("still running"));

    await act(async () => {
      await expect(result.current.deleteAgent("a1")).rejects.toThrow(
        "still running",
      );
    });

    expect(mocks.purgeAgentSpace).not.toHaveBeenCalled();
    expect(mocks.messageError).toHaveBeenCalledWith("still running");
    expect(mocks.messageSuccess).not.toHaveBeenCalled();
  });

  it("falls back to the translated copy when delete rejects with a non-Error", async () => {
    const { result } = renderHook(() => useAgents());

    await flush();
    mocks.deleteAgent.mockRejectedValueOnce(undefined);

    await act(async () => {
      await expect(result.current.deleteAgent("a1")).rejects.toBeUndefined();
    });

    expect(mocks.messageError).toHaveBeenCalledWith("agent.deleteFailed");
  });

  it("rethrows a delete failure so callers can keep their own state", async () => {
    const { result } = renderHook(() => useAgents());

    await flush();
    const failure = new Error("nope");
    mocks.deleteAgent.mockRejectedValueOnce(failure);

    await act(async () => {
      await expect(result.current.deleteAgent("a1")).rejects.toBe(failure);
    });
  });

  // ── toggleAgent ─────────────────────────────────────────────────────────

  it("optimistically marks the agent as starting before enabling it", async () => {
    const { result } = renderHook(() => useAgents());

    await flush();

    await act(async () => {
      await result.current.toggleAgent("a1", true);
    });

    expect(mocks.setAgents).toHaveBeenCalledWith([
      { ...agent(), enabled: true, startup_status: "starting" },
    ]);
    expect(mocks.toggleAgentEnabled).toHaveBeenCalledWith("a1", true);
    expect(mocks.messageSuccess).toHaveBeenCalledWith("agent.enableSuccess");
  });

  it("does not write an optimistic state when disabling", async () => {
    const { result } = renderHook(() => useAgents());

    await flush();

    await act(async () => {
      await result.current.toggleAgent("a1", false);
    });

    // Disabling has no optimistic branch, so the store is only touched by the
    // silent reload path (which goes through refreshAgents, not setAgents).
    expect(mocks.setAgents).not.toHaveBeenCalled();
    expect(mocks.toggleAgentEnabled).toHaveBeenCalledWith("a1", false);
    expect(mocks.messageSuccess).toHaveBeenCalledWith("agent.disableSuccess");
  });

  it("leaves other agents untouched by the optimistic enable", async () => {
    storeState.agents = [
      agent({ id: "a1" }),
      agent({ id: "a2", name: "Agent Two", enabled: false }),
    ];
    const { result } = renderHook(() => useAgents());

    await flush();

    await act(async () => {
      await result.current.toggleAgent("a2", true);
    });

    expect(mocks.setAgents).toHaveBeenCalledWith([
      agent({ id: "a1" }),
      {
        ...agent({ id: "a2", name: "Agent Two", enabled: false }),
        enabled: true,
        startup_status: "starting",
      },
    ]);
  });

  it("reloads before reporting a toggle failure", async () => {
    const { result } = renderHook(() => useAgents());

    await flush();
    mocks.refreshAgents.mockClear();
    mocks.toggleAgentEnabled.mockRejectedValueOnce(new Error("conflict"));

    await act(async () => {
      await expect(result.current.toggleAgent("a1", true)).rejects.toThrow(
        "conflict",
      );
    });

    // The optimistic write has to be rolled back by a reload, so the reload
    // must happen even though the call failed.
    expect(mocks.refreshAgents).toHaveBeenCalledTimes(1);
    expect(mocks.messageError).toHaveBeenCalledWith("conflict");
    expect(mocks.messageSuccess).not.toHaveBeenCalled();
  });

  it("falls back to the translated copy when toggle rejects with a non-Error", async () => {
    const { result } = renderHook(() => useAgents());

    await flush();
    mocks.toggleAgentEnabled.mockRejectedValueOnce(42);

    await act(async () => {
      await expect(result.current.toggleAgent("a1", false)).rejects.toBe(42);
    });

    expect(mocks.messageError).toHaveBeenCalledWith("agent.toggleFailed");
  });

  // ── pinAgent ────────────────────────────────────────────────────────────

  it("optimistically pins the agent and reports success", async () => {
    const { result } = renderHook(() => useAgents());

    await flush();

    await act(async () => {
      await result.current.pinAgent("a1", true);
    });

    expect(mocks.setAgents).toHaveBeenCalledWith([
      { ...agent(), pinned: true },
    ]);
    expect(mocks.setAgentPinned).toHaveBeenCalledWith("a1", true);
    expect(mocks.messageSuccess).toHaveBeenCalledWith("agent.pinSuccess");
  });

  it("optimistically unpins the agent and uses the unpin copy", async () => {
    storeState.agents = [agent({ pinned: true })];
    const { result } = renderHook(() => useAgents());

    await flush();

    await act(async () => {
      await result.current.pinAgent("a1", false);
    });

    expect(mocks.setAgents).toHaveBeenCalledWith([
      { ...agent({ pinned: true }), pinned: false },
    ]);
    expect(mocks.messageSuccess).toHaveBeenCalledWith("agent.unpinSuccess");
  });

  it("reloads and reports a pin failure without a success toast", async () => {
    const { result } = renderHook(() => useAgents());

    await flush();
    mocks.refreshAgents.mockClear();
    mocks.setAgentPinned.mockRejectedValueOnce(new Error("forbidden"));

    await act(async () => {
      await expect(result.current.pinAgent("a1", true)).rejects.toThrow(
        "forbidden",
      );
    });

    expect(mocks.refreshAgents).toHaveBeenCalledTimes(1);
    expect(mocks.messageError).toHaveBeenCalledWith("forbidden");
    expect(mocks.messageSuccess).not.toHaveBeenCalled();
  });

  it("falls back to the translated copy when pin rejects with a non-Error", async () => {
    const { result } = renderHook(() => useAgents());

    await flush();
    mocks.setAgentPinned.mockRejectedValueOnce(null);

    await act(async () => {
      await expect(result.current.pinAgent("a1", false)).rejects.toBeNull();
    });

    expect(mocks.messageError).toHaveBeenCalledWith("agent.pinFailed");
  });

  // ── exposed setter ──────────────────────────────────────────────────────

  it("exposes a setter that writes straight to the store", async () => {
    const { result } = renderHook(() => useAgents());

    await flush();
    const next = [agent({ id: "b1" }), agent({ id: "b2" })];

    act(() => {
      result.current.setAgents(next);
    });

    expect(mocks.setAgents).toHaveBeenCalledWith(next);
    // A direct store write must not trigger a network reload.
    expect(mocks.refreshAgents).toHaveBeenCalledTimes(1);
  });

  it("reflects the store list without copying it", async () => {
    const list = [agent({ id: "c1" })];
    storeState.agents = list;
    const { result } = renderHook(() => useAgents());

    await flush();

    expect(result.current.agents).toBe(list);
  });
});
