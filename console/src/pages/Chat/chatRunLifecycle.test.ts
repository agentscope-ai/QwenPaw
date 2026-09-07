import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ChatRunLifecycle } from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/Execution/runLifecycle";
import { request } from "../../api/request";
import {
  useMessageQueueStore,
  withSendLock,
} from "../../stores/messageQueueStore";
import {
  awaitQueueAcceptance,
  recoverSendingQueueHead,
} from "./chatRunLifecycle";
vi.mock("../../api/request", () => ({ request: vi.fn() }));
const key = "chat-a";
function run() {
  return new ChatRunLifecycle({
    runId: "run-a",
    source: "host-queue",
    sessionId: key,
    cancel: vi.fn(),
  });
}
function sendingHead() {
  const store = useMessageQueueStore.getState();
  store.enqueue(key, { text: "first", agentId: "agent-a" });
  store.enqueue(key, { text: "second", agentId: "agent-a" });
  const head = store.getQueue(key)[0];
  store.setItemStatus(key, head.id, "sending");
  return head;
}
beforeEach(() => {
  localStorage.clear();
  useMessageQueueStore.setState({
    queues: {},
    runStates: {},
    currentSendingId: null,
  });
  vi.mocked(request).mockReset();
});
afterEach(() => vi.unstubAllGlobals());
describe("queue Run handoff", () => {
  it("releases the send lock when switching away from a real disconnected SDK Run", async () => {
    let held = false;
    vi.stubGlobal("navigator", {
      locks: {
        request: async (
          _name: string,
          _options: unknown,
          callback: (lock: unknown) => Promise<unknown>,
        ) => {
          if (held) return callback(null);
          held = true;
          try {
            return await callback({});
          } finally {
            held = false;
          }
        },
      },
    });
    const lifecycle = run();
    lifecycle.markSubmitting();
    lifecycle.markDispatched();
    const controller = new AbortController();
    const locked = withSendLock(key, () =>
      awaitQueueAcceptance(
        Promise.resolve(lifecycle.handle),
        controller.signal,
      ),
    );
    lifecycle.markDisconnected(
      new Error("chat session changed during streaming"),
    );
    expect(await withSendLock(key, () => "next")).toBeNull();
    controller.abort();
    await locked;
    expect(lifecycle.getState()).toBe("disconnected");
    expect(await withSendLock(key, () => "next")).toBe("next");
  });
  it("also leaves an unresolved SDK execution when its Chat scope ends", async () => {
    const controller = new AbortController();
    const pending = awaitQueueAcceptance(
      new Promise(() => {}),
      controller.signal,
    );
    controller.abort();
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
  });
  it("retains normal accepted and rejected SDK results", async () => {
    const accepted = run();
    accepted.markAccepted(key);
    await expect(
      awaitQueueAcceptance(
        Promise.resolve(accepted.handle),
        new AbortController().signal,
      ),
    ).resolves.toMatchObject({ accepted: true });
    const rejected = run();
    rejected.fail(new Error("offline"));
    await expect(
      awaitQueueAcceptance(
        Promise.resolve(rejected.handle),
        new AbortController().signal,
      ),
    ).resolves.toMatchObject({ accepted: false });
  });
});
describe("persisted sending recovery", () => {
  it("removes a confirmed receipt after reload and preserves the next queued task", async () => {
    const head = sendingHead();
    useMessageQueueStore.setState({ queues: {}, runStates: {} });
    useMessageQueueStore.getState().loadFromStorage(key);
    vi.mocked(request).mockResolvedValue({
      status: "idle",
      messages: [
        {
          role: "user",
          metadata: { qwenpaw_client_message_id: head.clientMessageId },
        },
      ],
    });
    await recoverSendingQueueHead(
      key,
      new AbortController().signal,
      "agent-a",
      key,
      "retry required",
    );
    expect(
      useMessageQueueStore
        .getState()
        .getQueue(key)
        .map((item) => [item.text, item.status]),
    ).toEqual([["second", "pending"]]);
    expect(request).toHaveBeenCalledWith(
      "/chats/chat-a",
      expect.objectContaining({ headers: { "X-Agent-Id": "agent-a" } }),
    );
  });
  it("makes an unknown receipt explicitly retryable instead of silently resending", async () => {
    sendingHead();
    vi.mocked(request).mockResolvedValue({ status: "idle", messages: [] });
    await recoverSendingQueueHead(
      key,
      new AbortController().signal,
      "agent-a",
      key,
      "retry required",
    );
    expect(useMessageQueueStore.getState().getQueue(key)[0]).toMatchObject({
      status: "failed",
      errorMessage: "retry required",
    });
    expect(useMessageQueueStore.getState().getRunState(key)).toBe("error");
    expect(useMessageQueueStore.getState().getQueue(key)).toHaveLength(2);
  });
  it("does not mutate a sending item after another Agent switch during recovery", async () => {
    sendingHead();
    const controller = new AbortController();
    vi.mocked(request).mockImplementation(async () => {
      controller.abort();
      return { status: "idle", messages: [] };
    });
    await recoverSendingQueueHead(
      key,
      controller.signal,
      "agent-a",
      key,
      "retry required",
    );
    expect(useMessageQueueStore.getState().getQueue(key)[0].status).toBe(
      "sending",
    );
  });
});
