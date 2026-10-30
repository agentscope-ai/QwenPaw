import { beforeEach, describe, expect, it, vi } from "vitest";
import { subscribeDesktopConsolePush } from "../tauri/consoleNotifications";

const mocks = vi.hoisted(() => ({
  invoke: vi.fn(),
  listen: vi.fn(),
  unlisten: vi.fn(),
  handler: undefined as
    | ((event: { payload: { generation: number; snapshot: unknown } }) => void)
    | undefined,
}));

vi.mock("@tauri-apps/api/core", () => ({ invoke: mocks.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: mocks.listen }));
vi.mock("../api/authHeaders", () => ({
  buildAuthHeaders: () => ({
    Authorization: "Bearer test-fixture-token",
    "X-Agent-Id": "agent-1",
  }),
}));

describe("native console push subscription", () => {
  const snapshot = { messages: [], pending_approvals: [] };
  beforeEach(() => {
    mocks.invoke.mockReset().mockResolvedValue(7);
    mocks.unlisten.mockReset();
    mocks.listen.mockReset().mockImplementation(async (_name, handler) => {
      mocks.handler = handler;
      return mocks.unlisten;
    });
  });

  it("subscribes before starting the native poller and forwards matching snapshots", async () => {
    const accept = vi.fn();
    const stop = await subscribeDesktopConsolePush(accept);
    expect(mocks.listen.mock.invocationCallOrder[0]).toBeLessThan(
      mocks.invoke.mock.invocationCallOrder[0],
    );
    mocks.handler?.({ payload: { generation: 7, snapshot } });
    expect(accept).toHaveBeenCalledWith(snapshot);
    stop();
    expect(mocks.unlisten).toHaveBeenCalledOnce();
    expect(mocks.invoke).toHaveBeenLastCalledWith("stop_console_polling", {
      generation: 7,
    });
  });

  it("ignores events from a previous native polling generation", async () => {
    const accept = vi.fn();
    const stop = await subscribeDesktopConsolePush(accept);
    mocks.handler?.({ payload: { generation: 6, snapshot } });
    expect(accept).not.toHaveBeenCalled();
    stop();
  });

  it("keeps a snapshot that arrives before start returns its generation", async () => {
    mocks.invoke.mockImplementation(async () => {
      mocks.handler?.({ payload: { generation: 7, snapshot } });
      return 7;
    });
    const accept = vi.fn();
    const stop = await subscribeDesktopConsolePush(accept);
    expect(accept).toHaveBeenCalledExactlyOnceWith(snapshot);
    stop();
  });

  it("removes the event listener if native startup fails", async () => {
    mocks.invoke.mockRejectedValue(new Error("native startup unavailable"));
    await expect(subscribeDesktopConsolePush(vi.fn())).rejects.toThrow(
      "native startup unavailable",
    );
    expect(mocks.unlisten).toHaveBeenCalledOnce();
  });

  it("does not deliver events after the subscription is disposed", async () => {
    const accept = vi.fn();
    const stop = await subscribeDesktopConsolePush(accept);
    stop();
    mocks.handler?.({ payload: { generation: 7, snapshot } });
    expect(accept).not.toHaveBeenCalled();
  });
});
