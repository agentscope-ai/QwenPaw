import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { AgentEventFeed } from "@/components/agent";
import { useCreatorTaskViewStore } from "@/store/creatorTaskViewStore";
import { useCreatorSessionStore } from "@/store/creatorSessionStore";
import { useAgentDockUiStore } from "@/store/agentDockUiStore";
import { evt, makeRun } from "@/test/agentFixtures";

// The feed reads the "s1" session stream seeded by these tests.
const e = (type: string, seq: number, data: Record<string, unknown>) =>
  evt(type, seq, data, { creatorSessionId: "s1" });

const sub = {
  parentActionId: "a1",
  runId: "r1",
  role: "visual_development_agent",
};

describe("AgentEventFeed", () => {
  beforeEach(() => {
    useCreatorTaskViewStore.setState({ runs: [], tasks: [] });
    useCreatorSessionStore.setState({ events: [], session: null });
    useAgentDockUiStore.getState().reset();
  });
  it("shows multiple independent active Specialist Runs at once", () => {
    useCreatorTaskViewStore.setState({
      runs: [
        makeRun({
          id: "run-r2v",
          role: "r2v_generation_director",
          displayName: "R2V 生成导演",
          status: "WAITING_RUNTIME",
          targetRefs: ["element:r2v-1"],
          taskRefs: ["task-video"],
        }),
        makeRun({
          id: "run-story",
          status: "RUNNING_MODEL",
          targetRefs: ["timeline:main"],
        }),
      ],
    });
    render(<AgentEventFeed />);
    expect(screen.getByText("制作流程")).toBeInTheDocument();
    expect(
      screen.getByText(/R2V 生成导演 · 时间线内容 · 等待制作结果/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/故事规划 · 主时间轴 · 正在构思/),
    ).toBeInTheDocument();
    expect(screen.getByText("后台等待中")).toBeInTheDocument();
  });

  it("leaves conversation-scoped plan and tool events to their AgentDock turn", () => {
    useCreatorSessionStore.setState({
      events: [
        e("agent.plan", 1, {
          summary: "先完成故事规划",
          steps: ["建立 Element", "安排重叠关系"],
          scope: ["timeline:main"],
        }),
        e("agent.tool_started", 2, {
          actionId: "a1",
          tool: "delegate_to_agent",
        }),
        e("subagent.message_delta", 3, {
          ...sub,
          messageId: "m1",
          deltaIndex: 0,
          delta: "实时正文",
        }),
        e("subagent.message_completed", 5, {
          ...sub,
          messageId: "m1",
          text: "[SUCCESS]\n不应出现在全局事件流",
        }),
        e("creator.yielded", 8, {
          summary:
            "[RUNTIME_EVENT: CREATOR_WAITING]\nCreator 已显式等待异步 Run",
        }),
        e("runtime.work_update_appended", 10, { text: "内部 Runtime 更新" }),
      ],
    });
    render(<AgentEventFeed />);
    expect(
      screen.queryByText("执行计划：先完成故事规划"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("delegate_to_agent")).not.toBeInTheDocument();
    expect(screen.queryByText("实时正文")).not.toBeInTheDocument();
    expect(screen.queryByText(/不应出现在全局事件流/)).not.toBeInTheDocument();
    expect(
      screen.queryByText(/RUNTIME_EVENT: CREATOR_WAITING/),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("内部 Runtime 更新")).not.toBeInTheDocument();
    expect(
      document.querySelector("[data-origin-run-block]"),
    ).not.toBeInTheDocument();
  });

  it("keeps resumed role state visible without a snake_case reason, and hides lifecycle rows nested in a delegate tool card", () => {
    useCreatorSessionStore.setState({
      events: [
        e("subagent.resumed", 1, {
          runId: "run-r2v",
          role: "r2v_generation_director",
          roleDisplayName: "R2V 生成导演",
          reason: "authorization_approved",
        }),
        e("subagent.accepted", 2, {
          parentActionId: "delegate-action-1",
          runId: "run-story",
          role: "visual_development_agent",
          roleDisplayName: "故事规划",
        }),
      ],
    });

    render(<AgentEventFeed />);

    expect(screen.getByText("→ R2V 生成导演")).toBeInTheDocument();
    expect(
      screen.queryByText("authorization_approved"),
    ).not.toBeInTheDocument();
    expect(
      document.querySelector('[data-agent-event-card="subagent.resumed"]'),
    ).toBeInTheDocument();
    expect(screen.queryByText("→ 故事规划")).not.toBeInTheDocument();
    expect(
      document.querySelector('[data-agent-event-card="subagent.accepted"]'),
    ).not.toBeInTheDocument();
  });

  it("presents a hard stop once as cancelled without leaking Runtime reason codes", () => {
    useCreatorSessionStore.setState({
      session: {
        id: "s1",
        projectId: "p1",
        status: "CANCELLED",
        lastMessageSeq: 0,
        lastConsumedMessageSeq: 0,
        lastEventSeq: 2,
      },
      events: [
        e("transaction.progress", 1, {
          status: "CANCELLED",
          reason: "USER_HARD_STOP",
        }),
        e("session.status_changed", 2, {
          status: "CANCELLED",
          reason: "USER_HARD_STOP",
        }),
      ],
    });

    render(<AgentEventFeed />);

    expect(screen.getByText("已取消")).toBeInTheDocument();
    expect(screen.queryByText("USER_HARD_STOP")).not.toBeInTheDocument();
    expect(document.querySelectorAll("[data-agent-event-card]")).toHaveLength(
      0,
    );
  });

  it("reports only genuinely failed or blocked Timeline/Element runs", () => {
    useCreatorTaskViewStore.setState({
      runs: [
        makeRun({
          id: "run-failed-timeline",
          role: "ai_editing_director",
          displayName: "AI 剪辑导演",
          status: "FAILED",
          targetRefs: ["timeline:main", "artifact:preview"],
          finalSummaryText: "剪辑失败",
        }),
        makeRun({
          id: "run-blocked-element",
          role: "r2v_generation_director",
          displayName: "R2V 生成导演",
          status: "BLOCKED",
          targetRefs: ["element:r2v-2"],
        }),
        makeRun({
          id: "run-stale-element",
          role: "r2v_generation_director",
          displayName: "R2V 生成导演",
          status: "STALE",
          targetRefs: ["element:r2v-3"],
        }),
        makeRun({
          id: "run-cancelled-element",
          role: "r2v_generation_director",
          displayName: "R2V 生成导演",
          status: "CANCELLED",
          targetRefs: ["element:cancelled"],
        }),
        makeRun({
          id: "run-failed-project",
          status: "FAILED",
          targetRefs: ["project:plan"],
        }),
      ],
    });

    render(<AgentEventFeed />);

    expect(screen.getByText("2 项专业制作失败")).toBeInTheDocument();
    expect(screen.getByText("主时间轴：剪辑失败")).toBeInTheDocument();
    expect(screen.getByText("时间线内容：需要处理")).toBeInTheDocument();
    // Superseded, cancelled and project-level runs never surface as failures.
    expect(
      screen.getByText(/R2V 生成导演 · 时间线内容 · 已取消/),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/artifact:preview：剪辑失败/),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("project:plan：FAILED")).not.toBeInTheDocument();
  });

  it("shows a review-blocked run as waiting instead of failed", () => {
    useCreatorSessionStore.setState({
      session: {
        id: "session-review",
        projectId: "project-review",
        status: "PENDING_REVIEW",
        lastMessageSeq: 1,
        lastConsumedMessageSeq: 1,
        lastEventSeq: 1,
      },
    });
    useCreatorTaskViewStore.setState({
      runs: [
        makeRun({
          id: "run-waiting-review",
          role: "r2v_generation_director",
          displayName: "R2V 生成导演",
          status: "BLOCKED",
          targetRefs: ["element:ep22"],
          finalSummaryText:
            "element:ep22 的分镜图已生成；视频生成尚未开始，等待审阅通过后自动继续。",
        }),
      ],
    });

    render(<AgentEventFeed />);

    expect(screen.getAllByText(/等待审阅/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/专业制作失败/)).not.toBeInTheDocument();
    expect(screen.queryByText("失败")).not.toBeInTheDocument();
  });
});
