import { describe, expect, it, vi } from "vitest";
import { cancelSdkChatRequest } from "./sdkCancellation";

describe("cancelSdkChatRequest", () => {
  it("aborts locally and stops the resolved backend chat", async () => {
    const abort = vi.fn();
    const stopChat = vi.fn().mockResolvedValue(undefined);

    await cancelSdkChatRequest(
      { session_id: "local-session", abort },
      {
        resolveBackendSessionId: () => "backend-session",
        stopChat,
      },
    );

    expect(abort).toHaveBeenCalledOnce();
    expect(stopChat).toHaveBeenCalledWith("backend-session");
  });

  it("reports backend stop failure while retaining local cancellation", async () => {
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

    expect(abort).toHaveBeenCalledOnce();
    expect(onError).toHaveBeenCalledWith(error);
  });
});
