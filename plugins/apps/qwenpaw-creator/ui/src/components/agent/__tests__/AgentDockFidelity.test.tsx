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

describe("AgentDock public output and interactions", () => {
  beforeEach(() => {
    seedCreatorSession();
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
    useAgentDockUiStore.getState().setOpen(false);
    renderDock();
    fireEvent.click(screen.getByRole("button", { name: "创作助手" }));
    expect(document.querySelector("[data-agent-dock]")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "工作区事实" }));
    expect(screen.getByText("当前任务")).toBeInTheDocument();
    expect(screen.getByText("素材概况（0）")).toBeInTheDocument();

    // Chat input stays while the workspace panel is expanded.
    expect(composerBox()).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "最大化面板" }),
    ).not.toBeInTheDocument();

    const { width, height } = useAgentDockUiStore.getState();
    fireEvent.pointerDown(document.querySelector('[title="拖拽调整大小"]')!, {
      clientX: 440,
      clientY: 100,
    });
    fireEvent.pointerMove(window, { clientX: 380, clientY: 40 });
    fireEvent.pointerUp(window);
    await waitFor(() => {
      expect(useAgentDockUiStore.getState().width).toBe(width + 60);
      expect(useAgentDockUiStore.getState().height).toBe(height + 60);
    });

    fireEvent.keyDown(window, { key: "Escape" });
    expect(document.querySelector("[data-agent-dock]")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "创作助手" }),
    ).toBeInTheDocument();
  });

  it("streams public narration while keeping thinking and tool schemas out of every disclosure", () => {
    useAgentDockUiStore.getState().setOpen(true);
    useAgentDockUiStore.getState().setAllowExpandDetails(true);
    seedSession("RUNNING", {
      streamingAssistantMessages: {
        live: {
          messageId: "live",
          firstEventSeq: 10,
          deltas: {
            0: '我先读取计划。\n```json\n{"action":"tool_call","tool":"read_project_file","arguments":{"path":"plan',
          },
          thinkingDeltas: { 0: "SECRET_THINKING" },
          createdAt: "now",
        },
      },
    });
    renderDock();
    expect(screen.getByText("我先读取计划。")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("SECRET_THINKING");
    expect(document.body).not.toHaveTextContent('"arguments"');
    expect(
      screen.queryByRole("button", { name: "详情" }),
    ).not.toBeInTheDocument();
    act(() =>
      useCreatorSessionStore.setState({
        streamingAssistantMessages: {},
        messages: [
          asst({
            messageId: "live",
            text: "计划已读取。",
            metadata: { providerThinking: "SECRET_THINKING" },
          }),
        ],
      }),
    );
    expect(screen.getByText("计划已读取。")).toBeInTheDocument();
    expect(document.querySelector("[data-agent-thinking]")).toBeNull();
    expect(document.body).not.toHaveTextContent("SECRET_THINKING");
  });

  it("shows public waiting narration without internal wait reasons or identifiers", () => {
    useAgentDockUiStore.getState().setOpen(true);
    seedSession("WAITING_RUNTIME", {
      messages: [
        asst({
          messageId: "wait",
          text: '剪辑任务仍在运行。\n```json\n{"action":"yield_until_runtime_event","arguments":{"reason":"PRIVATE_RUNTIME","waitForRunIds":["run-secret"]}}\n```',
          metadata: {
            parsedAction: {
              action: "yield_until_runtime_event",
              arguments: {
                reason: "PRIVATE_RUNTIME",
                waitForRunIds: ["run-secret"],
              },
            },
          },
        }),
      ],
    });
    renderDock();
    expect(screen.getByText("剪辑任务仍在运行。")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("PRIVATE_RUNTIME");
    expect(document.body).not.toHaveTextContent("run-secret");
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

    expect(screen.getByText("发送未成功，请重新发送。")).toBeInTheDocument();
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
    const responseFlow = userBubble
      ?.closest("[data-agent-turn]")
      ?.querySelector(":scope > [data-agent-response-flow]");
    expect(screen.getByText("我先读取当前计划。")).toBeInTheDocument();
    expect(screen.queryByText(/"action"/)).not.toBeInTheDocument();
    expect(screen.queryByText(/RUNTIME_ACTION_RESULT/)).not.toBeInTheDocument();
    expect(
      responseFlow?.querySelector("[data-agent-thinking]"),
    ).not.toBeInTheDocument();

    const toolStatus = screen.getByText("读取素材分析");
    expect(
      toolStatus
        .closest("[data-agent-tool]")
        ?.querySelector(".agent-activity-indicator"),
    ).toHaveAttribute("data-phase", "completed");
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
    expect(tool).toHaveTextContent("待审阅");
    expect(tool).toHaveTextContent("结果已准备好");
    expect(tool).not.toHaveTextContent("element:ep22");
    expect(tool).not.toHaveTextContent("失败");
    const waitingNotice = tool.querySelector("[data-agent-waiting-review]");
    expect(waitingNotice).not.toBeNull();
    expect(tool.querySelector(".agent-activity-indicator")).toHaveAttribute(
      "data-phase",
      "attention",
    );
    expect(
      useCreatorSessionStore.getState().subagentActivities[
        "delegate-review-wait"
      ],
    ).toMatchObject({ waitingReview: true, terminalKind: "BLOCKED" });
  });

  it("keeps specialist tools private when expanded and alive after the main session becomes idle", () => {
    useAgentDockUiStore.getState().setOpen(true);
    useAgentDockUiStore.getState().setAllowExpandDetails(true);
    seedSession("RUNNING", {
      messages: [
        delegateMsg(
          "asst",
          "delegate",
          { role: "ai_editing_director" },
          "正在处理剪辑。",
        ),
      ],
    });
    const sub = subFor("delegate", "child");
    act(() =>
      useCreatorSessionStore.getState().ingestEvents([
        sub("subagent.started", 1, { role: "ai_editing_director" }),
        sub("subagent.message_delta", 2, {
          messageId: "m",
          deltaIndex: 0,
          delta:
            '<function=read_project_file><parameter=arguments>{"path":"PRIVATE_FILE"}',
        }),
        sub("subagent.tool_progress", 3, {
          toolCallId: "tool",
          tool: "read_project_file",
          receivedBytes: 64,
          complete: true,
        }),
      ]),
    );
    renderDock();
    const card = document.querySelector('[data-agent-tool="delegate"]')!;
    fireEvent.click(
      within(card as HTMLElement).getByRole("button", { name: "查看进展" }),
    );
    expect(
      document.querySelectorAll('[data-subagent-tool="tool"]'),
    ).toHaveLength(1);
    expect(document.body).not.toHaveTextContent("PRIVATE_FILE");
    expect(document.body).not.toHaveTextContent("<function");
    expect(
      document.querySelector(
        '[data-subagent-tool="tool"] .agent-activity-indicator',
      ),
    ).toHaveAttribute("data-phase", "waiting");
    act(() =>
      useCreatorSessionStore.getState().ingestEvent(
        sub("subagent.tool_started", 4, {
          toolCallId: "tool",
          tool: "read_project_file",
          arguments: { path: "PRIVATE_FILE" },
        }),
      ),
    );
    expect(
      document.querySelector(
        '[data-subagent-tool="tool"] .agent-activity-indicator',
      ),
    ).toHaveAttribute("data-phase", "running");
    act(() =>
      useCreatorSessionStore
        .getState()
        .ingestEvent(evt("session.status_changed", 5, { status: "IDLE" })),
    );
    expect(card).toHaveAttribute("data-status", "started");
    expect(
      document.querySelector('[data-subagent-tool="tool"]'),
    ).toHaveTextContent("进行中");
    act(() =>
      useCreatorSessionStore.getState().ingestEvent(
        sub("subagent.message_delta", 6, {
          messageId: "public",
          deltaIndex: 0,
          delta: "片段顺序正在调整。",
        }),
      ),
    );
    expect(screen.getByText("片段顺序正在调整。")).toBeInTheDocument();
    act(() =>
      useCreatorSessionStore.getState().ingestEvent(
        sub("subagent.tool_completed", 7, {
          toolCallId: "tool",
          tool: "read_project_file",
          result: { secret: "PRIVATE_RESULT" },
          state: "succeeded",
        }),
      ),
    );
    expect(document.body).not.toHaveTextContent("PRIVATE_RESULT");
    expect(
      document.querySelector('[data-subagent-tool="tool"]'),
    ).toHaveTextContent("已完成");
    expect(
      document.querySelector(
        '[data-subagent-tool="tool"] .agent-activity-indicator',
      ),
    ).toHaveAttribute("data-phase", "completed");
  });

  it("treats delegation acceptance as active until its own terminal event", () => {
    useAgentDockUiStore.getState().setOpen(true);
    seedSession("RUNNING", {
      messages: [
        delegateMsg(
          "asst",
          "delegate",
          { role: "ai_editing_director" },
          "我会处理剪辑任务。",
        ),
      ],
    });
    const sub = subFor("delegate", "child");
    act(() =>
      useCreatorSessionStore.getState().ingestEvents([
        evt("agent.tool_started", 1, {
          actionId: "delegate",
          tool: "delegate_to_agent",
        }),
        evt("agent.tool_completed", 2, {
          actionId: "delegate",
          tool: "delegate_to_agent",
          status: "succeeded",
        }),
        sub("subagent.accepted", 3, { role: "ai_editing_director" }),
      ]),
    );
    renderDock();
    const card = document.querySelector('[data-agent-tool="delegate"]')!;
    expect(card).toHaveAttribute("data-status", "started");
    expect(card.querySelector(".agent-activity-indicator")).toHaveAttribute(
      "data-phase",
      "waiting",
    );
    act(() =>
      useCreatorSessionStore
        .getState()
        .ingestEvent(
          sub("subagent.started", 4, { role: "ai_editing_director" }),
        ),
    );
    expect(card.querySelector(".agent-activity-indicator")).toHaveAttribute(
      "data-phase",
      "running",
    );
    act(() =>
      useCreatorSessionStore.getState().ingestEvent(
        sub("subagent.completed", 5, {
          status: "SUCCEEDED",
          summary: "PRIVATE_SUMMARY",
        }),
      ),
    );
    expect(card).toHaveAttribute("data-status", "succeeded");
    expect(card).toHaveTextContent("已完成");
    expect(card.querySelector(".agent-activity-indicator")).toHaveAttribute(
      "data-phase",
      "completed",
    );
    expect(document.body).not.toHaveTextContent("PRIVATE_SUMMARY");
    act(() =>
      useCreatorSessionStore.setState((state) => ({
        subagentActivities: {
          ...state.subagentActivities,
          delegate: {
            ...state.subagentActivities.delegate,
            terminalKind: undefined,
          },
        },
      })),
    );
    expect(card).toHaveAttribute("data-status", "succeeded");
    expect(card).toHaveTextContent("已完成");
    expect(card.querySelector(".agent-activity-indicator")).toHaveAttribute(
      "data-phase",
      "completed",
    );
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
    expect(narration.parentElement).toBe(responseFlow);
    expect(
      screen.queryByText("执行计划：先完成故事规划"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("建立 Element")).not.toBeInTheDocument();
    expect(screen.queryByText("安排重叠关系")).not.toBeInTheDocument();
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
    expect(row.textContent).toContain("随时可以继续创作");

    try {
      await act(async () => {
        await i18n.changeLanguage("en");
      });
      expect(row.textContent).toContain("Ready to keep creating");
    } finally {
      await act(async () => {
        await i18n.changeLanguage("zh");
      });
    }
    expect(row.textContent).toContain("随时可以继续创作");
  });
});
