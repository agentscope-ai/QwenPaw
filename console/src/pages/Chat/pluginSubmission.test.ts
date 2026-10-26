import { beforeEach, describe, expect, it } from "vitest";
import { enqueuePluginSubmission } from "./pluginSubmission";
import {
  MAX_QUEUE_SIZE,
  useMessageQueueStore,
} from "../../stores/messageQueueStore";

const input = { query: "Use 8 seeds", agentId: "a", sessionId: "sdk-a" };
const context = {
  active: true,
  ready: true,
  agentId: "a",
  currentSessionId: "chat-a",
  queueKey: "chat-a",
  resolveIdentity: (id: string) => ({
    sdkSessionId: ["sdk-a", "chat-a"].includes(id) ? "sdk-a" : "sdk-b",
    chatId: ["sdk-a", "chat-a"].includes(id) ? "chat-a" : "chat-b",
    sessionId: ["sdk-a", "chat-a"].includes(id) ? "backend-a" : "backend-b",
    userId: "user",
    channel: "console",
  }),
  prepareQuery: (query: string) => query,
  requestContext: { approval_level: "default" },
  queueFullMessage: "Queue full",
  staleMessage: "请回到原来的对话后再提交。",
};

beforeEach(() => {
  useMessageQueueStore.setState({
    queues: {},
    runStates: {},
    currentSendingId: null,
  });
  localStorage.clear();
});

describe("plugin queue admission", () => {
  it("captures one complete route and request identity without consuming drafts", () => {
    localStorage.setItem("draft", "unsubmitted composer text and attachments");
    enqueuePluginSubmission(input, context);
    const queue = useMessageQueueStore.getState().getQueue("chat-a");
    expect(queue).toHaveLength(1);
    expect(queue[0]).toMatchObject({
      text: "Use 8 seeds",
      agentId: "a",
      backendSessionId: "backend-a",
      userId: "user",
      channel: "console",
      requestContext: context.requestContext,
    });
    expect(queue[0].clientMessageId).toBeTruthy();
    expect(queue[0].attachments).toBeUndefined();
    expect(localStorage.getItem("draft")).toBe(
      "unsubmitted composer text and attachments",
    );
  });
  it("rejects stale sessions, agent switches and unavailable chat", () => {
    for (const changed of [
      { active: false },
      { ready: false },
      { agentId: "b" },
      { currentSessionId: "chat-b" },
    ]) {
      expect(() =>
        enqueuePluginSubmission(input, { ...context, ...changed }),
      ).toThrow(context.staleMessage);
    }
    expect(useMessageQueueStore.getState().getQueue("chat-a")).toHaveLength(0);
  });
  it("rejects a different Chat even when both share a runtime session", () => {
    expect(() =>
      enqueuePluginSubmission(input, {
        ...context,
        currentSessionId: "chat-b",
        resolveIdentity: (id: string) => ({
          ...context.resolveIdentity(id),
          sessionId: "shared-runtime",
        }),
      }),
    ).toThrow(context.staleMessage);
    expect(useMessageQueueStore.getState().getQueue("chat-a")).toHaveLength(0);
  });

  it("accepts the same local SDK chat before a backend chat ID is assigned", () => {
    enqueuePluginSubmission(input, {
      ...context,
      resolveIdentity: (id: string) => ({
        ...context.resolveIdentity(id),
        chatId: undefined,
      }),
    });
    expect(useMessageQueueStore.getState().getQueue("chat-a")).toHaveLength(1);
  });

  it("rejects unresolved chat references", () => {
    expect(() =>
      enqueuePluginSubmission(input, {
        ...context,
        resolveIdentity: () => ({
          sdkSessionId: "",
          sessionId: "runtime",
          userId: "user",
          channel: "console",
        }),
      }),
    ).toThrow(context.staleMessage);
    expect(useMessageQueueStore.getState().getQueue("chat-a")).toHaveLength(0);
  });

  it("reports a full queue without silently losing or duplicating the action", () => {
    for (let i = 0; i < MAX_QUEUE_SIZE; i++)
      enqueuePluginSubmission(input, context);
    expect(() => enqueuePluginSubmission(input, context)).toThrow("Queue full");
    expect(useMessageQueueStore.getState().getQueue("chat-a")).toHaveLength(
      MAX_QUEUE_SIZE,
    );
  });
});
