import { act, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useCreatorSessionStore } from "@/store/creatorSessionStore";
import { installMockFetch } from "@/test/mockFetch";

describe("bounded frontend caches", () => {
  beforeEach(() => useCreatorSessionStore.getState().reset());
  it("deduplicates durable events by seq and never treats streaming state as completion", () => {
    useCreatorSessionStore.setState({
      projectId: "p1",
      lastEventSeq: 3,
      events: [],
    });
    const event = {
      eventId: "e4",
      seq: 4,
      type: "subagent.waiting_runtime",
      projectId: "p1",
      creatorSessionId: "s1",
      at: "now",
      data: {},
    };
    useCreatorSessionStore.getState().ingestEvent(event);
    useCreatorSessionStore.getState().ingestEvent(event);
    expect(useCreatorSessionStore.getState().events).toHaveLength(1);
    expect(useCreatorSessionStore.getState().lastEventSeq).toBe(4);
  });

  it("projects a recovered Creator Session as running when creator.woken arrives", () => {
    useCreatorSessionStore.setState({
      projectId: "p1",
      lastEventSeq: 9,
      session: {
        id: "s1",
        projectId: "p1",
        status: "ERROR",
        lastMessageSeq: 1,
        lastConsumedMessageSeq: 0,
        lastEventSeq: 9,
      },
    });

    act(() =>
      useCreatorSessionStore.getState().ingestEvent({
        eventId: "wake-10",
        seq: 10,
        type: "creator.woken",
        projectId: "p1",
        creatorSessionId: "s1",
        at: "now",
        data: { trigger: "user_message" },
      }),
    );

    expect(useCreatorSessionStore.getState().session?.status).toBe("RUNNING");
  });

  it("streams task telemetry into the active Sub-agent tool card", () => {
    useCreatorSessionStore.setState({ projectId: "p1", lastEventSeq: 0 });
    act(() =>
      useCreatorSessionStore.getState().ingestEvents([
        {
          eventId: "tool-start",
          seq: 1,
          type: "subagent.tool_started",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: {
            parentActionId: "delegate-1",
            runId: "run-1",
            role: "visual_development_agent",
            toolCallId: "tool-1",
            tool: "generate_video",
            state: "started",
          },
        },
        {
          eventId: "task-progress",
          seq: 2,
          type: "task.progress_updated",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: {
            taskId: "task-1",
            specialistRunId: "run-1",
            status: "RUNNING",
            progress: 0.4,
          },
        },
      ]),
    );

    expect(
      useCreatorSessionStore.getState().subagentActivities["delegate-1"].tools[
        "run-1:tool-1"
      ],
    ).toMatchObject({
      taskId: "task-1",
      outputEvents: [
        { seq: 2, type: "task.progress_updated", data: { progress: 0.4 } },
      ],
    });
  });

  it("tracks Sub-agent tool progress and canonical arguments", () => {
    useCreatorSessionStore.setState({ projectId: "p1", lastEventSeq: 0 });
    act(() =>
      useCreatorSessionStore.getState().ingestEvents([
        {
          eventId: "delegate-start",
          seq: 1,
          type: "agent.tool_started",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: {
            actionId: "delegate-1",
            tool: "delegate_to_agent",
            role: "visual_development_agent",
          },
        },
        {
          eventId: "tool-progress",
          seq: 2,
          type: "subagent.tool_progress",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: {
            parentActionId: "delegate-1",
            runId: "run-1",
            role: "visual_development_agent",
            toolCallId: "tool-1",
            tool: "read_project_file",
            receivedBytes: 2048,
            providerChunkCount: 12,
            complete: false,
          },
        },
      ]),
    );

    let tool =
      useCreatorSessionStore.getState().subagentActivities["delegate-1"].tools[
        "run-1:tool-1"
      ];
    expect(tool).toMatchObject({
      status: "started",
      receivedBytes: 2048,
      providerChunkCount: 12,
      argumentStreamComplete: false,
    });
    expect(tool.arguments).toBeUndefined();

    act(() =>
      useCreatorSessionStore.getState().ingestEvents([
        {
          eventId: "tool-started",
          seq: 3,
          type: "subagent.tool_started",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: {
            parentActionId: "delegate-1",
            runId: "run-1",
            role: "visual_development_agent",
            messageId: "message-1",
            toolCallId: "tool-1",
            tool: "read_project_file",
            arguments: { path: "story/outline.md" },
            state: "started",
          },
        },
      ]),
    );

    tool =
      useCreatorSessionStore.getState().subagentActivities["delegate-1"].tools[
        "run-1:tool-1"
      ];
    expect(tool.arguments).toEqual({ path: "story/outline.md" });
    expect(tool.firstEventSeq).toBe(2);
  });

  it("projects aggregated tool progress without retaining raw fragments", () => {
    useCreatorSessionStore.setState({ projectId: "p1", lastEventSeq: 0 });
    act(() =>
      useCreatorSessionStore.getState().ingestEvents([
        {
          eventId: "main-tool-progress-1",
          seq: 1,
          type: "agent.tool_progress",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: {
            messageId: "assistant-progress",
            toolCallId: "call-jq",
            tool: "jq_project",
            receivedBytes: 24_576,
            providerChunkCount: 2_021,
            complete: false,
          },
        },
      ]),
    );

    expect(
      useCreatorSessionStore.getState().streamingAssistantMessages[
        "assistant-progress"
      ].toolCall,
    ).toEqual({
      id: "call-jq",
      name: "jq_project",
      arguments: undefined,
      receivedBytes: 24_576,
      providerChunkCount: 2_021,
      argumentStreamComplete: false,
    });
  });

  it("bootstraps canonical DTOs and replays the durable named SSE log after refresh", async () => {
    installMockFetch([
      {
        match: "/conversations/c1/messages",
        response: {
          json: {
            items: [
              {
                messageId: "m1",
                messageSeq: 1,
                role: "assistant",
                content: [{ type: "text", text: "已开始" }],
                source: "creator",
                metadata: {},
                createdAt: "now",
              },
            ],
          },
        },
      },
      {
        match: "/conversations",
        response: {
          json: {
            items: [
              {
                conversationId: "c1",
                title: "默认对话",
                isDefault: true,
                createdAt: "now",
              },
            ],
          },
        },
      },
      {
        match: "/session",
        response: {
          json: {
            session: {
              id: "s1",
              projectId: "p1",
              status: "RUNNING",
              lastMessageSeq: 1,
              lastConsumedMessageSeq: 1,
              lastEventSeq: 7,
            },
            agentStatusBar: {
              progress: {
                phase: "timeline_edit",
                label: "执行中",
                sourceEventSeq: 7,
                updatedAt: "now",
              },
              badges: [],
            },
          },
        },
      },
    ]);
    await useCreatorSessionStore.getState().bootstrap("p1");
    expect(useCreatorSessionStore.getState().activeConversationId).toBe("c1");
    expect(useCreatorSessionStore.getState().messages[0].messageSeq).toBe(1);
    const sources = (
      globalThis as unknown as {
        __testEventSources: Array<{
          url: string;
          emit: (type: string, value: unknown) => void;
        }>;
      }
    ).__testEventSources;
    expect(sources[0].url).toContain("events?after=0");
    act(() =>
      sources[0].emit("session.status_changed", {
        eventId: "e8",
        seq: 8,
        type: "session.status_changed",
        projectId: "p1",
        creatorSessionId: "s1",
        at: "now",
        data: { status: "WAITING_RUNTIME" },
      }),
    );
    await waitFor(() =>
      expect(useCreatorSessionStore.getState().session?.status).toBe(
        "WAITING_RUNTIME",
      ),
    );
    expect(useCreatorSessionStore.getState().lastEventSeq).toBe(8);
    act(() =>
      sources[0].emit("subagent.message_delta", {
        eventId: "e9",
        seq: 9,
        type: "subagent.message_delta",
        projectId: "p1",
        creatorSessionId: "s1",
        at: "now",
        data: {
          parentActionId: "delegate-1",
          runId: "run-1",
          role: "visual_development_agent",
          messageId: "sub-message-1",
          deltaIndex: 0,
          delta: "实时输出",
        },
      }),
    );
    await waitFor(() =>
      expect(
        useCreatorSessionStore.getState().subagentActivities["delegate-1"]
          .messages["run-1:sub-message-1"].deltas[0],
      ).toBe("实时输出"),
    );
    expect(useCreatorSessionStore.getState().lastEventSeq).toBe(9);
  });

  it("resumes a same-project remount from its durable cursor without clearing visible messages", async () => {
    installMockFetch([
      {
        match: "/conversations/c1/messages",
        response: { json: { items: [] } },
      },
      {
        match: "/conversations",
        response: {
          json: {
            items: [
              {
                conversationId: "c1",
                title: "默认对话",
                isDefault: true,
                createdAt: "now",
              },
            ],
          },
        },
      },
      {
        match: "/session",
        response: {
          json: {
            session: {
              id: "s1",
              projectId: "p1",
              status: "RUNNING",
              lastMessageSeq: 1,
              lastConsumedMessageSeq: 1,
              lastEventSeq: 7,
            },
            agentStatusBar: {
              progress: {
                phase: "timeline_edit",
                label: "执行中",
                sourceEventSeq: 7,
                updatedAt: "now",
              },
              badges: [],
            },
          },
        },
      },
    ]);
    const visibleMessage = {
      messageId: "m1",
      messageSeq: 1,
      role: "assistant" as const,
      content: [{ type: "text" as const, text: "保持可见" }],
      source: "creator_agent",
      metadata: {},
      createdAt: "now",
    };
    useCreatorSessionStore.setState({
      projectId: "p1",
      session: {
        id: "s1",
        projectId: "p1",
        status: "RUNNING",
        lastMessageSeq: 1,
        lastConsumedMessageSeq: 1,
        lastEventSeq: 7,
      },
      activeConversationId: "c1",
      messages: [visibleMessage],
      events: [
        {
          eventId: "e7",
          seq: 7,
          type: "task.progress_updated",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: {},
        },
      ],
      lastEventSeq: 7,
    });

    await useCreatorSessionStore.getState().bootstrap("p1");

    expect(useCreatorSessionStore.getState().messages).toContainEqual(
      visibleMessage,
    );
    expect(useCreatorSessionStore.getState().events).toHaveLength(1);
    expect(useCreatorSessionStore.getState().lastEventSeq).toBe(7);
    const sources = (
      globalThis as unknown as { __testEventSources: Array<{ url: string }> }
    ).__testEventSources;
    expect(sources[0].url).toContain("events?after=7");
  });

  it("folds a large durable SSE replay into one bounded store update", async () => {
    installMockFetch([
      {
        match: "/conversations/c1/messages",
        response: { json: { items: [] } },
      },
      {
        match: "/conversations",
        response: {
          json: {
            items: [
              {
                conversationId: "c1",
                title: "默认对话",
                isDefault: true,
                createdAt: "now",
              },
            ],
          },
        },
      },
      {
        match: "/session",
        response: {
          json: {
            session: {
              id: "s1",
              projectId: "p1",
              status: "RUNNING",
              lastMessageSeq: 0,
              lastConsumedMessageSeq: 0,
              lastEventSeq: 307,
            },
            agentStatusBar: {
              progress: {
                phase: "timeline_edit",
                label: "执行中",
                sourceEventSeq: 307,
                updatedAt: "now",
              },
              badges: [],
            },
          },
        },
      },
    ]);
    await useCreatorSessionStore.getState().bootstrap("p1");
    const sources = (
      globalThis as unknown as {
        __testEventSources: Array<{
          emit: (type: string, value: unknown) => void;
        }>;
      }
    ).__testEventSources;
    let notifications = 0;
    const unsubscribe = useCreatorSessionStore.subscribe(() => {
      notifications += 1;
    });
    act(() => {
      for (let seq = 8; seq <= 307; seq += 1) {
        sources[0].emit("task.progress_updated", {
          eventId: `e${seq}`,
          seq,
          type: "task.progress_updated",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: { taskId: "t1", progress: seq / 307 },
        });
      }
    });
    await waitFor(() =>
      expect(useCreatorSessionStore.getState().lastEventSeq).toBe(307),
    );
    expect(useCreatorSessionStore.getState().events).toHaveLength(300);
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
    useCreatorSessionStore.setState({
      projectId: "p1",
      lastEventSeq: 0,
      agentStatusBar: { progress, badges: [] },
    });
    useCreatorSessionStore.getState().ingestEvent({
      eventId: "e1",
      seq: 1,
      type: "task_progress.updated",
      projectId: "p1",
      creatorSessionId: "s1",
      at: "now",
      data: { taskId: "t1", progress: 0.5 },
    });
    expect(useCreatorSessionStore.getState().agentStatusBar?.progress).toEqual(
      progress,
    );
  });

  it("pulls and merges a completed assistant from the real SSE payload without a page refresh", async () => {
    const assistant = {
      messageId: "assistant-2",
      messageSeq: 2,
      role: "assistant" as const,
      content: [{ type: "text" as const, text: "已完成读取。" }],
      source: "creator_agent",
      metadata: {},
      createdAt: "now",
    };
    const { calls } = installMockFetch([
      {
        match: "/conversations/c1/messages?after=1&limit=500",
        response: { json: { items: [assistant] } },
      },
    ]);
    useCreatorSessionStore.setState({
      projectId: "p1",
      activeConversationId: "c1",
      messages: [
        {
          messageId: "user-1",
          messageSeq: 1,
          role: "user",
          content: [{ type: "text", text: "读取计划" }],
          source: "initial_goal",
          metadata: {},
          createdAt: "now",
        },
      ],
      lastEventSeq: 0,
    });

    act(() =>
      useCreatorSessionStore.getState().ingestEvents([
        {
          eventId: "event-completed",
          seq: 1,
          type: "message.completed",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: { messageId: "assistant-2", openActionIds: [] },
        },
        {
          eventId: "event-tool",
          seq: 2,
          type: "agent.tool_completed",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: { actionId: "action-1", remainingActionIds: [] },
        },
      ]),
    );

    await waitFor(() =>
      expect(useCreatorSessionStore.getState().messages).toContainEqual(
        assistant,
      ),
    );
    expect(
      calls.filter((call) => call.url.includes("/conversations/c1/messages")),
    ).toHaveLength(1);
  });

  it("refreshes durable assistant and tool messages from file-native Runtime events", async () => {
    const assistant = {
      messageId: "assistant-file-2",
      messageSeq: 2,
      role: "assistant" as const,
      content: [{ type: "text" as const, text: "准备读取 Project。" }],
      source: "file_agent_runtime",
      metadata: { runId: "run-file-1" },
      createdAt: "now",
    };
    const tool = {
      messageId: "tool-file-3",
      messageSeq: 3,
      role: "tool" as const,
      content: [{ type: "text" as const, text: "读取完成" }],
      source: "file_agent_runtime",
      metadata: {
        runId: "run-file-1",
        toolCallId: "call-file-1",
        toolName: "read_project",
      },
      createdAt: "now",
    };
    const { calls } = installMockFetch([
      {
        match: "/conversations/c1/messages?after=1&limit=500",
        response: { json: { items: [assistant, tool] } },
      },
    ]);
    useCreatorSessionStore.setState({
      projectId: "p1",
      activeConversationId: "c1",
      messages: [
        {
          messageId: "user-file-1",
          messageSeq: 1,
          role: "user",
          content: [{ type: "text", text: "读取 Project" }],
          source: "agent_dock",
          metadata: {},
          createdAt: "now",
        },
      ],
      lastEventSeq: 0,
    });

    act(() =>
      useCreatorSessionStore.getState().ingestEvents([
        {
          eventId: "assistant-file-event",
          seq: 1,
          type: "agent.assistant_message",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: {
            runId: "run-file-1",
            messageId: assistant.messageId,
            messageSeq: 2,
          },
        },
        {
          eventId: "tool-file-event",
          seq: 2,
          type: "agent.tool.completed",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: {
            runId: "run-file-1",
            toolCallId: "call-file-1",
            toolName: "read_project",
            messageId: tool.messageId,
            messageSeq: 3,
          },
        },
      ]),
    );

    await waitFor(() =>
      expect(useCreatorSessionStore.getState().messages).toEqual([
        expect.objectContaining({ messageId: "user-file-1" }),
        assistant,
        tool,
      ]),
    );
    expect(
      calls.filter((call) => call.url.includes("/conversations/c1/messages")),
    ).toHaveLength(1);
  });

  it("merges Creator deltas by messageId and deltaIndex without polling messages per token", () => {
    const { calls } = installMockFetch([]);
    useCreatorSessionStore.setState({
      projectId: "p1",
      activeConversationId: "c1",
      lastEventSeq: 0,
    });

    act(() =>
      useCreatorSessionStore.getState().ingestEvents([
        {
          eventId: "delta-1",
          seq: 1,
          type: "agent.message_delta",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: { messageId: "assistant-stream", deltaIndex: 1, delta: "世界" },
        },
        {
          eventId: "delta-0",
          seq: 2,
          type: "agent.message_delta",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: {
            messageId: "assistant-stream",
            deltaIndex: 0,
            delta: "你好，",
          },
        },
        {
          eventId: "delta-1-duplicate",
          seq: 3,
          type: "agent.message_delta",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: {
            messageId: "assistant-stream",
            deltaIndex: 1,
            delta: "不应重复",
          },
        },
        {
          eventId: "thinking-2",
          seq: 4,
          type: "agent.message_delta",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: {
            messageId: "assistant-stream",
            deltaIndex: 2,
            delta: "真实模型思考",
            streamKind: "thinking",
          },
        },
      ]),
    );

    const streaming =
      useCreatorSessionStore.getState().streamingAssistantMessages[
        "assistant-stream"
      ];
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
    const durable = {
      messageId: "assistant-stream",
      messageSeq: 2,
      role: "assistant" as const,
      content: [{ type: "text" as const, text: "## 最终结果\n\n已完成。" }],
      source: "creator_agent",
      metadata: {},
      createdAt: "now",
    };
    const { calls } = installMockFetch([
      {
        match: "/conversations/c1/messages?after=1&limit=500",
        response: { json: { items: [durable] } },
      },
    ]);
    useCreatorSessionStore.setState({
      projectId: "p1",
      activeConversationId: "c1",
      lastEventSeq: 0,
      messages: [
        {
          messageId: "user-1",
          messageSeq: 1,
          role: "user",
          content: [{ type: "text", text: "开始" }],
          source: "initial_goal",
          metadata: {},
          createdAt: "now",
        },
      ],
    });

    act(() =>
      useCreatorSessionStore.getState().ingestEvent({
        eventId: "delta-0",
        seq: 1,
        type: "agent.message_delta",
        projectId: "p1",
        creatorSessionId: "s1",
        at: "now",
        data: {
          messageId: "assistant-stream",
          deltaIndex: 0,
          delta: "## 最终",
        },
      }),
    );
    expect(
      useCreatorSessionStore.getState().streamingAssistantMessages[
        "assistant-stream"
      ],
    ).toBeDefined();
    expect(calls).toHaveLength(0);

    act(() =>
      useCreatorSessionStore.getState().ingestEvent({
        eventId: "completed",
        seq: 2,
        type: "message.completed",
        projectId: "p1",
        creatorSessionId: "s1",
        at: "now",
        data: { messageId: "assistant-stream", openActionIds: [] },
      }),
    );
    expect(
      useCreatorSessionStore.getState().streamingAssistantMessages[
        "assistant-stream"
      ],
    ).toBeDefined();

    await waitFor(() =>
      expect(useCreatorSessionStore.getState().messages).toContainEqual(
        durable,
      ),
    );
    expect(
      useCreatorSessionStore.getState().streamingAssistantMessages[
        "assistant-stream"
      ],
    ).toBeUndefined();
    expect(calls).toHaveLength(1);
  });

  it("drops abandoned partial assistants on rejection, error and crash-recovery terminal events", () => {
    const { calls } = installMockFetch([]);
    useCreatorSessionStore.setState({
      projectId: "p1",
      activeConversationId: "c1",
      lastEventSeq: 0,
    });
    const delta = (messageId: string, seq: number) => ({
      eventId: `delta-${messageId}`,
      seq,
      type: "agent.message_delta",
      projectId: "p1",
      creatorSessionId: "s1",
      at: "now",
      data: { messageId, deltaIndex: 0, delta: "不完整内容" },
    });

    act(() =>
      useCreatorSessionStore.getState().ingestEvents([
        delta("rejected-message", 1),
        {
          eventId: "rejected",
          seq: 2,
          type: "assistant.output_rejected",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: { assistantMessageId: "rejected-message" },
        },
        delta("errored-message", 3),
        {
          eventId: "errored",
          seq: 4,
          type: "session.error",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: { assistantMessageId: "errored-message" },
        },
        delta("recovered-message", 5),
        {
          eventId: "recovered",
          seq: 6,
          type: "session.status_changed",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: {
            status: "RUNNING",
            recoveredIncompleteAssistant: true,
            assistantMessageId: "recovered-message",
          },
        },
      ]),
    );

    expect(
      useCreatorSessionStore.getState().streamingAssistantMessages,
    ).toEqual({});
    expect(calls).toHaveLength(0);
  });

  it("drops abandoned partial assistants when their Agent run fails or is cancelled", () => {
    const { calls } = installMockFetch([]);
    useCreatorSessionStore.setState({
      projectId: "p1",
      activeConversationId: "c1",
      lastEventSeq: 0,
    });

    act(() =>
      useCreatorSessionStore.getState().ingestEvents([
        {
          eventId: "failed-delta",
          seq: 1,
          type: "agent.message_delta",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: {
            runId: "run-failed",
            messageId: "assistant-failed",
            deltaIndex: 0,
            delta: "停在半截",
          },
        },
        {
          eventId: "failed-run",
          seq: 2,
          type: "agent.run.failed",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: {
            runId: "run-failed",
            error: {
              code: "STREAM_PERSISTENCE_FAILED",
              message: "lock timeout",
            },
          },
        },
        {
          eventId: "cancelled-delta",
          seq: 3,
          type: "agent.message_delta",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: {
            runId: "run-cancelled",
            messageId: "assistant-cancelled",
            deltaIndex: 0,
            delta: "也未完成",
          },
        },
        {
          eventId: "cancelled-run",
          seq: 4,
          type: "agent.run.cancelled",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: { runId: "run-cancelled" },
        },
      ]),
    );

    expect(
      useCreatorSessionStore.getState().streamingAssistantMessages,
    ).toEqual({});
    expect(calls).toHaveLength(0);
  });

  it("tracks rate-limit retry notices until the throttled run fails", () => {
    installMockFetch([]);
    useCreatorSessionStore.setState({
      projectId: "p1",
      activeConversationId: "c1",
      lastEventSeq: 0,
      session: {
        id: "s1",
        projectId: "p1",
        status: "RUNNING",
        lastMessageSeq: 1,
        lastConsumedMessageSeq: 1,
        lastEventSeq: 0,
      },
    });

    act(() =>
      useCreatorSessionStore.getState().ingestEvents([
        {
          eventId: "throttle-retry-1",
          seq: 1,
          type: "agent.model.rate_limit_retry",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: {
            runId: "run-throttled",
            attempt: 1,
            maxAttempts: 5,
            delaySeconds: 2,
          },
        },
      ]),
    );

    expect(useCreatorSessionStore.getState().rateLimitRetry).toEqual({
      attempt: 1,
      maxAttempts: 5,
      runId: "run-throttled",
    });

    act(() =>
      useCreatorSessionStore.getState().ingestEvents([
        {
          eventId: "throttled-failed",
          seq: 2,
          type: "agent.run.failed",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: {
            runId: "run-throttled",
            error: {
              code: "MODEL_RATE_LIMITED",
              message: "模型遭遇限流，已重试 5 次仍无法访问",
              retryable: true,
              details: { retryCount: 5 },
            },
          },
        },
      ]),
    );

    const state = useCreatorSessionStore.getState();
    expect(state.rateLimitRetry).toBeNull();
    expect(state.session?.error).toEqual({
      code: "MODEL_RATE_LIMITED",
      message: "模型遭遇限流，已重试 5 次仍无法访问",
      retryable: true,
      details: { retryCount: 5 },
    });
  });

  it("does not resurrect a failed draft while replaying a completed retry", () => {
    const durableRetry = {
      messageId: "assistant-retry",
      messageSeq: 2,
      role: "assistant" as const,
      content: [{ type: "text" as const, text: "完整重试结果" }],
      source: "creator_agent",
      metadata: {},
      createdAt: "later",
    };
    const { calls } = installMockFetch([]);
    useCreatorSessionStore.setState({
      projectId: "p1",
      activeConversationId: "c1",
      lastEventSeq: 0,
      messages: [
        {
          messageId: "user-1",
          messageSeq: 1,
          role: "user",
          content: [{ type: "text", text: "开始" }],
          source: "initial_goal",
          metadata: {},
          createdAt: "now",
        },
        durableRetry,
      ],
    });

    act(() =>
      useCreatorSessionStore.getState().ingestEvents([
        {
          eventId: "old-delta",
          seq: 1,
          type: "agent.message_delta",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: {
            runId: "run-old",
            messageId: "assistant-old",
            deltaIndex: 0,
            delta: "不完整结果",
          },
        },
        {
          eventId: "old-failed",
          seq: 2,
          type: "agent.run.failed",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: { runId: "run-old" },
        },
        {
          eventId: "retry-delta",
          seq: 3,
          type: "agent.message_delta",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "later",
          data: {
            runId: "run-retry",
            messageId: "assistant-retry",
            deltaIndex: 0,
            delta: "完整重试结果",
          },
        },
      ]),
    );

    expect(useCreatorSessionStore.getState().messages).toContainEqual(
      durableRetry,
    );
    expect(
      useCreatorSessionStore.getState().streamingAssistantMessages,
    ).toEqual({});
    expect(calls).toHaveLength(0);
  });

  it("aggregates replayable Sub-agent messages and nested tools under the parent delegate action", () => {
    const { calls } = installMockFetch([]);
    useCreatorSessionStore.setState({
      projectId: "p1",
      activeConversationId: "c1",
      lastEventSeq: 0,
    });

    act(() =>
      useCreatorSessionStore.getState().ingestEvents([
        {
          eventId: "delegate-started",
          seq: 1,
          type: "agent.tool_started",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: {
            actionId: "delegate-action",
            tool: "delegate_to_agent",
            role: "visual_development_agent",
            roleDisplayName: "故事规划",
            delegationText: "请完善开场冲突。",
            targetRefs: ["timeline:main"],
          },
        },
        {
          eventId: "delegate-accepted",
          seq: 2,
          type: "agent.tool_completed",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: {
            actionId: "delegate-action",
            tool: "delegate_to_agent",
            status: "succeeded",
          },
        },
        {
          eventId: "sub-accepted",
          seq: 3,
          type: "subagent.accepted",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: {
            parentActionId: "delegate-action",
            runId: "run-1",
            role: "visual_development_agent",
            roleDisplayName: "故事规划",
            delegationText: "请完善开场冲突。",
            targetRefs: ["timeline:main"],
          },
        },
        {
          eventId: "sub-delta-1",
          seq: 4,
          type: "subagent.message_delta",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: {
            parentActionId: "delegate-action",
            runId: "run-1",
            role: "visual_development_agent",
            messageId: "sub-message-1",
            deltaIndex: 1,
            delta: "处理中",
          },
        },
        {
          eventId: "sub-delta-0",
          seq: 5,
          type: "subagent.message_delta",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: {
            parentActionId: "delegate-action",
            runId: "run-1",
            role: "visual_development_agent",
            messageId: "sub-message-1",
            deltaIndex: 0,
            delta: "[SUCCESS]\n",
          },
        },
        {
          eventId: "sub-delta-duplicate",
          seq: 6,
          type: "subagent.message_delta",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: {
            parentActionId: "delegate-action",
            runId: "run-1",
            role: "visual_development_agent",
            messageId: "sub-message-1",
            deltaIndex: 1,
            delta: "不应重复",
          },
        },
        {
          eventId: "sub-tool-started",
          seq: 7,
          type: "subagent.tool_started",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: {
            parentActionId: "delegate-action",
            runId: "run-1",
            role: "visual_development_agent",
            toolCallId: "nested-tool-1",
            tool: "read_project_file",
            arguments: { path: "story/outline.md" },
            state: "started",
          },
        },
        {
          eventId: "sub-tool-completed",
          seq: 8,
          type: "subagent.tool_completed",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: {
            parentActionId: "delegate-action",
            runId: "run-1",
            role: "visual_development_agent",
            toolCallId: "nested-tool-1",
            tool: "read_project_file",
            result: { summary: "读取完成" },
            state: "succeeded",
          },
        },
        {
          eventId: "sub-message-completed",
          seq: 9,
          type: "subagent.message_completed",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: {
            parentActionId: "delegate-action",
            runId: "run-1",
            role: "visual_development_agent",
            messageId: "sub-message-1",
            text: "[SUCCESS]\n## 已完成\n\n第一幕冲突已完善。",
            finishReason: "stop",
          },
        },
      ]),
    );

    const activity =
      useCreatorSessionStore.getState().subagentActivities["delegate-action"];
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
    act(() =>
      useCreatorSessionStore.getState().ingestEvent({
        eventId: "sub-terminal",
        seq: 10,
        type: "subagent.completed",
        projectId: "p1",
        creatorSessionId: "s1",
        at: "now",
        data: {
          parentActionId: "delegate-action",
          runId: "run-1",
          role: "visual_development_agent",
          marker: "SUCCESS",
          status: "SUCCEEDED",
          summaryText: "第一幕冲突已完善。",
        },
      }),
    );
    expect(
      useCreatorSessionStore.getState().subagentActivities["delegate-action"],
    ).toMatchObject({
      completed: true,
      terminalKind: "SUCCESS",
      summaryText: "第一幕冲突已完善。",
      terminalEventSeq: 10,
    });
    act(() =>
      useCreatorSessionStore.getState().ingestEvent({
        eventId: "sub-continuation-completed",
        seq: 11,
        type: "subagent.continuation_completed",
        projectId: "p1",
        creatorSessionId: "s1",
        at: "now",
        data: {
          parentActionId: "delegate-action",
          runId: "run-1",
          role: "visual_development_agent",
          count: 1,
        },
      }),
    );
    expect(
      useCreatorSessionStore.getState().subagentActivities["delegate-action"],
    ).toMatchObject({
      completed: true,
      terminalKind: "SUCCESS",
      summaryText: "第一幕冲突已完善。",
      terminalEventSeq: 10,
    });
    expect(
      calls.filter((call) => call.url.includes("/conversations/c1/messages")),
    ).toHaveLength(1);
  });

  it("settles a delegate bubble when the standard tool completion fails before a run exists", () => {
    useCreatorSessionStore.setState({ projectId: "p1", lastEventSeq: 0 });
    act(() =>
      useCreatorSessionStore.getState().ingestEvents([
        {
          eventId: "delegate-started",
          seq: 1,
          type: "agent.tool_started",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: {
            actionId: "delegate-failed",
            tool: "delegate_to_agent",
            role: "ai_editing_director",
            roleDisplayName: "AI 剪辑导演",
            delegationText: "剪辑主时间轴",
            targetRefs: ["timeline:main"],
          },
        },
        {
          eventId: "delegate-failed",
          seq: 2,
          type: "agent.tool_completed",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: {
            actionId: "delegate-failed",
            tool: "delegate_to_agent",
            failed: true,
            errorType: "ProjectionInputError",
          },
        },
      ]),
    );

    expect(
      useCreatorSessionStore.getState().subagentActivities["delegate-failed"],
    ).toMatchObject({
      completed: true,
      terminalKind: "FAILED",
      summaryText: "ProjectionInputError",
      terminalEventSeq: 2,
    });
  });

  it("settles a hard-crash partial Sub-agent bubble on recovery and terminal replay", () => {
    const { calls } = installMockFetch([]);
    useCreatorSessionStore.setState({
      projectId: "p1",
      activeConversationId: "c1",
      lastEventSeq: 0,
    });

    act(() =>
      useCreatorSessionStore.getState().ingestEvents([
        {
          eventId: "old-partial",
          seq: 1,
          type: "subagent.message_delta",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: {
            parentActionId: "delegate-crash",
            runId: "run-crash",
            role: "visual_development_agent",
            messageId: "message-before-crash",
            deltaIndex: 0,
            delta: "崩溃前的部分输出",
          },
        },
        {
          eventId: "recovered-stream",
          seq: 2,
          type: "subagent.message_delta",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: {
            parentActionId: "delegate-crash",
            runId: "run-crash",
            role: "visual_development_agent",
            messageId: "message-after-recovery",
            deltaIndex: 0,
            delta: "恢复后的输出",
          },
        },
      ]),
    );

    let activity =
      useCreatorSessionStore.getState().subagentActivities["delegate-crash"];
    expect(activity.messages["run-crash:message-before-crash"]).toMatchObject({
      completed: true,
      finishReason: "superseded_after_recovery",
    });
    expect(
      activity.messages["run-crash:message-after-recovery"].completed,
    ).toBe(false);

    act(() =>
      useCreatorSessionStore.getState().ingestEvent({
        eventId: "recovered-terminal",
        seq: 3,
        type: "subagent.failed",
        projectId: "p1",
        creatorSessionId: "s1",
        at: "now",
        data: {
          parentActionId: "delegate-crash",
          runId: "run-crash",
          role: "visual_development_agent",
          status: "FAILED",
          summaryText: "恢复后已安全收口。",
        },
      }),
    );
    activity =
      useCreatorSessionStore.getState().subagentActivities["delegate-crash"];
    expect(activity.messages["run-crash:message-after-recovery"]).toMatchObject(
      {
        completed: true,
        finishReason: "terminal:failed",
      },
    );
    expect(activity).toMatchObject({ completed: true, terminalKind: "FAILED" });
    expect(calls).toHaveLength(0);
  });

  it("coalesces message.appended and message.completed into one earliest-cursor pull", async () => {
    const { calls } = installMockFetch([
      {
        match: "/conversations/c1/messages?after=1&limit=500",
        response: { json: { items: [] } },
      },
    ]);
    useCreatorSessionStore.setState({
      projectId: "p1",
      activeConversationId: "c1",
      messages: [
        {
          messageId: "user-1",
          messageSeq: 1,
          role: "user",
          content: [{ type: "text", text: "开始" }],
          source: "initial_goal",
          metadata: {},
          createdAt: "now",
        },
      ],
      lastEventSeq: 0,
    });
    act(() =>
      useCreatorSessionStore.getState().ingestEvents([
        {
          eventId: "event-appended",
          seq: 1,
          type: "message.appended",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: { messageId: "user-2", messageSeq: 2, source: "agent_dock" },
        },
        {
          eventId: "event-completed",
          seq: 2,
          type: "message.completed",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: { messageId: "assistant-3", openActionIds: [] },
        },
      ]),
    );
    await waitFor(() =>
      expect(
        calls.filter((call) => call.url.includes("/conversations/c1/messages")),
      ).toHaveLength(1),
    );
    expect(calls[0].url).toContain("after=1&limit=500");
  });

  it("pulls the Runtime action result when tool_completed arrives after the assistant pull", async () => {
    const assistant = {
      messageId: "assistant-2",
      messageSeq: 2,
      role: "assistant" as const,
      content: [{ type: "text" as const, text: "开始读取" }],
      source: "creator_agent",
      metadata: {
        actionId: "action-1",
        parsedAction: { action: "tool_call", tool: "read_file", arguments: {} },
      },
      createdAt: "now",
    };
    const result = {
      messageId: "result-3",
      messageSeq: 3,
      role: "user" as const,
      content: [
        {
          type: "text" as const,
          text: '[RUNTIME_ACTION_RESULT]\n\n{"ok":true}',
        },
      ],
      source: "runtime_action_result",
      metadata: { actionId: "action-1", tool: "read_file" },
      createdAt: "now",
    };
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        calls.push(url);
        const items = calls.length === 1 ? [assistant] : [result];
        return {
          ok: true,
          status: 200,
          statusText: "OK",
          json: async () => ({ items }),
        } as Response;
      }),
    );
    useCreatorSessionStore.setState({
      projectId: "p1",
      activeConversationId: "c1",
      messages: [
        {
          messageId: "user-1",
          messageSeq: 1,
          role: "user",
          content: [{ type: "text", text: "读取" }],
          source: "initial_goal",
          metadata: {},
          createdAt: "now",
        },
      ],
      lastEventSeq: 0,
    });

    act(() =>
      useCreatorSessionStore.getState().ingestEvent({
        eventId: "assistant-completed",
        seq: 1,
        type: "message.completed",
        projectId: "p1",
        creatorSessionId: "s1",
        at: "now",
        data: { messageId: "assistant-2", openActionIds: ["action-1"] },
      }),
    );
    await waitFor(() =>
      expect(useCreatorSessionStore.getState().messages).toContainEqual(
        assistant,
      ),
    );

    act(() =>
      useCreatorSessionStore.getState().ingestEvent({
        eventId: "tool-completed",
        seq: 2,
        type: "agent.tool_completed",
        projectId: "p1",
        creatorSessionId: "s1",
        at: "now",
        data: { actionId: "action-1", remainingActionIds: [] },
      }),
    );
    await waitFor(() =>
      expect(useCreatorSessionStore.getState().messages).toContainEqual(result),
    );
    expect(calls).toHaveLength(2);
    expect(calls[0]).toContain("after=1&limit=500");
    expect(calls[1]).toContain("after=2&limit=500");
  });

  it("retries the final durable message pull after a transient failure without another event", async () => {
    const result = {
      messageId: "result-2",
      messageSeq: 2,
      role: "user" as const,
      content: [
        {
          type: "text" as const,
          text: '[RUNTIME_ACTION_RESULT]\n\n{"ok":true}',
        },
      ],
      source: "runtime_action_result",
      metadata: { actionId: "action-1", tool: "read_file" },
      createdAt: "now",
    };
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
            json: async () => ({
              code: "TEMPORARY",
              message: "瞬时失败",
              retryable: true,
            }),
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
    useCreatorSessionStore.setState({
      projectId: "p1",
      activeConversationId: "c1",
      lastEventSeq: 0,
      messages: [
        {
          messageId: "user-1",
          messageSeq: 1,
          role: "user",
          content: [{ type: "text", text: "读取" }],
          source: "initial_goal",
          metadata: {},
          createdAt: "now",
        },
      ],
    });

    act(() =>
      useCreatorSessionStore.getState().ingestEvent({
        eventId: "tool-completed",
        seq: 1,
        type: "agent.tool_completed",
        projectId: "p1",
        creatorSessionId: "s1",
        at: "now",
        data: { actionId: "action-1", remainingActionIds: [] },
      }),
    );

    await waitFor(() =>
      expect(useCreatorSessionStore.getState().messages).toContainEqual(result),
    );
    expect(attempts).toBe(2);
    expect(useCreatorSessionStore.getState().lastEventSeq).toBe(1);
  });

  it("replaces a terminal delegate bubble when Creator creates a new run for the same action", () => {
    useCreatorSessionStore.setState({ projectId: "p1", lastEventSeq: 0 });
    act(() =>
      useCreatorSessionStore.getState().ingestEvents([
        {
          eventId: "old-start",
          seq: 1,
          type: "subagent.started",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: {
            parentActionId: "delegate-action",
            runId: "run-old",
            role: "r2v_generation_director",
          },
        },
        {
          eventId: "old-terminal",
          seq: 2,
          type: "subagent.failed",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: {
            parentActionId: "delegate-action",
            runId: "run-old",
            role: "r2v_generation_director",
            marker: "FAILED",
            summaryText: "旧任务失败",
          },
        },
        {
          eventId: "new-accepted",
          seq: 3,
          type: "subagent.accepted",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: {
            parentActionId: "delegate-action",
            runId: "run-new",
            role: "r2v_generation_director",
            delegationText: "使用当前配置重新完成后期制作",
          },
        },
      ]),
    );

    expect(
      useCreatorSessionStore.getState().subagentActivities["delegate-action"],
    ).toMatchObject({
      runId: "run-new",
      completed: false,
      delegationText: "使用当前配置重新完成后期制作",
      messages: {},
      tools: {},
    });
  });
});
