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
import { taskErrorMessage, taskProgressPercent } from "@/lib/taskPresentation";
import i18n from "@/i18n";
import {
  creatorToolLabel,
  getToolRunningLabel,
} from "@/lib/creatorPresentation";

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

function text(value: string): CreatorMessage["content"] {
  return [{ type: "text", text: value }];
}

const tev = (seq: number, type: string, data: Record<string, unknown>) =>
  creatorEvent({ eventId: `event-${seq}`, seq, type, data });

const actionMeta = (tool: string, args: Record<string, unknown>) => ({
  actionId: "action-1",
  parsedAction: { action: "tool_call", tool, arguments: args },
});

describe("Creator conversation presentation", () => {
  it("keeps actual user authority sources and rejects Runtime control rows as user bubbles", () => {
    const userSources = [
      "initial_goal",
      "agent_dock",
      "frontend_action",
      "frontend_manual_edit",
      "user",
      "user_continuation",
      "review_rejection_feedback",
    ];
    const controlSources = [
      "runtime_action_result",
      "runtime_work_update",
      "specialist_result",
      "completion_context",
      "completion_rejected",
    ];
    for (const source of [...userSources, ...controlSources]) {
      const message = creatorMessage({ source });
      const isUser = userSources.includes(source);
      expect(isUserAuthorityMessage(message)).toBe(isUser);
      expect(shouldRenderConversationMessage(message)).toBe(isUser);
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
    const unrelated = creatorMessage({ messageId: "ordinary", messageSeq: 9 });

    expect(isReviewFeedbackMessage(first)).toBe(true);
    expect(shouldRenderConversationMessage(first)).toBe(true);
    expect(
      deduplicateReviewFeedbackMessages([replay, unrelated, first]),
    ).toEqual([unrelated, first]);
  });

  it("never renders reserved control markers or legacy file Runtime tool rows", () => {
    const hidden: Array<Partial<CreatorMessage>> = [
      ...(
        [
          ["runtime_action_result", "[CREATOR_ACTION_REJECTED]\n\n必须持久化"],
          ["user", "[RUNTIME_EVENT: CREATOR_WAITING]\n\ninternal"],
          ["user", "[RUNTIME_ACTION_BLOCKED]\n\ninternal"],
          ["user", "USER_HARD_STOP"],
        ] as const
      ).map(([source, body]) => ({ source, content: text(body) })),
      {
        role: "tool" as const,
        source: "file_agent_runtime",
        content: text("读取完成"),
        metadata: { toolCallId: "call-read", toolName: "read_project" },
      },
    ];
    for (const overrides of hidden) {
      expect(shouldRenderConversationMessage(creatorMessage(overrides))).toBe(
        false,
      );
    }
    expect(
      shouldRenderConversationMessage(
        creatorMessage({ role: "tool", source: "another_runtime" }),
      ),
    ).toBe(true);
  });

  it.each([
    "[RUNTIME_EVENT: CREATOR_WAITING]\n\nCreator 已显式等待异步 Run",
    '我会等待当前任务完成。\n[RUNTIME_ACTION_RESULT]\n\n{"ok":true}',
    "我会先处理可恢复问题。\n[RUNTIME_ACTION_BLOCKED]\n\ninternal",
    "USER_HARD_STOP",
    "正在重新确认已有任务。\n这里连续出现了 `[CREATOR_OUTPUT_REJECTED]`，说明内部协议被拒绝。",
  ])("keeps every in-flight assistant stream byte unchanged: %s", (body) => {
    const message = creatorMessage({
      role: "assistant",
      source: "creator_agent_stream",
      content: text(body),
    });
    expect(conversationContent(message)).toEqual(message.content);
  });

  it("recognizes a tool action before its SSE JSON is complete and moves syntax into the action card", () => {
    const message = creatorMessage({
      role: "assistant",
      source: "creator_agent_stream",
      content: text(
        '我先读取计划。\n```json\n{"action":"tool_call","tool":"read_project_file","arguments":{"path":"plan',
      ),
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
    expect(actionAwareConversationContent(message, envelope)).toEqual(
      text("我先读取计划。"),
    );
  });

  it("parses streamed function-call parameters before and after completion", () => {
    expect(
      actionEnvelopeFromStreamText(
        '<function=read_project_file><parameter=arguments>{"path":"story/',
      ),
    ).toMatchObject({
      action: "tool_call",
      tool: "read_project_file",
      complete: false,
    });
    expect(
      actionEnvelopeFromStreamText(
        '<function=read_project_file><parameter=arguments>{"path":"story/outline.md"}</parameter></function></tool_call>',
      ),
    ).toMatchObject({
      action: "tool_call",
      tool: "read_project_file",
      complete: true,
      payload: { arguments: { path: "story/outline.md" } },
    });
  });

  it("merges assistant arguments, Runtime result metadata/text and tool events by actionId", () => {
    const messages = [
      creatorMessage({
        messageId: "assistant-1",
        messageSeq: 2,
        role: "assistant",
        source: "creator_agent",
        metadata: actionMeta("read_project_file", { path: "plan.json" }),
      }),
      creatorMessage({
        messageId: "result-1",
        messageSeq: 3,
        source: "runtime_action_result",
        content: text('[RUNTIME_ACTION_RESULT]\n\n{"head":"h2","ok":true}'),
        metadata: { actionId: "action-1", tool: "read_project_file" },
      }),
    ];
    const events = [
      tev(1, "agent.tool_started", { actionId: "action-1" }),
      tev(2, "agent.tool_completed", { actionId: "action-1" }),
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

  it("surfaces failures from durable result text, event errorType and file-native lifecycle", () => {
    const failed = [
      creatorMessage({
        messageId: "assistant-1",
        role: "assistant",
        metadata: actionMeta("write_file", { path: "x" }),
      }),
      creatorMessage({
        messageId: "result-1",
        messageSeq: 2,
        source: "runtime_action_result",
        content: text("[RUNTIME_ACTION_ERROR]\n\n权限不足"),
        metadata: { actionId: "action-1", tool: "write_file", failed: true },
      }),
    ];
    expect(toolCallPresentations(failed, [])).toMatchObject([
      { status: "failed", tool: "write_file", error: "权限不足" },
    ]);

    const delegate = [
      tev(1, "agent.tool_started", {
        actionId: "d1",
        tool: "delegate_to_agent",
      }),
      tev(2, "agent.tool_completed", {
        actionId: "d1",
        tool: "delegate_to_agent",
        failed: true,
        errorType: "ProjectionInputError",
      }),
    ];
    expect(toolCallPresentations([], delegate)).toMatchObject([
      { actionId: "d1", status: "failed", error: "ProjectionInputError" },
    ]);

    const fileNative = [
      tev(1, "agent.tool.started", {
        toolCallId: "c1",
        toolName: "read_project",
      }),
      tev(2, "agent.tool.failed", {
        toolCallId: "c1",
        toolName: "read_project",
        messageId: "tool-msg-1",
      }),
    ];
    expect(toolCallPresentations([], fileNative)).toMatchObject([
      {
        actionId: "c1",
        anchorMessageId: "tool-msg-1",
        status: "failed",
        tool: "read_project",
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
      payload: { message: "原生工具回复", awaitUserInput: false },
    });
    expect(actionAwareConversationContent(message, envelope)).toEqual(
      text("原生工具回复"),
    );
  });

  it("projects canonical tool arguments, aggregated progress and removes rejected calls", () => {
    const started = [
      tev(1, "agent.tool_progress", {
        messageId: "assistant-native",
        toolCallId: "call-read",
        tool: "read_file",
        receivedBytes: 25_257,
        providerChunkCount: 2_140,
        complete: true,
      }),
      tev(2, "agent.tool_started", {
        messageId: "assistant-native",
        toolCallId: "call-read",
        tool: "read_file",
        arguments: { file_path: "story/outline.md" },
      }),
    ];
    expect(toolCallPresentations([], started)).toMatchObject([
      {
        actionId: "call-read",
        anchorMessageId: "assistant-native",
        status: "started",
        tool: "read_file",
        arguments: { file_path: "story/outline.md" },
        receivedBytes: 25_257,
        providerChunkCount: 2_140,
        argumentStreamComplete: true,
      },
    ]);
    const rejected = [
      ...started,
      tev(3, "assistant.output_rejected", {
        rejectedAssistantMessageId: "assistant-native",
      }),
    ];
    expect(toolCallPresentations([], rejected)).toEqual([]);
  });
});

describe("durable Task presentation", () => {
  it("converts progress into bounded percentages and surfaces task errors", () => {
    expect(taskProgressPercent(0)).toBe(0);
    expect(taskProgressPercent(0.42)).toBe(42);
    expect(taskProgressPercent(1)).toBe(100);
    expect(taskProgressPercent(null)).toBeNull();

    const perItem = {
      kind: "ASSET_INGEST_FAILED",
      items: [{ name: "large.mp4", error: "远程素材下载连接超时" }],
    };
    expect(taskErrorMessage(perItem, "素材处理失败（FAILED）")).toBe(
      "远程素材下载连接超时",
    );
    expect(
      taskErrorMessage({ message: "provider rejected input" }, "任务失败"),
    ).toBe("provider rejected input");
    expect(taskErrorMessage(null, "任务失败")).toBe("任务失败");
  });
});

describe("creatorToolLabel", () => {
  it("labels specialist tools and never falls back to the processing status label", () => {
    for (const [tool, label] of [
      ["tts_generation", "合成语音"],
      ["s2v_generation", "生成口型视频"],
      ["create_character_voice", "创建角色音色"],
      ["read_document", "读取文档"],
      ["query_source_memory", "查询素材记忆"],
      ["design_motion_overlays", "设计动态字幕"],
    ]) {
      expect(creatorToolLabel(tool)).toBe(label);
    }
    expect(getToolRunningLabel("tts_generation")).toBe("语音合成中…");
    expect(getToolRunningLabel("design_motion_overlays")).toBe(
      "动态字幕设计中…",
    );
    // The action title appends 处理中/完成 after the label, so the
    // fallback must stay neutral to avoid "处理中处理中" / "处理中完成".
    const fallback = creatorToolLabel("some_future_tool");
    expect(fallback).not.toBe(i18n.t("presentation.processing"));
    expect(fallback).not.toContain("处理中");
  });
});
