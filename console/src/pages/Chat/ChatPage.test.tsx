/**
 * Chat/index.tsx behavior tests
 *
 * Strategy (following the openclaw chat.test.ts pattern):
 * - Mock AgentScopeRuntimeWebUI as a spy component that captures the options prop
 * - Directly invoke callbacks like options.api.fetch and
 *   options.sender.attachments.customRequest to test ChatPage logic
 *   without depending on a real WebSocket runtime
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useNavigate } from "react-router-dom";
import { renderWithProviders } from "@/test/common_setup";
import ChatPage from "./index";
import { chatExtensions } from "@/plugins/registry/chatExtensions";
import { useUploadLimitStore } from "@/stores/uploadLimitStore";
import { useMessageQueueStore } from "@/stores/messageQueueStore";

// ---------------------------------------------------------------------------
// Capture AgentScopeRuntimeWebUI options
// ---------------------------------------------------------------------------
let capturedOptions: any = null;

const {
  mockListProviders,
  mockGetActiveModels,
  mockUploadFile,
  mockFilePreviewUrl,
  mockGetApiUrl,
  mockSelectedAgent,
  mockSetSelectedAgent,
  mockGetTranscriptionProviderType,
  mockGetChatSpec,
  mockPreloadSession,
  mockChatInputSubmit,
  mockChatMessageUpdate,
  mockChatMessageRemove,
  mockChatMessages,
  mockVoiceOptions,
  mockVoiceControlsProps,
  mockRealtimeVoice,
} = vi.hoisted(() => ({
  mockListProviders: vi.fn(),
  mockGetActiveModels: vi.fn(),
  mockUploadFile: vi.fn(),
  mockFilePreviewUrl: vi.fn((f: string) => `/preview/${f}`),
  mockGetApiUrl: vi.fn((p: string) => `/api${p}`),
  mockSelectedAgent: vi.fn(() => "default"),
  mockSetSelectedAgent: vi.fn(),
  mockGetTranscriptionProviderType: vi.fn(),
  mockGetChatSpec: vi.fn(),
  mockPreloadSession: vi.fn(),
  mockChatInputSubmit: vi.fn(),
  mockChatMessageUpdate: vi.fn(),
  mockChatMessageRemove: vi.fn(),
  mockChatMessages: [] as any[],
  mockVoiceOptions: { current: null as any },
  mockVoiceControlsProps: {
    current: null as { canStart?: boolean } | null,
  },
  mockRealtimeVoice: {
    capabilities: null,
    status: "idle",
    reloadCapabilities: vi.fn(async () => null),
    start: vi.fn(),
    stop: vi.fn(),
    observeAgentRun: vi.fn(),
  },
}));

vi.mock("../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
  }),
}));

vi.mock("../../contexts/ApprovalContext", () => ({
  useApprovalContext: () => ({
    approvals: [] as any[],
    setApprovals: vi.fn(),
  }),
}));

vi.mock("../../plugins/PluginContext", () => ({
  usePlugins: () => ({
    plugins: [],
    registerPlugin: vi.fn(),
    toolRenderConfig: {},
  }),
  PluginContext: { Provider: ({ children }: any) => children },
}));

vi.mock("./components/ChatSessionInitializer", () => ({
  default: () => null,
}));

vi.mock("@agentscope-ai/chat", async () => {
  const React = await import("react");
  return {
    SESSION_TIMELINE_MODE_VERSION: 4,
    AgentScopeRuntimeWebUI: React.forwardRef((props: any, ref) => {
      capturedOptions = props.options;
      React.useImperativeHandle(
        ref,
        () => ({
          messages: {
            appendTimelineEvents: vi.fn(),
            updateMessage: mockChatMessageUpdate,
            removeMessage: mockChatMessageRemove,
            getMessages: () => mockChatMessages,
          },
          input: {
            setDisabled: vi.fn(),
            submit: mockChatInputSubmit,
          },
        }),
        [],
      );
      return (
        <div data-testid="chat-ui">
          {props.options?.theme?.rightHeader}
          {props.options?.sender?.beforeUI}
          {!mockChatMessages.length && props.options?.welcome?.render?.({})}
        </div>
      );
    }),
    useChatAnywhereSessionsState: vi.fn(() => ({
      sessions: [],
      currentSessionId: null,
      setCurrentSessionId: vi.fn(),
      setSessions: vi.fn(),
    })),
    useChatAnywhereSessions: vi.fn(() => ({ createSession: vi.fn() })),
    useChatAnywhereInput: vi.fn(() => ({
      setLoading: vi.fn(),
      getLoading: vi.fn(),
    })),
  };
});

vi.mock("../../features/realtime-voice/useRealtimeVoice", () => ({
  useRealtimeVoice: (options: any) => {
    mockVoiceOptions.current = options;
    return mockRealtimeVoice;
  },
  isRealtimeVoiceActive: (status: string) => status !== "idle",
  isRealtimeVoiceReady: () => false,
}));

vi.mock("../../features/realtime-voice/RealtimeVoicePanel", () => ({
  RealtimeVoiceControls: (props: { canStart?: boolean }) => {
    mockVoiceControlsProps.current = props;
    return <div data-testid="voice-controls" />;
  },
  RealtimeVoiceConflictModal: () => null,
}));

vi.mock("@/api/modules/provider", () => ({
  providerApi: {
    listProviders: mockListProviders,
    getActiveModels: mockGetActiveModels,
  },
}));

vi.mock("@/api/modules/chat", () => ({
  chatApi: {
    uploadFile: mockUploadFile,
    filePreviewUrl: mockFilePreviewUrl,
    stopChat: vi.fn(),
    getChatSpec: mockGetChatSpec,
  },
  sessionApi: {
    getRealIdForSession: vi.fn(() => null),
    setLastUserMessage: vi.fn(),
    getSessionList: vi.fn(() => Promise.resolve([])),
  },
}));

vi.mock("@/api/modules/agent", () => ({
  agentApi: {
    getTranscriptionProviderType: mockGetTranscriptionProviderType,
  },
  TranscriptionError: class TranscriptionError extends Error {},
}));

vi.mock("antd", async (importOriginal) => {
  const actual = await importOriginal<typeof import("antd")>();
  return {
    ...actual,
    // Modal: do not render when open=false, avoids CSS animation leaving content in the DOM
    Modal: ({
      open,
      children,
    }: {
      open: boolean;
      children: React.ReactNode;
    }) => (open ? <div data-testid="modal">{children}</div> : null),
  };
});
vi.mock("@/api/config", () => ({
  getApiUrl: mockGetApiUrl,
  getApiToken: vi.fn(() => ""),
}));

vi.mock("@/stores/agentStore", () => {
  const makeState = () => ({
    selectedAgent: mockSelectedAgent(),
    setSelectedAgent: mockSetSelectedAgent,
    agents: [{ id: "default", backend: "qwenpaw" }],
    setLastChatId: vi.fn(),
    getLastChatId: vi.fn(() => null),
    removeLastChatId: vi.fn(),
  });
  const store = Object.assign(vi.fn(makeState), {
    subscribe: vi.fn(() => vi.fn()),
    getState: vi.fn(makeState),
    setState: vi.fn(),
  });
  return { useAgentStore: store };
});

vi.mock("@/contexts/ThemeContext", () => ({
  useTheme: vi.fn(() => ({ isDark: false })),
}));

vi.mock("./sessionApi", () => ({
  default: {
    onSessionIdResolved: null,
    onSessionRemoved: null,
    onSessionSelected: null,
    onSessionCreated: null,
    getRealIdForSession: vi.fn(() => null),
    getBackendSessionId: vi.fn((chatId: string) => chatId),
    triggerResolve: vi.fn(),
    preloadSession: mockPreloadSession,
    getSessionIdentity: vi.fn((chatId: string) => ({
      chatId,
      sessionId: chatId,
      sdkSessionId: chatId,
      userId: "admin",
      channel: "console",
    })),
    setLastUserMessage: vi.fn(),
  },
}));

vi.mock("./OptionsPanel/defaultConfig", () => ({
  default: {
    theme: {
      leftHeader: {},
      bubbleList: {
        userMessageAnchors: {},
        assistantMessageAnchors: {},
      },
    },
    api: {},
  },
  getDefaultConfig: vi.fn(() => ({
    theme: {
      leftHeader: {},
      bubbleList: {
        userMessageAnchors: {},
        assistantMessageAnchors: {},
      },
    },
    welcome: {},
    sender: {},
  })),
}));

vi.mock("./ModelSelector", () => ({
  default: () => <div data-testid="model-selector" />,
}));

vi.mock("./components/ChatActionGroup", () => ({
  default: () => <div data-testid="action-group" />,
}));

vi.mock("./components/ChatHeaderTitle", () => ({
  default: () => <div data-testid="header-title" />,
}));

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------
const mockActiveModel = {
  active_llm: { provider_id: "openai", model: "gpt-4" },
};
const mockProviders = [
  {
    id: "openai",
    name: "OpenAI",
    models: [
      {
        id: "gpt-4",
        name: "GPT-4",
        supports_multimodal: true,
        supports_image: true,
        supports_video: false,
      },
    ],
    extra_models: [],
  },
];

// ---------------------------------------------------------------------------
// tests
// ---------------------------------------------------------------------------
describe("ChatPage", () => {
  beforeEach(() => {
    chatExtensions.__resetForTests();
    capturedOptions = null;
    mockVoiceOptions.current = null;
    mockVoiceControlsProps.current = null;
    mockRealtimeVoice.status = "idle";
    mockChatMessages.length = 0;
    mockListProviders.mockResolvedValue(mockProviders);
    mockGetActiveModels.mockResolvedValue(mockActiveModel);
    mockUploadFile.mockResolvedValue({
      url: "uploaded.png",
      file_name: "uploaded.png",
    });
    mockGetTranscriptionProviderType.mockResolvedValue({
      transcription_provider_type: "disabled",
    });
    mockGetChatSpec.mockResolvedValue({ source: "chat" });
    mockPreloadSession.mockResolvedValue({ session: {}, realId: null });
    useUploadLimitStore.setState({ uploadMaxSizeMb: 10 });
  });

  afterEach(() => {
    chatExtensions.__resetForTests();
    useUploadLimitStore.setState({ uploadMaxSizeMb: null });
    vi.clearAllMocks();
  });

  // ── basic rendering ───────────────────────────────────────────────────────

  it("renders AgentScopeRuntimeWebUI", async () => {
    renderWithProviders(<ChatPage />, { initialEntries: ["/chat"] });
    expect(await screen.findByTestId("chat-ui")).toBeInTheDocument();
  });

  it("renders child components ModelSelector / ChatActionGroup / ChatHeaderTitle", async () => {
    renderWithProviders(<ChatPage />, { initialEntries: ["/chat"] });
    await screen.findByTestId("chat-ui");
    console.log("DOM:", document.body.innerHTML.substring(0, 500));
    expect(screen.getByTestId("model-selector")).toBeInTheDocument();
    expect(screen.getByTestId("action-group")).toBeInTheDocument();
    expect(screen.getByTestId("header-title")).toBeInTheDocument();
  });

  it("selects the Voice surface without waiting for large history", async () => {
    const chatId = "ae7fd036-d5e9-4a57-af67-e50b6e8d6052";
    let resolveSpec!: (spec: { source: string }) => void;
    mockGetChatSpec.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveSpec = resolve;
      }),
    );
    mockPreloadSession.mockReturnValueOnce(new Promise(() => {}));

    renderWithProviders(<ChatPage />, {
      initialEntries: [`/chat/${chatId}`],
    });

    expect(await screen.findByRole("status")).toHaveTextContent("Loading...");
    expect(screen.queryByTestId("chat-ui")).not.toBeInTheDocument();
    expect(screen.queryByTestId("model-selector")).not.toBeInTheDocument();

    await act(async () => resolveSpec({ source: "realtime_voice" }));

    expect(await screen.findByTestId("chat-ui")).toBeInTheDocument();
    expect(screen.getByTestId("model-selector")).toBeInTheDocument();
    expect(capturedOptions.sender.placeholder).toBe(
      "Type into the live Voice Chat...",
    );
    expect(screen.getByRole("status")).toHaveTextContent("Loading...");
    expect(capturedOptions.welcome.render).toBeTypeOf("function");
    expect(capturedOptions.welcome.nick).toBe("QwenPaw");
    expect(capturedOptions.sender.beforeUI).toBeTruthy();
    expect(mockVoiceControlsProps.current?.canStart).toBe(true);
    expect(mockGetChatSpec).toHaveBeenCalledWith(chatId, {
      signal: expect.anything(),
      include_app_owned: false,
    });
    expect(mockPreloadSession).toHaveBeenCalledWith(chatId, expect.anything());
  });

  it("shows pending keyboard input alongside Voice controls", async () => {
    const chatId = "c2854085-6be2-43d3-baab-ad1d40b9fcad";
    mockGetChatSpec.mockResolvedValue({ source: "realtime_voice" });
    useMessageQueueStore.getState().setRunState(chatId, "paused");
    useMessageQueueStore.getState().enqueue(chatId, {
      text: "排队中的键盘查询",
      agentId: "default",
      bizParams: {},
    });
    const { unmount } = renderWithProviders(<ChatPage />, {
      initialEntries: [`/chat/${chatId}`],
    });
    try {
      expect(await screen.findByTestId("voice-controls")).toBeInTheDocument();
      expect(await screen.findByText("排队中的键盘查询")).toBeInTheDocument();
      expect(mockChatInputSubmit).not.toHaveBeenCalled();
    } finally {
      unmount();
      useMessageQueueStore.getState().clear(chatId);
    }
  });

  it.each(["messages", "timelineEvents"])(
    "keeps loading until populated %s reaches the message list",
    async (field) => {
      mockPreloadSession.mockResolvedValueOnce({
        session: { [field]: [{ id: "saved" }] },
      });
      const { rerender } = renderWithProviders(<ChatPage />, {
        initialEntries: ["/chat/ae7fd036-d5e9-4a57-af67-e50b6e8d6052"],
      });
      await screen.findByTestId("chat-ui");
      expect(screen.getByRole("status")).toHaveTextContent("Loading...");
      mockChatMessages.push({ id: "saved" });
      rerender(<ChatPage />);
      expect(screen.queryByRole("status")).not.toBeInTheDocument();
    },
  );

  it("retains the normal welcome for confirmed empty history", async () => {
    mockPreloadSession.mockResolvedValueOnce({ session: { messages: [] } });
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/ae7fd036-d5e9-4a57-af67-e50b6e8d6052"],
    });
    await screen.findByTestId("chat-ui");
    await waitFor(() => expect(capturedOptions.welcome.render).toBeUndefined());
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("restores the ordinary plugin welcome only after confirming empty history", async () => {
    chatExtensions.setScalar("test", "welcome.render", () => (
      <div>Plugin welcome</div>
    ));
    let resolve!: (value: unknown) => void;
    mockPreloadSession.mockReturnValueOnce(
      new Promise((done) => {
        resolve = done;
      }),
    );
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/ae7fd036-d5e9-4a57-af67-e50b6e8d6052"],
    });
    await screen.findByTestId("chat-ui");
    expect(screen.queryByText("Plugin welcome")).not.toBeInTheDocument();
    await act(async () =>
      resolve({ session: { messages: [], timelineEvents: [] } }),
    );
    expect(await screen.findByText("Plugin welcome")).toBeInTheDocument();
  });

  it("shows history failure and retries instead of presenting an empty Chat", async () => {
    mockPreloadSession
      .mockRejectedValueOnce(new Error("history unavailable"))
      .mockResolvedValueOnce({ session: { messages: [] } });
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/ae7fd036-d5e9-4a57-af67-e50b6e8d6052"],
    });
    expect(await screen.findByText("Failed to load page")).toBeInTheDocument();
    expect(screen.getByTestId("chat-ui")).toBeInTheDocument();
    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(mockPreloadSession).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(capturedOptions.welcome.render).toBeUndefined());
  });

  it.each(["resolve", "reject"])(
    "ignores a previous route's late history %s",
    async (outcome) => {
      let resolve!: (value: unknown) => void;
      let reject!: (error: Error) => void;
      mockPreloadSession
        .mockReturnValueOnce(
          new Promise((yes, no) => {
            resolve = yes;
            reject = no;
          }),
        )
        .mockReturnValueOnce(new Promise(() => {}));
      function SwitchChat() {
        const navigate = useNavigate();
        return (
          <>
            <button
              onClick={() =>
                navigate("/chat/1a498700-e22f-4a31-81f4-a6ce1a470579")
              }
            >
              Switch Chat
            </button>
            <ChatPage />
          </>
        );
      }
      renderWithProviders(<SwitchChat />, {
        initialEntries: ["/chat/ae7fd036-d5e9-4a57-af67-e50b6e8d6052"],
      });
      await screen.findByTestId("chat-ui");
      await userEvent
        .setup()
        .click(screen.getByRole("button", { name: "Switch Chat" }));
      await waitFor(() => expect(mockPreloadSession).toHaveBeenCalledTimes(2));
      await act(async () => {
        if (outcome === "resolve") resolve({ session: { messages: [] } });
        else reject(new Error("old history failure"));
      });
      expect(screen.getByRole("status")).toHaveTextContent("Loading...");
      expect(screen.queryByText("Failed to load page")).not.toBeInTheDocument();
    },
  );

  it("disables and stops Voice when another tab owns the Chat", async () => {
    const chatId = "ae7fd036-d5e9-4a57-af67-e50b6e8d6052";
    const locksDescriptor = Object.getOwnPropertyDescriptor(navigator, "locks");
    Object.defineProperty(navigator, "locks", {
      configurable: true,
      value: { request: vi.fn(() => new Promise(() => {})) },
    });
    mockGetChatSpec.mockResolvedValueOnce({ source: "realtime_voice" });
    mockRealtimeVoice.status = "listening";

    try {
      renderWithProviders(<ChatPage />, {
        initialEntries: [`/chat/${chatId}`],
      });

      await screen.findByTestId("chat-ui");
      await waitFor(
        () => {
          expect(mockVoiceControlsProps.current?.canStart).toBe(false);
          expect(
            screen.getByText(
              "This tab queues only; sending is handled by another tab",
            ),
          ).toBeVisible();
          expect(mockRealtimeVoice.stop).toHaveBeenCalledOnce();
        },
        { timeout: 1500 },
      );
    } finally {
      if (locksDescriptor) {
        Object.defineProperty(navigator, "locks", locksDescriptor);
      } else {
        Reflect.deleteProperty(navigator, "locks");
      }
    }
  });

  it("reconnects the standard timeline when a speech Agent run starts", async () => {
    const chatId = "ae7fd036-d5e9-4a57-af67-e50b6e8d6052";
    mockGetChatSpec.mockResolvedValueOnce({ source: "realtime_voice" });

    renderWithProviders(<ChatPage />, {
      initialEntries: [`/chat/${chatId}`],
    });

    await screen.findByTestId("chat-ui");
    const dispatch = vi.spyOn(document, "dispatchEvent");
    mockVoiceOptions.current.onAgentRunStarted();

    expect(dispatch).toHaveBeenCalledWith(
      expect.objectContaining({ type: "handleReconnect" }),
    );
  });

  it("mounts ordinary Chat controls after an ordinary deep link resolves", async () => {
    const chatId = "1a498700-e22f-4a31-81f4-a6ce1a470579";
    renderWithProviders(<ChatPage />, {
      initialEntries: [`/chat/${chatId}`],
    });

    expect(await screen.findByTestId("chat-ui")).toBeInTheDocument();
    expect(screen.getByTestId("model-selector")).toBeInTheDocument();
    expect(capturedOptions.sender.placeholder).toBe(
      '"↑↓" for message navigation · "/" for quick commands',
    );
  });

  it("fails closed and retries Chat source hydration", async () => {
    const chatId = "ae7fd036-d5e9-4a57-af67-e50b6e8d6052";
    mockGetChatSpec
      .mockRejectedValueOnce(new Error("network"))
      .mockResolvedValueOnce({ source: "realtime_voice" });
    const user = userEvent.setup();

    renderWithProviders(<ChatPage />, {
      initialEntries: [`/chat/${chatId}`],
    });

    expect(await screen.findByText("Failed to load page")).toBeInTheDocument();
    expect(screen.queryByTestId("chat-ui")).not.toBeInTheDocument();
    expect(screen.queryByTestId("model-selector")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByTestId("chat-ui")).toBeInTheDocument();
    expect(screen.getByTestId("model-selector")).toBeInTheDocument();
    expect(mockGetChatSpec).toHaveBeenCalledTimes(2);
  });

  // ── customFetch: model not configured → show modal ────────────────────────

  it("customFetch returns 400 and shows modal when model is not configured", async () => {
    mockGetActiveModels.mockResolvedValue({ active_llm: undefined });
    renderWithProviders(<ChatPage />, { initialEntries: ["/chat"] });
    await screen.findByTestId("chat-ui");

    // directly invoke capturedOptions.api.fetch (openclaw pattern)
    const response = await capturedOptions.api.fetch({
      input: [],
      signal: undefined,
    });
    expect(response.status).toBe(400);
    expect(
      await screen.findByText("modelConfig.promptTitle"),
    ).toBeInTheDocument();
  });

  it("shows model config modal when provider API throws", async () => {
    mockGetActiveModels.mockRejectedValue(new Error("network"));
    renderWithProviders(<ChatPage />, { initialEntries: ["/chat"] });
    await screen.findByTestId("chat-ui");

    const response = await capturedOptions.api.fetch({
      input: [],
      signal: undefined,
    });
    expect(response.status).toBe(400);
    expect(
      await screen.findByText("modelConfig.promptTitle"),
    ).toBeInTheDocument();
  });

  // ── modal interaction ─────────────────────────────────────────────────────

  it("clicking Skip button closes the modal", async () => {
    mockGetActiveModels.mockResolvedValue({ active_llm: undefined });
    const user = userEvent.setup();
    renderWithProviders(<ChatPage />, { initialEntries: ["/chat"] });
    await screen.findByTestId("chat-ui");

    await capturedOptions.api.fetch({ input: [], signal: undefined });
    await screen.findByText("modelConfig.promptTitle");

    await user.click(screen.getByText("modelConfig.skipButton"));
    // antd Modal has animations; wait for DOM removal
    await waitFor(
      () =>
        expect(
          screen.queryByText("modelConfig.skipButton"),
        ).not.toBeInTheDocument(),
      { timeout: 3000 },
    );
  });

  // ── customFetch: normal send ──────────────────────────────────────────────

  it("customFetch calls /api/console/chat when model is configured", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValue({ ok: true, status: 200 } as Response);
    renderWithProviders(<ChatPage />, { initialEntries: ["/chat"] });
    await screen.findByTestId("chat-ui");

    await capturedOptions.api.fetch({
      input: [{ role: "user", content: "hello" }],
      signal: undefined,
    });

    expect(fetch).toHaveBeenCalledWith(
      "/api/console/chat",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("customFetch applies request payload transforms before sending", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValue({ ok: true, status: 200 } as Response);
    chatExtensions.addRequestPayloadTransform("plugin-a", {
      id: "plugin-a.request-context",
      order: 10,
      transform: ({ payload, sessionId, selectedAgent }) => ({
        ...payload,
        request_context: {
          session_id: sessionId,
          agent_id: selectedAgent,
          datasource_id: "ds-123",
        },
      }),
    });

    renderWithProviders(<ChatPage />, { initialEntries: ["/chat"] });
    await screen.findByTestId("chat-ui");

    await capturedOptions.api.fetch({
      input: [
        {
          role: "user",
          content: "hello",
          session: { session_id: "session-1" },
        },
      ],
      signal: undefined,
    });

    const init = vi.mocked(fetch).mock.calls[0][1] as RequestInit;
    const body = JSON.parse(String(init.body)) as Record<string, unknown>;
    expect(body.request_context).toEqual({
      session_id: "session-1",
      agent_id: "default",
      datasource_id: "ds-123",
    });
  });

  it("renders fallback metadata as an in-chat system message", async () => {
    renderWithProviders(<ChatPage />, { initialEntries: ["/chat"] });
    await screen.findByTestId("chat-ui");

    const parsed = capturedOptions.api.responseParser(
      JSON.stringify({
        object: "response",
        status: "completed",
        metadata: {
          qwenpaw_model_fallbacks: [
            {
              type: "model_fallback",
              from_provider_id: "openai",
              from_model_id: "gpt-primary",
              to_provider_id: "anthropic",
              to_model_id: "claude-fallback",
              reason_kind: "rate_limited",
            },
          ],
        },
        output: [
          {
            type: "message",
            role: "assistant",
            content: [{ type: "text", text: "answer" }],
          },
        ],
      }),
    );

    expect(parsed.output[0]).toMatchObject({
      type: "message",
      role: "system",
      metadata: {
        qwenpaw_model_fallbacks: [
          expect.objectContaining({
            from_model_id: "gpt-primary",
            to_model_id: "claude-fallback",
            reason_kind: "rate_limited",
          }),
        ],
      },
    });
    expect(parsed.output[0].content[0].text).toContain("openai:gpt-primary");
    expect(parsed.output[0].content[0].text).toContain(
      "anthropic:claude-fallback",
    );
    expect(parsed.output[1].role).toBe("assistant");
  });

  it("deduplicates repeated fallback metadata across stream chunks", async () => {
    renderWithProviders(<ChatPage />, { initialEntries: ["/chat"] });
    await screen.findByTestId("chat-ui");
    const event = {
      type: "model_fallback",
      from_provider_id: "openai",
      from_model_id: "gpt-primary",
      to_provider_id: "anthropic",
      to_model_id: "claude-fallback",
      reason_kind: "rate_limited",
    };

    capturedOptions.api.responseParser(
      JSON.stringify({
        object: "response.delta",
        metadata: { qwenpaw_model_fallbacks: [event] },
      }),
    );
    const parsed = capturedOptions.api.responseParser(
      JSON.stringify({
        object: "response",
        status: "completed",
        metadata: { qwenpaw_model_fallbacks: [event] },
        output: [],
      }),
    );

    expect(parsed.output[0].metadata.qwenpaw_model_fallbacks).toHaveLength(1);
  });

  // ── handleFileUpload ──────────────────────────────────────────────────────

  it("calls onError and skips upload when file exceeds 10MB", async () => {
    renderWithProviders(<ChatPage />, { initialEntries: ["/chat"] });
    await screen.findByTestId("chat-ui");

    const bigFile = new File([new ArrayBuffer(11 * 1024 * 1024)], "big.bin", {
      type: "application/octet-stream",
    });
    const onError = vi.fn();
    const onSuccess = vi.fn();

    await capturedOptions.sender.attachments.customRequest({
      file: bigFile,
      onSuccess,
      onError,
    });

    expect(onError).toHaveBeenCalledOnce();
    expect(mockUploadFile).not.toHaveBeenCalled();
  });

  it("uploads successfully and calls onSuccess when file is within size limit", async () => {
    renderWithProviders(<ChatPage />, { initialEntries: ["/chat"] });
    await screen.findByTestId("chat-ui");

    const smallFile = new File(["content"], "img.png", { type: "image/png" });
    const onSuccess = vi.fn();
    const onError = vi.fn();

    await capturedOptions.sender.attachments.customRequest({
      file: smallFile,
      onSuccess,
      onError,
      onProgress: vi.fn(),
    });

    expect(mockUploadFile).toHaveBeenCalledWith(smallFile);
    expect(onSuccess).toHaveBeenCalledWith({ url: "/preview/uploaded.png" });
    expect(onError).not.toHaveBeenCalled();
  });

  // ── voice input mode ───────────────────────────────────────────────────────

  it("does not enable browser speech before transcription provider type loads", async () => {
    let resolveProviderType!: (value: {
      transcription_provider_type: string;
    }) => void;
    mockGetTranscriptionProviderType.mockReturnValue(
      new Promise((resolve) => {
        resolveProviderType = resolve;
      }),
    );

    renderWithProviders(<ChatPage />, { initialEntries: ["/chat"] });
    await screen.findByTestId("chat-ui");

    expect(capturedOptions.sender.allowSpeech).toBe(false);
    expect(capturedOptions.sender.prefix).toBeUndefined();

    act(() => {
      resolveProviderType({ transcription_provider_type: "disabled" });
    });
  });

  it("uses Whisper speech button and disables browser speech when transcription provider is enabled", async () => {
    mockGetTranscriptionProviderType.mockResolvedValue({
      transcription_provider_type: "whisper_api",
    });

    renderWithProviders(<ChatPage />, { initialEntries: ["/chat"] });
    await screen.findByTestId("chat-ui");

    await waitFor(() => {
      expect(capturedOptions.sender.allowSpeech).toBe(false);
      expect(capturedOptions.sender.prefix).toBeTruthy();
    });
  });

  it("keeps browser speech enabled when transcription provider is disabled", async () => {
    mockGetTranscriptionProviderType.mockResolvedValue({
      transcription_provider_type: "disabled",
    });

    renderWithProviders(<ChatPage />, { initialEntries: ["/chat"] });
    await screen.findByTestId("chat-ui");

    await waitFor(() => {
      expect(capturedOptions.sender.allowSpeech).toBe(true);
      expect(capturedOptions.sender.prefix).toBeUndefined();
    });
  });

  // ── multimodal caps ───────────────────────────────────────────────────────

  it("calls providerApi on mount to fetch multimodal capabilities", async () => {
    renderWithProviders(<ChatPage />, { initialEntries: ["/chat"] });
    await screen.findByTestId("chat-ui");
    await waitFor(() => expect(mockGetActiveModels).toHaveBeenCalled());
    expect(mockListProviders).toHaveBeenCalled();
  });

  it("model-switched event triggers re-fetch of multimodal capabilities", async () => {
    renderWithProviders(<ChatPage />, { initialEntries: ["/chat"] });
    await screen.findByTestId("chat-ui");
    // wait for initial mount calls to settle
    await waitFor(() => expect(mockGetActiveModels).toHaveBeenCalled());
    const callsBefore = mockGetActiveModels.mock.calls.length;

    act(() => {
      window.dispatchEvent(new CustomEvent("model-switched"));
    });

    await waitFor(() =>
      expect(mockGetActiveModels.mock.calls.length).toBeGreaterThan(
        callsBefore,
      ),
    );
  });
});
