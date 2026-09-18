import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  createSession: vi.fn<() => Promise<string | undefined>>(),
  setCurrentSessionId: vi.fn(),
  navigate: vi.fn(),
}));

vi.mock("react-router-dom", () => ({
  useNavigate: () => mocks.navigate,
}));

vi.mock("@agentscope-ai/chat", () => ({
  useChatAnywhereSessions: () => ({
    createSession: mocks.createSession,
  }),
  useChatAnywhereSessionsState: () => ({
    setCurrentSessionId: mocks.setCurrentSessionId,
  }),
}));

import { useCreateNewSession } from "./useCreateNewSession";
import sessionApi from "../sessionApi";
import { useAgentStore } from "../../../stores/agentStore";

describe("useCreateNewSession", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.createSession.mockResolvedValue("local-session");
  });

  it("opens the blank composer without allocating a backend session", async () => {
    sessionApi.lastActiveChatId = "previous-chat";
    sessionApi.preferredChatId = "previous-chat";
    const agents = useAgentStore.getState();
    agents.setLastChatId(agents.selectedAgent, "previous-chat");
    const { result } = renderHook(() => useCreateNewSession());

    await act(async () => {
      await result.current();
    });

    expect(mocks.navigate).toHaveBeenCalledWith("/chat", { replace: true });
    expect(mocks.setCurrentSessionId).toHaveBeenCalledWith(undefined);
    expect(mocks.createSession).not.toHaveBeenCalled();
    expect(sessionApi.lastActiveChatId).toBeNull();
    expect(sessionApi.preferredChatId).toBeNull();
    expect(
      useAgentStore.getState().getLastChatId(agents.selectedAgent),
    ).toBeUndefined();
  });

  it("keeps repeated new-chat requests empty, including the post-delete action", async () => {
    const { result } = renderHook(() => useCreateNewSession());

    await act(async () => {
      await Promise.all([result.current(), result.current(), result.current()]);
    });

    expect(mocks.createSession).not.toHaveBeenCalled();
    expect(mocks.setCurrentSessionId).toHaveBeenCalledTimes(3);
    expect(mocks.navigate).toHaveBeenLastCalledWith("/chat", { replace: true });
  });
});
