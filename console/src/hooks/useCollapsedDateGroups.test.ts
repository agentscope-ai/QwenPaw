/**
 * What this file pins for `useCollapsedDateGroups`:
 *
 * The hook is consumed by `src/layouts/SidebarSessionList.tsx:317`, so its
 * default path (empty storage) is already exercised indirectly by that
 * suite. What no indirect render can reach are the storage-rehydration
 * branches and the "expand a group that really is collapsed" branch, and
 * those are exactly the paths where a silent regression is invisible to a
 * user until the next reload.
 *
 * Persisted key: `qwenpaw_collapsed_date_groups_v1` (STORAGE_KEY at :3).
 * Harness follows the sibling precedent
 * `src/hooks/useCollapsedChatGroups.test.ts:1-6` verbatim in shape
 * (renderHook + act + localStorage.clear), no mocks needed.
 */
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { useCollapsedDateGroups } from "./useCollapsedDateGroups";

const STORAGE_KEY = "qwenpaw_collapsed_date_groups_v1";

/** Read the persisted payload back and hand over the raw string too. */
function readStored(): { raw: string | null; parsed: unknown } {
  const raw = localStorage.getItem(STORAGE_KEY);
  return { raw, parsed: raw === null ? null : JSON.parse(raw) };
}

describe("useCollapsedDateGroups", () => {
  beforeEach(() => localStorage.clear());

  it("starts with nothing collapsed when storage is empty", () => {
    const { result } = renderHook(() => useCollapsedDateGroups());

    expect(result.current.collapsedDateGroups instanceof Set).toBe(true);
    expect(result.current.collapsedDateGroups.size).toBe(0);
    // Reading state must not write anything back.
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it("restores persisted group keys on mount", () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(["today", "older"]));

    const { result } = renderHook(() => useCollapsedDateGroups());

    expect([...result.current.collapsedDateGroups].sort()).toEqual([
      "older",
      "today",
    ]);
  });

  it("falls back to an empty set when the payload is valid JSON but not an array", () => {
    // Array.isArray(parsed) is the guard at :10; a plain object would
    // otherwise be spread into `new Set(...)` as garbage.
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ today: true }));

    const { result } = renderHook(() => useCollapsedDateGroups());

    expect(result.current.collapsedDateGroups.size).toBe(0);
  });

  it("falls back to an empty set when the payload is valid JSON but a scalar", () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(42));

    const { result } = renderHook(() => useCollapsedDateGroups());

    expect(result.current.collapsedDateGroups.size).toBe(0);
  });

  it("survives an unparseable payload instead of throwing on mount", () => {
    localStorage.setItem(STORAGE_KEY, "not-json-at-all");

    const { result } = renderHook(() => useCollapsedDateGroups());

    expect(result.current.collapsedDateGroups.size).toBe(0);
  });

  it("ignores a storage backend that throws on read", () => {
    const original = localStorage.getItem.bind(localStorage);
    localStorage.getItem = () => {
      throw new Error("storage disabled");
    };
    try {
      const { result } = renderHook(() => useCollapsedDateGroups());
      expect(result.current.collapsedDateGroups.size).toBe(0);
    } finally {
      localStorage.getItem = original;
    }
  });

  it("adds a key on toggle and persists it as an array", () => {
    const { result } = renderHook(() => useCollapsedDateGroups());

    act(() => result.current.toggleDateGroup("week"));

    expect(result.current.collapsedDateGroups.has("week")).toBe(true);
    expect(readStored().parsed).toEqual(["week"]);
  });

  it("removes a key when the same group is toggled twice", () => {
    const { result } = renderHook(() => useCollapsedDateGroups());

    act(() => result.current.toggleDateGroup("month"));
    expect(result.current.collapsedDateGroups.has("month")).toBe(true);

    act(() => result.current.toggleDateGroup("month"));
    expect(result.current.collapsedDateGroups.has("month")).toBe(false);
    expect(readStored().parsed).toEqual([]);
  });

  it("returns a new Set instance so consumers can detect the change", () => {
    const { result } = renderHook(() => useCollapsedDateGroups());
    const before = result.current.collapsedDateGroups;

    act(() => result.current.toggleDateGroup("today"));

    expect(result.current.collapsedDateGroups).not.toBe(before);
    // The old snapshot must not have been mutated in place.
    expect(before.has("today")).toBe(false);
  });

  it("expands a group that is currently collapsed and persists the result", () => {
    // This is the branch at :50-54: expandDateGroup on a key that IS
    // present, i.e. the only path that reaches the delete + save body.
    localStorage.setItem(STORAGE_KEY, JSON.stringify(["pinned", "older"]));
    const { result } = renderHook(() => useCollapsedDateGroups());

    act(() => result.current.expandDateGroup("pinned"));

    expect(result.current.collapsedDateGroups.has("pinned")).toBe(false);
    expect(result.current.collapsedDateGroups.has("older")).toBe(true);
    expect(readStored().parsed).toEqual(["older"]);
  });

  it("leaves state untouched when expanding a group that is not collapsed", () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(["today"]));
    const { result } = renderHook(() => useCollapsedDateGroups());
    const before = result.current.collapsedDateGroups;

    act(() => result.current.expandDateGroup("week"));

    // Early return at :50 must hand back the very same instance.
    expect(result.current.collapsedDateGroups).toBe(before);
    expect(readStored().parsed).toEqual(["today"]);
  });

  it("keeps state across a remount", () => {
    const first = renderHook(() => useCollapsedDateGroups());
    act(() => first.result.current.toggleDateGroup("older"));
    first.unmount();

    const second = renderHook(() => useCollapsedDateGroups());
    expect(second.result.current.collapsedDateGroups.has("older")).toBe(true);
  });

  it("exposes exactly three members on its return value", () => {
    const { result } = renderHook(() => useCollapsedDateGroups());

    expect(Object.keys(result.current).sort()).toEqual([
      "collapsedDateGroups",
      "expandDateGroup",
      "toggleDateGroup",
    ]);
    expect(typeof result.current.toggleDateGroup).toBe("function");
    expect(typeof result.current.expandDateGroup).toBe("function");
  });

  it("hands out stable callback identities across renders", () => {
    const { result, rerender } = renderHook(() => useCollapsedDateGroups());
    const toggleBefore = result.current.toggleDateGroup;
    const expandBefore = result.current.expandDateGroup;

    rerender();

    expect(result.current.toggleDateGroup).toBe(toggleBefore);
    expect(result.current.expandDateGroup).toBe(expandBefore);
  });
});
