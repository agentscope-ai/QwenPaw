import { describe, expect, it } from "vitest";
import type {
  AgentStatusBarView,
  CreatorSessionStatus,
  CreatorSessionView,
  ProjectDocument,
  TaskStatus,
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
          e1: { element_id: "e1", label: "镜头一" },
          e2: { element_id: "e2", label: "在厨房准备早餐的特写镜头" },
        },
      },
    },
  },
  assets: {
    source_versions_by_id: {
      v1: { logical_asset_id: "la1", name: "主角小狐" },
    },
    artifact_versions_by_id: {},
  },
  sources: { sources: { items: {} } },
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
    activity: { runningTaskCount: 0 },
    badges: [],
  };
}

function subagentActivity(
  tool: string,
  args?: Record<string, unknown>,
  targetRefs: string[] = [],
): SubagentActivity {
  return {
    parentActionId: "action-1",
    runId: "run-1",
    role: "visual_development_agent",
    targetRefs,
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

function mainToolCall(
  tool: string,
  args?: Record<string, unknown>,
): ToolCallPresentation {
  return {
    actionId: "action-main",
    order: 1,
    status: "started",
    tool,
    arguments: args,
  };
}

function task(
  kind: TaskView["kind"],
  status: TaskStatus,
  progress: number | null,
  targetRef = "asset:la1",
): TaskView {
  return {
    id: "task-1",
    projectId: "p1",
    transactionId: "tx1",
    specialistRunId: "run1",
    kind,
    targetRef,
    status,
    progress,
    resultRefs: [],
    updatedAt: "2026-01-01T00:00:00Z",
  };
}

function baseInput(
  overrides: Partial<AgentLiveStatusInput> = {},
): AgentLiveStatusInput {
  return {
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
  };
}

describe("deriveAgentLiveStatus", () => {
  it("is idle with a standby label when nothing is running", () => {
    const result = deriveAgentLiveStatus(
      baseInput({ session: session("IDLE"), agentStatusBar: null }),
    );
    expect(result.state).toBe("idle");
    expect(result.label).toBe("待命中，可随时输入修改意图。");
    expect(result.progressPercent).toBeNull();
  });

  it("prioritises stopping over any running work", () => {
    const result = deriveAgentLiveStatus(
      baseInput({
        stopping: true,
        toolCalls: [mainToolCall("jq_project")],
      }),
    );
    expect(result.state).toBe("stopping");
    expect(result.label).toBe("正在停止所有 Agent…");
    expect(result.progressPercent).toBeNull();
  });

  it("shows the rate-limit retry notice above any other working label", () => {
    const result = deriveAgentLiveStatus(
      baseInput({
        rateLimitRetry: { attempt: 2, maxAttempts: 5 },
        subagentActivities: {
          "action-1": subagentActivity("image_generation", {
            targetRef: "element:e1",
          }),
        },
      }),
    );
    expect(result.state).toBe("working");
    expect(result.label).toBe("遇到限流，正在重试（2/5）…");
  });

  it("labels storyboard image generation with the resolved element name", () => {
    const result = deriveAgentLiveStatus(
      baseInput({
        subagentActivities: {
          "action-1": subagentActivity("image_generation", {
            targetRef: "element:e1",
          }),
        },
      }),
    );
    expect(result.state).toBe("working");
    expect(result.label).toBe("正在生成「镜头一」分镜图…");
  });

  it("labels visual asset image generation with the resolved asset name", () => {
    const result = deriveAgentLiveStatus(
      baseInput({
        subagentActivities: {
          "action-1": subagentActivity("image_generation", {
            targetRef: "asset:la1",
          }),
        },
      }),
    );
    expect(result.label).toBe("正在生成「主角小狐」画面…");
  });

  it("falls back to a generic storyboard label when the element is unknown", () => {
    const result = deriveAgentLiveStatus(
      baseInput({
        subagentActivities: {
          "action-1": subagentActivity("image_generation", {
            targetRef: "element:unknown",
          }),
        },
      }),
    );
    expect(result.label).toBe("正在生成分镜图…");
  });

  it("clamps an over-long target name inside the label, keeping the suffix keyword", () => {
    const result = deriveAgentLiveStatus(
      baseInput({
        subagentActivities: {
          "action-1": subagentActivity("image_generation", {
            targetRef: "element:e2",
          }),
        },
      }),
    );
    expect(result.label).toBe("正在生成「在厨房准备早餐的特…」分镜图…");
  });

  it("skips internal project tools and falls back to thinking label", () => {
    const result = deriveAgentLiveStatus(
      baseInput({
        toolCalls: [mainToolCall("jq_project")],
        agentStatusBar: null,
      }),
    );
    expect(result.label).toBe("正在思考…");
  });

  it("expresses an active delegation through the role sub-state", () => {
    const result = deriveAgentLiveStatus(
      baseInput({
        toolCalls: [
          {
            ...mainToolCall("delegate_to_agent", {
              role: "visual_development_agent",
            }),
            actionId: "action-1",
          },
        ],
        subagentActivities: {
          "action-1": {
            ...subagentActivity("unknown_tool"),
            tools: {},
          },
        },
      }),
    );
    expect(result.label).toBe("视觉开发中");
  });

  it("does not show '正在安排' once the delegated subagent has completed (e.g. cancelled)", () => {
    // Reproduces the manual-stop state: the delegate tool call is still
    // marked "started" (no terminal event arrived for it), but the
    // specialist activity has already terminated as CANCELLED. The status
    // bar must not claim "正在安排「视觉开发」…" — that would contradict the
    // activity card's "已取消" state. It should fall through instead.
    const result = deriveAgentLiveStatus(
      baseInput({
        toolCalls: [
          {
            ...mainToolCall("delegate_to_agent", {
              role: "visual_development_agent",
            }),
            actionId: "action-1",
          },
        ],
        subagentActivities: {
          "action-1": {
            ...subagentActivity("unknown_tool"),
            tools: {},
            completed: true,
            terminalKind: "CANCELLED",
          },
        },
        agentStatusBar: statusBar({ label: "后端进度" }),
      }),
    );
    expect(result.label).not.toBe("正在安排「视觉开发」…");
    expect(result.label).not.toBe("正在安排专业制作…");
    expect(result.label).toBe("后端进度");
  });

  it("maps specialist tools to fine-grained sub-states", () => {
    const writing = deriveAgentLiveStatus(
      baseInput({
        subagentActivities: {
          "action-1": {
            ...subagentActivity("commit_source_intelligence"),
            role: "source_intelligence_agent",
          },
        },
      }),
    );
    expect(writing.label).toBe("素材理解写入中…");

    const idleRole = deriveAgentLiveStatus(
      baseInput({
        subagentActivities: {
          "action-1": {
            ...subagentActivity("unknown_tool"),
            role: "source_intelligence_agent",
            tools: {},
          },
        },
      }),
    );
    expect(idleRole.label).toBe("素材理解中");
  });

  it("shows a mini progress bar only for quantified task progress", () => {
    const result = deriveAgentLiveStatus(
      baseInput({ tasks: [task("asset_ingest", "RUNNING", 0.42)] }),
    );
    expect(result.state).toBe("working");
    expect(result.label).toBe("「主角小狐」素材入库中…");
    expect(result.progressPercent).toBe(42);
  });

  it("hides progress when the running task has no measurable value", () => {
    const result = deriveAgentLiveStatus(
      baseInput({
        agentStatusBar: statusBar(),
        tasks: [task("r2v_generation", "RUNNING", null, "element:e1")],
      }),
    );
    expect(result.label).toBe("「镜头一」视频生成中…");
    expect(result.progressPercent).toBeNull();
  });

  it("uses the backend completed/total pair when no task progress exists", () => {
    const result = deriveAgentLiveStatus(
      baseInput({
        agentStatusBar: statusBar({ completed: 3, total: 10 }),
      }),
    );
    expect(result.progressPercent).toBe(30);
  });

  it("turns to waiting when the session asks for more input", () => {
    const result = deriveAgentLiveStatus(
      baseInput({
        session: session("WAITING_USER_INPUT"),
        agentStatusBar: null,
      }),
    );
    expect(result.state).toBe("waiting");
    expect(result.label).toBe("等待补充信息，请继续输入。");
  });

  it("reports a queued instruction before the session starts running", () => {
    const result = deriveAgentLiveStatus(
      baseInput({
        session: session("IDLE"),
        agentStatusBar: null,
        hasQueuedInput: true,
      }),
    );
    expect(result.state).toBe("working");
    expect(result.label).toBe("指令已发出，等待响应…");
  });
});
