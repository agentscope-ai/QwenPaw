import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { useCollapsedChatGroups } from "./useCollapsedChatGroups";

describe("useCollapsedChatGroups", () => {
  beforeEach(() => localStorage.clear());

  it("keeps the Subagents group collapsed until the user expands it", () => {
    const { result, unmount } = renderHook(() => useCollapsedChatGroups());

    expect(result.current.collapsedGroups.has("subagents")).toBe(true);

    act(() => result.current.toggleGroup("subagents"));
    expect(result.current.collapsedGroups.has("subagents")).toBe(false);

    unmount();
    const remounted = renderHook(() => useCollapsedChatGroups());
    expect(remounted.result.current.collapsedGroups.has("subagents")).toBe(
      false,
    );
  });
});
