import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { AgentEventFeed } from "@/components/agent";
import { useCreatorTaskViewStore } from "@/store/creatorTaskViewStore";
import { useCreatorSessionStore } from "@/store/creatorSessionStore";
import { useAgentDockUiStore } from "@/store/agentDockUiStore";

describe("AgentEventFeed", () => {
  beforeEach(() => {
    useCreatorTaskViewStore.setState({ runs: [], tasks: [] });
    useCreatorSessionStore.setState({ events: [], session: null });
    useAgentDockUiStore.getState().reset();
  });
  it("shows multiple independent active Specialist Runs at once", () => {
    useCreatorTaskViewStore.setState({
      runs: [
        {
          id: "run-r2v",
          role: "r2v_generation_director",
          displayName: "R2V 生成导演",
          status: "WAITING_RUNTIME",
          targetRefs: ["element:r2v-1"],
          taskRefs: ["task-video"],
          metadata: {},
        },
        {
          id: "run-story",
          role: "visual_development_agent",
          displayName: "故事规划",
          status: "RUNNING_MODEL",
          targetRefs: ["timeline:main"],
          taskRefs: [],
          metadata: {},
        },
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
    expect(screen.queryByText("继续轮询")).not.toBeInTheDocument();
    expect(
      screen.queryByText(/可能仍有未完成的视频任务/),
    ).not.toBeInTheDocument();
  });

  it("leaves conversation-scoped plan and tool events to their AgentDock turn", () => {
    useCreatorSessionStore.setState({
      events: [
        {
          eventId: "e1",
          seq: 1,
          type: "agent.plan",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: {
            summary: "先完成故事规划",
            steps: ["建立 Element", "安排重叠关系"],
            scope: ["timeline:main"],
          },
        },
        {
          eventId: "e2",
          seq: 2,
          type: "agent.tool_started",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: { actionId: "a1", tool: "delegate_to_agent" },
        },
        {
          eventId: "e3",
          seq: 3,
          type: "subagent.message_delta",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: {
            parentActionId: "a1",
            runId: "r1",
            role: "visual_development_agent",
            messageId: "m1",
            deltaIndex: 0,
            delta: "实时正文",
          },
        },
        {
          eventId: "e3b",
          seq: 4,
          type: "subagent.tool_delta",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: {
            parentActionId: "a1",
            runId: "r1",
            role: "visual_development_agent",
            toolCallId: "t1",
            tool: "read_file",
            deltaIndex: 0,
            argumentsDelta: '{"path":"story/',
          },
        },
        {
          eventId: "e4",
          seq: 5,
          type: "subagent.message_completed",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: {
            parentActionId: "a1",
            runId: "r1",
            role: "visual_development_agent",
            messageId: "m1",
            text: "[SUCCESS]\n不应出现在全局事件流",
          },
        },
        {
          eventId: "e5",
          seq: 6,
          type: "subagent.tool_started",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: {
            parentActionId: "a1",
            runId: "r1",
            role: "visual_development_agent",
            toolCallId: "t1",
            tool: "read_file",
          },
        },
        {
          eventId: "e6",
          seq: 7,
          type: "subagent.tool_completed",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: {
            parentActionId: "a1",
            runId: "r1",
            role: "visual_development_agent",
            toolCallId: "t1",
            tool: "read_file",
            result: { text: "机器结果" },
          },
        },
        {
          eventId: "e7",
          seq: 8,
          type: "creator.yielded",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: {
            summary:
              "[RUNTIME_EVENT: CREATOR_WAITING]\nCreator 已显式等待异步 Run",
          },
        },
        {
          eventId: "e8",
          seq: 9,
          type: "creator.woken",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: { reason: "authorization_approved" },
        },
        {
          eventId: "e9",
          seq: 10,
          type: "runtime.work_update_appended",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: { text: "内部 Runtime 更新" },
        },
      ],
    });
    render(<AgentEventFeed />);
    expect(
      screen.queryByText("执行计划：先完成故事规划"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("建立 Element")).not.toBeInTheDocument();
    expect(screen.queryByText("delegate_to_agent")).not.toBeInTheDocument();
    expect(screen.queryByText("实时正文")).not.toBeInTheDocument();
    expect(screen.queryByText(/不应出现在全局事件流/)).not.toBeInTheDocument();
    expect(screen.queryByText("read_file")).not.toBeInTheDocument();
    expect(
      screen.queryByText(/RUNTIME_EVENT: CREATOR_WAITING/),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("authorization_approved"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("内部 Runtime 更新")).not.toBeInTheDocument();
    expect(
      document.querySelector("[data-origin-run-block]"),
    ).not.toBeInTheDocument();
  });

  it("keeps resumed role state visible without rendering a technical snake_case reason", () => {
    useCreatorSessionStore.setState({
      events: [
        {
          eventId: "resume-1",
          seq: 1,
          type: "subagent.resumed",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: {
            runId: "run-r2v",
            role: "r2v_generation_director",
            roleDisplayName: "R2V 生成导演",
            reason: "authorization_approved",
          },
        },
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
        {
          eventId: "hard-stop-transaction",
          seq: 1,
          type: "transaction.progress",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: { status: "CANCELLED", reason: "USER_HARD_STOP" },
        },
        {
          eventId: "hard-stop-session",
          seq: 2,
          type: "session.status_changed",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: { status: "CANCELLED", reason: "USER_HARD_STOP" },
        },
      ],
    });

    render(<AgentEventFeed />);

    expect(screen.getByText("已取消")).toBeInTheDocument();
    expect(screen.queryByText("USER_HARD_STOP")).not.toBeInTheDocument();
    expect(document.querySelectorAll("[data-agent-event-card]")).toHaveLength(
      0,
    );
  });

  it("does not duplicate lifecycle rows already nested in a delegate tool card", () => {
    useCreatorSessionStore.setState({
      events: [
        {
          eventId: "accepted-1",
          seq: 1,
          type: "subagent.accepted",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: {
            parentActionId: "delegate-action-1",
            runId: "run-story",
            role: "visual_development_agent",
            roleDisplayName: "故事规划",
          },
        },
      ],
    });

    render(<AgentEventFeed />);

    expect(screen.queryByText("→ 故事规划")).not.toBeInTheDocument();
    expect(
      document.querySelector('[data-agent-event-card="subagent.accepted"]'),
    ).not.toBeInTheDocument();
  });

  it("does not report superseded, cancelled, or project-level runs as failed Timeline targets", () => {
    useCreatorTaskViewStore.setState({
      runs: [
        {
          id: "run-stale-plan",
          role: "visual_development_agent",
          displayName: "故事规划",
          status: "STALE",
          targetRefs: ["project:plan"],
          taskRefs: [],
          metadata: {},
        },
        {
          id: "run-cancelled-element",
          role: "r2v_generation_director",
          displayName: "R2V 生成导演",
          status: "CANCELLED",
          targetRefs: ["element:cancelled"],
          taskRefs: [],
          metadata: {},
        },
        {
          id: "run-failed-project",
          role: "visual_development_agent",
          displayName: "视觉开发",
          status: "FAILED",
          targetRefs: ["project:assets"],
          taskRefs: [],
          metadata: {},
        },
      ],
    });

    render(<AgentEventFeed />);

    expect(
      screen.getByText(/故事规划 · 视频方案 · 已被新版本替换/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/R2V 生成导演 · 时间线内容 · 已取消/),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/个 Timeline\/Element 任务失败/),
    ).not.toBeInTheDocument();
  });

  it("keeps an entirely superseded run history in a neutral terminal state", () => {
    useCreatorTaskViewStore.setState({
      runs: [
        {
          id: "run-stale-plan",
          role: "visual_development_agent",
          displayName: "故事规划",
          status: "STALE",
          targetRefs: ["project:plan"],
          taskRefs: [],
          metadata: {},
        },
      ],
    });

    render(<AgentEventFeed />);

    expect(screen.getByText("已取消")).toBeInTheDocument();
    expect(screen.queryByText("失败")).not.toBeInTheDocument();
    expect(screen.queryByText("执行中")).not.toBeInTheDocument();
  });

  it("reports only genuinely failed or blocked Timeline/Element runs", () => {
    useCreatorTaskViewStore.setState({
      runs: [
        {
          id: "run-failed-timeline",
          role: "ai_editing_director",
          displayName: "AI 剪辑导演",
          status: "FAILED",
          targetRefs: ["timeline:main", "artifact:preview"],
          finalSummaryText: "剪辑失败",
          taskRefs: [],
          metadata: {},
        },
        {
          id: "run-blocked-element",
          role: "r2v_generation_director",
          displayName: "R2V 生成导演",
          status: "BLOCKED",
          targetRefs: ["element:r2v-2"],
          taskRefs: [],
          metadata: {},
        },
        {
          id: "run-stale-element",
          role: "r2v_generation_director",
          displayName: "R2V 生成导演",
          status: "STALE",
          targetRefs: ["element:r2v-3"],
          taskRefs: [],
          metadata: {},
        },
        {
          id: "run-failed-project",
          role: "visual_development_agent",
          displayName: "故事规划",
          status: "FAILED",
          targetRefs: ["project:plan"],
          taskRefs: [],
          metadata: {},
        },
      ],
    });

    render(<AgentEventFeed />);

    expect(screen.getByText("2 项专业制作失败")).toBeInTheDocument();
    expect(screen.getByText("主时间轴：剪辑失败")).toBeInTheDocument();
    expect(screen.getByText("时间线内容：需要处理")).toBeInTheDocument();
    expect(
      screen.queryByText(/artifact:preview：剪辑失败/),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("project:plan：FAILED")).not.toBeInTheDocument();
    expect(screen.queryByText("element:r2v-3：STALE")).not.toBeInTheDocument();
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
        {
          id: "run-waiting-review",
          role: "r2v_generation_director",
          displayName: "R2V 生成导演",
          status: "BLOCKED",
          targetRefs: ["element:ep22"],
          finalSummaryText:
            "element:ep22 的分镜图已生成；视频生成尚未开始，等待审阅通过后自动继续。",
          taskRefs: [],
          metadata: {},
        },
      ],
    });

    render(<AgentEventFeed />);

    expect(screen.getAllByText(/等待审阅/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/专业制作失败/)).not.toBeInTheDocument();
    expect(screen.queryByText("失败")).not.toBeInTheDocument();
  });
});
