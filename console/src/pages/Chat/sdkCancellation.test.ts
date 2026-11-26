import { describe, expect, it, vi } from "vitest";
import { cancelSdkChatRequest } from "./sdkCancellation";

describe("cancelSdkChatRequest", () => {
  it("preserves SSE while stopping the resolved backend chat", async () => {
    const abort = vi.fn();
    const stopChat = vi.fn().mockResolvedValue({ stopped: true });

    await expect(
      cancelSdkChatRequest(
        { session_id: "local-session", abort },
        {
          resolveBackendSessionId: () => "backend-session",
          stopChat,
        },
      ),
    ).resolves.toBe(true);

    expect(abort).not.toHaveBeenCalled();
    expect(stopChat).toHaveBeenCalledWith("backend-session");
  });

  it("reports an unsuccessful stop without treating it as canceled", async () => {
    const stopChat = vi.fn().mockResolvedValue({ stopped: false });

    await expect(
      cancelSdkChatRequest(
        { session_id: "session" },
        {
          resolveBackendSessionId: () => null,
          stopChat,
        },
      ),
    ).resolves.toBe(false);
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
