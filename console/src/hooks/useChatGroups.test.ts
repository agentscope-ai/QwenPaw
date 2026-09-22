import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const h = vi.hoisted(() => ({
  selectedAgent: { id: "agent-1", name: "demo" } as unknown,
  listGroups: vi.fn(),
  createGroup: vi.fn(),
  updateGroup: vi.fn(),
  deleteGroup: vi.fn(),
  reorderGroups: vi.fn(),
}));

vi.mock("../stores/agentStore", () => {
  // The hook subscribes with a selector: useAgentStore((s) => s.selectedAgent).
  const useAgentStore = Object.assign(
    (selector: (s: { selectedAgent: unknown }) => unknown) =>
      selector({ selectedAgent: h.selectedAgent }),
    { getState: () => ({ selectedAgent: h.selectedAgent }) },
  );
  return { useAgentStore };
});

vi.mock("../api/modules/chat", () => ({
  chatApi: {
    listGroups: h.listGroups,
    createGroup: h.createGroup,
    updateGroup: h.updateGroup,
    deleteGroup: h.deleteGroup,
    reorderGroups: h.reorderGroups,
  },
}));

import { useChatGroups } from "./useChatGroups";

const GROUPS = [
  { id: "g1", name: "first" },
  { id: "g2", name: "second" },
];

beforeEach(() => {
  vi.clearAllMocks();
  h.listGroups.mockResolvedValue(GROUPS);
  h.createGroup.mockResolvedValue(undefined);
  h.updateGroup.mockResolvedValue(undefined);
  h.deleteGroup.mockResolvedValue(undefined);
  h.reorderGroups.mockResolvedValue(GROUPS);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useChatGroups initial load", () => {
  it("starts in the loading state and then exposes the fetched groups", async () => {
    const { result } = renderHook(() => useChatGroups());
    expect(result.current.loading).toBe(true);
    expect(result.current.groups).toEqual([]);
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.groups).toEqual(GROUPS);
    expect(h.listGroups).toHaveBeenCalledTimes(1);
  });

  it("does not fetch at all when the hook is inactive", async () => {
    const { result } = renderHook(() => useChatGroups(false));
    // loading stays at its initial true because the effect returns early.
    expect(result.current.loading).toBe(true);
    expect(h.listGroups).not.toHaveBeenCalled();
    await waitFor(() => expect(h.listGroups).not.toHaveBeenCalled());
  });

  // Pins the `cancelled` latch in the load effect. Going inactive (rather than
  // unmounting) keeps the component mounted, so a setState that the latch should
  // have suppressed stays observable on result.current. Without the latch the
  // in-flight response would land after the cleanup and populate `groups`.
  it("ignores an in-flight response that settles after the hook went inactive", async () => {
    let resolveList!: (v: typeof GROUPS) => void;
    h.listGroups.mockReturnValue(
      new Promise<typeof GROUPS>((resolve) => {
        resolveList = resolve;
      }),
    );
    const { result, rerender } = renderHook(
      ({ active }: { active: boolean }) => useChatGroups(active),
      { initialProps: { active: true } },
    );
    expect(result.current.loading).toBe(true);
    // Becoming inactive runs the effect cleanup, which flips cancelled for the
    // request that is still pending.
    rerender({ active: false });
    await act(async () => {
      resolveList(GROUPS);
    });
    // The latch suppressed setGroups; the finally block's own latch kept loading.
    expect(result.current.groups).toEqual([]);
    expect(result.current.loading).toBe(true);
  });

  it("keeps loading true but does not crash when the request rejects", async () => {
    h.listGroups.mockRejectedValue(new Error("network down"));
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const { result } = renderHook(() => useChatGroups());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.groups).toEqual([]);
    expect(errorSpy).toHaveBeenCalledWith(
      "Failed to load chat groups:",
      expect.any(Error),
    );
  });
});

describe("useChatGroups refreshGroups", () => {
  it("re-fetches and replaces the group list", async () => {
    const { result } = renderHook(() => useChatGroups());
    await waitFor(() => expect(result.current.loading).toBe(false));
    const NEXT = [{ id: "g3", name: "third" }];
    h.listGroups.mockResolvedValue(NEXT);
    await act(async () => {
      await result.current.refreshGroups();
    });
    expect(result.current.groups).toEqual(NEXT);
    expect(h.listGroups).toHaveBeenCalledTimes(2);
  });
});

