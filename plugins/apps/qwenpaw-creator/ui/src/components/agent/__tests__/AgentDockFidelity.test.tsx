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
import { useCreatorInteractionStore } from "@/store/creatorInteractionStore";
import { useCreatorSessionStore } from "@/store/creatorSessionStore";
import { useCreatorTaskViewStore } from "@/store/creatorTaskViewStore";
import { useFileProjectReviewStore } from "@/store/fileProjectReviewStore";
import { useExecutionAuthorizationStore } from "@/store/executionAuthorizationStore";
import { installMockFetch } from "@/test/mockFetch";
import type { FileProjectReviewRecord } from "@/contracts/creator";

function fileProjectReview(): FileProjectReviewRecord {
  return {
    review_id: "file-review-1",
    round_id: "round-1",
    request_id: "request-1",
    request_message_seq: 1,
    interrupted_run_id: "run-1",
    baseline_generation: 1,
    baseline_etag: "base-1",
    candidate_generation: 2,
    candidate_etag: "candidate-2",
    decision_token: "file-token-1",
    status: "PENDING",
    operations: [
      {
        kind: "update",
        json_pointer: "/story/title",
        file_id: null,
        target_ref: null,
        before_hash: "before",
        after_hash: "after",
        before: "旧标题",
        after: "新标题",
        operation_id: "file-operation-1",
        ui_locator: {},
        decision: "PENDING",
      },
    ],
    created_at: "2026-07-15T00:00:00Z",
    updated_at: "2026-07-15T00:00:01Z",
  };
}

