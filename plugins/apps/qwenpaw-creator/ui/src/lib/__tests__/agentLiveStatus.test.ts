import { describe, expect, it } from "vitest";
import type {
  AgentStatusBarView,
  CreatorSessionStatus,
  CreatorSessionView,
  ProjectDocument,
  TaskView,
} from "@/contracts/creator";
import type { SubagentActivity } from "@/store/creatorSessionStore";
import type { ToolCallPresentation } from "@/lib/creatorMessagePresentation";
import {
  deriveAgentLiveStatus,
  type AgentLiveStatusInput,
} from "@/lib/agentLiveStatus";

const project = {
  timelines: {
    items: {
      t1: {
        elements_by_id: {
          e2: { element_id: "e2", label: "在厨房准备早餐的特写镜头" },
        },
      },
    },
  },
  assets: {
    source_versions_by_id: {
      v1: { logical_asset_id: "la1", name: "主角小狐" },
    },
  },
} as unknown as ProjectDocument;

function session(status: CreatorSessionStatus): CreatorSessionView {
  return {
    id: "session-1",
    projectId: "p1",
    status,
    lastMessageSeq: 0,
    lastConsumedMessageSeq: 0,
    lastEventSeq: 0,
  };
}

function statusBar(
  overrides: Partial<AgentStatusBarView["progress"]> = {},
): AgentStatusBarView {
  return {
    progress: {
      phase: "visual_development",
      label: "正在制作",
      sourceEventSeq: 1,
      updatedAt: "now",
      ...overrides,
    },
    badges: [],
  };
}

function subagentActivity(
  tool: string,
  args?: Record<string, unknown>,
): SubagentActivity {
  return {
    parentActionId: "action-1",
    runId: "run-1",
    role: "visual_development_agent",
    targetRefs: [],
    firstEventSeq: 1,
    completed: false,
    messages: {},
    tools: {
      "tc-1": {
        toolCallId: "tc-1",
        runId: "run-1",
        tool,
        firstEventSeq: 2,
        status: "started",
        arguments: args,
        outputEvents: [],
      },
    },
  };
}

const delegateCall: ToolCallPresentation = {
  actionId: "action-1",
  order: 1,
  status: "started",
  tool: "delegate_to_agent",
  arguments: { role: "visual_development_agent" },
};

const task = (
  kind: TaskView["kind"],
  progress: number | null,
  targetRef = "asset:la1",
) =>
  ({
    id: "task-1",
    projectId: "p1",
    kind,
    targetRef,
    status: "RUNNING",
    progress,
    resultRefs: [],
  }) as TaskView;

const live = (overrides: Partial<AgentLiveStatusInput> = {}) =>
  deriveAgentLiveStatus({
    session: session("RUNNING"),
    agentStatusBar: statusBar(),
    stopping: false,
    hasQueuedInput: false,
    isReplaying: false,
    subagentActivities: {},
    toolCalls: [],
    tasks: [],
    project,
    ...overrides,
  });

const withActivity = (
  activity: SubagentActivity,
  extra: Partial<AgentLiveStatusInput> = {},
) => live({ subagentActivities: { "action-1": activity }, ...extra });

describe("deriveAgentLiveStatus", () => {
  it.each([
    ["IDLE", false, "idle", "待命中，可随时输入修改意图。"],
    ["WAITING_USER_INPUT", false, "waiting", "等待补充信息，请继续输入。"],
    ["IDLE", true, "working", "指令已发出，等待响应…"],
  ] as const)(
    "maps session %s (queued=%s) to %s",
    (status, hasQueuedInput, state, label) => {
      const result = live({
        session: session(status),
        agentStatusBar: null,
        hasQueuedInput,
      });
      expect(result.state).toBe(state);
      expect(result.label).toBe(label);
    },
  );

  it("prioritises stopping over any running work", () => {
    const result = live({ stopping: true, toolCalls: [delegateCall] });
    expect(result.state).toBe("stopping");
  });

  it("shows the rate-limit retry notice above any other working label", () => {
    const result = withActivity(
      subagentActivity("image_generation", { targetRef: "element:e2" }),
      { rateLimitRetry: { attempt: 2, maxAttempts: 5 } },
    );
    expect(result.label).toBe("遇到限流，正在重试（2/5）…");
  });

  it.each([
    ["element:e2", "正在生成「在厨房准备早餐的特…」分镜图…"],
    ["asset:la1", "正在生成「主角小狐」画面…"],
  ])("labels image generation for %s", (targetRef, label) => {
    expect(
      withActivity(subagentActivity("image_generation", { targetRef })).label,
    ).toBe(label);
  });

  it("does not show '正在安排' once the delegated subagent has completed (e.g. cancelled)", () => {
    // Incident regression: delegate still "started" but the specialist already
    // terminated — fall back to the backend label.
    const result = withActivity(
      {
        ...subagentActivity("unknown_tool"),
        tools: {},
        completed: true,
        terminalKind: "CANCELLED",
      },
      {
        toolCalls: [delegateCall],
        agentStatusBar: statusBar({ label: "后端进度" }),
      },
    );
    expect(result.label).not.toBe("正在安排「视觉开发」…");
    expect(result.label).toBe("后端进度");
  });

  it("shows a mini progress bar only for quantified task progress", () => {
    const quantified = live({ tasks: [task("asset_ingest", 0.42)] });
    expect(quantified.state).toBe("working");
    expect(quantified.label).toBe("「主角小狐」素材入库中…");
    expect(quantified.progressPercent).toBe(42);
    expect(
      live({ tasks: [task("r2v_generation", null, "element:e2")] })
        .progressPercent,
    ).toBeNull();
    expect(
      live({ agentStatusBar: statusBar({ completed: 3, total: 10 }) })
        .progressPercent,
    ).toBe(30);
  });
});
