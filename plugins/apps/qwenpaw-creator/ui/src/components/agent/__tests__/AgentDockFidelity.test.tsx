import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AgentDock, { simplifyErrorMessage } from "@/components/agent/AgentDock";
import { useAgentDockUiStore } from "@/store/agentDockUiStore";
import { useCreatorSessionStore } from "@/store/creatorSessionStore";
import { useCreatorTaskViewStore } from "@/store/creatorTaskViewStore";
import { useFileProjectReviewStore } from "@/store/fileProjectReviewStore";
import { useExecutionAuthorizationStore } from "@/store/executionAuthorizationStore";
import { useCreatorInteractionStore } from "@/store/creatorInteractionStore";
import { projectDocument } from "@/test/creatorFixtures";
import { installMockFetch } from "@/test/mockFetch";
import {
  evt,
  makePendingAuthorization,
  makeReviewRecord,
  makeRun,
  msg,
  seedCreatorSession,
} from "@/test/agentFixtures";

function renderDock(switchProjects = false) {
  return render(
    <MemoryRouter initialEntries={["/project/p1/plan"]}>
      {switchProjects && <Link to="/project/p2/plan">切到第二项目</Link>}
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

const executionNotice = (overrides: Parameters<typeof msg>[0] = {}) =>
  asst({
    messageId: "execution-pause-1",
    source: "creator_execution_notice",
    text: "自动创作已暂停，作品尚未完成。已连续自动处理 5 轮，仍待处理序章剧本。",
    metadata: { executionPause: { reason: "consecutive_resume_limit" } },
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

function stagedSubmission(names = ["a.png"], switchProjects = false) {
  const { calls, fetchMock } = installMockFetch([
    { match: "/messages", method: "POST", response: { json: ACCEPTED } },
    { match: "/specialist-runs", response: { json: { items: [] } } },
    { match: "/tasks", response: { json: { items: [] } } },
    {
      match: "/projects/p1/project",
      response: { json: { project: projectDocument } },
    },
  ]);
  const uploads: Array<{
    resolve: (body: unknown) => void;
    reject: (error: Error) => void;
  }> = [];
  vi.stubGlobal("fetch", (input: RequestInfo | URL, init?: RequestInit) =>
    String(input).endsWith("/assets") && init?.method === "POST"
      ? new Promise<Response>((resolve, reject) =>
          uploads.push({
            resolve: (body) =>
              resolve({
                ok: true,
                status: 200,
                headers: new Headers(),
                json: async () => body,
              } as Response),
            reject,
          }),
        )
      : fetchMock(input, init),
  );
  useAgentDockUiStore.getState().setOpen(true);
  renderDock(switchProjects);
  fireEvent.change(document.querySelector("[data-agent-upload-input]")!, {
    target: {
      files: names.map((name) => new File([name], name, { type: "image/png" })),
    },
  });
  const write = (text: string) => {
    composerBox().textContent = text;
    fireEvent.input(composerBox());
  };
  write("指令 A");
  return { uploads, calls, write };
}

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

  it("pins and opens a pause buried by runtime notifications and assistant output only once", async () => {
    const { calls } = installMockFetch([]);
    useAgentDockUiStore.getState().setOpen(false);
    renderDock();
    const notice = executionNotice();
    const laterMessages = [
      msg({
        messageId: "runtime-notification",
        messageSeq: 3,
        source: "runtime_notification",
        text: "[RUNTIME_EVENT:completed] 后台任务已完成",
      }),
      asst({
        messageId: "later-tool",
        messageSeq: 4,
        text: "正在整理后台结果。",
        metadata: {
          actionId: "read-after-pause",
          parsedAction: {
            action: "tool_call",
            tool: "read_project_file",
            arguments: { path: "plan.json" },
          },
        },
      }),
      asst({
        messageId: "later-summary",
        messageSeq: 5,
        text: "已有素材已整理，剧本仍待处理。",
      }),
    ];
    act(() =>
      useCreatorSessionStore.setState({
        messages: [notice, ...laterMessages],
      }),
    );
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("自动创作已暂停，作品尚未完成");
    expect(alert).toHaveTextContent("仍待处理序章剧本");
    expect(alert.closest(".agent-conversation-feed")).toBeNull();
    expect(alert).toHaveClass("max-h-36", "overflow-y-auto");
    expect(alert).toHaveAttribute("tabindex", "0");
    expect(
      within(
        document.querySelector(".agent-conversation-feed") as HTMLElement,
      ).getByText(/自动创作已暂停，作品尚未完成/),
    ).toBeInTheDocument();
    expect(
      screen.getByText("已有素材已整理，剧本仍待处理。"),
    ).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("RUNTIME_EVENT");
    expect(useExecutionAuthorizationStore.getState().items).toHaveLength(0);
    expect(calls.filter((call) => call.method === "POST")).toHaveLength(0);

    fireEvent.keyDown(window, { key: "Escape" });
    act(() =>
      useCreatorSessionStore.setState({
        messages: [{ ...notice }, ...laterMessages],
      }),
    );
    expect(document.querySelector("[data-agent-dock]")).not.toBeInTheDocument();
    act(() =>
      useCreatorSessionStore.setState({
        messages: [
          notice,
          ...laterMessages,
          executionNotice({
            messageId: "execution-pause-2",
            messageSeq: 6,
            text: "自动创作已暂停，本轮未提交有效进展。",
            metadata: { executionPause: { reason: "no_committed_progress" } },
          }),
        ],
      }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "本轮未提交有效进展",
    );
    expect(screen.getByRole("alert")).not.toHaveTextContent(
      "已连续自动处理 5 轮",
    );
  });

  it.each(["initial_goal", "agent_dock", "review_revise", "frontend_editor"])(
    "clears the pinned pause on a new %s user instruction, keeping its history",
    (source) => {
      const notice = executionNotice();
      useCreatorSessionStore.setState({ messages: [notice] });
      renderDock();
      expect(screen.getByRole("alert")).toBeInTheDocument();
      act(() =>
        useCreatorSessionStore.setState({
          messages: [
            notice,
            msg({
              messageId: "new-instruction",
              messageSeq: 3,
              source,
              text: "请继续修改剧本",
            }),
            asst({
              messageId: "reply",
              messageSeq: 4,
              text: "收到新的修改指令。",
            }),
          ],
        }),
      );
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      expect(
        screen.getByText(/自动创作已暂停，作品尚未完成/),
      ).toBeInTheDocument();
      fireEvent.keyDown(window, { key: "Escape" });
      act(() =>
        useCreatorSessionStore.setState((state) => ({
          messages: [...state.messages],
        })),
      );
      expect(
        document.querySelector("[data-agent-dock]"),
      ).not.toBeInTheDocument();
    },
  );

  it("clears the pause as soon as a new instruction is submitted", async () => {
    installMockFetch([
      { match: "/messages", method: "POST", response: { json: ACCEPTED } },
    ]);
    useCreatorSessionStore.setState({ messages: [executionNotice()] });
    renderDock();
    expect(screen.getByRole("alert")).toBeInTheDocument();
    composerBox().textContent = "请继续修改剧本";
    fireEvent.input(composerBox());
    fireEvent.keyDown(composerBox(), { key: "Enter" });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await waitFor(() =>
      expect(useCreatorSessionStore.getState().queuedUi[0]?.state).toBe(
        "queued",
      ),
    );
  });

  it.each(["RUNNING", "RESUMING", "WAITING_RUNTIME", "INTERRUPT_REQUESTED"])(
    "does not pin or auto-open pause history while the session is %s",
    (status) => {
      seedSession(status, { messages: [executionNotice()] });
      useAgentDockUiStore.getState().setOpen(false);
      renderDock();
      expect(
        document.querySelector("[data-agent-dock]"),
      ).not.toBeInTheDocument();
      act(() => useAgentDockUiStore.getState().setOpen(true));
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      expect(
        screen.getByText(/自动创作已暂停，作品尚未完成/),
      ).toBeInTheDocument();
    },
  );

  it.each(["RUNNING", "RESUMING"])(
    "clears a visible pause when execution becomes %s",
    (status) => {
      useCreatorSessionStore.setState({ messages: [executionNotice()] });
      renderDock();
      expect(screen.getByRole("alert")).toBeInTheDocument();
      act(() => seedSession(status));
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      expect(
        screen.getByText(/自动创作已暂停，作品尚未完成/),
      ).toBeInTheDocument();
    },
  );

  it("excludes the previous project's pause while its session store is still loaded", () => {
    useCreatorSessionStore.setState({ messages: [executionNotice()] });
    renderDock(true);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: "切到第二项目" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    act(() =>
      useCreatorSessionStore.setState({
        messages: [executionNotice({ messageId: "old-project-pause" })],
      }),
    );
    expect(document.querySelector("[data-agent-dock]")).not.toBeInTheDocument();
  });

  it("excludes a previous conversation and respects manual close when returning to it", async () => {
    const notice = executionNotice();
    installMockFetch([
      {
        match: "/conversations/conversation-other/messages",
        response: { json: { items: [] } },
      },
      {
        match: "/conversations/conversation-1/messages",
        response: { json: { items: [notice] } },
      },
    ]);
    useCreatorSessionStore.setState({ messages: [notice] });
    renderDock();
    expect(screen.getByRole("alert")).toBeInTheDocument();
    await act(async () =>
      useCreatorSessionStore.getState().setConversation("conversation-other"),
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(
      screen.queryByText(/自动创作已暂停，作品尚未完成/),
    ).not.toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    await act(async () =>
      useCreatorSessionStore.getState().setConversation("conversation-1"),
    );
    expect(document.querySelector("[data-agent-dock]")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "创作助手" }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "自动创作已暂停，作品尚未完成",
    );
  });

  it("pins an active media-budget pause so the user can resolve it", async () => {
    const text = "自动创作已暂停，媒体调用预算已用完。";
    useCreatorSessionStore.setState({
      messages: [
        executionNotice({
          text,
          metadata: { executionPause: { reason: "media_budget_exhausted" } },
        }),
      ],
    });
    useAgentDockUiStore.getState().setOpen(false);
    renderDock();
    expect(await screen.findByRole("alert")).toHaveTextContent(text);
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

  it("keeps transient thinking out of the conversation through tool-result persistence", () => {
    useAgentDockUiStore.getState().setOpen(true);
    const narration = asst({
      messageId: "narration",
      text: "我先检查当前剧本。",
    });
    seedSession("RUNNING", {
      messages: [narration],
      streamingAssistantMessages: {
        reasoning: {
          messageId: "reasoning",
          firstEventSeq: 10,
          deltas: {},
          thinkingDeltas: { 0: "PRIVATE_REASONING" },
          createdAt: "now",
        },
      },
    });
    renderDock();
    const flow = document.querySelector("[data-agent-response-flow]")!;
    const liveStatus = document.querySelector("[data-agent-live-status]")!;
    expect(flow.children).toHaveLength(1);
    expect(liveStatus).toHaveTextContent("正在思考");

    const progress = evt("agent.tool_progress", 11, {
      toolCallId: "read-plan",
      tool: "read_project",
    });
    const started = evt("agent.tool_started", 12, {
      toolCallId: "read-plan",
      tool: "read_project",
    });
    act(() => useCreatorSessionStore.setState({ events: [progress, started] }));
    expect(flow.children).toHaveLength(2);
    expect(flow).not.toHaveTextContent("正在思考");
    expect(liveStatus).toHaveTextContent("处理中");

    // The durable envelope arrives later, with the reasoning placeholder
    // cleared in the same publication. No temporary row may disappear.
    act(() =>
      useCreatorSessionStore.setState({
        streamingAssistantMessages: {},
        messages: [
          narration,
          asst({
            messageId: "read-plan-message",
            messageSeq: 3,
            text: "",
            metadata: {
              actionId: "read-plan",
              toolCall: { id: "read-plan", name: "read_project" },
            },
          }),
        ],
        events: [
          progress,
          started,
          evt("agent.tool_completed", 13, {
            toolCallId: "read-plan",
            tool: "read_project",
          }),
        ],
      }),
    );
    expect(flow.children).toHaveLength(2);
    expect(flow.querySelectorAll("[data-agent-tool]")).toHaveLength(1);
    expect(flow).toHaveTextContent("已完成");
    expect(document.body).not.toHaveTextContent("PRIVATE_REASONING");
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

  it.each(["selection", "reference"])(
    "preserves a changed %s with identical text during upload",
    async (kind) => {
      const { uploads, calls } = stagedSubmission();
      const first = {
        text: "同一段文字",
        label: "提示词",
        ref: "element:a",
        field: "prompt",
        path: "/a",
        start: 0,
        end: 5,
      };
      if (kind === "selection") {
        act(() => useAgentDockUiStore.getState().setSelection(first));
      } else {
        act(() =>
          useCreatorInteractionStore.getState().setExtraRefs([
            {
              ref: "asset-version:a",
              name: "同名素材",
              type: "asset",
              uiLocator: {},
            },
          ]),
        );
      }
      fireEvent.keyDown(composerBox(), { key: "Enter" });
      expect(uploads).toHaveLength(1);
      if (kind === "selection") {
        fireEvent.click(composerBox().querySelector("[data-sel]")!);
        act(() =>
          useAgentDockUiStore
            .getState()
            .setSelection({ ...first, start: 10, end: 15 }),
        );
      } else {
        act(() =>
          useCreatorInteractionStore.getState().setExtraRefs([
            {
              ref: "asset-version:b",
              name: "同名素材",
              type: "asset",
              uiLocator: {},
            },
          ]),
        );
      }
      await act(async () => uploads[0].resolve({ assetVersionId: "uploaded" }));
      await waitFor(() =>
        expect(calls.some((call) => call.method === "POST")).toBe(true),
      );
      expect(composerBox()).toHaveTextContent("指令 A");
      const body = calls.find((call) => call.method === "POST")!.body as {
        context: { selections: unknown[]; extraRefs: string[] };
      };
      if (kind === "selection") {
        expect(body.context.selections).toEqual([first]);
        expect(composerBox().querySelector("[data-sel]")).toHaveAttribute(
          "data-sel-start",
          "10",
        );
      } else {
        expect(body.context.extraRefs).toContain("asset-version:a");
        expect(useCreatorInteractionStore.getState().extraRefs[0].ref).toBe(
          "asset-version:b",
        );
      }
    },
  );

  it("offers the original instruction after a partial upload failure without overwriting the new draft", async () => {
    const { uploads, calls, write } = stagedSubmission(["a.png", "b.png"]);
    const selection = {
      text: "原选区",
      label: "提示词",
      ref: "element:a",
      field: "prompt",
      path: "/a",
      start: 0,
      end: 3,
    };
    act(() => useAgentDockUiStore.getState().setSelection(selection));
    fireEvent.keyDown(composerBox(), { key: "Enter" });
    await act(async () => uploads[0].resolve({ assetVersionId: "a" }));
    await waitFor(() => expect(uploads).toHaveLength(2));
    write("指令 B");
    await act(async () => uploads[1].reject(new Error("upload interrupted")));
    expect(composerBox()).toHaveTextContent("指令 B");
    expect(
      document.querySelector("[data-agent-interrupted-text]"),
    ).toHaveTextContent("指令 A");
    expect(calls.filter((call) => call.method === "POST")).toHaveLength(0);
    fireEvent.click(
      within(
        document.querySelector("[data-agent-interrupted-text]") as HTMLElement,
      ).getByRole("button", { name: "恢复到输入框" }),
    );
    expect(composerBox()).toHaveTextContent("指令 A");
    fireEvent.keyDown(composerBox(), { key: "Enter" });
    await waitFor(() => expect(uploads).toHaveLength(3));
    await act(async () => uploads[2].resolve({ assetVersionId: "b" }));
    await waitFor(() =>
      expect(calls.find((call) => call.method === "POST")?.body).toMatchObject({
        assetVersionRefs: ["asset-version:a", "asset-version:b"],
        context: { selections: [selection] },
      }),
    );
    expect(
      (
        calls.find((call) => call.method === "POST")!.body as {
          message: string;
        }
      ).message,
    ).toContain("指令 A");
  });

  it("preserves a draft retargeted to another editing field while uploading", async () => {
    const { uploads, calls } = stagedSubmission();
    act(() =>
      useCreatorInteractionStore
        .getState()
        .setEditingField("storyboard_prompt"),
    );
    fireEvent.keyDown(composerBox(), { key: "Enter" });
    act(() =>
      useCreatorInteractionStore.getState().setEditingField("video_prompt"),
    );
    await act(async () => uploads[0].resolve({ assetVersionId: "uploaded" }));
    await waitFor(() =>
      expect(calls.find((call) => call.method === "POST")?.body).toMatchObject({
        context: { editingField: "storyboard_prompt" },
      }),
    );
    expect(composerBox()).toHaveTextContent("指令 A");
    expect(useCreatorInteractionStore.getState().editingField).toBe(
      "video_prompt",
    );
  });

  it("finishes an upload in its original conversation after the user switches", async () => {
    const { uploads, calls, write } = stagedSubmission();
    fireEvent.keyDown(composerBox(), { key: "Enter" });
    act(() =>
      useCreatorSessionStore.setState({
        activeConversationId: "conversation-other",
      }),
    );
    write("指令 B");
    await act(async () => uploads[0].resolve({ assetVersionId: "uploaded" }));
    await waitFor(() =>
      expect(calls.find((call) => call.method === "POST")?.body).toMatchObject({
        conversationId: "conversation-1",
        message: "指令 A",
      }),
    );
    expect(composerBox()).toHaveTextContent("指令 B");
    expect(
      screen.queryByText("指令 A", { selector: "p" }),
    ).not.toBeInTheDocument();
  });

  it("keeps the new project's upload locked when an old upload finishes", async () => {
    const { uploads, calls, write } = stagedSubmission(["a.png"], true);
    fireEvent.keyDown(composerBox(), { key: "Enter" });
    fireEvent.click(screen.getByRole("link", { name: "切到第二项目" }));
    act(() =>
      useCreatorSessionStore.setState({
        projectId: "p2",
        activeConversationId: "conversation-p2",
        session: {
          ...useCreatorSessionStore.getState().session!,
          projectId: "p2",
        },
      }),
    );
    fireEvent.change(document.querySelector('input[type="file"]')!, {
      target: { files: [new File(["b"], "b.png", { type: "image/png" })] },
    });
    write("指令 B");
    fireEvent.keyDown(composerBox(), { key: "Enter" });
    expect(uploads).toHaveLength(2);
    await act(async () => uploads[0].resolve({ assetVersionId: "a" }));
    fireEvent.keyDown(composerBox(), { key: "Enter" });
    expect(uploads).toHaveLength(2);
    await act(async () => uploads[1].resolve({ assetVersionId: "b" }));
    await waitFor(() =>
      expect(calls.find((call) => call.method === "POST")?.body).toMatchObject({
        message: "指令 B",
        assetVersionRefs: ["asset-version:b"],
        conversationId: "conversation-p2",
      }),
    );
  });

  it("excludes removed files from both the remaining uploads and final message", async () => {
    const { uploads, calls } = stagedSubmission(["a.png", "b.png", "c.png"]);
    fireEvent.keyDown(composerBox(), { key: "Enter" });
    const remove = (name: string) =>
      fireEvent.click(
        within(screen.getByText(name).parentElement!).getByRole("button"),
      );
    remove("a.png");
    remove("b.png");
    await act(async () => uploads[0].resolve({ assetVersionId: "a" }));
    await waitFor(() => expect(uploads).toHaveLength(2));
    await act(async () => uploads[1].resolve({ assetVersionId: "c" }));
    await waitFor(() =>
      expect(calls.find((call) => call.method === "POST")?.body).toMatchObject({
        assetVersionRefs: ["asset-version:c"],
      }),
    );
  });

  it("shows the same simplified copy for queued message failures", () => {
    useCreatorSessionStore.setState({
      queuedUi: [
        {
          clientMessageId: "failed-message",
          conversationId: "conversation-1",
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
    act(() =>
      useCreatorSessionStore.setState({
        activeConversationId: "conversation-other",
      }),
    );
    expect(screen.queryByText("重新生成视频")).not.toBeInTheDocument();
    act(() =>
      useCreatorSessionStore.setState({
        activeConversationId: "conversation-1",
      }),
    );
    expect(screen.getByText("重新生成视频")).toBeInTheDocument();
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
    await waitFor(() =>
      expect(useCreatorSessionStore.getState().stopping).toBe(false),
    );
    expect(stop).toBeDisabled();
    fireEvent.click(stop);
    expect(
      calls.filter((call) => call.url.includes("/interrupt")),
    ).toHaveLength(1);
  });

  it("settles the stop button with cancelled media Tasks and still allows stopping newly started work", async () => {
    const task = {
      id: "task-stopped-image",
      projectId: "p1",
      transactionId: null,
      specialistRunId: "run-1",
      kind: "image_generation" as const,
      targetRef: "element:one",
      status: "CANCELLED" as const,
      progress: null,
      resultRefs: [],
    };
    const staleRun = makeRun({
      status: "WAITING_RUNTIME",
      taskRefs: [task.id],
      metadata: { commandType: "GENERATE_STORYBOARD_IMAGE" },
    });
    installMockFetch([
      {
        match: "/interrupt",
        method: "POST",
        response: {
          json: {
            creatorSessionId: "session-1",
            status: "CANCELLED",
            stopRequested: true,
          },
        },
      },
      { match: "/specialist-runs", response: { json: { items: [staleRun] } } },
      { match: "/tasks", response: { json: { items: [task] } } },
    ]);
    seedSession("RUNNING");
    useCreatorTaskViewStore.setState({ projectId: "p1", runs: [staleRun] });
    useAgentDockUiStore.getState().setOpen(true);
    renderDock();
    fireEvent.click(screen.getByRole("button", { name: "停止所有 Agent" }));
    await waitFor(() =>
      expect(useCreatorSessionStore.getState().session?.status).toBe(
        "CANCELLED",
      ),
    );
    await act(() => useCreatorTaskViewStore.getState().refresh("p1"));
    expect(
      screen.queryByRole("button", { name: "停止所有 Agent" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "发送" })).toBeDisabled();

    // A later manual generation can run independently of the stopped chat.
    act(() =>
      useCreatorTaskViewStore.setState({
        tasks: [
          task,
          {
            ...task,
            id: "new-manual-task",
            specialistRunId: null,
            status: "RUNNING",
          },
        ],
      }),
    );
    expect(
      screen.getByRole("button", { name: "停止所有 Agent" }),
    ).toBeEnabled();
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

  it("answers a proven-unfittable input without promising a resume", async () => {
    // The runtime parked the run only after the demotion ladder had given up
    // every byte it is allowed to move. Its text names handles and media
    // counts nobody can act on, and the generic banner reads as "retry to
    // continue" for a request that has nothing smaller left to become.
    useAgentDockUiStore.getState().setOpen(true);
    renderDock();
    act(() =>
      useCreatorSessionStore.setState({
        session: {
          id: "session-1",
          projectId: "p1",
          status: "ERROR",
          lastMessageSeq: 2,
          lastConsumedMessageSeq: 1,
          lastEventSeq: 5,
          error: {
            code: "MODEL_CONTEXT_UNFIT",
            message:
              "Error code: 400: This model's maximum context length is " +
              "32768 tokens.\n媒体降级记录：真人附件媒体 2 块（已存档 2 块）",
            retryable: false,
          },
        },
      }),
    );

    await waitFor(() =>
      expect(screen.getByText(/可让出的内容已全部让出/)).toBeInTheDocument(),
    );
    expect(
      screen.queryByText(/maximum context length/),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/媒体降级记录/)).not.toBeInTheDocument();
  });
});

describe("safe provider failure messages", () => {
  it("explains unsupported temperature without exposing provider details", () => {
    const message = simplifyErrorMessage(
      "Parameter 'temperature'=0.2 is not supported for kimi-k3; secret-token /private/path",
    );
    expect(message).toContain("temperature");
    expect(message).not.toContain("secret-token");
    expect(message).not.toContain("/private/path");
    expect(message).not.toBe(simplifyErrorMessage("unknown provider failure"));
  });

  it("also classifies a Moonshot invalid-temperature refusal", () => {
    // Moonshot direct calls phrase the refusal as an invalid temperature;
    // it must map to the same safe hint as the DashScope wording.
    const invalid = simplifyErrorMessage(
      "Invalid temperature: this model uses a fixed sampling temperature",
    );
    const notSupported = simplifyErrorMessage(
      "Parameter 'temperature'=0.2 is not supported for kimi-k3",
    );
    expect(invalid).toBe(notSupported);
    expect(invalid).not.toBe(simplifyErrorMessage("unknown provider failure"));
  });

  it("does not misread a generic invalid_request_error as a refusal", () => {
    // Gateways wrap unrelated 400s as ``invalid_request_error``; one that
    // merely echoes ``temperature`` must fall back to the generic hint, or a
    // real config error would be masked as an unsupported-temperature refusal.
    const generic = simplifyErrorMessage(
      '{"error": {"type": "invalid_request_error", "message": "temperature must be <= 2.0"}}',
    );
    const refusal = simplifyErrorMessage(
      "Parameter 'temperature'=0.2 is not supported for kimi-k3",
    );
    expect(generic).not.toBe(refusal);
    expect(generic).toBe(simplifyErrorMessage("unknown provider failure"));
  });
});

describe("AgentDock older-history paging while replay is suppressed", () => {
  beforeEach(() => {
    seedCreatorSession();
    useAgentDockUiStore.getState().setOpen(true);
  });

  const historyCalls = (calls: Array<{ url: string }>) =>
    calls.filter((call) => call.url.includes("messages?before=")).length;

  const routes: Parameters<typeof installMockFetch>[0] = [
    {
      match: "messages?before=",
      response: {
        json: {
          items: [
            msg({ messageId: "tail-4", messageSeq: 4, text: "更早的消息" }),
          ],
          nextBefore: null,
        },
      },
    },
    { match: "/specialist-runs", response: { json: { items: [] } } },
    { match: "/tasks", response: { json: { items: [] } } },
  ];

  /** The state a dying EventSource leaves behind: replay never finished. */
  const seedStuckReplay = (connectionState: "reconnecting" | "connected") =>
    useCreatorSessionStore.setState({
      messages: [msg({ messageId: "tail-5", messageSeq: 5 })],
      hasMoreMessages: true,
      isReplaying: true,
      loadingOlder: false,
      connectionState,
    });

  it("pages older history over HTTP when the event stream is unhealthy", async () => {
    const { calls } = installMockFetch(routes);
    seedStuckReplay("reconnecting");
    renderDock();

    fireEvent.click(
      document.querySelector("[data-agent-history-sentinel] button")!,
    );

    await waitFor(() => expect(historyCalls(calls)).toBe(1));
    await waitFor(() =>
      expect(
        useCreatorSessionStore
          .getState()
          .messages.map((item) => item.messageId),
      ).toContain("tail-4"),
    );
  });

  it("still holds the button back while a healthy replay is running", () => {
    const { calls } = installMockFetch(routes);
    seedStuckReplay("connected");
    renderDock();

    // The sentinel auto-load is what this guard protects: the viewport parks at
    // the top during replay and would otherwise pull extra pages that fight the
    // replay-end snap.
    fireEvent.click(
      document.querySelector("[data-agent-history-sentinel] button")!,
    );

    expect(historyCalls(calls)).toBe(0);
  });

  it("keeps an unsent draft across a fold and reopen", async () => {
    // Review #243: folding unmounts the input and live typing never reaches
    // the store, so the unsent instruction used to vanish with the component.
    renderDock();
    const box = composerBox();
    fireEvent.input(box, {
      target: { textContent: "Keep this unsent instruction" },
    });
    expect(box.textContent).toBe("Keep this unsent instruction");

    fireEvent.keyDown(window, { key: "Escape" });
    expect(document.querySelector("[data-agent-dock]")).not.toBeInTheDocument();
    expect(useAgentDockUiStore.getState().unsentDraft).toEqual({
      projectId: "p1",
      content: ["Keep this unsent instruction"],
    });

    fireEvent.click(screen.getByRole("button", { name: "创作助手" }));
    await waitFor(() => {
      expect(composerBox().textContent).toBe("Keep this unsent instruction");
    });
  });

  it("does not restore an unsent draft that belongs to another Project", async () => {
    // Review #243 blocking #5: the stash used to be untagged, so a
    // Project switch that unmounted the dock (which fired
    // onUnmountDraft) followed by a mount on a different Project would
    // hand A's half-typed instruction to B's composer -- and one
    // Enter key would send it to the wrong session.
    useAgentDockUiStore.setState({
      unsentDraft: {
        projectId: "p-other",
        content: ["Leaked from another Project"],
      },
    });
    renderDock();

    // The stash is preserved for its own Project but never applied.
    expect(composerBox().textContent ?? "").toBe("");
    expect(useAgentDockUiStore.getState().unsentDraft?.projectId).toBe(
      "p-other",
    );
  });

  it("prefers the edited draft over a one-shot injection on reopen", async () => {
    // Review #243 P2: BlueprintScriptPanel request-changes sets store.draft
    // once, and the old effect re-applied that value every time the dock
    // reopened against an empty input -- silently overwriting whatever the
    // user had typed after the injection. The injection is now consumed
    // after it lands, so unsentDraft wins on the next fold/reopen.
    renderDock();
    useAgentDockUiStore.getState().setDraft("Original injection");
    await waitFor(() =>
      expect(composerBox().textContent).toBe("Original injection"),
    );
    // Consume the injection: store.draft is cleared once it has landed.
    expect(useAgentDockUiStore.getState().draft).toBe("");

    fireEvent.input(composerBox(), {
      target: { textContent: "Edited instruction" },
    });

    fireEvent.keyDown(window, { key: "Escape" });
    expect(document.querySelector("[data-agent-dock]")).not.toBeInTheDocument();
    expect(useAgentDockUiStore.getState().unsentDraft).toEqual({
      projectId: "p1",
      content: ["Edited instruction"],
    });

    fireEvent.click(screen.getByRole("button", { name: "创作助手" }));
    await waitFor(() =>
      expect(composerBox().textContent).toBe("Edited instruction"),
    );
  });

  it("holds the composer button at 发送 while a replay is still catching up", () => {
    // The measured defect: a Project whose session had already ended in ERROR
    // flipped this button to 停止所有 Agent three times inside 1.5s, because
    // the four sources behind `stoppable` land at different moments and the
    // replay walks through the run's own WAITING_EXECUTION_AUTH history.
    useCreatorSessionStore.setState({
      isReplaying: true,
      session: {
        id: "session-1",
        projectId: "p1",
        status: "WAITING_EXECUTION_AUTH",
        activeGoalId: null,
        lastMessageSeq: 3,
        lastConsumedMessageSeq: 3,
        lastEventSeq: 10,
        error: null,
      } as never,
    });
    renderDock();

    expect(screen.getByRole("button", { name: "发送" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "停止所有 Agent" }),
    ).not.toBeInTheDocument();
  });

  it("re-reads the authoritative session the moment a replay catches up", async () => {
    // Replay replays events, not the session row. Without this the corrected
    // status only arrives with the next ~10s poll batch.
    const refresh = vi.fn(async () => undefined);
    useCreatorSessionStore.setState({
      isReplaying: true,
      refreshSession: refresh,
    });
    renderDock();

    useCreatorSessionStore.setState({ isReplaying: false });

    await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
  });
});
