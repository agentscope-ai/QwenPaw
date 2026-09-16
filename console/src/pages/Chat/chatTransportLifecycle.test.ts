import { describe, expect, it } from "vitest";
import { ChatTransportLifecycle } from "./chatTransportLifecycle";

describe("ChatTransportLifecycle", () => {
  it("aborts the active response stream before canonical resume history is applied", () => {
    const lifecycle = new ChatTransportLifecycle();
    const signal = lifecycle.begin();

    lifecycle.abortCurrent();

    expect(signal.aborted).toBe(true);
  });

  it("propagates the SDK request cancellation into the owned transport", () => {
    const lifecycle = new ChatTransportLifecycle();
    const sdkController = new AbortController();
    const signal = lifecycle.begin(sdkController.signal);

    sdkController.abort();

    expect(signal.aborted).toBe(true);
  });

  it("invalidates the previous response stream when a new request begins", () => {
    const lifecycle = new ChatTransportLifecycle();
    const first = lifecycle.begin();
    const second = lifecycle.begin();

    expect(first.aborted).toBe(true);
    expect(second.aborted).toBe(false);
  });
});
