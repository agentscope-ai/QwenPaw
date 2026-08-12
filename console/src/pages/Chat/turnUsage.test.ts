import { describe, expect, it, vi } from "vitest";
import { wrapChatResponseUsageStream } from "./turnUsage";

describe("wrapChatResponseUsageStream", () => {
  it("runs its completion callback after the response stream is consumed", async () => {
    const onComplete = vi.fn();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode("data: {}\n\n"));
        controller.close();
      },
    });
    const wrapped = wrapChatResponseUsageStream(
      new Response(body),
      { current: null },
      onComplete,
    );

    expect(onComplete).not.toHaveBeenCalled();
    await wrapped.text();
    expect(onComplete).toHaveBeenCalledOnce();
  });
});
