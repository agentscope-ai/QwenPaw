import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useCreateNewSession } from "./useCreateNewSession";

const {
  changeCurrentSessionId,
  createSession,
  navigate,
  sessionApi,
  setCurrentSessionId,
} = vi.hoisted(() => ({
  changeCurrentSessionId: vi.fn(),
  createSession: vi.fn(),
  navigate: vi.fn(),
  sessionApi: { userInitiatedCreate: false },
  setCurrentSessionId: vi.fn(),
}));

vi.mock("react-router-dom", () => ({
  useNavigate: () => navigate,
}));

vi.mock("@agentscope-ai/chat", () => ({
  useChatAnywhereSessions: () => ({
    changeCurrentSessionId,
    createSession,
  }),
  useChatAnywhereSessionsState: () => ({ setCurrentSessionId }),
}));

vi.mock("../sessionApi", () => ({ default: sessionApi }));

describe("useCreateNewSession", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    sessionApi.userInitiatedCreate = false;
    createSession.mockResolvedValue("local-new-session");
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("commits the blank route before creating and reasserts the new session", async () => {
    const { result } = renderHook(() => useCreateNewSession());

    let creation: Promise<void> | undefined;
    act(() => {
      creation = result.current();
    });

    expect(navigate).toHaveBeenCalledWith("/chat", { replace: true });
    expect(createSession).not.toHaveBeenCalled();

    await act(async () => {
      await vi.runAllTimersAsync();
      await creation;
    });

    expect(setCurrentSessionId).toHaveBeenCalledWith(undefined);
    expect(sessionApi.userInitiatedCreate).toBe(true);
    expect(createSession).toHaveBeenCalledOnce();
    expect(changeCurrentSessionId).toHaveBeenCalledWith("local-new-session");

    expect(navigate.mock.invocationCallOrder[0]).toBeLessThan(
      setCurrentSessionId.mock.invocationCallOrder[0],
    );
    expect(setCurrentSessionId.mock.invocationCallOrder[0]).toBeLessThan(
      createSession.mock.invocationCallOrder[0],
    );
    expect(createSession.mock.invocationCallOrder[0]).toBeLessThan(
      changeCurrentSessionId.mock.invocationCallOrder[0],
    );
  });
});