describe("useChatGroups mutations", () => {
  it("creates a group then refreshes the list", async () => {
    const { result } = renderHook(() => useChatGroups());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      await result.current.createGroup("new one");
    });
    expect(h.createGroup).toHaveBeenCalledWith("new one");
    // initial load + the refresh triggered by createGroup
    expect(h.listGroups).toHaveBeenCalledTimes(2);
  });

  it("renames a group with only the name in the update payload", async () => {
    const { result } = renderHook(() => useChatGroups());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      await result.current.renameGroup("g1", "renamed");
    });
    expect(h.updateGroup).toHaveBeenCalledWith("g1", { name: "renamed" });
    expect(h.listGroups).toHaveBeenCalledTimes(2);
  });

  it("pins and unpins a group with only the pinned flag", async () => {
    const { result } = renderHook(() => useChatGroups());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      await result.current.pinGroup("g1", true);
    });
    expect(h.updateGroup).toHaveBeenLastCalledWith("g1", { pinned: true });
    await act(async () => {
      await result.current.pinGroup("g2", false);
    });
    expect(h.updateGroup).toHaveBeenLastCalledWith("g2", { pinned: false });
    expect(h.updateGroup).toHaveBeenCalledTimes(2);
  });

  it("deletes a group then refreshes the list", async () => {
    const { result } = renderHook(() => useChatGroups());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      await result.current.deleteGroup("g2");
    });
    expect(h.deleteGroup).toHaveBeenCalledWith("g2");
    expect(h.listGroups).toHaveBeenCalledTimes(2);
  });

  it("propagates a rejection from the mutation instead of swallowing it", async () => {
    h.deleteGroup.mockRejectedValue(new Error("delete failed"));
    const { result } = renderHook(() => useChatGroups());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await expect(
      act(async () => {
        await result.current.deleteGroup("g2");
      }),
    ).rejects.toThrow("delete failed");
    // refreshGroups never runs because the await above threw first
    expect(h.listGroups).toHaveBeenCalledTimes(1);
  });
});

describe("useChatGroups reorderGroups", () => {
  it("applies the server's ordering without an extra list call", async () => {
    const { result } = renderHook(() => useChatGroups());
    await waitFor(() => expect(result.current.loading).toBe(false));
    const REORDERED = [GROUPS[1], GROUPS[0]];
    h.reorderGroups.mockResolvedValue(REORDERED);
    await act(async () => {
      await result.current.reorderGroups(["g2", "g1"]);
    });
    expect(h.reorderGroups).toHaveBeenCalledWith(["g2", "g1"]);
    expect(result.current.groups).toEqual(REORDERED);
    // Unlike the other mutations this one sets state directly.
    expect(h.listGroups).toHaveBeenCalledTimes(1);
  });

  it("accepts an empty ordering from the server", async () => {
    const { result } = renderHook(() => useChatGroups());
    await waitFor(() => expect(result.current.loading).toBe(false));
    h.reorderGroups.mockResolvedValue([]);
    await act(async () => {
      await result.current.reorderGroups([]);
    });
    expect(result.current.groups).toEqual([]);
  });
});

describe("useChatGroups state surface", () => {
  it("exposes every documented member of the state object", async () => {
    const { result } = renderHook(() => useChatGroups());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(Object.keys(result.current).sort()).toEqual([
      "createGroup",
      "deleteGroup",
      "groups",
      "loading",
      "pinGroup",
      "refreshGroups",
      "renameGroup",
      "reorderGroups",
    ]);
    for (const key of [
      "refreshGroups",
      "createGroup",
      "renameGroup",
      "pinGroup",
      "deleteGroup",
      "reorderGroups",
    ] as const) {
      expect(typeof result.current[key]).toBe("function");
    }
  });

  it("defaults the active flag to true", async () => {
    const { result } = renderHook(() => useChatGroups());
    await waitFor(() => expect(h.listGroups).toHaveBeenCalledTimes(1));
    expect(result.current.loading).toBe(false);
  });
});
