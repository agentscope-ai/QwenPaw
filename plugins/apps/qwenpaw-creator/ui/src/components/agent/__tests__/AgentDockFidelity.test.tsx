import { MemoryRouter, Route, Routes } from "react-router-dom";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AgentDock from "@/components/agent/AgentDock";
import { useAgentDockUiStore } from "@/store/agentDockUiStore";
import { useCreatorSessionStore } from "@/store/creatorSessionStore";
import { useFileProjectReviewStore } from "@/store/fileProjectReviewStore";
import { useExecutionAuthorizationStore } from "@/store/executionAuthorizationStore";
import { installMockFetch } from "@/test/mockFetch";
import {
  evt,
  makePendingAuthorization,
  makeReviewRecord,
  msg,
  seedCreatorSession,
} from "@/test/agentFixtures";

function renderDock() {
  return render(
    <MemoryRouter initialEntries={["/project/p1/plan"]}>
      <Routes>
        <Route path="/project/:id/plan" element={<AgentDock />} />
      </Routes>
    </MemoryRouter>,
  );
}

const composerBox = () =>
  screen.getByRole("textbox", { name: "输入修改意图，@ 可引用对象…" });

const asst = (overrides: Parameters<typeof msg>[0]) =>
  msg({
    messageSeq: 2,
    role: "assistant",
    source: "creator_agent",
    ...overrides,
  });

const delegateMsg = (
  messageId: string,
  actionId: string,
  args: Record<string, unknown>,
  text: string,
) =>
  asst({
    messageId,
    text,
    metadata: {
      actionId,
      parsedAction: {
        action: "tool_call",
        tool: "delegate_to_agent",
        arguments: args,
      },
    },
  });

const subFor =
  (parentActionId: string, runId: string) =>
  (type: string, seq: number, data: Record<string, unknown>) =>
    evt(type, seq, {
      parentActionId,
      runId,
      role: "visual_development_agent",
      ...data,
    });

const ACCEPTED = {
  messageSeq: 2,
  eventSeq: 20,
  classification: "mutation_instruction",
  appendState: "queued_until_message_boundary",
  creatorSessionId: "session-1",
  conversationId: "conversation-1",
};

const seedSession = (status: string, patch: Record<string, unknown> = {}) =>
  useCreatorSessionStore.setState(
    (state) =>
      ({
        session: { ...state.session!, status },
        ...patch,
      }) as never,
  );

