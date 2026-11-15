import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { subscribeNativeActivation } from "./nativeActivation";

const mocks = vi.hoisted(() => ({
  invoke: vi.fn(),
  listen: vi.fn(),
  unlisten: vi.fn(),
}));
vi.mock("@tauri-apps/api/core", () => ({ invoke: mocks.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: mocks.listen }));

describe("native notification activation", () => {
  beforeEach(() => {
    mocks.invoke.mockReset().mockResolvedValue(null);
    mocks.listen.mockReset().mockResolvedValue(mocks.unlisten);
    mocks.unlisten.mockClear();
  });
  afterEach(() => vi.restoreAllMocks());

  it("subscribes before opening a target queued during application startup", async () => {
    const target = { requestId: "request-1", agentId: "agent-2" };
    mocks.invoke.mockResolvedValueOnce({ kind: "approval", target });
    const open = vi.fn();
    const dispose = await subscribeNativeActivation(
      "approval",
      "qwenpaw:open-approval",
      open,
    );
    await vi.waitFor(() => expect(open).toHaveBeenCalledWith(target));
    expect(mocks.listen.mock.invocationCallOrder[0]).toBeLessThan(
      mocks.invoke.mock.invocationCallOrder[0],
    );
    expect(mocks.invoke).toHaveBeenCalledWith("take_notification_target", {
      kind: "approval",
    });
    dispose();
    expect(mocks.unlisten).toHaveBeenCalledOnce();
  });

  it("opens a live system event once and ignores consumed signals", async () => {
    const open = vi.fn();
    const dispose = await subscribeNativeActivation(
      "event",
      "qwenpaw:open-notification",
      open,
    );
    const callback = mocks.listen.mock.calls[0][1] as () => void;
    const target = { category: "conversation", session_id: "session-2" };
    mocks.invoke.mockResolvedValueOnce({ kind: "event", target });
    callback();
    await vi.waitFor(() => expect(open).toHaveBeenCalledWith(target));
    callback();
    await Promise.resolve();
    expect(open).toHaveBeenCalledOnce();
    dispose();
  });

  it("ignores an in-flight response after the listener is disposed", async () => {
    const open = vi.fn();
    let finish: ((target: unknown) => void) | undefined;
    mocks.invoke.mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    const dispose = await subscribeNativeActivation(
      "approval",
      "qwenpaw:open-approval",
      open,
    );
    dispose();
    finish?.({ target: { requestId: "stale" } });
    await Promise.resolve();
    expect(open).not.toHaveBeenCalled();
  });
});
