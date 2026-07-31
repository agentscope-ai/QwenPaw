/**
 * Collapsed session-group state shared by SidebarSessionList and
 * ChatSessionDrawer.
 *
 * Previously each list kept the collapsed set in component state with
 * "month" and "older" collapsed by default. Leaving the page remounted
 * the list and silently re-collapsed those groups, so a conversation
 * older than 7 days seemed to vanish from the list (no amount of
 * scrolling reveals a row inside a collapsed group). The hook fixes
 * both halves: the set persists across remounts, and the group holding
 * the active session is expanded automatically.
 */
import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useCollapsedSessionGroups } from "./useCollapsedSessionGroups";

const STORAGE_KEY = "qwenpaw_collapsed_session_groups";

function daysAgoIso(days: number): string {
  return new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString();
}

describe("useCollapsedSessionGroups", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('collapses "month" and "older" by default', () => {
    const { result } = renderHook(() => useCollapsedSessionGroups());
    expect(result.current.collapsedGroups.has("month")).toBe(true);
    expect(result.current.collapsedGroups.has("older")).toBe(true);
    expect(result.current.collapsedGroups.has("today")).toBe(false);
  });

  it("persists toggles across remounts", () => {
    const first = renderHook(() => useCollapsedSessionGroups());
    act(() => first.result.current.toggleGroup("older"));
    expect(first.result.current.collapsedGroups.has("older")).toBe(false);
    first.unmount();

    // Remount (e.g. navigating away from the page and back).
    const second = renderHook(() => useCollapsedSessionGroups());
    expect(second.result.current.collapsedGroups.has("older")).toBe(false);
    expect(second.result.current.collapsedGroups.has("month")).toBe(true);
  });

  it("toggle collapses an expanded group again and persists it", () => {
    const { result } = renderHook(() => useCollapsedSessionGroups());
    act(() => result.current.toggleGroup("today"));
    expect(result.current.collapsedGroups.has("today")).toBe(true);
    expect(localStorage.getItem(STORAGE_KEY)).toContain("today");
  });

  it("expands the group containing the active session", () => {
    const { result } = renderHook(() => useCollapsedSessionGroups());
    act(() =>
      result.current.expandGroupForSession({
        pinned: false,
        updatedAt: daysAgoIso(45),
      }),
    );
    expect(result.current.collapsedGroups.has("older")).toBe(false);
    // Unrelated groups remain collapsed.
    expect(result.current.collapsedGroups.has("month")).toBe(true);
  });

  it("expandGroupForSession is a no-op when the group is already open", () => {
    const { result } = renderHook(() => useCollapsedSessionGroups());
    const before = result.current.collapsedGroups;
    act(() =>
      result.current.expandGroupForSession({
        pinned: false,
        updatedAt: daysAgoIso(0),
      }),
    );
    // Same Set identity — no state churn for already-visible groups.
    expect(result.current.collapsedGroups).toBe(before);
  });

  it("ignores corrupted persisted state", () => {
    localStorage.setItem(STORAGE_KEY, "not json");
    const { result } = renderHook(() => useCollapsedSessionGroups());
    expect(result.current.collapsedGroups.has("month")).toBe(true);
    expect(result.current.collapsedGroups.has("older")).toBe(true);
  });
});