describe("AgentDock origin/main visible fidelity", () => {
  beforeEach(() => {
    seedCreatorSession();
  });

  it("matches the right-edge handle trigger and exact 440x620 floating shell", async () => {
    useAgentDockUiStore.getState().setOpen(false);
    renderDock();
    const trigger = screen.getByRole("button", { name: "创作助手" });
    expect(trigger).toHaveAttribute("data-agent-dock-handle");
    expect(trigger).toHaveAttribute("data-state", "idle");

    fireEvent.click(trigger);
    const dock = document.querySelector<HTMLElement>("[data-agent-dock]")!;
    await waitFor(() =>
      expect(dock).toHaveStyle({ width: "440px", height: "620px" }),
    );
    expect(dock).toHaveAttribute("data-agent-dock-width", "440");
    expect(dock).toHaveAttribute("data-agent-dock-height", "620");
    expect(screen.getByText("创作助手")).toBeInTheDocument();
    // Top-bar entries dropped from the redesigned shell:
    for (const name of ["审阅与决策中心", "新对话", "历史聊天", "最大化面板"]) {
      expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
    }
    // With no pending decisions the tray takes up no space at all.
    expect(
      document.querySelector("[data-decision-tray]"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "工作区事实" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "收起 Agent 面板" }),
    ).toBeInTheDocument();
    expect(composerBox()).toHaveClass("min-h-[32px]", "max-h-24");
  });

  it("pops the dock open with the inline tray when a production confirmation arrives live", async () => {
    useAgentDockUiStore.getState().setOpen(false);
    renderDock();
    expect(document.querySelector("[data-agent-dock]")).not.toBeInTheDocument();

    act(() =>
      useExecutionAuthorizationStore.setState({
        projectId: "p1",
        items: [
          makePendingAuthorization({
            id: "auth-image-live",
            transactionId: "tx1",
            specialistRunId: "run-visual",
            executionRequestId: "request-image",
            targetRef: "project:assets",
            authorizationToken: "token-image",
          }),
        ],
      }),
    );

    await waitFor(() => {
      expect(document.querySelector("[data-agent-dock]")).toBeInTheDocument();
      // Blocking item arrived: tray force-expands and is flagged urgent.
      const tray = document.querySelector("[data-decision-tray]");
      expect(tray).toBeInTheDocument();
      expect(tray).toHaveAttribute("data-decision-tray-urgent", "true");
      expect(tray).not.toHaveAttribute("data-decision-tray-collapsed");
    });
    expect(screen.getAllByText("生产确认").length).toBeGreaterThan(0);
    // Chat input shares the screen with the tray; no view switching needed.
    expect(composerBox()).toBeInTheDocument();
  });

  it("keeps workspace and collapse interactions, resizes and closes with Escape", async () => {
    useAgentDockUiStore.getState().setOpen(true);
    renderDock();

    fireEvent.click(screen.getByRole("button", { name: "工作区事实" }));
    expect(screen.getByText("当前任务")).toBeInTheDocument();
    expect(screen.getByText("素材概况（0）")).toBeInTheDocument();

    // Chat input stays while the workspace panel is expanded.
    expect(composerBox()).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "最大化面板" }),
    ).not.toBeInTheDocument();

    fireEvent.pointerDown(document.querySelector('[title="拖拽调整大小"]')!, {
      clientX: 440,
      clientY: 100,
    });
    fireEvent.pointerMove(window, { clientX: 380, clientY: 40 });
    fireEvent.pointerUp(window);
    await waitFor(() => {
      expect(useAgentDockUiStore.getState().width).toBe(500);
      expect(useAgentDockUiStore.getState().height).toBe(680);
    });

    fireEvent.keyDown(window, { key: "Escape" });
    expect(document.querySelector("[data-agent-dock]")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "创作助手" }),
    ).toBeInTheDocument();
  });

  it("shows streaming tool status without exposing internal JSON details", async () => {
    useAgentDockUiStore.getState().setOpen(true);
    const user = msg({ messageId: "user-stream-tool", text: "读取计划" });
    seedSession("RUNNING", {
      messages: [user],
      streamingAssistantMessages: {
        "assistant-stream-tool": {
          messageId: "assistant-stream-tool",
          firstEventSeq: 10,
          deltas: {
            0: '我先读取计划。\n```json\n{"action":"tool_call","tool":"read_project_file",',
            1: '"arguments":{"path":"plan',
          },
          thinkingDeltas: { 0: "确认需要读取的文件。" },
          createdAt: "now",
        },
      },
    });
    renderDock();

    const streamingAction = document.querySelector<HTMLElement>(
      '[data-agent-action="tool_call"]',
    )!;
    expect(streamingAction).toHaveAttribute("data-streaming-action", "true");
    expect(streamingAction).toHaveAttribute("data-expanded", "false");
    expect(streamingAction).toHaveTextContent("读取素材分析处理中");
    expect(
      within(streamingAction).queryByText(/"path":"plan/),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("我先读取计划。")).not.toBeInTheDocument();

    act(() =>
      useCreatorSessionStore.setState({
        streamingAssistantMessages: {},
        messages: [
          user,
          asst({
            messageId: "assistant-stream-tool",
            text: '我先读取计划。\n```json\n{"action":"tool_call","tool":"read_project_file","arguments":{"path":"plan.json"}}\n```',
            metadata: {
              providerThinking: "确认需要读取的文件。",
              actionId: "action-stream-tool",
              parsedAction: {
                action: "tool_call",
                tool: "read_project_file",
                arguments: { path: "plan.json" },
              },
            },
          }),
        ],
        events: [
          evt("agent.tool_started", 20, {
            actionId: "action-stream-tool",
            tool: "read_project_file",
          }),
        ],
      }),
    );
    const thinking = document.querySelector<HTMLElement>(
      "[data-agent-thinking]",
    )!;
    const tool = document.querySelector<HTMLElement>(
      '[data-agent-tool="action-stream-tool"]',
    )!;
    await waitFor(() =>
      expect(thinking).toHaveAttribute("data-expanded", "false"),
    );
    expect(thinking).toHaveTextContent("思考完成");
    expect(
      thinking.querySelector("[data-agent-thinking-output]"),
    ).not.toBeInTheDocument();
    expect(tool).toHaveAttribute("data-expanded", "false");
    expect(tool).toHaveTextContent("读取素材分析处理中");
    expect(
      within(tool).queryByText(/"path": "plan.json"/),
    ).not.toBeInTheDocument();
  });

  it("renders yield_until_runtime_event as a collapsed waiting action", () => {
    useAgentDockUiStore.getState().setOpen(true);
    useCreatorSessionStore.setState({
      messages: [
        msg({ messageId: "user-yield", text: "等待剪辑" }),
        asst({
          messageId: "assistant-yield",
          text: '剪辑任务仍在运行。\n```json\n{"action":"yield_until_runtime_event","arguments":{"waitForRunIds":["run-video-1"],"reason":"等待 Source Intelligence 完成素材分析，以便 Runtime 投影 Timeline 和 Element，然后委派 AI Editing Director 进行剪辑"}}\n```',
          metadata: {
            parsedAction: {
              action: "yield_until_runtime_event",
              arguments: {
                waitForRunIds: ["run-video-1"],
                reason:
                  "等待 Source Intelligence 完成素材分析，以便 Runtime 投影 Timeline 和 Element，然后委派 AI Editing Director 进行剪辑",
              },
            },
          },
        }),
      ],
    });
    renderDock();

    const waiting = document.querySelector<HTMLElement>(
      '[data-agent-action="yield_until_runtime_event"]',
    )!;
    expect(waiting).toHaveAttribute("data-expanded", "false");
    expect(waiting).toHaveTextContent(
      "等待 Source Intelligence 完成素材分析，以便 Runtime 投影 Timeline 和 Element，然后委派 AI Editing Director 进行剪辑中",
    );
    expect(waiting).not.toHaveTextContent("等待等待");
    expect(
      within(waiting).queryByText(/"run-video-1"/),
    ).not.toBeInTheDocument();
  });

  it("keeps the focused modification editor writable and submits at a live SSE boundary", async () => {
    const { calls } = installMockFetch([
      {
        match: "/projects/p1/messages",
        method: "POST",
        response: { json: ACCEPTED },
      },
    ]);
    useAgentDockUiStore.getState().setOpen(true);
    renderDock();

    const textbox = composerBox();
    textbox.focus();
    textbox.textContent = "请把故事设定在温暖厨房";
    fireEvent.input(textbox);
    expect(document.activeElement).toBe(textbox);
    expect(textbox).toHaveAttribute("contenteditable", "true");

    act(() =>
      seedSession("RUNNING", {
        streamingAssistantMessages: {
          "assistant-live": {
            messageId: "assistant-live",
            firstEventSeq: 19,
            deltas: { 0: "正在处理已有计划。" },
            thinkingDeltas: {},
            createdAt: "now",
          },
        },
      }),
    );

    await waitFor(() => {
      const liveTextbox = composerBox();
      expect(liveTextbox).toBe(textbox);
      expect(liveTextbox).toHaveAttribute("contenteditable", "true");
      expect(liveTextbox).toHaveTextContent("请把故事设定在温暖厨房");
      expect(document.activeElement).toBe(liveTextbox);
    });

    fireEvent.keyDown(textbox, { key: "Enter" });
    await waitFor(() =>
      expect(
        calls.find((call) => call.url.includes("/projects/p1/messages"))?.body,
      ).toMatchObject({
        creatorSessionId: "session-1",
        conversationId: "conversation-1",
        message: "请把故事设定在温暖厨房",
      }),
    );
  });

  it("clears submitted text immediately while the server is still accepting the message", async () => {
    let releaseRequest!: (response: Response) => void;
    const requestPending = new Promise<Response>((resolve) => {
      releaseRequest = resolve;
    });
    const fetchMock = vi.fn(() => requestPending);
    vi.stubGlobal("fetch", fetchMock);
    useAgentDockUiStore.getState().setOpen(true);
    renderDock();

    const textbox = composerBox();
    textbox.textContent = "立即发送，不要留在输入框";
    fireEvent.input(textbox);
    fireEvent.keyDown(textbox, { key: "Enter" });

    expect(textbox).toHaveTextContent("");
    expect(screen.getByText("立即发送，不要留在输入框")).toBeInTheDocument();
    expect(useCreatorSessionStore.getState().queuedUi[0]?.state).toBe(
      "sending",
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);

    releaseRequest({
      ok: true,
      status: 202,
      statusText: "Accepted",
      json: async () => ACCEPTED,
    } as Response);
    await waitFor(() =>
      expect(useCreatorSessionStore.getState().queuedUi[0]?.state).toBe(
        "queued",
      ),
    );
  });

  it("shows the same simplified copy for queued message failures", () => {
    useCreatorSessionStore.setState({
      queuedUi: [
        {
          clientMessageId: "failed-message",
          requestSignature: "failed-signature",
          text: "重新生成视频",
          state: "failed",
          error:
            "R2V ArtifactSlot 归属冲突: internal/path/project.json\ntraceback",
        },
      ],
    });
    useAgentDockUiStore.getState().setOpen(true);

    renderDock();

    expect(screen.getByText("视频生成失败，请重试")).toBeInTheDocument();
    expect(
      screen.queryByText(/internal\/path\/project\.json/),
    ).not.toBeInTheDocument();
  });

  it("morphs the composer button between send and stop across idle/running states", async () => {
    const { calls } = installMockFetch([
      {
        match: "/projects/p1/interrupt",
        method: "POST",
        response: {
          json: {
            creatorSessionId: "session-1",
            status: "INTERRUPT_REQUESTED",
            stopRequested: true,
          },
        },
      },
    ]);
    useAgentDockUiStore.getState().setOpen(true);
    renderDock();

    // Idle + empty input → disabled (greyed) send button; idle + content → clickable
    expect(
      screen.queryByRole("button", { name: "停止所有 Agent" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "发送" })).toBeDisabled();
    const textbox = composerBox();
    textbox.textContent = "运行中追加指令";
    fireEvent.input(textbox);
    expect(screen.getByRole("button", { name: "发送" })).toBeEnabled();

    // Running + input has content → still a clickable send button
    act(() => seedSession("RUNNING"));
    expect(
      screen.queryByRole("button", { name: "停止所有 Agent" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "发送" })).toBeEnabled();

    // Running + empty input → the stop button replaces send, with a breathing glow
    textbox.textContent = "";
    fireEvent.input(textbox);
    const stop = screen.getByRole("button", { name: "停止所有 Agent" });
    expect(stop).toHaveClass("agent-dock-stop-glow");
    expect(
      screen.queryByRole("button", { name: "发送" }),
    ).not.toBeInTheDocument();

    // Clicking stop interrupts the whole Creator Session
    fireEvent.click(stop);
    expect(useCreatorSessionStore.getState().session?.status).toBe(
      "INTERRUPT_REQUESTED",
    );
    await waitFor(() =>
      expect(
        calls.some((call) => call.url.includes("/projects/p1/interrupt")),
      ).toBe(true),
    );
    expect(
      calls.find((call) => call.url.includes("/projects/p1/interrupt"))?.method,
    ).toBe("POST");
  });

  it("keeps file-native review feedback on the Session message API", async () => {
    const { calls } = installMockFetch([
      {
        match: "/projects/p1/messages",
        response: {
          json: {
            ...ACCEPTED,
            messageSeq: 1,
            eventSeq: 1,
            classification: "review_revise",
          },
        },
      },
    ]);
    seedSession("PENDING_REVIEW");
    useFileProjectReviewStore.setState({
      projectId: "p1",
      reviews: [makeReviewRecord()],
      etag: '"token-1"',
      syncStatus: "healthy",
    });
    useAgentDockUiStore.getState().setOpen(true);
    renderDock();
    // File review lands in the inline tray; chat input stays usable.
    await waitFor(() =>
      expect(
        document.querySelector("[data-decision-tray]"),
      ).toBeInTheDocument(),
    );

    const textbox = composerBox();
    textbox.textContent = "请根据这处 diff 再调整标题";
    fireEvent.input(textbox);
    fireEvent.keyDown(textbox, { key: "Enter" });

    await waitFor(() =>
      expect(
        calls.some((call) => call.url.endsWith("/projects/p1/messages")),
      ).toBe(true),
    );
    expect(calls.some((call) => call.url.endsWith("/comments"))).toBe(false);
  });

  it("keeps real user authority, hides Runtime rows and renders the expandable origin tool card", () => {
    useAgentDockUiStore.getState().setOpen(true);
    useCreatorSessionStore.setState({
      messages: [
        msg({ messageId: "user-1", text: "请检查当前计划" }),
        asst({
          messageId: "assistant-1",
          text: '我先读取当前计划。\n```json\n{"action":"tool_call","tool":"read_project_file"}\n```',
          metadata: {
            actionId: "action-1",
            parsedAction: {
              action: "tool_call",
              tool: "read_project_file",
              arguments: { path: "plan.json" },
            },
          },
        }),
        msg({
          messageId: "result-1",
          messageSeq: 3,
          source: "runtime_action_result",
          text: '[RUNTIME_ACTION_RESULT]\n\n{"head":"h2","ok":true}',
          metadata: {
            actionId: "action-1",
            tool: "read_project_file",
            resultKind: "workspace_read",
          },
        }),
      ],
      events: [
        evt("agent.tool_started", 1, {
          actionId: "action-1",
          tool: "read_project_file",
        }),
        evt("agent.tool_completed", 2, {
          actionId: "action-1",
          remainingActionIds: [],
        }),
      ],
    });
    seedSession("RUNNING");
    renderDock();

    const userBubble = screen
      .getByText("请检查当前计划")
      .closest("[data-agent-message]");
    expect(userBubble).toHaveClass("bg-[var(--color-accent)]", "text-white");
    const responseFlow = userBubble
      ?.closest("[data-agent-turn]")
      ?.querySelector(":scope > [data-agent-response-flow]");
    expect(screen.getByText("我先读取当前计划。")).toBeInTheDocument();
    expect(screen.queryByText(/"action"/)).not.toBeInTheDocument();
    expect(screen.queryByText(/RUNTIME_ACTION_RESULT/)).not.toBeInTheDocument();
    expect(
      responseFlow?.querySelector("[data-agent-thinking]"),
    ).not.toBeInTheDocument();

    const toolStatus = screen.getByText("读取素材分析完成");
    expect(toolStatus.closest("[data-agent-tool]")?.parentElement).toBe(
      responseFlow,
    );
    expect(
      screen.queryByRole("button", { name: "详情" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/"path": "plan.json"/)).not.toBeInTheDocument();
  });

  it("renders rejection feedback once as a compact review card", () => {
    useAgentDockUiStore.getState().setOpen(true);
    const feedbackMessage = msg({
      messageId: "review-feedback-first",
      source: "review_rejection_feedback",
      text: "【系统自动消息 · 用户审阅反馈】原始内部消息",
      metadata: {
        decisionId: "decision-review-feedback",
        rejectionFeedback: {
          action: "UNDO_AND_REGENERATE",
          feedbackNote: "人物仍像巅峰时期；请保持身份一致，改成落魄时期",
        },
        targets: [{ label: "哈兰德 · 落魄时期分镜图" }],
      },
    });
    useCreatorSessionStore.setState({
      messages: [
        feedbackMessage,
        {
          ...feedbackMessage,
          messageId: "review-feedback-replay",
          messageSeq: 2,
        },
      ],
    });

    renderDock();

    const cards = document.querySelectorAll("[data-agent-review-feedback]");
    expect(cards).toHaveLength(1);
    expect(cards[0]).toHaveTextContent("已撤销并安排重做");
    expect(cards[0]).toHaveTextContent("哈兰德 · 落魄时期分镜图");
    expect(cards[0]).not.toHaveTextContent("原始内部消息");
  });

  it("renders a review-blocked delegation as waiting, not failed", () => {
    useAgentDockUiStore.getState().setOpen(true);
    seedSession("PENDING_REVIEW", {
      messages: [
        delegateMsg(
          "assistant-review-wait",
          "delegate-review-wait",
          {
            role: "r2v_generation_director",
            target_refs: ["element:ep22"],
            task: "生成 ep22 视频",
          },
          "继续生成 ep22 视频。",
        ),
      ],
    });
    const sub = subFor("delegate-review-wait", "run-review-wait");
    act(() =>
      useCreatorSessionStore.getState().ingestEvents([
        evt("agent.tool_started", 1, {
          actionId: "delegate-review-wait",
          tool: "delegate_to_agent",
          role: "r2v_generation_director",
          targetRefs: ["element:ep22"],
        }),
        sub("subagent.blocked", 2, {
          role: "r2v_generation_director",
          targetRefs: ["element:ep22"],
          waitingReview: true,
          summary:
            "element:ep22 的分镜图已生成，视频尚未开始。请先审阅分镜图；审阅通过后将自动继续生成视频。",
        }),
        evt("agent.tool_completed", 3, {
          actionId: "delegate-review-wait",
          runId: "parent-run",
          tool: "delegate_to_agent",
          failed: false,
        }),
      ]),
    );

    renderDock();

    const tool = document.querySelector<HTMLElement>(
      '[data-agent-tool="delegate-review-wait"]',
    )!;
    expect(tool).toHaveTextContent("等待审阅");
    expect(tool).toHaveTextContent("视频尚未开始");
    expect(tool).not.toHaveTextContent("失败");
    const waitingNotice = tool.querySelector("[data-agent-waiting-review]");
    expect(waitingNotice).not.toBeNull();
    expect(
      useCreatorSessionStore.getState().subagentActivities[
        "delegate-review-wait"
      ],
    ).toMatchObject({ waitingReview: true, terminalKind: "BLOCKED" });
  });

  it("moves a streamed Sub-agent function call into its tool card and preserves detail scrolling", async () => {
    useAgentDockUiStore.getState().setOpen(true);
    useAgentDockUiStore.getState().setAllowExpandDetails(true);
    seedSession("RUNNING", {
      messages: [
        msg({ messageId: "user-function", text: "读取故事文件" }),
        delegateMsg(
          "assistant-function",
          "delegate-function",
          {
            role: "visual_development_agent",
            target_refs: ["timeline:main"],
            task: "读取项目文件",
          },
          "委派故事规划。",
        ),
      ],
    });
    const sub = subFor("delegate-function", "run-function");
    act(() =>
      useCreatorSessionStore.getState().ingestEvents([
        evt("agent.tool_started", 1, {
          actionId: "delegate-function",
          tool: "delegate_to_agent",
          role: "visual_development_agent",
          roleDisplayName: "故事规划",
          delegationText: "读取项目文件",
          targetRefs: ["timeline:main"],
        }),
        sub("subagent.message_delta", 2, {
          messageId: "message-function",
          deltaIndex: 0,
          delta:
            '<function=read_project_file><parameter=arguments>{"path":"story/',
        }),
      ]),
    );
    renderDock();

    const delegateTool = document.querySelector<HTMLElement>(
      '[data-agent-tool="delegate-function"]',
    )!;
    fireEvent.click(within(delegateTool).getByRole("button", { name: "详情" }));
    const subagentMessage = document.querySelector<HTMLElement>(
      '[data-subagent-message="message-function"]',
    )!;
    const streamingFunction = subagentMessage.querySelector<HTMLElement>(
      '[data-agent-action="tool_call"]',
    )!;
    expect(streamingFunction).toHaveAttribute("data-expanded", "false");
    fireEvent.click(
      within(streamingFunction).getByRole("button", { name: "详情" }),
    );
    expect(streamingFunction).toHaveAttribute("data-expanded", "true");
    expect(streamingFunction).toHaveTextContent("读取素材分析处理中");
    expect(streamingFunction).toHaveTextContent('"path":"story/');

    act(() =>
      useCreatorSessionStore.getState().ingestEvent(
        sub("subagent.message_delta", 3, {
          messageId: "message-function",
          deltaIndex: 1,
          delta: 'outline.md"}</parameter></function></tool_call>',
        }),
      ),
    );
    await waitFor(() =>
      expect(streamingFunction).toHaveTextContent('"path": "story/outline.md"'),
    );

    // Duplicate started events for one toolCallId collapse into one card.
    act(() =>
      useCreatorSessionStore.getState().ingestEvents([
        sub("subagent.message_completed", 4, {
          messageId: "message-function",
          text: '<function=read_project_file><parameter=arguments>{"path":"story/outline.md"}</parameter></function></tool_call>',
          finishReason: "tool_call",
        }),
        ...[5, 6].map((seq) =>
          sub("subagent.tool_started", seq, {
            toolCallId: "function-tool",
            tool: "read_project_file",
            arguments: { path: "story/outline.md" },
            state: "started",
          }),
        ),
        evt("task.progress_updated", 7, {
          specialistRunId: "run-function",
          taskId: "task-function",
          progress: 0.4,
          detail: "已读取前 400 行",
        }),
      ]),
    );
    let nestedTool: HTMLElement | null = null;
    await waitFor(() => {
      nestedTool = document.querySelector<HTMLElement>(
        '[data-subagent-tool="function-tool"]',
      );
      expect(nestedTool).toHaveAttribute("data-expanded", "false");
    });
    expect(nestedTool).not.toBeNull();
    expect(
      document.querySelectorAll('[data-subagent-tool="function-tool"]'),
    ).toHaveLength(1);
    fireEvent.click(within(nestedTool!).getByRole("button", { name: "详情" }));
    expect(nestedTool).toHaveAttribute("data-expanded", "true");
    expect(
      nestedTool!.querySelector("[data-subagent-tool-arguments]"),
    ).toHaveTextContent('"path": "story/outline.md"');
    expect(
      subagentMessage.querySelector('[data-agent-action="tool_call"]'),
    ).not.toBeInTheDocument();
    const toolOutput = nestedTool!.querySelector<HTMLElement>(
      "[data-subagent-tool-stream]",
    )!;
    expect(toolOutput).toHaveTextContent("已读取前 400 行");
    Object.defineProperties(toolOutput, {
      scrollHeight: { configurable: true, value: 900 },
      clientHeight: { configurable: true, value: 180 },
    });
    toolOutput.scrollTop = 420;

    act(() =>
      useCreatorSessionStore.getState().ingestEvent(
        evt("task.progress_updated", 8, {
          specialistRunId: "run-function",
          taskId: "task-function",
          progress: 0.8,
          detail: "已读取前 800 行",
        }),
      ),
    );
    await waitFor(() =>
      expect(toolOutput).toHaveTextContent("已读取前 800 行"),
    );
    expect(toolOutput.scrollTop).toBe(420);

    act(() =>
      useCreatorSessionStore.getState().ingestEvent(
        sub("subagent.tool_completed", 9, {
          toolCallId: "function-tool",
          tool: "read_project_file",
          result: { lines: 800 },
          state: "succeeded",
        }),
      ),
    );
    await waitFor(() =>
      expect(nestedTool).toHaveAttribute("data-expanded", "false"),
    );
    expect(
      nestedTool!.querySelector("[data-subagent-tool-stream]"),
    ).not.toBeInTheDocument();
  });

  it("treats delegate acceptance as waiting and only a Sub-agent terminal event as finished", async () => {
    useAgentDockUiStore.getState().setOpen(true);
    useAgentDockUiStore.getState().setAllowExpandDetails(true);
    seedSession("RUNNING", {
      messages: [
        msg({ messageId: "user-service", text: "执行剪辑" }),
        delegateMsg(
          "assistant-service",
          "delegate-service-action",
          {
            role: "ai_editing_director",
            target_refs: ["timeline:main"],
            task: "根据当前素材完成主 Timeline 的剪辑。",
          },
          "我会委派剪辑任务。",
        ),
      ],
    });
    const sub = subFor("delegate-service-action", "run-service-1");
    act(() =>
      useCreatorSessionStore.getState().ingestEvents([
        evt("agent.tool_started", 1, {
          actionId: "delegate-service-action",
          tool: "delegate_to_agent",
          role: "ai_editing_director",
          roleDisplayName: "AI 剪辑导演",
          delegationText: "根据当前素材完成主 Timeline 的剪辑。",
          targetRefs: ["timeline:main"],
        }),
        evt("agent.tool_completed", 2, {
          actionId: "delegate-service-action",
          tool: "delegate_to_agent",
          status: "succeeded",
        }),
        sub("subagent.accepted", 3, {
          role: "ai_editing_director",
          roleDisplayName: "AI 剪辑导演",
          delegationText: "根据当前素材完成主 Timeline 的剪辑。",
          targetRefs: ["timeline:main"],
        }),
      ]),
    );
    renderDock();

    const delegateTool = document.querySelector<HTMLElement>(
      '[data-agent-tool="delegate-service-action"]',
    )!;
    expect(delegateTool).toHaveAttribute("data-expanded", "false");
    fireEvent.click(within(delegateTool).getByRole("button", { name: "详情" }));
    expect(delegateTool).toHaveAttribute("data-expanded", "true");
    expect(screen.getByText("等待输出中")).toBeInTheDocument();
    expect(screen.getByText("处理中")).toBeInTheDocument();
    expect(screen.queryByText("Sub-agent 已结束")).not.toBeInTheDocument();

    act(() =>
      useCreatorSessionStore.getState().ingestEvents([
        sub("subagent.completed", 4, {
          role: "ai_editing_director",
          marker: "SUCCESS",
          status: "SUCCEEDED",
          summary: "剪辑方案已生成并等待执行确认。",
        }),
        evt("agent.tool_completed", 5, {
          actionId: "delegate-service-action",
          runId: "parent-agent-run-1",
          tool: "delegate_to_agent",
          status: "succeeded",
        }),
      ]),
    );
    await waitFor(() =>
      expect(delegateTool).toHaveAttribute("data-expanded", "false"),
    );
    expect(
      screen.queryByText("剪辑方案已生成并等待执行确认"),
    ).not.toBeInTheDocument();
    fireEvent.click(within(delegateTool).getByRole("button", { name: "详情" }));
    expect(
      screen.getByText("剪辑方案已生成并等待执行确认"),
    ).toBeInTheDocument();
    expect(screen.getByText("完成")).toBeInTheDocument();
    expect(screen.queryByText("等待输出中")).not.toBeInTheDocument();
  });

  it("anchors the origin plan card after assistant narration inside the same human turn", () => {
    useAgentDockUiStore.getState().setOpen(true);
    seedSession("RUNNING", {
      messages: [
        msg({ messageId: "user-1", text: "先制定计划" }),
        asst({
          messageId: "assistant-1",
          text: '我会分两步推进。\n```json\n{"action":"plan","summary":"先完成故事规划"}\n```',
          metadata: {
            parsedAction: {
              action: "plan",
              summary: "先完成故事规划",
              steps: ["1. 建立 Element", "2、安排重叠关系"],
              scope: ["timeline:main"],
            },
          },
        }),
      ],
      events: [
        evt("agent.plan", 1, {
          summary: "先完成故事规划",
          steps: ["1. 建立 Element", "2、安排重叠关系"],
          scope: ["timeline:main"],
        }),
      ],
    });
    renderDock();

    const turn = screen.getByText("先制定计划").closest("[data-agent-turn]");
    const responseFlow = turn?.querySelector(
      ":scope > [data-agent-response-flow]",
    );
    const narration = screen
      .getByText("我会分两步推进。")
      .closest("[data-agent-message]")!;
    const plan = screen.getByText("执行计划：先完成故事规划").closest("div")!;
    expect(narration.parentElement).toBe(responseFlow);
    expect(plan.parentElement).toBe(responseFlow);
    expect(
      narration.compareDocumentPosition(plan) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(screen.getByText("建立 Element")).toBeInTheDocument();
    expect(screen.getByText("安排重叠关系")).toBeInTheDocument();
    expect(screen.queryByText("1. 建立 Element")).not.toBeInTheDocument();
    expect(screen.queryByText(/"action"/)).not.toBeInTheDocument();
    expect(
      responseFlow?.querySelector("[data-agent-thinking]"),
    ).not.toBeInTheDocument();
  });

  it("recomputes the live status label on a runtime language switch", async () => {
    // TC-PL-02 F-1: a runtime locale switch must refresh the memoized
    // liveStatus label in both directions without a remount.
    const i18n = (await import("@/i18n")).default;
    useAgentDockUiStore.getState().setOpen(true);
    renderDock();

    const row = await waitFor(() => {
      const found = document.querySelector<HTMLElement>(
        "[data-agent-live-status]",
      );
      expect(found).not.toBeNull();
      return found!;
    });
    expect(row.textContent).toContain("待命中");

    try {
      await act(async () => {
        await i18n.changeLanguage("en");
      });
      expect(row.textContent).toContain("Idle, ready");
    } finally {
      await act(async () => {
        await i18n.changeLanguage("zh");
      });
    }
    expect(row.textContent).toContain("待命中");
  });
});
