import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  createSession: vi.fn<() => Promise<string | undefined>>(),
  navigate: vi.fn(),
}));

vi.mock("react-router-dom", () => ({
  useNavigate: () => mocks.navigate,
}));

vi.mock("@agentscope-ai/chat", () => ({
  useChatAnywhereSessions: () => ({ createSession: mocks.createSession }),
}));

import { useCreateNewSession } from "./useCreateNewSession";

describe("useCreateNewSession", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.createSession.mockResolvedValue("local-session");
  });

  it("lets the SDK activate and clear the newly created session", async () => {
    const { result } = renderHook(() => useCreateNewSession());

    await act(async () => {
      await result.current();
    });

    expect(mocks.navigate).toHaveBeenCalledWith("/chat", { replace: true });
    expect(mocks.createSession).toHaveBeenCalledOnce();
  });
});