function renderDock() {
  return render(
    <MemoryRouter initialEntries={["/project/p1/plan"]}>
      <Routes>
        <Route path="/project/:id/plan" element={<AgentDock />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("AgentDock origin/main visible fidelity", () => {
  beforeEach(() => {
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: {
        getItem: vi.fn(() => null),
        setItem: vi.fn(),
        removeItem: vi.fn(),
        clear: vi.fn(),
      },
    });
    useAgentDockUiStore.getState().reset();
    useCreatorInteractionStore.getState().reset();
    useFileProjectReviewStore.getState().reset();
    useExecutionAuthorizationStore.getState().reset();
    useCreatorTaskViewStore.getState().reset();
    useCreatorSessionStore.getState().reset();
    useCreatorSessionStore.setState({
      projectId: "p1",
      session: {
        id: "session-1",
        projectId: "p1",
        status: "IDLE",
        lastMessageSeq: 0,
        lastConsumedMessageSeq: 0,
        lastEventSeq: 0,
      },
      conversations: [
        {
          conversationId: "conversation-1",
          title: "默认对话",
          isDefault: true,
          createdAt: "2026-07-11T00:00:00Z",
        },
      ],
      activeConversationId: "conversation-1",
      messages: [],
      queuedUi: [],
      events: [],
      hasMoreMessages: false,
      agentStatusBar: null,
    });
  });

  it("matches the right-edge handle trigger and exact 440x620 floating shell", async () => {
    useAgentDockUiStore.getState().setOpen(false);
    renderDock();
    const trigger = screen.getByRole("button", { name: "创作助手" });
    expect(trigger).toHaveAttribute("data-agent-dock-handle");
    expect(trigger).toHaveAttribute("data-state", "idle");
    expect(trigger).toHaveClass(
      "fixed",
      "right-0",
      "top-20",
      "rounded-l-xl",
      "z-40",
    );
    expect(trigger.querySelector(".agent-live-dot")).not.toBeInTheDocument();

    fireEvent.click(trigger);
    const dock = document.querySelector<HTMLElement>("[data-agent-dock]")!;
    await waitFor(() =>
      expect(dock).toHaveStyle({ width: "440px", height: "620px" }),
    );
    expect(dock).toHaveAttribute("data-agent-dock-width", "440");
    expect(dock).toHaveAttribute("data-agent-dock-height", "620");
    expect(dock).toHaveClass(
      "agent-dock-enter",
      "fixed",
      "bottom-5",
      "right-5",
      "z-40",
      "rounded-2xl",
      "backdrop-blur-xl",
    );
    expect(screen.getByText("创作助手")).toBeInTheDocument();
    // No hint copy is shown anymore when no context is bound.
    expect(
      screen.queryByText("未绑定上下文，作用于整个项目"),
    ).not.toBeInTheDocument();
    // The standalone decision center was replaced by the inline decision tray;
    // the top bar no longer offers an entry button.
    expect(
      screen.queryByRole("button", { name: "审阅与决策中心" }),
    ).not.toBeInTheDocument();
    // With no pending decisions the tray takes up no space at all.
    expect(
      document.querySelector("[data-decision-tray]"),
    ).not.toBeInTheDocument();
    // New-conversation and chat-history entries were removed.
    expect(
      screen.queryByRole("button", { name: "新对话" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "历史聊天" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "工作区事实" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "最大化面板" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "收起 Agent 面板" }),
    ).toBeInTheDocument();
    expect(document.querySelector('[title="拖拽调整高度"]')).toHaveClass(
      "cursor-ns-resize",
    );
    expect(document.querySelector('[title="拖拽调整宽度"]')).toHaveClass(
      "cursor-ew-resize",
    );
    expect(document.querySelector('[title="拖拽调整大小"]')).toHaveClass(
      "cursor-nwse-resize",
    );
    expect(
      screen.getByRole("textbox", { name: "输入修改意图，@ 可引用对象…" }),
    ).toHaveClass("min-h-[32px]", "max-h-24");
  });

  it("pops the dock open with the inline tray when a production confirmation arrives live", async () => {
    useAgentDockUiStore.getState().setOpen(false);
    renderDock();
    expect(document.querySelector("[data-agent-dock]")).not.toBeInTheDocument();

    act(() =>
      useExecutionAuthorizationStore.setState({
        projectId: "p1",
        items: [
          {
            id: "auth-image-live",
            transactionId: "tx1",
            specialistRunId: "run-visual",
            executionRequestId: "request-image",
            targetRef: "project:assets",
            scope: { operation: "image_generation" },
            status: "PENDING",
            authorizationToken: "token-image",
            provider: "dashscope",
            model: "qwen-image-2.0-pro",
            maxCandidates: 1,
            createdAt: "now",
          },
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
    expect(
      screen.getByRole("textbox", { name: "输入修改意图，@ 可引用对象…" }),
    ).toBeInTheDocument();
  });

  it("keeps workspace and collapse interactions without maximize controls", async () => {
    useAgentDockUiStore.getState().setOpen(true);
    renderDock();

    fireEvent.click(screen.getByRole("button", { name: "工作区事实" }));
    expect(screen.getByText("当前任务")).toBeInTheDocument();
    expect(screen.getByText("素材概况（0）")).toBeInTheDocument();

    // Chat input stays while the workspace panel is expanded (the chat view is
    // no longer replaced by a decision view).
    expect(
      screen.getByRole("textbox", { name: "输入修改意图，@ 可引用对象…" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "最大化面板" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "还原面板" }),
    ).not.toBeInTheDocument();
    expect(
      document.querySelector('[title="拖拽调整高度"]'),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "收起 Agent 面板" }));
    expect(document.querySelector("[data-agent-dock]")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "创作助手" }),
    ).toBeInTheDocument();
  });

  it("resizes from the top and left handles and closes with Escape", async () => {
    useAgentDockUiStore.getState().setOpen(true);
    renderDock();
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
    expect(
      screen.getByRole("button", { name: "创作助手" }),
    ).toBeInTheDocument();
  });

  it("keeps an in-flight Creator SSE message compact until it completes", () => {
    useAgentDockUiStore.getState().setOpen(true);
    useCreatorSessionStore.setState((state) => ({
      ...state,
      session: { ...state.session!, status: "RUNNING" },
      messages: [
        {
          messageId: "user-1",
          messageSeq: 1,
          role: "user",
          source: "initial_goal",
          content: [{ type: "text", text: "汇报实时进度" }],
          metadata: {},
          createdAt: "now",
        },
      ],
      streamingAssistantMessages: {
        "assistant-stream-1": {
          messageId: "assistant-stream-1",
          firstEventSeq: 10,
          deltas: {
            1: "- **第一项**\n- [详情](https://example.com) 与 `内联代码`",
            0: "## 实时结果\n\n",
          },
          thinkingDeltas: { 2: "正在核对真实上下文。" },
          createdAt: "now",
        },
      },
    }));
    renderDock();

    const thinking = document.querySelector<HTMLElement>(
      "[data-agent-thinking]",
    )!;
    const assistant = thinking.closest<HTMLElement>("[data-agent-message]")!;
    expect(assistant).toHaveClass(
      "text-[11px]",
      "leading-5",
      "text-[var(--color-text-secondary)]",
    );
    expect(
      screen.queryByRole("heading", { level: 2, name: "实时结果" }),
    ).not.toBeInTheDocument();
    expect(assistant.querySelector("ul")).not.toBeInTheDocument();
    expect(thinking).toBeInTheDocument();
    expect(thinking).toHaveAttribute("data-expanded", "false");
    expect(thinking).toHaveTextContent("思考中");
    expect(
      thinking.querySelector("[data-agent-thinking-output]"),
    ).not.toBeInTheDocument();
  });

  it("shows streaming tool status without exposing internal JSON details", async () => {
    useAgentDockUiStore.getState().setOpen(true);
    const user = {
      messageId: "user-stream-tool",
      messageSeq: 1,
      role: "user" as const,
      source: "initial_goal",
      content: [{ type: "text" as const, text: "读取计划" }],
      metadata: {},
      createdAt: "now",
    };
    useCreatorSessionStore.setState((state) => ({
      ...state,
      session: { ...state.session!, status: "RUNNING" },
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
    }));
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
      useCreatorSessionStore.setState((state) => ({
        streamingAssistantMessages: {
          ...state.streamingAssistantMessages,
          "assistant-stream-tool": {
            ...state.streamingAssistantMessages["assistant-stream-tool"],
            deltas: {
              ...state.streamingAssistantMessages["assistant-stream-tool"]
                .deltas,
              2: '.json"}}\n```',
            },
          },
        },
      })),
    );
    await waitFor(() =>
      expect(streamingAction).toHaveTextContent("读取素材分析处理中"),
    );
    expect(
      within(streamingAction).queryByText(/"path": "plan.json"/),
    ).not.toBeInTheDocument();

    act(() =>
      useCreatorSessionStore.setState({
        streamingAssistantMessages: {},
        messages: [
          user,
          {
            messageId: "assistant-stream-tool",
            messageSeq: 2,
            role: "assistant",
            source: "creator_agent",
            content: [
              {
                type: "text",
                text: '我先读取计划。\n```json\n{"action":"tool_call","tool":"read_project_file","arguments":{"path":"plan.json"}}\n```',
              },
            ],
            metadata: {
              providerThinking: "确认需要读取的文件。",
              actionId: "action-stream-tool",
              parsedAction: {
                action: "tool_call",
                tool: "read_project_file",
                arguments: { path: "plan.json" },
              },
            },
            createdAt: "now",
          },
        ],
        events: [
          {
            eventId: "tool-started-live",
            seq: 20,
            type: "agent.tool_started",
            projectId: "p1",
            creatorSessionId: "session-1",
            at: "now",
            data: { actionId: "action-stream-tool", tool: "read_project_file" },
          },
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

    act(() =>
      useCreatorSessionStore.setState((state) => ({
        messages: [
          ...state.messages,
          {
            messageId: "result-stream-tool",
            messageSeq: 3,
            role: "user",
            source: "runtime_action_result",
            content: [
              { type: "text", text: '[RUNTIME_ACTION_RESULT]\n\n{"ok":true}' },
            ],
            metadata: {
              actionId: "action-stream-tool",
              tool: "read_project_file",
            },
            createdAt: "now",
          },
        ],
        events: [
          ...state.events,
          {
            eventId: "tool-completed-live",
            seq: 21,
            type: "agent.tool_completed",
            projectId: "p1",
            creatorSessionId: "session-1",
            at: "now",
            data: { actionId: "action-stream-tool", tool: "read_project_file" },
          },
        ],
      })),
    );
    await waitFor(() => expect(tool).toHaveAttribute("data-expanded", "false"));
    expect(tool).toHaveTextContent("读取素材分析完成");
    expect(
      within(tool).queryByText(/"path": "plan.json"/),
    ).not.toBeInTheDocument();
  });

  it("renders yield_until_runtime_event as a collapsed waiting action", () => {
    useAgentDockUiStore.getState().setOpen(true);
    useCreatorSessionStore.setState({
      messages: [
        {
          messageId: "user-yield",
          messageSeq: 1,
          role: "user",
          source: "initial_goal",
          content: [{ type: "text", text: "等待剪辑" }],
          metadata: {},
          createdAt: "now",
        },
        {
          messageId: "assistant-yield",
          messageSeq: 2,
          role: "assistant",
          source: "creator_agent",
          content: [
            {
              type: "text",
              text: '剪辑任务仍在运行。\n```json\n{"action":"yield_until_runtime_event","arguments":{"waitForRunIds":["run-video-1"],"reason":"等待 Source Intelligence 完成素材分析，以便 Runtime 投影 Timeline 和 Element，然后委派 AI Editing Director 进行剪辑"}}\n```',
            },
          ],
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
          createdAt: "now",
        },
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
      within(waiting).queryByRole("button", { name: "详情" }),
    ).not.toBeInTheDocument();
    expect(
      within(waiting).queryByText(/"run-video-1"/),
    ).not.toBeInTheDocument();
  });

  it("keeps the focused modification editor writable and submits at a live SSE boundary", async () => {
    const { calls } = installMockFetch([
      {
        match: "/projects/p1/messages",
        method: "POST",
        response: {
          json: {
            messageSeq: 2,
            eventSeq: 20,
            classification: "mutation_instruction",
            appendState: "queued_until_message_boundary",
            creatorSessionId: "session-1",
            conversationId: "conversation-1",
          },
        },
      },
    ]);
    useAgentDockUiStore.getState().setOpen(true);
    renderDock();

    const textbox = screen.getByRole("textbox", {
      name: "输入修改意图，@ 可引用对象…",
    });
    textbox.focus();
    textbox.textContent = "请把故事设定在温暖厨房";
    fireEvent.input(textbox);
    expect(document.activeElement).toBe(textbox);
    expect(textbox).toHaveAttribute("contenteditable", "true");

    act(() =>
      useCreatorSessionStore.setState((state) => ({
        session: { ...state.session!, status: "RUNNING" },
        streamingAssistantMessages: {
          "assistant-live": {
            messageId: "assistant-live",
            firstEventSeq: 19,
            deltas: { 0: "正在处理已有计划。" },
            thinkingDeltas: {},
            createdAt: "now",
          },
        },
      })),
    );

    await waitFor(() => {
      const liveTextbox = screen.getByRole("textbox", {
        name: "输入修改意图，@ 可引用对象…",
      });
      expect(liveTextbox).toBe(textbox);
      expect(liveTextbox).toHaveAttribute("contenteditable", "true");
      expect(liveTextbox).toHaveTextContent("请把故事设定在温暖厨房");
      expect(document.activeElement).toBe(liveTextbox);
    });

    fireEvent.keyDown(textbox, { key: "Enter" });
    await waitFor(() =>
      expect(
        calls.some((call) => call.url.includes("/projects/p1/messages")),
      ).toBe(true),
    );
    expect(
      calls.find((call) => call.url.includes("/projects/p1/messages"))?.body,
    ).toMatchObject({
      creatorSessionId: "session-1",
      conversationId: "conversation-1",
      message: "请把故事设定在温暖厨房",
    });
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

    const textbox = screen.getByRole("textbox", {
      name: "输入修改意图，@ 可引用对象…",
    });
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
      json: async () => ({
        messageSeq: 2,
        eventSeq: 20,
        classification: "mutation_instruction",
        appendState: "queued_until_message_boundary",
        creatorSessionId: "session-1",
        conversationId: "conversation-1",
      }),
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

  it("morphs the composer button into a stop control while agents run with an empty input", async () => {
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
    useCreatorSessionStore.setState((state) => ({
      session: { ...state.session!, status: "RUNNING" },
    }));
    useAgentDockUiStore.getState().setOpen(true);
    renderDock();

    // Running + empty input → the stop button replaces send, with a breathing glow
    const stop = screen.getByRole("button", { name: "停止所有 Agent" });
    expect(stop).toHaveClass("agent-dock-stop-glow");
    expect(
      screen.queryByRole("button", { name: "发送" }),
    ).not.toBeInTheDocument();

    // Running + input has content → back to a clickable send button
    const textbox = screen.getByRole("textbox", {
      name: "输入修改意图，@ 可引用对象…",
    });
    textbox.textContent = "运行中追加指令";
    fireEvent.input(textbox);
    expect(
      screen.queryByRole("button", { name: "停止所有 Agent" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "发送" })).toBeEnabled();

    // Clearing the input → stop button returns; clicking interrupts the whole Creator Session
    textbox.textContent = "";
    fireEvent.input(textbox);
    fireEvent.click(screen.getByRole("button", { name: "停止所有 Agent" }));
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

  it("keeps the send button whenever agents are idle, regardless of input content", () => {
    useAgentDockUiStore.getState().setOpen(true);
    renderDock();

    // Idle + empty input → disabled (greyed) send button
    expect(
      screen.queryByRole("button", { name: "停止所有 Agent" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "发送" })).toBeDisabled();

    // Idle + has content → clickable send button
    const textbox = screen.getByRole("textbox", {
      name: "输入修改意图，@ 可引用对象…",
    });
    textbox.textContent = "新的修改意图";
    fireEvent.input(textbox);
    expect(screen.getByRole("button", { name: "发送" })).toBeEnabled();
  });

  it("mounts the origin run block with Timeline/Element targets", () => {
    useAgentDockUiStore.getState().setOpen(true);
    useCreatorTaskViewStore.setState({
      projectId: "p1",
      runs: [
        {
          id: "run-1",
          role: "visual_development_agent",
          displayName: "故事规划",
          status: "SUCCEEDED",
          targetRefs: ["timeline:main"],
          taskRefs: [],
          metadata: {},
        },
      ],
    });
    renderDock();
    act(() => useAgentDockUiStore.getState().setTab("conversation"));

    expect(screen.getByText("制作流程")).toBeInTheDocument();
    expect(
      screen.getByText(/故事规划 · 主时间轴 · 已完成/),
    ).toBeInTheDocument();
  });

  it("keeps file-native review feedback on the Session message API", async () => {
    const { calls } = installMockFetch([
      {
        match: "/projects/p1/messages",
        response: {
          json: {
            messageSeq: 1,
            eventSeq: 1,
            classification: "review_revise",
            appendState: "queued_until_message_boundary",
            creatorSessionId: "session-1",
            conversationId: "conversation-1",
          },
        },
      },
    ]);
    useCreatorSessionStore.setState((state) => ({
      ...state,
      session: { ...state.session!, status: "PENDING_REVIEW" },
    }));
    useFileProjectReviewStore.setState({
      projectId: "p1",
      reviews: [fileProjectReview()],
      etag: '"file-token-1"',
      syncStatus: "healthy",
    });
    useAgentDockUiStore.getState().setOpen(true);
    renderDock();
    // File review content shows up directly in the inline decision tray while
    // the chat input remains usable on the same screen.
    await waitFor(() =>
      expect(
        document.querySelector("[data-decision-tray]"),
      ).toBeInTheDocument(),
    );

    const textbox = screen.getByRole("textbox", {
      name: "输入修改意图，@ 可引用对象…",
    });
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
        {
          messageId: "user-1",
          messageSeq: 1,
          role: "user",
          source: "initial_goal",
          content: [{ type: "text", text: "请检查当前计划" }],
          metadata: {},
          createdAt: "now",
        },
        {
          messageId: "assistant-1",
          messageSeq: 2,
          role: "assistant",
          source: "creator_agent",
          content: [
            {
              type: "text",
              text: '我先读取当前计划。\n```json\n{"action":"tool_call","tool":"read_project_file"}\n```',
            },
          ],
          metadata: {
            actionId: "action-1",
            parsedAction: {
              action: "tool_call",
              tool: "read_project_file",
              arguments: { path: "plan.json" },
            },
          },
          createdAt: "now",
        },
        {
          messageId: "result-1",
          messageSeq: 3,
          role: "user",
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
          createdAt: "now",
        },
      ],
      events: [
        {
          eventId: "tool-started",
          seq: 1,
          type: "agent.tool_started",
          projectId: "p1",
          creatorSessionId: "session-1",
          at: "now",
          data: { actionId: "action-1", tool: "read_project_file" },
        },
        {
          eventId: "tool-completed",
          seq: 2,
          type: "agent.tool_completed",
          projectId: "p1",
          creatorSessionId: "session-1",
          at: "now",
          data: { actionId: "action-1", remainingActionIds: [] },
        },
      ],
    });
    useCreatorSessionStore.setState((state) => ({
      session: { ...state.session!, status: "RUNNING" },
    }));
    renderDock();

    const userBubble = screen
      .getByText("请检查当前计划")
      .closest("[data-agent-message]");
    expect(userBubble).toHaveClass("bg-[var(--color-accent)]", "text-white");
    const turn = userBubble?.closest("[data-agent-turn]");
    expect(turn).toHaveClass("space-y-2");
    const responseFlow = turn?.querySelector(
      ":scope > [data-agent-response-flow]",
    );
    expect(responseFlow).toHaveClass("space-y-2");
    expect(screen.getByText("我先读取当前计划。")).toBeInTheDocument();
    expect(screen.queryByText(/"action"/)).not.toBeInTheDocument();
    expect(screen.queryByText(/RUNTIME_ACTION_RESULT/)).not.toBeInTheDocument();
    expect(
      responseFlow?.querySelector("[data-agent-thinking]"),
    ).not.toBeInTheDocument();

    const toolStatus = screen.getByText("读取素材分析完成");
    expect(toolStatus.parentElement).toHaveClass("text-[var(--color-success)]");
    expect(toolStatus.closest("[data-agent-tool]")?.parentElement).toBe(
      responseFlow,
    );
    expect(
      screen.queryByRole("button", { name: "详情" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/"path": "plan.json"/)).not.toBeInTheDocument();
    expect(screen.queryByText(/"head": "h2"/)).not.toBeInTheDocument();
  });

  it("folds legacy file Runtime tool turns into the anchored tool card without placeholder bubbles", () => {
    useAgentDockUiStore.getState().setOpen(true);
    useCreatorSessionStore.setState({
      messages: [
        {
          messageId: "user-file-runtime",
          messageSeq: 1,
          role: "user",
          source: "agent_dock",
          content: [{ type: "text", text: "读取当前项目" }],
          metadata: {},
          createdAt: "now",
        },
        {
          messageId: "assistant-file-runtime",
          messageSeq: 2,
          role: "assistant",
          source: "file_agent_runtime",
          content: [{ type: "text", text: "准备调用工具：read_project" }],
          metadata: {
            runId: "run-file-runtime",
            toolCalls: [{ id: "call-file-runtime", name: "read_project" }],
          },
          createdAt: "now",
        },
        {
          messageId: "tool-file-runtime",
          messageSeq: 3,
          role: "tool",
          source: "file_agent_runtime",
          content: [{ type: "text", text: '{"ok":true,"generation":2}' }],
          metadata: {
            runId: "run-file-runtime",
            toolCallId: "call-file-runtime",
            toolName: "read_project",
          },
          createdAt: "now",
        },
      ],
      events: [
        {
          eventId: "file-runtime-completed",
          seq: 1,
          type: "agent.tool.completed",
          projectId: "p1",
          creatorSessionId: "session-1",
          at: "now",
          data: {
            runId: "run-file-runtime",
            toolCallId: "call-file-runtime",
            toolName: "read_project",
            messageId: "tool-file-runtime",
            messageSeq: 3,
          },
        },
      ],
    });
    renderDock();

    expect(
      screen.queryByText("准备调用工具：read_project"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText('{"ok":true,"generation":2}'),
    ).not.toBeInTheDocument();
    expect(document.querySelectorAll("[data-agent-message]")).toHaveLength(1);
    const tool = document.querySelector<HTMLElement>(
      '[data-agent-tool="call-file-runtime"]',
    )!;
    expect(tool).toBeInTheDocument();
    expect(tool).toHaveTextContent("查看视频方案完成");
    expect(tool.closest("[data-agent-response-flow]")).toBeInTheDocument();
    expect(
      within(tool).queryByRole("button", { name: "详情" }),
    ).not.toBeInTheDocument();
    expect(tool).not.toHaveTextContent('"generation": 2');
  });

  it("renders rejection feedback once as a compact review card", () => {
    useAgentDockUiStore.getState().setOpen(true);
    const feedbackMessage = {
      messageId: "review-feedback-first",
      messageSeq: 1,
      role: "user" as const,
      source: "review_rejection_feedback",
      content: [
        {
          type: "text" as const,
          text: "【系统自动消息 · 用户审阅反馈】原始内部消息",
        },
      ],
      metadata: {
        decisionId: "decision-review-feedback",
        rejectionFeedback: {
          action: "UNDO_AND_REGENERATE",
          feedbackNote: "人物仍像巅峰时期；请保持身份一致，改成落魄时期",
        },
        targets: [{ label: "哈兰德 · 落魄时期分镜图" }],
      },
      createdAt: "now",
    };
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
    expect(cards[0]).toHaveTextContent(
      "人物仍像巅峰时期；请保持身份一致，改成落魄时期",
    );
    expect(cards[0]).not.toHaveTextContent("原始内部消息");
  });

  it("embeds the replayable Sub-agent SSE stream in one natural delegate tool card", async () => {
    useAgentDockUiStore.getState().setOpen(true);
    useAgentDockUiStore.getState().setAllowExpandDetails(true);
    useCreatorSessionStore.setState((state) => ({
      ...state,
      session: { ...state.session!, status: "RUNNING" },
      messages: [
        {
          messageId: "user-delegate",
          messageSeq: 1,
          role: "user",
          source: "initial_goal",
          content: [{ type: "text", text: "完善第一幕" }],
          metadata: {},
          createdAt: "now",
        },
        {
          messageId: "assistant-delegate",
          messageSeq: 2,
          role: "assistant",
          source: "creator_agent",
          content: [
            {
              type: "text",
              text: '我会请视觉开发 Agent 完善开场视觉。\n```json\n{"action":"tool_call","tool":"delegate_to_agent"}\n```',
            },
          ],
          metadata: {
            actionId: "delegate-action",
            parsedAction: {
              action: "tool_call",
              tool: "delegate_to_agent",
              arguments: {
                role: "visual_development_agent",
                target_refs: ["project:assets"],
                task: "请完善开场视觉，并说明改动结果。",
              },
            },
          },
          createdAt: "now",
        },
      ],
    }));
    act(() =>
      useCreatorSessionStore.getState().ingestEvents([
        {
          eventId: "delegate-started",
          seq: 1,
          type: "agent.tool_started",
          projectId: "p1",
          creatorSessionId: "session-1",
          at: "now",
          data: {
            actionId: "delegate-action",
            tool: "delegate_to_agent",
            role: "visual_development_agent",
            roleDisplayName: "视觉开发",
            delegationText: "请完善开场视觉，并说明改动结果。",
            targetRefs: ["project:assets"],
          },
        },
        {
          eventId: "sub-delta",
          seq: 2,
          type: "subagent.message_delta",
          projectId: "p1",
          creatorSessionId: "session-1",
          at: "now",
          data: {
            parentActionId: "delegate-action",
            runId: "run-story-1",
            role: "visual_development_agent",
            messageId: "sub-message-1",
            deltaIndex: 0,
            delta: "## 正在规划\n\n先梳理冲突。",
          },
        },
        {
          eventId: "nested-started",
          seq: 3,
          type: "subagent.tool_started",
          projectId: "p1",
          creatorSessionId: "session-1",
          at: "now",
          data: {
            parentActionId: "delegate-action",
            runId: "run-story-1",
            role: "visual_development_agent",
            toolCallId: "nested-tool-1",
            tool: "read_project_file",
            arguments: { projectId: "p1", fileId: "source-notes" },
            state: "started",
          },
        },
        {
          eventId: "nested-completed",
          seq: 4,
          type: "subagent.tool_completed",
          projectId: "p1",
          creatorSessionId: "session-1",
          at: "now",
          data: {
            parentActionId: "delegate-action",
            runId: "run-story-1",
            role: "visual_development_agent",
            toolCallId: "nested-tool-1",
            tool: "read_project_file",
            result: { summary: "读取完成" },
            state: "succeeded",
          },
        },
      ]),
    );
    renderDock();

    const delegateTool = document.querySelector<HTMLElement>(
      '[data-agent-tool="delegate-action"]',
    )!;
    expect(delegateTool).toHaveTextContent("视觉开发处理中");
    expect(delegateTool).toHaveAttribute("data-expanded", "false");
    fireEvent.click(within(delegateTool).getByRole("button", { name: "详情" }));
    expect(delegateTool).toHaveAttribute("data-expanded", "true");
    expect(
      screen.getByText("请完善开场视觉，并说明改动结果。"),
    ).toBeInTheDocument();
    expect(screen.getByText("目标：素材与生成结果")).toBeInTheDocument();
    expect(screen.queryByText(/## 正在规划/)).not.toBeInTheDocument();
    expect(screen.getByText("实时输出中")).toBeInTheDocument();
    expect(screen.getByText("处理中")).toBeInTheDocument();
    const subagentMessage = document.querySelector(
      '[data-subagent-message="sub-message-1"]',
    )!;
    expect(subagentMessage).toHaveClass(
      "text-[11px]",
      "leading-5",
      "text-[var(--color-text-secondary)]",
    );
    expect(subagentMessage).not.toHaveClass(
      "rounded-md",
      "bg-[var(--color-bg-card)]/80",
    );
    expect(document.querySelector("[data-subagent-input]")).toHaveClass(
      "max-h-32",
      "overflow-y-auto",
    );
    expect(document.querySelector("[data-subagent-output]")).toHaveClass(
      "max-h-[min(24rem,50vh)]",
      "overflow-y-auto",
      "overscroll-contain",
      "touch-pan-y",
    );
    expect(screen.getByText("读取素材分析完成")).toBeInTheDocument();
    expect(screen.queryByText(/"role":/)).not.toBeInTheDocument();
    expect(screen.queryByText(/"target_refs":/)).not.toBeInTheDocument();

    act(() =>
      useCreatorSessionStore.getState().ingestEvent({
        eventId: "sub-completed",
        seq: 5,
        type: "subagent.message_completed",
        projectId: "p1",
        creatorSessionId: "session-1",
        at: "now",
        data: {
          parentActionId: "delegate-action",
          runId: "run-story-1",
          role: "visual_development_agent",
          messageId: "sub-message-1",
          text: "[SUCCESS]\n## 已完成\n\n第一幕冲突已完善。",
          finishReason: "stop",
        },
      }),
    );
    await waitFor(() =>
      expect(
        document.querySelector('[data-subagent-message="sub-message-1"]'),
      ).toHaveTextContent("## 已完成"),
    );
    expect(
      document.querySelector('[data-subagent-message="sub-message-1"]'),
    ).not.toHaveTextContent("## 正在规划");
    expect(
      document.querySelector('[data-subagent-message="sub-message-1"]'),
    ).toHaveTextContent("[SUCCESS]");
    expect(
      document.querySelector('[data-subagent-message="sub-message-1"]'),
    ).toHaveTextContent("已完成");

    const nestedTool = document.querySelector(
      '[data-subagent-tool="nested-tool-1"]',
    )!;
    fireEvent.click(
      within(nestedTool as HTMLElement).getByRole("button", { name: "详情" }),
    );
    expect(screen.getByText(/"fileId": "source-notes"/)).toBeInTheDocument();
    expect(screen.getByText(/"summary": "读取完成"/)).toBeInTheDocument();
  });

  it("renders canonical Sub-agent tool arguments in one live tool card", async () => {
    useAgentDockUiStore.getState().setOpen(true);
    useAgentDockUiStore.getState().setAllowExpandDetails(true);
    useCreatorSessionStore.setState((state) => ({
      ...state,
      session: { ...state.session!, status: "RUNNING" },
      messages: [
        {
          messageId: "assistant-native-tool",
          messageSeq: 1,
          role: "assistant",
          source: "creator_agent",
          content: [{ type: "text", text: "委派故事规划。" }],
          metadata: {
            actionId: "delegate-native-tool",
            parsedAction: {
              action: "tool_call",
              tool: "delegate_to_agent",
              arguments: {
                role: "visual_development_agent",
                task: "读取故事文件",
              },
            },
          },
          createdAt: "now",
        },
      ],
    }));
    act(() =>
      useCreatorSessionStore.getState().ingestEvents([
        {
          eventId: "delegate-native-start",
          seq: 1,
          type: "agent.tool_started",
          projectId: "p1",
          creatorSessionId: "session-1",
          at: "now",
          data: {
            actionId: "delegate-native-tool",
            tool: "delegate_to_agent",
            role: "visual_development_agent",
            roleDisplayName: "故事规划",
            delegationText: "读取故事文件",
          },
        },
        {
          eventId: "native-tool-started-initial",
          seq: 2,
          type: "subagent.tool_started",
          projectId: "p1",
          creatorSessionId: "session-1",
          at: "now",
          data: {
            parentActionId: "delegate-native-tool",
            runId: "run-native-tool",
            role: "visual_development_agent",
            messageId: "message-native-tool",
            toolCallId: "call-native-tool",
            tool: "read_project_file",
            arguments: { path: "story/outline.md" },
            state: "started",
          },
        },
      ]),
    );
    renderDock();

    const delegateTool = document.querySelector<HTMLElement>(
      '[data-agent-tool="delegate-native-tool"]',
    )!;
    fireEvent.click(within(delegateTool).getByRole("button", { name: "详情" }));
    const tool = document.querySelector<HTMLElement>(
      '[data-subagent-tool="call-native-tool"]',
    )!;
    expect(tool).toHaveAttribute("data-expanded", "false");
    fireEvent.click(within(tool).getByRole("button", { name: "详情" }));
    expect(tool).toHaveAttribute("data-expanded", "true");
    expect(tool).toHaveTextContent("读取素材分析处理中");
    expect(
      tool.querySelector("[data-subagent-tool-arguments]"),
    ).toHaveTextContent('"path": "story/outline.md"');

    act(() =>
      useCreatorSessionStore.getState().ingestEvents([
        {
          eventId: "native-tool-started",
          seq: 4,
          type: "subagent.tool_started",
          projectId: "p1",
          creatorSessionId: "session-1",
          at: "now",
          data: {
            parentActionId: "delegate-native-tool",
            runId: "run-native-tool",
            role: "visual_development_agent",
            messageId: "message-native-tool",
            toolCallId: "call-native-tool",
            tool: "read_project_file",
            arguments: { path: "story/outline.md" },
            state: "started",
          },
        },
        {
          eventId: "native-tool-completed",
          seq: 5,
          type: "subagent.tool_completed",
          projectId: "p1",
          creatorSessionId: "session-1",
          at: "now",
          data: {
            parentActionId: "delegate-native-tool",
            runId: "run-native-tool",
            role: "visual_development_agent",
            messageId: "message-native-tool",
            toolCallId: "call-native-tool",
            tool: "read_project_file",
            result: { ok: true },
            state: "succeeded",
          },
        },
      ]),
    );
    await waitFor(() => expect(tool).toHaveAttribute("data-expanded", "false"));
    expect(
      document.querySelectorAll('[data-subagent-tool="call-native-tool"]'),
    ).toHaveLength(1);
  });

  it("renders a review-blocked delegation as waiting, not failed", () => {
    useAgentDockUiStore.getState().setOpen(true);
    useCreatorSessionStore.setState((state) => ({
      ...state,
      session: { ...state.session!, status: "PENDING_REVIEW" },
      messages: [
        {
          messageId: "assistant-review-wait",
          messageSeq: 1,
          role: "assistant",
          source: "creator_agent",
          content: [{ type: "text", text: "继续生成 ep22 视频。" }],
          metadata: {
            actionId: "delegate-review-wait",
            parsedAction: {
              action: "tool_call",
              tool: "delegate_to_agent",
              arguments: {
                role: "r2v_generation_director",
                target_refs: ["element:ep22"],
                task: "生成 ep22 视频",
              },
            },
          },
          createdAt: "now",
        },
      ],
    }));
    act(() =>
      useCreatorSessionStore.getState().ingestEvents([
        {
          eventId: "delegate-review-wait-start",
          seq: 1,
          type: "agent.tool_started",
          projectId: "p1",
          creatorSessionId: "session-1",
          at: "now",
          data: {
            actionId: "delegate-review-wait",
            tool: "delegate_to_agent",
            role: "r2v_generation_director",
            targetRefs: ["element:ep22"],
          },
        },
        {
          eventId: "delegate-review-wait-blocked",
          seq: 2,
          type: "subagent.blocked",
          projectId: "p1",
          creatorSessionId: "session-1",
          at: "now",
          data: {
            parentActionId: "delegate-review-wait",
            runId: "run-review-wait",
            role: "r2v_generation_director",
            targetRefs: ["element:ep22"],
            waitingReview: true,
            summary:
              "element:ep22 的分镜图已生成，视频尚未开始。请先审阅分镜图；审阅通过后将自动继续生成视频。",
          },
        },
        {
          eventId: "delegate-review-wait-completed",
          seq: 3,
          type: "agent.tool_completed",
          projectId: "p1",
          creatorSessionId: "session-1",
          at: "now",
          data: {
            actionId: "delegate-review-wait",
            runId: "parent-run",
            tool: "delegate_to_agent",
            failed: false,
          },
        },
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
    expect(waitingNotice).not.toHaveClass("text-[var(--color-danger)]");
    expect(
      useCreatorSessionStore.getState().subagentActivities[
        "delegate-review-wait"
      ],
    ).toMatchObject({ waitingReview: true, terminalKind: "BLOCKED" });
  });

  it("moves a streamed Sub-agent function call into its tool card and preserves detail scrolling", async () => {
    useAgentDockUiStore.getState().setOpen(true);
    useAgentDockUiStore.getState().setAllowExpandDetails(true);
    useCreatorSessionStore.setState((state) => ({
      ...state,
      session: { ...state.session!, status: "RUNNING" },
      messages: [
        {
          messageId: "user-function",
          messageSeq: 1,
          role: "user",
          source: "initial_goal",
          content: [{ type: "text", text: "读取故事文件" }],
          metadata: {},
          createdAt: "now",
        },
        {
          messageId: "assistant-function",
          messageSeq: 2,
          role: "assistant",
          source: "creator_agent",
          content: [{ type: "text", text: "委派故事规划。" }],
          metadata: {
            actionId: "delegate-function",
            parsedAction: {
              action: "tool_call",
              tool: "delegate_to_agent",
              arguments: {
                role: "visual_development_agent",
                target_refs: ["timeline:main"],
                task: "读取项目文件",
              },
            },
          },
          createdAt: "now",
        },
      ],
    }));
    act(() =>
      useCreatorSessionStore.getState().ingestEvents([
        {
          eventId: "delegate-function-start",
          seq: 1,
          type: "agent.tool_started",
          projectId: "p1",
          creatorSessionId: "session-1",
          at: "now",
          data: {
            actionId: "delegate-function",
            tool: "delegate_to_agent",
            role: "visual_development_agent",
            roleDisplayName: "故事规划",
            delegationText: "读取项目文件",
            targetRefs: ["timeline:main"],
          },
        },
        {
          eventId: "function-delta-1",
          seq: 2,
          type: "subagent.message_delta",
          projectId: "p1",
          creatorSessionId: "session-1",
          at: "now",
          data: {
            parentActionId: "delegate-function",
            runId: "run-function",
            role: "visual_development_agent",
            messageId: "message-function",
            deltaIndex: 0,
            delta:
              '<function=read_project_file><parameter=arguments>{"path":"story/',
          },
        },
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
      useCreatorSessionStore.getState().ingestEvent({
        eventId: "function-delta-2",
        seq: 3,
        type: "subagent.message_delta",
        projectId: "p1",
        creatorSessionId: "session-1",
        at: "now",
        data: {
          parentActionId: "delegate-function",
          runId: "run-function",
          role: "visual_development_agent",
          messageId: "message-function",
          deltaIndex: 1,
          delta: 'outline.md"}</parameter></function></tool_call>',
        },
      }),
    );
    await waitFor(() =>
      expect(streamingFunction).toHaveTextContent('"path": "story/outline.md"'),
    );

    act(() =>
      useCreatorSessionStore.getState().ingestEvents([
        {
          eventId: "function-message-completed",
          seq: 4,
          type: "subagent.message_completed",
          projectId: "p1",
          creatorSessionId: "session-1",
          at: "now",
          data: {
            parentActionId: "delegate-function",
            runId: "run-function",
            role: "visual_development_agent",
            messageId: "message-function",
            text: '<function=read_project_file><parameter=arguments>{"path":"story/outline.md"}</parameter></function></tool_call>',
            finishReason: "tool_call",
          },
        },
        {
          eventId: "function-tool-started",
          seq: 5,
          type: "subagent.tool_started",
          projectId: "p1",
          creatorSessionId: "session-1",
          at: "now",
          data: {
            parentActionId: "delegate-function",
            runId: "run-function",
            role: "visual_development_agent",
            toolCallId: "function-tool",
            tool: "read_project_file",
            arguments: { path: "story/outline.md" },
            state: "started",
          },
        },
        {
          eventId: "function-progress-1",
          seq: 6,
          type: "task.progress_updated",
          projectId: "p1",
          creatorSessionId: "session-1",
          at: "now",
          data: {
            specialistRunId: "run-function",
            taskId: "task-function",
            progress: 0.4,
            detail: "已读取前 400 行",
          },
        },
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
    fireEvent.click(within(nestedTool!).getByRole("button", { name: "详情" }));
    expect(nestedTool).toHaveAttribute("data-expanded", "true");
    expect(
      subagentMessage.querySelector('[data-agent-action="tool_call"]'),
    ).not.toBeInTheDocument();
    const toolOutput = nestedTool!.querySelector<HTMLElement>(
      "[data-subagent-tool-stream]",
    )!;
    expect(toolOutput).toHaveClass(
      "overflow-auto",
      "overscroll-contain",
      "touch-pan-y",
    );
    expect(toolOutput).toHaveTextContent("已读取前 400 行");
    Object.defineProperties(toolOutput, {
      scrollHeight: { configurable: true, value: 900 },
      clientHeight: { configurable: true, value: 180 },
    });
    toolOutput.scrollTop = 420;

    act(() =>
      useCreatorSessionStore.getState().ingestEvent({
        eventId: "function-progress-2",
        seq: 7,
        type: "task.progress_updated",
        projectId: "p1",
        creatorSessionId: "session-1",
        at: "now",
        data: {
          specialistRunId: "run-function",
          taskId: "task-function",
          progress: 0.8,
          detail: "已读取前 800 行",
        },
      }),
    );
    await waitFor(() =>
      expect(toolOutput).toHaveTextContent("已读取前 800 行"),
    );
    expect(toolOutput.scrollTop).toBe(420);
    toolOutput.scrollTop = toolOutput.scrollHeight - toolOutput.clientHeight;
    expect(toolOutput.scrollTop).toBe(720);

    act(() =>
      useCreatorSessionStore.getState().ingestEvent({
        eventId: "function-tool-completed",
        seq: 8,
        type: "subagent.tool_completed",
        projectId: "p1",
        creatorSessionId: "session-1",
        at: "now",
        data: {
          parentActionId: "delegate-function",
          runId: "run-function",
          role: "visual_development_agent",
          toolCallId: "function-tool",
          tool: "read_project_file",
          result: { lines: 800 },
          state: "succeeded",
        },
      }),
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
    useCreatorSessionStore.setState((state) => ({
      ...state,
      session: { ...state.session!, status: "RUNNING" },
      messages: [
        {
          messageId: "user-service",
          messageSeq: 1,
          role: "user",
          source: "initial_goal",
          content: [{ type: "text", text: "执行剪辑" }],
          metadata: {},
          createdAt: "now",
        },
        {
          messageId: "assistant-service",
          messageSeq: 2,
          role: "assistant",
          source: "creator_agent",
          content: [{ type: "text", text: "我会委派剪辑任务。" }],
          metadata: {
            actionId: "delegate-service-action",
            parsedAction: {
              action: "tool_call",
              tool: "delegate_to_agent",
              arguments: {
                role: "ai_editing_director",
                target_refs: ["timeline:main"],
                task: "根据当前素材完成主 Timeline 的剪辑。",
              },
            },
          },
          createdAt: "now",
        },
      ],
    }));
    act(() =>
      useCreatorSessionStore.getState().ingestEvents([
        {
          eventId: "delegate-service-started",
          seq: 1,
          type: "agent.tool_started",
          projectId: "p1",
          creatorSessionId: "session-1",
          at: "now",
          data: {
            actionId: "delegate-service-action",
            tool: "delegate_to_agent",
            role: "ai_editing_director",
            roleDisplayName: "AI 剪辑导演",
            delegationText: "根据当前素材完成主 Timeline 的剪辑。",
            targetRefs: ["timeline:main"],
          },
        },
        {
          eventId: "delegate-service-completed",
          seq: 2,
          type: "agent.tool_completed",
          projectId: "p1",
          creatorSessionId: "session-1",
          at: "now",
          data: {
            actionId: "delegate-service-action",
            tool: "delegate_to_agent",
            status: "succeeded",
          },
        },
        {
          eventId: "sub-service-accepted",
          seq: 3,
          type: "subagent.accepted",
          projectId: "p1",
          creatorSessionId: "session-1",
          at: "now",
          data: {
            parentActionId: "delegate-service-action",
            runId: "run-service-1",
            role: "ai_editing_director",
            roleDisplayName: "AI 剪辑导演",
            delegationText: "根据当前素材完成主 Timeline 的剪辑。",
            targetRefs: ["timeline:main"],
          },
        },
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
      useCreatorSessionStore.getState().ingestEvent({
        eventId: "sub-service-terminal",
        seq: 4,
        type: "subagent.completed",
        projectId: "p1",
        creatorSessionId: "session-1",
        at: "now",
        data: {
          parentActionId: "delegate-service-action",
          runId: "run-service-1",
          role: "ai_editing_director",
          marker: "SUCCESS",
          status: "SUCCEEDED",
          summary: "剪辑方案已生成并等待执行确认。",
        },
      }),
    );
    act(() =>
      useCreatorSessionStore.getState().ingestEvent({
        eventId: "delegate-service-parent-completed",
        seq: 5,
        type: "agent.tool_completed",
        projectId: "p1",
        creatorSessionId: "session-1",
        at: "now",
        data: {
          actionId: "delegate-service-action",
          runId: "parent-agent-run-1",
          tool: "delegate_to_agent",
          status: "succeeded",
        },
      }),
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

  it("does not synthesize a thinking block when the provider emitted none", async () => {
    useAgentDockUiStore.getState().setOpen(true);
    useCreatorSessionStore.setState((state) => ({
      session: { ...state.session!, status: "RUNNING" },
      messages: [
        {
          messageId: "user-1",
          messageSeq: 1,
          role: "user",
          source: "agent_dock",
          content: [{ type: "text", text: "继续处理" }],
          metadata: {},
          createdAt: "now",
        },
      ],
    }));
    renderDock();

    const responseFlow = screen
      .getByText("继续处理")
      .closest("[data-agent-turn]")
      ?.querySelector(":scope > [data-agent-response-flow]");
    expect(
      responseFlow?.querySelector("[data-agent-thinking]"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("正在分析上下文并决定下一步操作。"),
    ).not.toBeInTheDocument();

    act(() =>
      useCreatorSessionStore.setState((state) => ({
        messages: [
          ...state.messages,
          {
            messageId: "assistant-1",
            messageSeq: 2,
            role: "assistant",
            source: "creator_agent",
            content: [{ type: "text", text: "已找到需要处理的内容。" }],
            metadata: {},
            createdAt: "now",
          },
        ],
      })),
    );
    await waitFor(() =>
      expect(
        responseFlow?.querySelector("[data-agent-thinking]"),
      ).not.toBeInTheDocument(),
    );
    expect(
      screen.getByText("已找到需要处理的内容。").closest("[data-agent-message]")
        ?.parentElement,
    ).toBe(responseFlow);

    act(() =>
      useCreatorSessionStore.setState((state) => ({
        session: { ...state.session!, status: "IDLE" },
      })),
    );
    await waitFor(() =>
      expect(
        responseFlow?.querySelector("[data-agent-thinking]"),
      ).not.toBeInTheDocument(),
    );
  });

  it("keeps each native tool call directly after its own thinking message", () => {
    useAgentDockUiStore.getState().setOpen(true);
    useCreatorSessionStore.setState({
      messages: [
        {
          messageId: "user-native-order",
          messageSeq: 1,
          role: "user",
          source: "initial_goal",
          content: [{ type: "text", text: "依次读取并写入文件" }],
          metadata: {},
          createdAt: "now",
        },
        {
          messageId: "assistant-native-read",
          messageSeq: 2,
          role: "assistant",
          source: "creator_agent",
          content: [],
          metadata: {
            providerThinking: "先检查当前文件。",
            actionId: "call-native-read",
            toolCall: {
              id: "call-native-read",
              name: "read_file",
              arguments: { file_path: "plan.txt" },
            },
          },
          createdAt: "now",
        },
        {
          messageId: "result-native-read",
          messageSeq: 3,
          role: "tool",
          source: "runtime_action_result",
          content: [{ type: "text", text: '{"content":"旧内容"}' }],
          metadata: { actionId: "call-native-read", tool: "read_file" },
          createdAt: "now",
        },
        {
          messageId: "assistant-native-write",
          messageSeq: 4,
          role: "assistant",
          source: "creator_agent",
          content: [],
          metadata: {
            providerThinking: "读取完成，现在写入。",
            actionId: "call-native-write",
            toolCall: {
              id: "call-native-write",
              name: "write_file",
              arguments: { file_path: "plan.txt", content: "新内容" },
            },
          },
          createdAt: "now",
        },
        {
          messageId: "result-native-write",
          messageSeq: 5,
          role: "tool",
          source: "runtime_action_result",
          content: [{ type: "text", text: '{"ok":true}' }],
          metadata: { actionId: "call-native-write", tool: "write_file" },
          createdAt: "now",
        },
      ],
    });
    renderDock();

    const responseFlow = screen
      .getByText("依次读取并写入文件")
      .closest("[data-agent-turn]")
      ?.querySelector(":scope > [data-agent-response-flow]")!;
    const readTool = responseFlow.querySelector<HTMLElement>(
      '[data-agent-tool="call-native-read"]',
    )!;
    const writeTool = responseFlow.querySelector<HTMLElement>(
      '[data-agent-tool="call-native-write"]',
    )!;
    const orderedItems = Array.from(responseFlow.children);
    const [readThinking, , writeThinking] = orderedItems;

    expect(orderedItems).toHaveLength(4);
    expect(readThinking).toHaveAttribute("data-agent-message");
    expect(orderedItems[1]).toBe(readTool);
    expect(writeThinking).toHaveAttribute("data-agent-message");
    expect(orderedItems[3]).toBe(writeTool);
    expect(responseFlow.querySelectorAll("[data-agent-thinking]")).toHaveLength(
      2,
    );
  });

  it("anchors the origin plan card after assistant narration inside the same human turn", () => {
    useAgentDockUiStore.getState().setOpen(true);
    useCreatorSessionStore.setState((state) => ({
      session: { ...state.session!, status: "RUNNING" },
      messages: [
        {
          messageId: "user-1",
          messageSeq: 1,
          role: "user",
          source: "initial_goal",
          content: [{ type: "text", text: "先制定计划" }],
          metadata: {},
          createdAt: "now",
        },
        {
          messageId: "assistant-1",
          messageSeq: 2,
          role: "assistant",
          source: "creator_agent",
          content: [
            {
              type: "text",
              text: '我会分两步推进。\n```json\n{"action":"plan","summary":"先完成故事规划"}\n```',
            },
          ],
          metadata: {
            parsedAction: {
              action: "plan",
              summary: "先完成故事规划",
              steps: ["1. 建立 Element", "2、安排重叠关系"],
              scope: ["timeline:main"],
            },
          },
          createdAt: "now",
        },
      ],
      events: [
        {
          eventId: "plan-1",
          seq: 1,
          type: "agent.plan",
          projectId: "p1",
          creatorSessionId: "session-1",
          at: "now",
          data: {
            summary: "先完成故事规划",
            steps: ["1. 建立 Element", "2、安排重叠关系"],
            scope: ["timeline:main"],
          },
        },
      ],
    }));
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
    expect(plan).toHaveClass(
      "border-[var(--color-accent)]/30",
      "bg-[var(--color-accent-soft)]",
    );
    expect(screen.getByText("建立 Element")).toBeInTheDocument();
    expect(screen.getByText("安排重叠关系")).toBeInTheDocument();
    expect(screen.queryByText("1. 建立 Element")).not.toBeInTheDocument();
    expect(screen.queryByText("2、安排重叠关系")).not.toBeInTheDocument();
    expect(screen.queryByText(/"action"/)).not.toBeInTheDocument();
    expect(
      responseFlow?.querySelector("[data-agent-thinking]"),
    ).not.toBeInTheDocument();
  });

  it("recomputes the live status label on a runtime language switch", async () => {
    // TC-PL-02 F-1: liveStatus is memoized from agent state; switching the
    // locale must still refresh the label on the mounted component, both
    // directions, without a remount.
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
