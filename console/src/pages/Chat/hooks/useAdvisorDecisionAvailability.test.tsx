import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { sessionThinkingApi } from "@/features/thinking/sessionThinkingApi";
import { dispatchSessionModelChanged } from "@/features/session-settings/sessionModelEvents";
import { useAdvisorDecisionAvailability } from "./useAdvisorDecisionAvailability";

vi.mock("@/features/thinking/sessionThinkingApi", () => ({
  sessionThinkingApi: { get: vi.fn() },
}));

const view = (configured: boolean) =>
  ({ decision: { configured, enabled: false, override: null } }) as Awaited<
    ReturnType<typeof sessionThinkingApi.get>
  >;

afterEach(() => vi.clearAllMocks());

describe("useAdvisorDecisionAvailability", () => {
  it("loads the session setting and refreshes it when the model changes", async () => {
    const onChange = vi.fn();
    vi.mocked(sessionThinkingApi.get)
      .mockResolvedValueOnce(view(true))
      .mockResolvedValueOnce(view(false));

    const { unmount } = renderHook(() =>
      useAdvisorDecisionAvailability({
        active: true,
        agentId: "agent",
        sessionId: "session",
        chatId: "chat",
        onChange,
      }),
    );

    expect(onChange).toHaveBeenCalledWith(undefined);
    await waitFor(() =>
      expect(onChange).toHaveBeenLastCalledWith(view(true).decision),
    );
    expect(sessionThinkingApi.get).toHaveBeenCalledWith(
      "agent",
      "chat",
      "session",
    );

    act(() => window.dispatchEvent(new Event("session-model-changed")));
    await waitFor(() =>
      expect(onChange).toHaveBeenLastCalledWith(view(false).decision),
    );
    unmount();
  });

  it("ignores a stale response after the session changes", async () => {
    let resolveFirst!: (value: ReturnType<typeof view>) => void;
    vi.mocked(sessionThinkingApi.get)
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveFirst = resolve;
          }),
      )
      .mockResolvedValueOnce(view(false));
    const onChange = vi.fn();

    const { rerender } = renderHook(
      ({ sessionId }) =>
        useAdvisorDecisionAvailability({
          active: true,
          agentId: "agent",
          sessionId,
          onChange,
        }),
      { initialProps: { sessionId: "old" } },
    );

    rerender({ sessionId: "new" });
    await waitFor(() =>
      expect(onChange).toHaveBeenLastCalledWith(view(false).decision),
    );
    act(() => resolveFirst(view(true)));
    await act(async () => {});
    expect(onChange).toHaveBeenLastCalledWith(view(false).decision);
    expect(onChange).not.toHaveBeenCalledWith(view(true).decision);
  });

  it("ignores a scoped model change for another session", async () => {
    vi.mocked(sessionThinkingApi.get).mockResolvedValue(view(true));
    const onChange = vi.fn();
    const { unmount } = renderHook(() =>
      useAdvisorDecisionAvailability({
        active: true,
        agentId: "agent",
        sessionId: "old",
        chatId: "old-chat",
        onChange,
      }),
    );
    await waitFor(() =>
      expect(onChange).toHaveBeenLastCalledWith(view(true).decision),
    );
    const calls = vi.mocked(sessionThinkingApi.get).mock.calls.length;

    act(() => {
      dispatchSessionModelChanged({
        agentId: "agent",
        sessionId: "new",
        chatId: null,
      });
    });
    await act(async () => {});

    expect(sessionThinkingApi.get).toHaveBeenCalledTimes(calls);
    unmount();
  });

  it("refreshes the decision setting when the scoped model change matches", async () => {
    vi.mocked(sessionThinkingApi.get)
      .mockResolvedValueOnce(view(true))
      .mockResolvedValueOnce(view(false));
    const onChange = vi.fn();
    const { unmount } = renderHook(() =>
      useAdvisorDecisionAvailability({
        active: true,
        agentId: "agent",
        sessionId: "session",
        chatId: "chat",
        onChange,
      }),
    );
    await waitFor(() =>
      expect(onChange).toHaveBeenLastCalledWith(view(true).decision),
    );
    const calls = vi.mocked(sessionThinkingApi.get).mock.calls.length;

    act(() => {
      dispatchSessionModelChanged({
        agentId: "agent",
        sessionId: "session",
        chatId: "chat",
      });
    });

    await waitFor(() =>
      expect(onChange).toHaveBeenLastCalledWith(view(false).decision),
    );
    expect(sessionThinkingApi.get).toHaveBeenCalledTimes(calls + 1);
    unmount();
  });
});
