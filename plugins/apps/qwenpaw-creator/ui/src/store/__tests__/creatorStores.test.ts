import { act, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CreatorEvent } from "@/contracts/creator";
import { useCreatorSessionStore } from "@/store/creatorSessionStore";
import { installMockFetch } from "@/test/mockFetch";
import {
  bootstrapRoutes,
  ev,
  msg,
  sessionView,
  testEventSources,
} from "@/test/sessionEventBuilders";

const store = () => useCreatorSessionStore.getState();
const ingest = (...events: CreatorEvent[]) =>
  act(() => store().ingestEvents(events));
const seed = (state: Record<string, unknown> = {}) =>
  useCreatorSessionStore.setState({
    projectId: "p1",
    lastEventSeq: 0,
    ...state,
  });

describe("bounded frontend caches", () => {
  beforeEach(() => store().reset());

  it("deduplicates durable events by seq and never treats streaming state as completion", () => {
    seed({ lastEventSeq: 3, events: [] });
    const event = ev(4, "subagent.waiting_runtime");
    store().ingestEvent(event);
    store().ingestEvent(event);
    expect(store().events).toHaveLength(1);
    expect(store().lastEventSeq).toBe(4);
  });

  it("tracks Sub-agent tool progress, task telemetry and canonical arguments", () => {
    seed();
    ingest(
      ev(1, "agent.tool_started", {
        actionId: "delegate-1",
        tool: "delegate_to_agent",
        role: "visual_development_agent",
      }),
      ev(2, "subagent.tool_progress", {
        parentActionId: "delegate-1",
        runId: "run-1",
        role: "visual_development_agent",
        toolCallId: "tool-1",
        tool: "read_project_file",
        receivedBytes: 2048,
        providerChunkCount: 12,
        complete: false,
      }),
    );
    let tool = store().subagentActivities["delegate-1"].tools["run-1:tool-1"];
    expect(tool).toMatchObject({
      status: "started",
      receivedBytes: 2048,
      providerChunkCount: 12,
      argumentStreamComplete: false,
    });
    expect(tool.arguments).toBeUndefined();

    ingest(
      ev(3, "subagent.tool_started", {
        parentActionId: "delegate-1",
        runId: "run-1",
        role: "visual_development_agent",
        messageId: "message-1",
        toolCallId: "tool-1",
        tool: "read_project_file",
        arguments: { path: "story/outline.md" },
        state: "started",
      }),
      ev(4, "task.progress_updated", {
        taskId: "task-1",
        specialistRunId: "run-1",
        status: "RUNNING",
        progress: 0.4,
      }),
    );
    tool = store().subagentActivities["delegate-1"].tools["run-1:tool-1"];
    expect(tool.arguments).toEqual({ path: "story/outline.md" });
    expect(tool.firstEventSeq).toBe(2);
    expect(tool).toMatchObject({
      taskId: "task-1",
      outputEvents: [
        { seq: 4, type: "task.progress_updated", data: { progress: 0.4 } },
      ],
    });
  });

  it("bootstraps canonical DTOs and replays the durable named SSE log after refresh", async () => {
    installMockFetch(
      bootstrapRoutes({
        messages: [
          msg({
            messageId: "m1",
            messageSeq: 1,
            role: "assistant",
            content: [{ type: "text", text: "已开始" }],
            source: "creator",
          }),
        ],
        session: {
          lastMessageSeq: 1,
          lastConsumedMessageSeq: 1,
          lastEventSeq: 7,
        },
      }),
    );
    await store().bootstrap("p1");
    expect(store().activeConversationId).toBe("c1");
    expect(store().messages[0].messageSeq).toBe(1);
    const sources = testEventSources();
    expect(sources[0].url).toContain("events?after=0");
    act(() =>
      sources[0].emit(
        "session.status_changed",
        ev(8, "session.status_changed", { status: "WAITING_RUNTIME" }),
      ),
    );
    await waitFor(() =>
      expect(store().session?.status).toBe("WAITING_RUNTIME"),
    );
    expect(store().lastEventSeq).toBe(8);
    // A creator.woken replay projects the recovered Session as running again.
    act(() =>
      sources[0].emit(
        "creator.woken",
        ev(9, "creator.woken", { trigger: "user_message" }),
      ),
    );
    await waitFor(() => expect(store().session?.status).toBe("RUNNING"));
    expect(store().lastEventSeq).toBe(9);
  });

  it("resumes a same-project remount from its durable cursor without clearing visible messages", async () => {
    installMockFetch(
      bootstrapRoutes({
        session: {
          lastMessageSeq: 1,
          lastConsumedMessageSeq: 1,
          lastEventSeq: 7,
        },
      }),
    );
    const visibleMessage = msg({
      messageId: "m1",
      messageSeq: 1,
      role: "assistant",
      content: [{ type: "text", text: "保持可见" }],
      source: "creator_agent",
    });
    seed({
      session: sessionView({
        lastMessageSeq: 1,
        lastConsumedMessageSeq: 1,
        lastEventSeq: 7,
      }),
      activeConversationId: "c1",
      messages: [visibleMessage],
      events: [ev(7, "task.progress_updated")],
      lastEventSeq: 7,
    });

    await store().bootstrap("p1");

    expect(store().messages).toContainEqual(visibleMessage);
    expect(store().events).toHaveLength(1);
    expect(store().lastEventSeq).toBe(7);
    expect(testEventSources()[0].url).toContain("events?after=7");
  });

  it("folds a large durable SSE replay into one bounded store update", async () => {
    installMockFetch(bootstrapRoutes({ session: { lastEventSeq: 307 } }));
    await store().bootstrap("p1");
    const sources = testEventSources();
    let notifications = 0;
    const unsubscribe = useCreatorSessionStore.subscribe(() => {
      notifications += 1;
    });
    act(() => {
      for (let seq = 8; seq <= 307; seq += 1) {
        sources[0].emit(
          "task.progress_updated",
          ev(seq, "task.progress_updated", {
            taskId: "t1",
            progress: seq / 307,
          }),
        );
      }
    });
    await waitFor(() => expect(store().lastEventSeq).toBe(307));
    expect(store().events).toHaveLength(300);
    expect(notifications).toBe(1);
    unsubscribe();
  });

  it("does not confuse a concrete Task progress number with AgentStatusBar progress", () => {
    const progress = {
      phase: "timeline_edit" as const,
      label: "执行中",
      sourceEventSeq: 1,
      updatedAt: "now",
    };
    seed({ agentStatusBar: { progress, badges: [] } });
    store().ingestEvent(
      ev(1, "task_progress.updated", { taskId: "t1", progress: 0.5 }),
    );
    expect(store().agentStatusBar?.progress).toEqual(progress);
  });

  it("merges Creator deltas by messageId and deltaIndex without polling messages per token", () => {
    const { calls } = installMockFetch([]);
    seed({ activeConversationId: "c1" });

    ingest(
      ev(1, "agent.message_delta", {
        messageId: "assistant-stream",
        deltaIndex: 1,
        delta: "世界",
      }),
      ev(2, "agent.message_delta", {
        messageId: "assistant-stream",
        deltaIndex: 0,
        delta: "你好，",
      }),
      ev(3, "agent.message_delta", {
        messageId: "assistant-stream",
        deltaIndex: 1,
        delta: "不应重复",
      }),
      ev(4, "agent.message_delta", {
        messageId: "assistant-stream",
        deltaIndex: 2,
        delta: "真实模型思考",
        streamKind: "thinking",
      }),
    );

    const streaming = store().streamingAssistantMessages["assistant-stream"];
    expect(
      Object.entries(streaming.deltas)
        .sort(([left], [right]) => Number(left) - Number(right))
        .map(([, delta]) => delta)
        .join(""),
    ).toBe("你好，世界");
    expect(streaming.thinkingDeltas).toEqual({ 2: "真实模型思考" });
    expect(calls).toHaveLength(0);
  });

  it("keeps the streamed assistant until message.completed is durably pulled, then calibrates by messageId", async () => {
    const durable = msg({
      messageId: "assistant-stream",
      messageSeq: 2,
      role: "assistant",
      content: [{ type: "text", text: "## 最终结果\n\n已完成。" }],
      source: "creator_agent",
    });
    const { calls } = installMockFetch([
      {
        match: "/conversations/c1/messages?after=1&limit=500",
        response: { json: { items: [durable] } },
      },
    ]);
    seed({
      activeConversationId: "c1",
      messages: [
        msg({ messageId: "user-1", messageSeq: 1, source: "initial_goal" }),
      ],
    });

    ingest(
      ev(1, "agent.message_delta", {
        messageId: "assistant-stream",
        deltaIndex: 0,
        delta: "## 最终",
      }),
    );
    expect(
      store().streamingAssistantMessages["assistant-stream"],
    ).toBeDefined();
    expect(calls).toHaveLength(0);

    ingest(
      ev(2, "message.completed", {
        messageId: "assistant-stream",
        openActionIds: [],
      }),
    );
    expect(
      store().streamingAssistantMessages["assistant-stream"],
    ).toBeDefined();

    await waitFor(() => expect(store().messages).toContainEqual(durable));
    expect(
      store().streamingAssistantMessages["assistant-stream"],
    ).toBeUndefined();
    expect(calls).toHaveLength(1);
  });

  it("drops abandoned partial assistants on every terminal signal (rejection/error/recovery/run failed/cancelled)", () => {
    const { calls } = installMockFetch([]);
    seed({ activeConversationId: "c1" });
    const delta = (
      seq: number,
      messageId: string,
      runId?: string,
    ): CreatorEvent =>
      ev(seq, "agent.message_delta", {
        ...(runId ? { runId } : {}),
        messageId,
        deltaIndex: 0,
        delta: "不完整内容",
      });

    ingest(
      delta(1, "rejected-message"),
      ev(2, "assistant.output_rejected", {
        assistantMessageId: "rejected-message",
      }),
      delta(3, "errored-message"),
      ev(4, "session.error", { assistantMessageId: "errored-message" }),
      delta(5, "recovered-message"),
      ev(6, "session.status_changed", {
        status: "RUNNING",
        recoveredIncompleteAssistant: true,
        assistantMessageId: "recovered-message",
      }),
      delta(7, "assistant-failed", "run-failed"),
      ev(8, "agent.run.failed", {
        runId: "run-failed",
        error: { code: "STREAM_PERSISTENCE_FAILED", message: "lock timeout" },
      }),
      delta(9, "assistant-cancelled", "run-cancelled"),
      ev(10, "agent.run.cancelled", { runId: "run-cancelled" }),
    );

    expect(store().streamingAssistantMessages).toEqual({});
    expect(calls).toHaveLength(0);
  });

  it("tracks rate-limit retry notices until the throttled run fails", () => {
    installMockFetch([]);
    seed({ activeConversationId: "c1", session: sessionView() });

    ingest(
      ev(1, "agent.model.rate_limit_retry", {
        runId: "run-throttled",
        attempt: 1,
        maxAttempts: 5,
        delaySeconds: 2,
      }),
    );
    expect(store().rateLimitRetry).toEqual({
      attempt: 1,
      maxAttempts: 5,
      runId: "run-throttled",
    });

    const error = {
      code: "MODEL_RATE_LIMITED",
      message: "模型遭遇限流，已重试 5 次仍无法访问",
      retryable: true,
      details: { retryCount: 5 },
    };
    ingest(ev(2, "agent.run.failed", { runId: "run-throttled", error }));
    expect(store().rateLimitRetry).toBeNull();
    expect(store().session?.error).toEqual(error);
  });

  it("does not resurrect a failed draft while replaying a completed retry", () => {
    const durableRetry = msg({
      messageId: "assistant-retry",
      messageSeq: 2,
      role: "assistant",
      content: [{ type: "text", text: "完整重试结果" }],
      source: "creator_agent",
      createdAt: "later",
    });
    const { calls } = installMockFetch([]);
    seed({
      activeConversationId: "c1",
      messages: [
        msg({ messageId: "user-1", messageSeq: 1, source: "initial_goal" }),
        durableRetry,
      ],
    });

    ingest(
      ev(1, "agent.message_delta", {
        runId: "run-old",
        messageId: "assistant-old",
        deltaIndex: 0,
        delta: "不完整结果",
      }),
      ev(2, "agent.run.failed", { runId: "run-old" }),
      ev(3, "agent.message_delta", {
        runId: "run-retry",
        messageId: "assistant-retry",
        deltaIndex: 0,
        delta: "完整重试结果",
      }),
    );

    expect(store().messages).toContainEqual(durableRetry);
    expect(store().streamingAssistantMessages).toEqual({});
    expect(calls).toHaveLength(0);
  });

  it("aggregates replayable Sub-agent messages and nested tools under the parent delegate action", () => {
    installMockFetch([]);
    seed({ activeConversationId: "c1" });
    const sub = {
      parentActionId: "delegate-action",
      runId: "run-1",
      role: "visual_development_agent",
    };

    ingest(
      ev(1, "agent.tool_started", {
        actionId: "delegate-action",
        tool: "delegate_to_agent",
        role: "visual_development_agent",
        roleDisplayName: "故事规划",
        delegationText: "请完善开场冲突。",
        targetRefs: ["timeline:main"],
      }),
      ev(2, "agent.tool_completed", {
        actionId: "delegate-action",
        tool: "delegate_to_agent",
        status: "succeeded",
      }),
      ev(3, "subagent.accepted", {
        ...sub,
        roleDisplayName: "故事规划",
        delegationText: "请完善开场冲突。",
        targetRefs: ["timeline:main"],
      }),
      ev(4, "subagent.message_delta", {
        ...sub,
        messageId: "sub-message-1",
        deltaIndex: 1,
        delta: "处理中",
      }),
      ev(5, "subagent.message_delta", {
        ...sub,
        messageId: "sub-message-1",
        deltaIndex: 0,
        delta: "[SUCCESS]\n",
      }),
      ev(7, "subagent.tool_started", {
        ...sub,
        toolCallId: "nested-tool-1",
        tool: "read_project_file",
        arguments: { path: "story/outline.md" },
        state: "started",
      }),
      ev(8, "subagent.tool_completed", {
        ...sub,
        toolCallId: "nested-tool-1",
        tool: "read_project_file",
        result: { summary: "读取完成" },
        state: "succeeded",
      }),
      ev(9, "subagent.message_completed", {
        ...sub,
        messageId: "sub-message-1",
        text: "[SUCCESS]\n## 已完成\n\n第一幕冲突已完善。",
        finishReason: "stop",
      }),
    );

    const activity = store().subagentActivities["delegate-action"];
    expect(activity).toMatchObject({
      parentActionId: "delegate-action",
      runId: "run-1",
      role: "visual_development_agent",
      roleDisplayName: "故事规划",
      delegationText: "请完善开场冲突。",
      targetRefs: ["timeline:main"],
      completed: false,
    });
    expect(activity.messages["run-1:sub-message-1"]).toMatchObject({
      completed: true,
      completedText: "[SUCCESS]\n## 已完成\n\n第一幕冲突已完善。",
      finishReason: "stop",
      deltas: { 0: "[SUCCESS]\n", 1: "处理中" },
    });
    expect(activity.tools["run-1:nested-tool-1"]).toMatchObject({
      tool: "read_project_file",
      status: "succeeded",
      result: { summary: "读取完成" },
    });
    ingest(
      ev(10, "subagent.completed", {
        ...sub,
        marker: "SUCCESS",
        status: "SUCCEEDED",
        summaryText: "第一幕冲突已完善。",
      }),
    );
    const terminal = {
      completed: true,
      terminalKind: "SUCCESS",
      summaryText: "第一幕冲突已完善。",
      terminalEventSeq: 10,
    };
    expect(store().subagentActivities["delegate-action"]).toMatchObject(
      terminal,
    );
    // A later continuation completion must not reopen the bubble.
    ingest(ev(11, "subagent.continuation_completed", { ...sub, count: 1 }));
    expect(store().subagentActivities["delegate-action"]).toMatchObject(
      terminal,
    );
  });

  it("settles a hard-crash partial Sub-agent bubble on recovery and terminal replay", () => {
    const { calls } = installMockFetch([]);
    seed({ activeConversationId: "c1" });
    const sub = {
      parentActionId: "delegate-crash",
      runId: "run-crash",
      role: "visual_development_agent",
    };

    ingest(
      ev(1, "subagent.message_delta", {
        ...sub,
        messageId: "message-before-crash",
        deltaIndex: 0,
        delta: "崩溃前的部分输出",
      }),
      ev(2, "subagent.message_delta", {
        ...sub,
        messageId: "message-after-recovery",
        deltaIndex: 0,
        delta: "恢复后的输出",
      }),
    );

    let activity = store().subagentActivities["delegate-crash"];
    expect(activity.messages["run-crash:message-before-crash"]).toMatchObject({
      completed: true,
      finishReason: "superseded_after_recovery",
    });
    expect(
      activity.messages["run-crash:message-after-recovery"].completed,
    ).toBe(false);

    ingest(
      ev(3, "subagent.failed", {
        ...sub,
        status: "FAILED",
        summaryText: "恢复后已安全收口。",
      }),
    );
    activity = store().subagentActivities["delegate-crash"];
    expect(activity.messages["run-crash:message-after-recovery"]).toMatchObject(
      { completed: true, finishReason: "terminal:failed" },
    );
    expect(activity).toMatchObject({ completed: true, terminalKind: "FAILED" });
    expect(calls).toHaveLength(0);
  });

  it("retries the final durable message pull after a transient failure without another event", async () => {
    const result = msg({
      messageId: "result-2",
      messageSeq: 2,
      content: [
        { type: "text", text: '[RUNTIME_ACTION_RESULT]\n\n{"ok":true}' },
      ],
      source: "runtime_action_result",
      metadata: { actionId: "action-1", tool: "read_file" },
    });
    let attempts = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        attempts += 1;
        if (attempts === 1) {
          return {
            ok: false,
            status: 503,
            statusText: "Unavailable",
            json: async () => ({ code: "TEMPORARY", retryable: true }),
          } as Response;
        }
        return {
          ok: true,
          status: 200,
          statusText: "OK",
          json: async () => ({ items: [result] }),
        } as Response;
      }),
    );
    seed({
      activeConversationId: "c1",
      messages: [
        msg({ messageId: "user-1", messageSeq: 1, source: "initial_goal" }),
      ],
    });

    ingest(
      ev(1, "agent.tool_completed", {
        actionId: "action-1",
        remainingActionIds: [],
      }),
    );

    await waitFor(() => expect(store().messages).toContainEqual(result));
    expect(attempts).toBe(2);
    expect(store().lastEventSeq).toBe(1);
  });

  it("replaces a terminal delegate bubble when Creator creates a new run for the same action", () => {
    seed();
    ingest(
      ev(1, "subagent.started", {
        parentActionId: "delegate-action",
        runId: "run-old",
        role: "r2v_generation_director",
      }),
      ev(2, "subagent.failed", {
        parentActionId: "delegate-action",
        runId: "run-old",
        role: "r2v_generation_director",
        marker: "FAILED",
        summaryText: "旧任务失败",
      }),
      ev(3, "subagent.accepted", {
        parentActionId: "delegate-action",
        runId: "run-new",
        role: "r2v_generation_director",
        delegationText: "使用当前配置重新完成后期制作",
      }),
    );

    expect(store().subagentActivities["delegate-action"]).toMatchObject({
      runId: "run-new",
      completed: false,
      delegationText: "使用当前配置重新完成后期制作",
      messages: {},
      tools: {},
    });
  });
});
