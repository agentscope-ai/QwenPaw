import { describe, expect, it, vi } from "vitest";
import { cancelSdkChatRequest } from "./sdkCancellation";

describe("cancelSdkChatRequest", () => {
  it("preserves SSE while stopping the resolved backend chat", async () => {
    const abort = vi.fn();
    const stopChat = vi.fn().mockResolvedValue(undefined);

    await cancelSdkChatRequest(
      { session_id: "local-session", abort },
      {
        resolveBackendSessionId: () => "backend-session",
        stopChat,
      },
    );

    expect(abort).not.toHaveBeenCalled();
    expect(stopChat).toHaveBeenCalledWith("backend-session");
  });

  it("propagates stop failure so the SDK can perform local cleanup", async () => {
    const abort = vi.fn();
    const onError = vi.fn();
    const error = new Error("stop failed");

    await expect(
      cancelSdkChatRequest(
        { session_id: "session", abort },
        {
          resolveBackendSessionId: () => null,
          stopChat: vi.fn().mockRejectedValue(error),
          onError,
        },
      ),
    ).rejects.toBe(error);

    expect(abort).not.toHaveBeenCalled();
    expect(onError).toHaveBeenCalledWith(error);
  });
});
