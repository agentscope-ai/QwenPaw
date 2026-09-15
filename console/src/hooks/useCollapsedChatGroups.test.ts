import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { useCollapsedChatGroups } from "./useCollapsedChatGroups";

describe("useCollapsedChatGroups", () => {
  beforeEach(() => localStorage.clear());

  it("keeps automated source groups collapsed until the user expands them", () => {
    const { result, unmount } = renderHook(() => useCollapsedChatGroups());

    expect(result.current.collapsedGroups.has("cron")).toBe(true);
    expect(result.current.collapsedGroups.has("subagents")).toBe(true);

    act(() => result.current.toggleGroup("subagents"));
    expect(result.current.collapsedGroups.has("subagents")).toBe(false);

    unmount();
    const remounted = renderHook(() => useCollapsedChatGroups());
    expect(remounted.result.current.collapsedGroups.has("subagents")).toBe(
      false,
    );
  });

  it("applies default collapsed groups once", () => {
    const { result } = renderHook(() => useCollapsedChatGroups());

    act(() => result.current.initializeCollapsedGroups(new Set(["older"])));
    expect(result.current.collapsedGroups.has("older")).toBe(true);

    act(() => result.current.initializeCollapsedGroups(new Set(["newer"])));
    expect(result.current.collapsedGroups.has("newer")).toBe(false);
  });

  it("upgrades the legacy default so new group defaults can apply", () => {
    localStorage.setItem(
      "qwenpaw_collapsed_chat_groups_v3",
      JSON.stringify(["cron", "subagents"]),
    );
    const { result } = renderHook(() => useCollapsedChatGroups());

    act(() => result.current.initializeCollapsedGroups(new Set(["older"])));

    expect(result.current.collapsedGroups.has("older")).toBe(true);
    expect(localStorage.getItem("qwenpaw_collapsed_chat_groups_v3")).toBeNull();
  });
});
