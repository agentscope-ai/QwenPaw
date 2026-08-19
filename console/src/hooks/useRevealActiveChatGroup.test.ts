import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useRevealActiveChatGroup } from "./useRevealActiveChatGroup";

describe("useRevealActiveChatGroup", () => {
  it("reveals a session once without reopening its group after updates", () => {
    const expandGroup = vi.fn();
    const { rerender } = renderHook(
      ({ currentSessionId, sessions }) =>
        useRevealActiveChatGroup(currentSessionId, sessions, expandGroup),
      {
        initialProps: {
          currentSessionId: "session-1" as string | undefined,
          sessions: [{ id: "session-1", groupId: "work" }],
        },
      },
    );

    expect(expandGroup).toHaveBeenCalledOnce();
    expect(expandGroup).toHaveBeenCalledWith("work");

    rerender({
      currentSessionId: "session-1",
      sessions: [{ id: "session-1", groupId: "work" }],
    });
    expect(expandGroup).toHaveBeenCalledOnce();

    rerender({
      currentSessionId: "session-2",
      sessions: [{ id: "session-2", groupId: "research" }],
    });
    expect(expandGroup).toHaveBeenCalledTimes(2);
    expect(expandGroup).toHaveBeenLastCalledWith("research");
  });
});
