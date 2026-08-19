import { describe, expect, it } from "vitest";
import type { CreatorEvent, CreatorMessage } from "@/contracts/creator";
import {
  actionAwareConversationContent,
  actionEnvelopeFromStreamText,
  conversationContent,
  creatorActionEnvelope,
  deduplicateReviewFeedbackMessages,
  isReviewFeedbackMessage,
  isUserAuthorityMessage,
  shouldRenderConversationMessage,
  toolCallPresentations,
} from "@/lib/creatorMessagePresentation";

function creatorMessage(overrides: Partial<CreatorMessage>): CreatorMessage {
  return {
    messageId: "message-1",
    messageSeq: 1,
    role: "user",
    content: [{ type: "text", text: "消息" }],
    source: "user",
    metadata: {},
    createdAt: "now",
    ...overrides,
  };
}

function creatorEvent(overrides: Partial<CreatorEvent>): CreatorEvent {
  return {
    eventId: "event-1",
    seq: 1,
    type: "agent.tool_started",
    projectId: "p1",
    creatorSessionId: "s1",
    at: "now",
    data: {},
    ...overrides,
  };
}

describe("Creator conversation presentation", () => {
  it("keeps actual user authority sources and rejects Runtime control rows as user bubbles", () => {
    for (const source of [
      "initial_goal",
      "agent_dock",
      "frontend_action",
      "frontend_manual_edit",
      "user",
      "user_continuation",
      "review_rejection_feedback",
    ]) {
      const message = creatorMessage({ source });
      expect(isUserAuthorityMessage(message)).toBe(true);
      expect(shouldRenderConversationMessage(message)).toBe(true);
    }
    for (const source of [
      "runtime_action_result",
      "runtime_work_update",
      "specialist_result",
      "completion_context",
      "completion_rejected",
    ]) {
      const message = creatorMessage({ source });
      expect(isUserAuthorityMessage(message)).toBe(false);
      expect(shouldRenderConversationMessage(message)).toBe(false);
    }
  });

  it("renders one review feedback message per durable decision", () => {
    const first = creatorMessage({
      messageId: "feedback-first",
      messageSeq: 4,
      source: "review_rejection_feedback",
      metadata: {
        decisionId: "decision-1",
        rejectionFeedback: {
          action: "UNDO_AND_REGENERATE",
          feedbackNote: "人物状态不对，请保持身份一致",
        },
      },
    });
    const replay = creatorMessage({
      ...first,
      messageId: "feedback-replay",
      messageSeq: 8,
    });
    const unrelated = creatorMessage({
      messageId: "ordinary",
      messageSeq: 9,
      source: "user",
    });

    expect(isReviewFeedbackMessage(first)).toBe(true);
    expect(shouldRenderConversationMessage(first)).toBe(true);
    expect(
      deduplicateReviewFeedbackMessages([replay, unrelated, first]),
    ).toEqual([unrelated, first]);
  });

  it("never renders reserved Creator/Runtime control markers as user input", () => {
    const rejected = creatorMessage({
      source: "runtime_action_result",
      content: [
        {
          type: "text",
          text: "[CREATOR_ACTION_REJECTED]\n\n必须先持久化 plan",
        },
      ],
    });
    const malformedLegacyRuntimeRow = creatorMessage({
      source: "user",
      content: [
        { type: "text", text: "[RUNTIME_EVENT: CREATOR_WAITING]\n\ninternal" },
      ],
    });
    const blockedRuntimeRow = creatorMessage({
      source: "user",
      content: [{ type: "text", text: "[RUNTIME_ACTION_BLOCKED]\n\ninternal" }],
    });
    const bareHardStopRow = creatorMessage({
      source: "user",
      content: [{ type: "text", text: "USER_HARD_STOP" }],
    });

    expect(shouldRenderConversationMessage(rejected)).toBe(false);
    expect(shouldRenderConversationMessage(malformedLegacyRuntimeRow)).toBe(
      false,
    );
    expect(shouldRenderConversationMessage(blockedRuntimeRow)).toBe(false);
    expect(shouldRenderConversationMessage(bareHardStopRow)).toBe(false);
  });

  it("keeps legacy file Runtime tool rows out of the conversation", () => {
    expect(
      shouldRenderConversationMessage(
        creatorMessage({
          role: "tool",
          source: "file_agent_runtime",
          content: [{ type: "text", text: "读取完成" }],
          metadata: { toolCallId: "call-read", toolName: "read_project" },
        }),
      ),
    ).toBe(false);
    expect(
      shouldRenderConversationMessage(
        creatorMessage({
          role: "tool",
          source: "another_runtime",
        }),
      ),
    ).toBe(true);
  });

  it("hides only the exact legacy file Runtime tool placeholder and preserves narration", () => {
    const placeholder = creatorMessage({
      role: "assistant",
      source: "file_agent_runtime",
      content: [
        { type: "text", text: "准备调用工具：read_project、write_project" },
      ],
      metadata: {
        toolCalls: [
          { id: "call-read", name: "read_project" },
          { id: "call-write", name: "write_project" },
        ],
      },
    });
    const narration = creatorMessage({
      ...placeholder,
      content: [{ type: "text", text: "我先读取项目，再写入修改。" }],
    });

    expect(conversationContent(placeholder)).toEqual([]);
    expect(actionAwareConversationContent(placeholder)).toEqual([]);
    expect(conversationContent(narration)).toEqual(narration.content);
    expect(actionAwareConversationContent(narration)).toEqual(
      narration.content,
    );
  });

  it("preserves the complete raw assistant action envelope", () => {
    const message = creatorMessage({
      role: "assistant",
      source: "creator_agent",
      content: [
        {
          type: "text",
          text: '我先读取当前计划。\n```json\n{"action":"tool_call","tool":"read_file"}\n```',
        },
      ],
      metadata: {
        parsedAction: { action: "tool_call", tool: "read_file", arguments: {} },
      },
    });
    expect(conversationContent(message)).toEqual(message.content);
  });

  it("preserves protocol-rejected assistant output without content rewriting", () => {
    const message = creatorMessage({
      role: "assistant",
      source: undefined,
      content: [
        {
          type: "text",
          text: '我会先委派任务。\n```json\n{"action":"tool_call","tool":"delegate"}\n```',
        },
      ],
      metadata: {
        protocolError: { code: "INVALID_ACTION", message: "必须先 plan" },
      },
    });
    expect(conversationContent(message)).toEqual(message.content);
  });

  it("keeps every in-flight assistant stream byte unchanged", () => {
    const onlyRuntime = creatorMessage({
      role: "assistant",
      source: "creator_agent_stream",
      content: [
        {
          type: "text",
          text: "[RUNTIME_EVENT: CREATOR_WAITING]\n\nCreator 已显式等待异步 Run",
        },
      ],
    });
    const afterNarration = creatorMessage({
      role: "assistant",
      source: "creator_agent_stream",
      content: [
        {
          type: "text",
          text: '我会等待当前任务完成。\n[RUNTIME_ACTION_RESULT]\n\n{"ok":true}',
        },
      ],
    });
    const blockedAfterNarration = creatorMessage({
      role: "assistant",
      source: "creator_agent_stream",
      content: [
        {
          type: "text",
          text: "我会先处理可恢复问题。\n[RUNTIME_ACTION_BLOCKED]\n\ninternal",
        },
      ],
    });
    const bareHardStop = creatorMessage({
      role: "assistant",
      source: "creator_agent_stream",
      content: [{ type: "text", text: "USER_HARD_STOP" }],
    });

    expect(conversationContent(onlyRuntime)).toEqual(onlyRuntime.content);
    expect(conversationContent(afterNarration)).toEqual(afterNarration.content);
    expect(conversationContent(blockedAfterNarration)).toEqual(
      blockedAfterNarration.content,
    );
    expect(conversationContent(bareHardStop)).toEqual(bareHardStop.content);

    const echoedGovernance = creatorMessage({
      role: "assistant",
      source: "creator_agent_stream",
      content: [
        {
          type: "text",
          text: "正在重新确认已有任务。\n这里连续出现了 `[CREATOR_OUTPUT_REJECTED]`，说明内部协议被拒绝。",
        },
      ],
    });
    expect(conversationContent(echoedGovernance)).toEqual(
      echoedGovernance.content,
    );
  });

  it("recognizes a tool action before its SSE JSON is complete and moves syntax into the action card", () => {
    const message = creatorMessage({
      role: "assistant",
      source: "creator_agent_stream",
      content: [
        {
          type: "text",
          text: '我先读取计划。\n```json\n{"action":"tool_call","tool":"read_project_file","arguments":{"path":"plan',
        },
      ],
      metadata: { streaming: true },
    });

    const envelope = creatorActionEnvelope(message);
    expect(envelope).toMatchObject({
      action: "tool_call",
      tool: "read_project_file",
      complete: false,
      narration: "我先读取计划。",
    });
    expect(envelope?.rawPayload).toContain('"path":"plan');
    expect(actionAwareConversationContent(message, envelope)).toEqual([
      { type: "text", text: "我先读取计划。" },
    ]);
  });

  it("dynamically parses complete JSON before the closing fence arrives", () => {
    const envelope = actionEnvelopeFromStreamText(
      '```json\n{"action":"yield_until_runtime_event","arguments":{"waitForRunIds":["run-1"],"reason":"等待剪辑"}}',
    );
    expect(envelope).toMatchObject({
      action: "yield_until_runtime_event",
      complete: false,
      payload: {
        action: "yield_until_runtime_event",
        arguments: { waitForRunIds: ["run-1"], reason: "等待剪辑" },
      },
    });
  });

  it("recognizes a streamed Sub-agent function call and parses its parameters when complete", () => {
    const partial = actionEnvelopeFromStreamText(
      '<function=read_project_file><parameter=arguments>{"path":"story/',
    );
    expect(partial).toMatchObject({
      action: "tool_call",
      tool: "read_project_file",
      complete: false,
    });

    const complete = actionEnvelopeFromStreamText(
      '<function=read_project_file><parameter=arguments>{"path":"story/outline.md"}</parameter></function></tool_call>',
    );
    expect(complete).toMatchObject({
      action: "tool_call",
      tool: "read_project_file",
      complete: true,
      payload: {
        action: "tool_call",
        tool: "read_project_file",
        arguments: { path: "story/outline.md" },
      },
    });
  });

  it("renders a final action message as conversation prose while retaining its raw envelope", () => {
    const message = creatorMessage({
      role: "assistant",
      content: [
        {
          type: "text",
          text: '处理结束。\n```json\n{"action":"final","message":"全部完成。","awaitUserInput":false}\n```',
        },
      ],
      metadata: {
        parsedAction: {
          action: "final",
          message: "全部完成。",
          awaitUserInput: false,
        },
      },
    });
    const envelope = creatorActionEnvelope(message);
    expect(actionAwareConversationContent(message, envelope)).toEqual([
      { type: "text", text: "处理结束。\n\n全部完成。" },
    ]);
    expect(envelope?.rawPayload).toContain('"action":"final"');
  });

  it("preserves ordinary fenced Markdown and the final action envelope", () => {
    const message = creatorMessage({
      role: "assistant",
      source: "creator_agent",
      content: [
        {
          type: "text",
          text: '示例：\n```json\n{"value":1}\n```\n\n以上是结果。\n```json\n{"action":"final","summary":"done"}\n```',
        },
      ],
      metadata: { parsedAction: { action: "final", summary: "done" } },
    });
    expect(conversationContent(message)).toEqual(message.content);
  });

  it("merges assistant arguments, Runtime result metadata/text and tool events by actionId", () => {
    const messages = [
      creatorMessage({
        messageId: "assistant-1",
        messageSeq: 2,
        role: "assistant",
        source: "creator_agent",
        metadata: {
          actionId: "action-1",
          parsedAction: {
            action: "tool_call",
            tool: "read_project_file",
            arguments: { path: "plan.json" },
          },
        },
      }),
      creatorMessage({
        messageId: "result-1",
        messageSeq: 3,
        source: "runtime_action_result",
        content: [
          {
            type: "text",
            text: '[RUNTIME_ACTION_RESULT]\n\n{"head":"h2","ok":true}',
          },
        ],
        metadata: {
          actionId: "action-1",
          tool: "read_project_file",
          resultKind: "workspace_read",
        },
      }),
    ];
    const events = [
      creatorEvent({
        data: { actionId: "action-1", tool: "read_project_file" },
      }),
      creatorEvent({
        eventId: "event-2",
        seq: 2,
        type: "agent.tool_completed",
        data: { actionId: "action-1" },
      }),
    ];
    expect(toolCallPresentations(messages, events)).toEqual([
      {
        actionId: "action-1",
        anchorMessageId: "assistant-1",
        order: 2,
        status: "succeeded",
        tool: "read_project_file",
        arguments: { path: "plan.json" },
        result: { head: "h2", ok: true },
        error: undefined,
      },
    ]);
  });

  it("uses failed Runtime result text as the origin tool card error", () => {
    const messages = [
      creatorMessage({
        messageId: "assistant-1",
        role: "assistant",
        metadata: {
          actionId: "action-1",
          parsedAction: {
            action: "tool_call",
            tool: "write_file",
            arguments: { path: "x" },
          },
        },
      }),
      creatorMessage({
        messageId: "result-1",
        messageSeq: 2,
        source: "runtime_action_result",
        content: [{ type: "text", text: "[RUNTIME_ACTION_ERROR]\n\n权限不足" }],
        metadata: { actionId: "action-1", tool: "write_file", failed: true },
      }),
    ];
    expect(toolCallPresentations(messages, [])).toMatchObject([
      {
        status: "failed",
        tool: "write_file",
        error: "权限不足",
      },
    ]);
  });

  it("marks a standard failed tool completion as failed before the durable result arrives", () => {
    expect(
      toolCallPresentations(
        [],
        [
          creatorEvent({
            eventId: "event-started",
            seq: 1,
            type: "agent.tool_started",
            data: { actionId: "delegate-1", tool: "delegate_to_agent" },
          }),
          creatorEvent({
            eventId: "event-failed",
            seq: 2,
            type: "agent.tool_completed",
            data: {
              actionId: "delegate-1",
              tool: "delegate_to_agent",
              failed: true,
              errorType: "ProjectionInputError",
            },
          }),
        ],
      ),
    ).toMatchObject([
      {
        actionId: "delegate-1",
        status: "failed",
        tool: "delegate_to_agent",
        error: "ProjectionInputError",
      },
    ]);
  });

  it("projects file-native dotted tool lifecycle events", () => {
    expect(
      toolCallPresentations(
        [],
        [
          creatorEvent({
            eventId: "file-tool-started",
            seq: 1,
            type: "agent.tool.started",
            data: { toolCallId: "call-file-1", toolName: "read_project" },
          }),
          creatorEvent({
            eventId: "file-tool-failed",
            seq: 2,
            type: "agent.tool.failed",
            data: {
              toolCallId: "call-file-1",
              toolName: "read_project",
              messageId: "tool-message-file-1",
            },
          }),
        ],
      ),
    ).toMatchObject([
      {
        actionId: "call-file-1",
        anchorMessageId: "tool-message-file-1",
        status: "failed",
        tool: "read_project",
      },
    ]);
  });

  it("rebuilds legacy file Runtime cards from plural tool calls and tool result rows", () => {
    const messages = [
      creatorMessage({
        messageId: "assistant-file",
        messageSeq: 2,
        role: "assistant",
        source: "file_agent_runtime",
        content: [
          { type: "text", text: "准备调用工具：read_project、write_project" },
        ],
        metadata: {
          toolCalls: [
            {
              id: "call-read",
              name: "read_project",
              arguments: { include: ["story"] },
            },
            { id: "call-write", name: "write_project" },
          ],
        },
      }),
      creatorMessage({
        messageId: "tool-read",
        messageSeq: 3,
        role: "tool",
        source: "file_agent_runtime",
        content: [{ type: "text", text: '{"ok":true,"generation":2}' }],
        metadata: { toolCallId: "call-read", toolName: "read_project" },
      }),
      creatorMessage({
        messageId: "tool-write",
        messageSeq: 4,
        role: "tool",
        source: "file_agent_runtime",
        content: [{ type: "text", text: "已写入 Project（generation 3）" }],
        metadata: { toolCallId: "call-write", toolName: "write_project" },
      }),
    ];
    const presentations = toolCallPresentations(messages, [
      creatorEvent({
        eventId: "read-completed",
        seq: 1,
        type: "agent.tool.completed",
        data: {
          toolCallId: "call-read",
          toolName: "read_project",
          messageId: "tool-read",
        },
      }),
      creatorEvent({
        eventId: "write-completed",
        seq: 2,
        type: "agent.tool.completed",
        data: {
          toolCallId: "call-write",
          toolName: "write_project",
          messageId: "tool-write",
        },
      }),
    ]);

    expect(presentations).toMatchObject([
      {
        actionId: "call-read",
        anchorMessageId: "assistant-file",
        status: "succeeded",
        tool: "read_project",
        arguments: { include: ["story"] },
        result: { ok: true, generation: 2 },
      },
      {
        actionId: "call-write",
        anchorMessageId: "assistant-file",
        status: "succeeded",
        tool: "write_project",
        result: "已写入 Project（generation 3）",
      },
    ]);
  });

  it("projects native AgentScope control tool metadata without parsing assistant text", () => {
    const message = creatorMessage({
      role: "assistant",
      source: "creator_agent",
      content: [],
      metadata: {
        actionId: "call-final",
        toolCall: {
          id: "call-final",
          name: "final",
          arguments: { message: "原生工具回复", awaitUserInput: false },
        },
      },
    });
    const envelope = creatorActionEnvelope(message);
    expect(envelope).toMatchObject({
      action: "final",
      syntax: "native",
      payload: {
        action: "final",
        message: "原生工具回复",
        awaitUserInput: false,
      },
    });
    expect(actionAwareConversationContent(message, envelope)).toEqual([
      { type: "text", text: "原生工具回复" },
    ]);
  });

  it("projects canonical tool arguments and removes rejected calls", () => {
    const started = [
      creatorEvent({
        eventId: "started",
        seq: 1,
        type: "agent.tool_started",
        data: {
          messageId: "assistant-native",
          toolCallId: "call-read",
          tool: "read_file",
          arguments: { file_path: "story/outline.md" },
        },
      }),
    ];
    expect(toolCallPresentations([], started)).toMatchObject([
      {
        actionId: "call-read",
        anchorMessageId: "assistant-native",
        status: "started",
        tool: "read_file",
        arguments: { file_path: "story/outline.md" },
      },
    ]);
    expect(
      toolCallPresentations(
        [],
        [
          ...started,
          creatorEvent({
            eventId: "rejected",
            seq: 3,
            type: "assistant.output_rejected",
            data: { rejectedAssistantMessageId: "assistant-native" },
          }),
        ],
      ),
    ).toEqual([]);
  });

  it("shows aggregated argument progress and final parsed arguments", () => {
    const events = [
      creatorEvent({
        eventId: "progress",
        seq: 1,
        type: "agent.tool_progress",
        data: {
          messageId: "assistant-progress",
          toolCallId: "call-jq",
          tool: "jq_project",
          receivedBytes: 25_257,
          providerChunkCount: 2_140,
          complete: true,
        },
      }),
      creatorEvent({
        eventId: "started",
        seq: 2,
        type: "agent.tool_started",
        data: {
          messageId: "assistant-progress",
          toolCallId: "call-jq",
          tool: "jq_project",
          arguments: { projectId: "project-1", program: "." },
        },
      }),
    ];

    expect(toolCallPresentations([], events)).toMatchObject([
      {
        actionId: "call-jq",
        anchorMessageId: "assistant-progress",
        status: "started",
        tool: "jq_project",
        arguments: { projectId: "project-1", program: "." },
        receivedBytes: 25_257,
        providerChunkCount: 2_140,
        argumentStreamComplete: true,
      },
    ]);
  });
});
