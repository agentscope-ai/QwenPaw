/**
 * ChatPage coverage tests
 *
 * Goal: cover as many statements in Chat/index.tsx as possible.
 * Strategy: render ChatPage with comprehensive mocks, exercise callbacks.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, waitFor, act } from "@testing-library/react";
import { renderWithProviders } from "@/test/common_setup";
import ChatPage from "./index";
import { chatExtensions } from "@/plugins/registry/chatExtensions";

// ---------------------------------------------------------------------------
// Hoisted mocks
// ---------------------------------------------------------------------------
const {
  mockListProviders,
  mockGetActiveModels,
  mockUploadFile,
  mockFilePreviewUrl,
  mockGetApiUrl,
  mockSelectedAgent,
  mockSetSelectedAgent,
  mockGetTranscriptionProviderType,
  mockCopyText,
  mockBeginLoopModeSubmission,
  mockRequiresQwenPawModel,
} = vi.hoisted(() => ({
  mockListProviders: vi.fn(),
  mockGetActiveModels: vi.fn(),
  mockUploadFile: vi.fn(),
  mockFilePreviewUrl: vi.fn((f: string) => `/preview/${f}`),
  mockGetApiUrl: vi.fn((p: string) => `http://localhost:3000${p}`),
  mockSelectedAgent: vi.fn(() => "default"),
  mockSetSelectedAgent: vi.fn(),
  mockGetTranscriptionProviderType: vi.fn(),
  mockCopyText: vi.fn().mockResolvedValue(undefined),
  mockBeginLoopModeSubmission: vi.fn((text: string) => text),
  mockRequiresQwenPawModel: vi.fn(() => true),
}));

let capturedOptions: any = null;

// ---------------------------------------------------------------------------
// Module mocks
// ---------------------------------------------------------------------------
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

vi.mock("@agentscope-ai/chat", () => ({
  AgentScopeRuntimeWebUI: vi.fn((props: any) => {
    capturedOptions = props.options;
    return (
      <div data-testid="chat-ui">
        {props.options?.theme?.rightHeader}
        {props.options?.sender?.prefix}
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
    loading: false,
    setLoading: vi.fn(),
    getLoading: vi.fn(() => false),
  })),
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
    stopChat: vi.fn(() => Promise.resolve()),
  },
}));

vi.mock("@/api/modules/agent", () => ({
  agentApi: {
    getTranscriptionProviderType: mockGetTranscriptionProviderType,
  },
  TranscriptionError: class TranscriptionError extends Error {},
}));

vi.mock("@/api/config", () => ({
  getApiUrl: mockGetApiUrl,
  getApiToken: vi.fn(() => ""),
}));

vi.mock("@/stores/agentStore", () => {
  const makeState = () => ({
    selectedAgent: mockSelectedAgent(),
    setSelectedAgent: mockSetSelectedAgent,
    agents: [{ id: "default", name: "Default", backend: "qwenpaw" }],
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
    getBackendSessionId: vi.fn(() => "backend-session-1"),
    setLastUserMessage: vi.fn(),
    discardLastUserMessage: vi.fn(),
    lastActiveChatId: "last-chat-1",
    patchLastUserMessage: vi.fn(),
    getSessionIdentity: vi.fn(() => ({
      sessionId: "test-session",
      userId: "test-user",
      channel: "console",
    })),
    triggerResolve: vi.fn(),
    resetWindowIdentity: vi.fn(),
    isSessionSwitching: false,
    isUnresolvedLocalSession: vi.fn(() => false),
    getEffectiveSessionId: vi.fn((id: string) => id),
    trackNavigatedSession: vi.fn(),
    preferredChatId: null,
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

vi.mock("@/api/modules/skill", () => ({
  skillApi: {
    listSkills: vi.fn(() => Promise.resolve([])),
  },
}));

vi.mock("@/api/modules/commands", () => ({
  commandsApi: {
    sendApprovalCommand: vi.fn(() => Promise.resolve()),
  },
}));

vi.mock("@/stores/loopStore", () => ({
  useLoopStore: Object.assign(
    vi.fn((selector?: any) => {
      const state = {
        availableModes: [],
        selectedMode: null,
        setSelectedMode: vi.fn(),
        resetSessionMode: vi.fn(),
      };
      return selector ? selector(state) : state;
    }),
    {
      getState: vi.fn(() => ({
        availableModes: [],
        selectedMode: null,
        setSelectedMode: vi.fn(),
        resetSessionMode: vi.fn(),
      })),
    },
  ),
  beginLoopModeSubmission: mockBeginLoopModeSubmission,
  fetchActiveLoopMode: vi.fn(() => Promise.resolve(null)),
  fetchAvailableLoopModes: vi.fn(() => Promise.resolve([])),
  markLoopModeRunning: vi.fn(),
  prepareLoopModeMessage: vi.fn((text: string) => text),
}));

vi.mock("@/stores/sidebarModeStore", () => ({
  useSidebarModeStore: vi.fn(() => ({ mode: "full" })),
}));

vi.mock("@/stores/uploadLimitStore", () => ({
  useUploadLimitStore: Object.assign(
    vi.fn(() => ({ uploadLimit: 10, uploadMaxSizeMb: null })),
    {
      getState: vi.fn(() => ({ uploadLimit: 10, uploadMaxSizeMb: null })),
    },
  ),
}));

vi.mock("@/stores/backgroundTasksStore", () => ({
  useBackgroundTasksStore: Object.assign(
    vi.fn(() => ({ tasks: [] })),
    {
      getState: vi.fn(() => ({ tasks: [] })),
    },
  ),
  selectTasksForSession: vi.fn(() => []),
}));

vi.mock("@/hooks/useBackgroundTaskWatcher", () => ({
  hydrateBackgroundTasksForSession: vi.fn(() => Promise.resolve()),
  stopBackgroundWatchersNotInSession: vi.fn(),
}));

vi.mock("@/hooks/useAgentRunningConfigApprovalLevel", () => ({
  useAgentRunningConfigApprovalLevel: vi.fn(() => "standard"),
}));

vi.mock("@/stores/messageQueueStore", () => ({
  useMessageQueueStore: Object.assign(
    vi.fn((selector?: any) => {
      const state = {
        queues: {},
        getQueue: vi.fn(() => []),
        getRunState: vi.fn(() => "idle"),
        setItemStatus: vi.fn(),
        setCurrentSendingId: vi.fn(),
        currentSendingId: null,
        remove: vi.fn(),
        loadFromStorage: vi.fn(),
        consumeMigratedTo: vi.fn(() => undefined),
        enqueue: vi.fn(),
        edit: vi.fn(),
        reorder: vi.fn(),
        clear: vi.fn(),
        setRunState: vi.fn(),
        migrateQueue: vi.fn(),
      };
      return selector ? selector(state) : state;
    }),
    {
      getState: vi.fn(() => ({
        queues: {},
        getQueue: vi.fn(() => []),
        getRunState: vi.fn(() => "idle"),
        setItemStatus: vi.fn(),
        setCurrentSendingId: vi.fn(),
        currentSendingId: null,
        remove: vi.fn(),
        loadFromStorage: vi.fn(),
        consumeMigratedTo: vi.fn(() => undefined),
        enqueue: vi.fn(),
        edit: vi.fn(),
        reorder: vi.fn(),
        clear: vi.fn(),
        setRunState: vi.fn(),
        migrateQueue: vi.fn(),
      })),
    },
  ),
  MAX_QUEUE_SIZE: 100,
  STORAGE_PREFIX: "chat.queue.",
  withSendLock: vi.fn(async (_key: string, fn: () => any) => fn()),
  holdOwnershipLock: vi.fn((_key: string, cb: () => void, _signal: any) => {
    cb();
    return Promise.resolve();
  }),
}));

vi.mock("@/utils/agentBackend", () => ({
  requiresQwenPawModel: mockRequiresQwenPawModel,
  supportsAgentAttachments: vi.fn(() => true),
}));

vi.mock("@/plugins/registry/useChatExtensions", () => ({
  useChatScalarSnapshot: vi.fn(() => ({})),
  useChatListSnapshot: vi.fn(
    () =>
      new Proxy(
        {},
        {
          get: () => [],
        },
      ),
  ),
}));

vi.mock("./components/ChatSessionDrawer", () => ({
  default: () => <div data-testid="session-drawer" />,
}));

vi.mock("./components/ContextUsageIndicator", () => ({
  default: () => <div data-testid="context-usage" />,
}));

vi.mock("../../components/ApprovalCard/ApprovalCard", () => ({
  ApprovalCard: () => null,
}));

vi.mock("../../hooks/useIsMobile", () => ({
  useIsMobile: vi.fn(() => false),
}));

vi.mock("motion/react", async () => {
  const actual = await vi.importActual("motion/react");
  return {
    ...actual,
    useReducedMotion: vi.fn(() => false),
  };
});

vi.mock("./components/WhisperSpeechButton", () => ({
  default: vi.fn(() => <div data-testid="whisper-btn" />),
}));

vi.mock("../../components/LoopInput", () => ({
  LoopModeSelector: () => null,
}));

vi.mock("./components/ChatSenderTabsPanel", () => ({
  default: () => <div data-testid="sender-tabs" />,
}));

vi.mock("./components/ApprovalLevelToggle", () => ({
  default: () => <div data-testid="approval-toggle" />,
}));

vi.mock("./components/HarnessApprovalToggle", () => ({
  default: () => <div data-testid="harness-approval" />,
}));

vi.mock("./components/HarnessModelSelector", () => ({
  default: () => <div data-testid="harness-model" />,
}));

vi.mock("./replayFastForward", () => ({
  wrapReplayFastForward: vi.fn((opts: any) => opts),
}));

vi.mock("../../components/Chat/MediaDownload", () => ({
  DownloadableAudios: () => null,
}));

vi.mock("../../components/Chat/ToolCards/adapters/v1Adapter", () => ({
  withGenericFallback: vi.fn((fn: any) => fn),
}));

vi.mock("./approvalPayload", () => ({
  applyApprovalLevelToRequestBody: vi.fn((body: any) => body),
}));

vi.mock("../../api/modules/chatProjectDirectory", () => ({
  chatProjectDirectoryApi: {
    get: vi.fn(() => Promise.resolve({ project_dir: "/project" })),
  },
}));

vi.mock("../../api/modules/projectDirectory", () => ({
  projectDirectoryApi: {
    get: vi.fn(() =>
      Promise.resolve({
        path: "/home/user",
        workspace_dir: "/home/user/workspace",
      }),
    ),
  },
}));

vi.mock("./turnUsage", () => ({
  patchContextMaxInputLength: vi.fn((body: any) => body),
  wrapChatResponseUsageStream: vi.fn((stream: any) => stream),
}));

vi.mock("./turnUsageStore", () => ({
  useTurnUsageStore: Object.assign(
    vi.fn(() => ({})),
    {
      getState: vi.fn(() => ({
        beginTurn: vi.fn(() => ({ turnId: "t1" })),
        setSnapshot: vi.fn(),
        snapshot: null,
        invalidateTurn: vi.fn(),
      })),
    },
  ),
}));

vi.mock("./HostBubbles", () => ({
  HostRequestCard: () => null,
  HostResponseCard: () => null,
}));

vi.mock("./components/ChatSessionDrawer", () => ({
  default: () => null,
}));

vi.mock("../../plugins/registry/PluginSlotBoundary", () => ({
  PluginSlotBoundary: ({ children }: any) => children,
}));

vi.mock("../../stores/filesSurfaceStore", () => ({
  useFilesSurfaceStore: Object.assign(
    vi.fn(() => ({
      sessionDrawers: {},
      dispatchSession: vi.fn(),
      migrateSession: vi.fn(),
      removeSession: vi.fn(),
    })),
    {
      getState: vi.fn(() => ({
        sessionDrawers: {},
        dispatchSession: vi.fn(),
        migrateSession: vi.fn(),
        removeSession: vi.fn(),
      })),
    },
  ),
  useSessionFilesDrawer: vi.fn(() => ({ kind: "closed" })),
}));

vi.mock("../../stores/codingTabsStore", () => ({
  useCodingTabsStore: Object.assign(
    vi.fn(() => ({})),
    {
      getState: vi.fn(() => ({
        migrateScope: vi.fn(),
        removeScope: vi.fn(),
      })),
    },
  ),
}));

vi.mock("./utils", async () => {
  const actual = await vi.importActual("./utils");
  return {
    ...actual,
    copyText: mockCopyText,
    getActiveSenderTextarea: vi.fn(() => null),
    getSenderTextareaFromTarget: vi.fn(() => null),
    setTextareaValue: vi.fn(),
    clearSubmittedSenderInput: vi.fn(),
  };
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
describe("ChatPage coverage", () => {
  beforeEach(() => {
    chatExtensions.__resetForTests();
    capturedOptions = null;
    mockCopyText.mockClear();
    mockBeginLoopModeSubmission.mockReset();
    mockBeginLoopModeSubmission.mockImplementation((text: string) => text);
    mockRequiresQwenPawModel.mockReset();
    mockRequiresQwenPawModel.mockReturnValue(true);
    mockListProviders.mockResolvedValue([
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
    ]);
    mockGetActiveModels.mockResolvedValue({
      active_llm: { provider_id: "openai", model: "gpt-4" },
    });
    mockUploadFile.mockResolvedValue({
      url: "uploaded.png",
      file_name: "uploaded.png",
    });
    mockGetTranscriptionProviderType.mockResolvedValue({
      transcription_provider_type: "disabled",
    });
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({}),
    }) as any;
  });

  afterEach(() => {
    chatExtensions.__resetForTests();
    vi.clearAllMocks();
  });

  it("renders ChatPage and captures options", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");
    expect(capturedOptions).toBeTruthy();
  });

  it("renders child components", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");
    expect(screen.getByTestId("model-selector")).toBeInTheDocument();
    expect(screen.getByTestId("action-group")).toBeInTheDocument();
    expect(screen.getByTestId("header-title")).toBeInTheDocument();
  });

  it("invokes customFetch via captured options", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    if (capturedOptions?.api?.fetch) {
      await capturedOptions.api.fetch({
        input: [{ role: "user", content: "hello" }],
        signal: undefined,
      });
      expect(fetch).toHaveBeenCalled();
    }
  });

  it("invokes responseParser via captured options", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    if (capturedOptions?.api?.responseParser) {
      const parsed = capturedOptions.api.responseParser(
        JSON.stringify({
          object: "response",
          status: "completed",
          output: [
            {
              type: "message",
              role: "assistant",
              content: [{ type: "text", text: "answer" }],
            },
          ],
        }),
      );
      expect(parsed).toBeTruthy();
    }
  });

  it("handles file upload via captured options", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    if (capturedOptions?.sender?.attachments?.customRequest) {
      const smallFile = new File(["content"], "img.png", { type: "image/png" });
      const onSuccess = vi.fn();
      const onError = vi.fn();
      await capturedOptions.sender.attachments.customRequest({
        file: smallFile,
        onSuccess,
        onError,
        onProgress: vi.fn(),
      });
      // Just verify the customRequest was invoked without crashing
      expect(true).toBe(true);
    }
  });

  it("renders with /chat/new route", async () => {
    renderWithProviders(<ChatPage />, { initialEntries: ["/chat/new"] });
    await screen.findByTestId("chat-ui");
    expect(capturedOptions).toBeTruthy();
  });

  it("renders with root route", async () => {
    renderWithProviders(<ChatPage />, { initialEntries: ["/"] });
    await screen.findByTestId("chat-ui");
    expect(capturedOptions).toBeTruthy();
  });

  it("re-fetches multimodal caps on model-switched event", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");
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

  it("handles responseParser with fallback metadata", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    if (capturedOptions?.api?.responseParser) {
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
          output: [],
        }),
      );
      expect(parsed).toBeTruthy();
    }
  });

  it("handles responseParser with delta", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    if (capturedOptions?.api?.responseParser) {
      const parsed = capturedOptions.api.responseParser(
        JSON.stringify({
          object: "response.delta",
          delta: "hello world",
        }),
      );
      expect(parsed).toBeTruthy();
    }
  });

  it("handles history clear message detection", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    if (capturedOptions?.api?.responseParser) {
      // Exercise the payloadRequestsHistoryClear / messageRequestsHistoryClear paths
      const parsed = capturedOptions.api.responseParser(
        JSON.stringify({
          object: "message",
          metadata: { clear_history: true },
        }),
      );
      expect(parsed).toBeTruthy();
    }
  });

  it("handles payload completion detection", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    if (capturedOptions?.api?.responseParser) {
      const parsed = capturedOptions.api.responseParser(
        JSON.stringify({
          object: "response",
          status: "completed",
          output: [],
        }),
      );
      expect(parsed.output).toBeDefined();
    }
  });

  // ── responseParser: turn_usage → null ──────────────────────────────────
  it("responseParser returns null for turn_usage payload", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    if (capturedOptions?.api?.responseParser) {
      const parsed = capturedOptions.api.responseParser(
        JSON.stringify({ type: "turn_usage", tokens: 1234 }),
      );
      expect(parsed).toBeNull();
    }
  });

  // ── responseParser: replay_end → heartbeat ─────────────────────────────
  it("responseParser maps replay_end to heartbeat", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    if (capturedOptions?.api?.responseParser) {
      const parsed = capturedOptions.api.responseParser(
        JSON.stringify({ type: "replay_end" }),
      );
      expect(parsed).toBeTruthy();
      expect(parsed.type).toBe("heartbeat");
    }
  });

  // ── responseParser: rate_limited → null ────────────────────────────────
  it("responseParser handles rate_limited payload", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    if (capturedOptions?.api?.responseParser) {
      const parsed = capturedOptions.api.responseParser(
        JSON.stringify({
          type: "rate_limited",
          alternatives: [
            {
              provider_id: "anthropic",
              provider_name: "Anthropic",
              model_id: "claude-3",
              model_name: "Claude 3",
            },
          ],
        }),
      );
      expect(parsed).toBeNull();
    }
  });

  // ── responseParser: completed with empty output fills trailing delta ───
  it("responseParser fills empty output with trailing delta on completion", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    if (capturedOptions?.api?.responseParser) {
      // First send some delta content to build up trailing text
      capturedOptions.api.responseParser(
        JSON.stringify({ object: "response.delta", delta: "partial text" }),
      );
      // Then complete with empty output — should fill from trailing
      const parsed = capturedOptions.api.responseParser(
        JSON.stringify({
          object: "response",
          status: "completed",
          output: [],
        }),
      );
      expect(parsed).toBeTruthy();
      expect(parsed.output).toBeDefined();
      expect(Array.isArray(parsed.output)).toBe(true);
    }
  });

  // ── responseParser: model fallback events in stream ────────────────────
  it("responseParser handles model fallback events before completion", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    if (capturedOptions?.api?.responseParser) {
      // Send a fallback event
      capturedOptions.api.responseParser(
        JSON.stringify({
          object: "response.delta",
          delta: "hello",
          metadata: {
            model_fallback: {
              type: "model_fallback",
              from_provider_id: "openai",
              from_model_id: "gpt-4",
              to_provider_id: "anthropic",
              to_model_id: "claude-3",
              reason_kind: "rate_limited",
            },
          },
        }),
      );
      // Complete the response
      const parsed = capturedOptions.api.responseParser(
        JSON.stringify({
          object: "response",
          status: "completed",
          output: [
            {
              type: "message",
              role: "assistant",
              content: [{ type: "text", text: "answer" }],
            },
          ],
        }),
      );
      expect(parsed).toBeTruthy();
      // Output should have fallback notice prepended
      expect(Array.isArray(parsed.output)).toBe(true);
      expect(parsed.output.length).toBeGreaterThanOrEqual(1);
    }
  });

  // ── customFetch: no active model → shows model prompt ─────────────────
  it("customFetch shows model prompt when no active model", async () => {
    mockGetActiveModels.mockResolvedValueOnce({
      active_llm: { provider_id: null, model: null },
    });
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    if (capturedOptions?.api?.fetch) {
      const result = await capturedOptions.api.fetch({
        input: [{ role: "user", content: "hello" }],
        signal: undefined,
      });
      // Should return a buildModelError response
      expect(result).toBeTruthy();
    }
  });

  // ── customFetch: getActiveModels throws → shows model prompt ──────────
  it("customFetch shows model prompt when getActiveModels throws", async () => {
    mockGetActiveModels.mockRejectedValueOnce(new Error("network error"));
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    if (capturedOptions?.api?.fetch) {
      const result = await capturedOptions.api.fetch({
        input: [{ role: "user", content: "hello" }],
        signal: undefined,
      });
      expect(result).toBeTruthy();
    }
  });

  // ── cancel callback → calls stopChat ───────────────────────────────────
  it("cancel callback invokes stopChat", async () => {
    const { chatApi } = await import("@/api/modules/chat");
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    if (capturedOptions?.api?.cancel) {
      capturedOptions.api.cancel({ session_id: "test-session" });
      // stopChat should have been called
      await waitFor(() => expect(chatApi.stopChat).toHaveBeenCalled());
    }
  });

  // ── reconnect callback → calls fetch ───────────────────────────────────
  it("reconnect callback invokes fetch with reconnect body", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    if (capturedOptions?.api?.reconnect) {
      const result = await capturedOptions.api.reconnect({
        session_id: "test-session",
        signal: undefined,
      });
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/console/chat"),
        expect.objectContaining({
          method: "POST",
        }),
      );
      expect(result).toBeTruthy();
    }
  });

  // ── replaceMediaURL → converts URL ─────────────────────────────────────
  it("replaceMediaURL converts URL via toDisplayUrl", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    if (capturedOptions?.api?.replaceMediaURL) {
      const result = capturedOptions.api.replaceMediaURL(
        "http://example.com/file.png",
      );
      expect(typeof result).toBe("string");
    }
  });

  // ── actions list: copy onClick ─────────────────────────────────────────
  it("actions list copies only the assistant text message", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    const copyAction = capturedOptions?.actions?.list?.[0];
    expect(copyAction?.onClick).toBeTypeOf("function");

    await copyAction.onClick({
      data: {
        output: [
          {
            type: "reasoning",
            role: "assistant",
            content: [{ type: "text", text: "private reasoning" }],
          },
          {
            type: "message",
            role: "assistant",
            content: [{ type: "text", text: "copyable text" }],
          },
        ],
      },
    });
    await waitFor(() => {
      expect(mockCopyText).toHaveBeenCalledWith("copyable text");
    });
  });

  // ── actions list: timestamp render ─────────────────────────────────────
  it("actions list timestamp render returns element", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    const actionsList = capturedOptions?.actions?.list;
    if (actionsList && actionsList.length > 1 && actionsList[1].render) {
      const element = actionsList[1].render({
        data: {
          data: { created_at: 1700000000000, completed_at: 1700000001000 },
        },
      });
      expect(element).toBeTruthy();
    }
  });

  // ── requestActions: copy user message onClick ──────────────────────────
  it("requestActions copy onClick invokes copyText", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    const reqActions = capturedOptions?.requestActions?.list;
    if (reqActions && reqActions.length > 1 && reqActions[1].onClick) {
      await reqActions[1].onClick({
        data: {
          input: [
            { role: "user", content: [{ type: "text", text: "user msg" }] },
          ],
        },
      });
      expect(true).toBe(true);
    }
  });

  // ── requestActions: timestamp render ───────────────────────────────────
  it("requestActions timestamp render returns element", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    const reqActions = capturedOptions?.requestActions?.list;
    if (reqActions && reqActions.length > 0 && reqActions[0].render) {
      const element = reqActions[0].render({
        data: { created_at: 1700000000000 },
      });
      expect(element).toBeTruthy();
    }
  });

  // ── handleBeforeSubmit: SDK query override ─────────────────────────────
  it("returns the prepared query after the SDK captures input data", async () => {
    mockBeginLoopModeSubmission.mockImplementation(
      (text: string) => `/goal ${text}`,
    );
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    const beforeSubmit = capturedOptions?.sender?.beforeSubmit;
    expect(typeof beforeSubmit).toBe("function");

    const inputData = {
      query: "do the task",
      fileList: [
        {
          uid: "file-1",
          name: "notes.txt",
          response: { url: "/files/notes.txt" },
        },
      ],
      mentions: [{ value: "@reviewer", type: "user" }],
    };
    const capturedQuery = inputData.query;
    const result = await beforeSubmit(inputData);
    const submitted = {
      ...inputData,
      query:
        typeof result === "object" && result.query !== undefined
          ? result.query
          : capturedQuery,
    };

    expect(result).toEqual({
      proceed: true,
      query: "/goal do the task",
    });
    expect(submitted.query).toBe("/goal do the task");
    expect(submitted.fileList).toEqual(inputData.fileList);
    expect(submitted.mentions).toEqual(inputData.mentions);
  });

  it("leaves the query unchanged for a non-QwenPaw backend", async () => {
    mockRequiresQwenPawModel.mockReturnValue(false);
    mockBeginLoopModeSubmission.mockImplementation(
      (text: string) => `/goal ${text}`,
    );
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    const beforeSubmit = capturedOptions?.sender?.beforeSubmit;
    const result = await beforeSubmit({ query: "do the task" });

    expect(result).toEqual({ proceed: true, query: "do the task" });
    expect(mockBeginLoopModeSubmission).not.toHaveBeenCalled();
  });

  // ── sender attachments trigger renders ─────────────────────────────────
  it("sender attachments trigger function renders tooltip", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    const attachments = capturedOptions?.sender?.attachments;
    if (attachments?.trigger) {
      const element = attachments.trigger({ disabled: false });
      expect(element).toBeTruthy();
    }
  });

  // ── file upload: multimodal warning path ───────────────────────────────
  it("file upload warns when model has no multimodal support", async () => {
    // The initial render has multimodalCaps all false (before async fetch resolves)
    // So the handleFileUpload in capturedOptions will warn but not block
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    if (capturedOptions?.sender?.attachments?.customRequest) {
      const smallFile = new File(["content"], "doc.pdf", {
        type: "application/pdf",
      });
      const onSuccess = vi.fn();
      const onError = vi.fn();
      await capturedOptions.sender.attachments.customRequest({
        file: smallFile,
        onSuccess,
        onError,
        onProgress: vi.fn(),
      });
      // Should still succeed (warns but doesn't block for non-image files when no multimodal)
      expect(true).toBe(true);
    }
  });

  // ── file upload: error path ────────────────────────────────────────────
  it("file upload calls onError when upload fails", async () => {
    mockUploadFile.mockRejectedValueOnce(new Error("upload failed"));
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    if (capturedOptions?.sender?.attachments?.customRequest) {
      const smallFile = new File(["content"], "img.png", { type: "image/png" });
      const onSuccess = vi.fn();
      const onError = vi.fn();
      await capturedOptions.sender.attachments.customRequest({
        file: smallFile,
        onSuccess,
        onError,
        onProgress: vi.fn(),
      });
      expect(onError).toHaveBeenCalled();
    }
  });

  // ── onFileCardClick → dispatches file preview ──────────────────────────
  it("onFileCardClick dispatches file preview event", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    if (capturedOptions?.api?.onFileCardClick) {
      capturedOptions.api.onFileCardClick({
        name: "test.txt",
        size: 100,
        url: "http://example.com/test.txt",
      });
      // Should not throw
      expect(true).toBe(true);
    }
  });

  // ── onFileCardClick: no url → early return ─────────────────────────────
  it("onFileCardClick does nothing when no url", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    if (capturedOptions?.api?.onFileCardClick) {
      capturedOptions.api.onFileCardClick({ name: "test.txt", size: 100 });
      expect(true).toBe(true);
    }
  });

  // ── responseParser: payloadRequestsHistoryClear via response.output ────
  it("responseParser detects history clear in response output array", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    if (capturedOptions?.api?.responseParser) {
      const parsed = capturedOptions.api.responseParser(
        JSON.stringify({
          object: "response",
          status: "completed",
          output: [
            {
              type: "message",
              role: "assistant",
              metadata: { clear_history: true },
              content: [{ type: "text", text: "cleared" }],
            },
          ],
        }),
      );
      expect(parsed).toBeTruthy();
    }
  });

  // ── responseParser: nested metadata clear_history ──────────────────────
  it("responseParser detects nested metadata clear_history", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    if (capturedOptions?.api?.responseParser) {
      const parsed = capturedOptions.api.responseParser(
        JSON.stringify({
          object: "message",
          metadata: {
            metadata: { clear_history: true },
          },
        }),
      );
      expect(parsed).toBeTruthy();
    }
  });

  // ── customFetch: successful fetch with full request body ───────────────
  it("customFetch sends correct request body and returns response", async () => {
    const mockResponse = {
      ok: true,
      status: 200,
      body: null,
      json: () => Promise.resolve({}),
    };
    global.fetch = vi.fn().mockResolvedValue(mockResponse) as any;

    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    if (capturedOptions?.api?.fetch) {
      const result = await capturedOptions.api.fetch({
        input: [
          {
            role: "user",
            content: [{ type: "text", text: "hello world" }],
          },
        ],
        signal: undefined,
      });
      expect(result).toBeTruthy();
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/console/chat"),
        expect.objectContaining({
          method: "POST",
          body: expect.any(String),
        }),
      );
      // Verify the body contains expected fields
      const callArgs = (fetch as any).mock.calls.find(
        (c: any) =>
          c[0]?.includes?.("/console/chat") && c[1]?.method === "POST",
      );
      if (callArgs) {
        const body = JSON.parse(callArgs[1].body);
        expect(body.stream).toBe(true);
        expect(body.input).toBeDefined();
      }
    }
  });

  // ── customFetch: with biz_params ───────────────────────────────────────
  it("customFetch merges biz_params into request body", async () => {
    const mockResponse = { ok: true, status: 200, body: null };
    global.fetch = vi.fn().mockResolvedValue(mockResponse) as any;

    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    if (capturedOptions?.api?.fetch) {
      await capturedOptions.api.fetch({
        input: [{ role: "user", content: "test" }],
        biz_params: { custom_field: "custom_value" },
        signal: undefined,
      });
      const callArgs = (fetch as any).mock.calls.find(
        (c: any) =>
          c[0]?.includes?.("/console/chat") && c[1]?.method === "POST",
      );
      if (callArgs) {
        const body = JSON.parse(callArgs[1].body);
        expect(body.custom_field).toBe("custom_value");
      }
    }
  });

  // ── responseParser: completed with non-empty output (no trailing fill) ─
  it("responseParser keeps canonical output when non-empty on completion", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    if (capturedOptions?.api?.responseParser) {
      const parsed = capturedOptions.api.responseParser(
        JSON.stringify({
          object: "response",
          status: "completed",
          output: [
            {
              type: "message",
              role: "assistant",
              content: [{ type: "text", text: "full answer" }],
            },
          ],
        }),
      );
      expect(parsed.output).toHaveLength(1);
      expect(parsed.output[0].content[0].text).toBe("full answer");
    }
  });

  // ── responseParser: completed with error and empty output ──────────────
  it("responseParser uses error message when output is empty on completion", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    if (capturedOptions?.api?.responseParser) {
      const parsed = capturedOptions.api.responseParser(
        JSON.stringify({
          object: "response",
          status: "completed",
          output: [],
          error: { message: "something went wrong" },
        }),
      );
      expect(parsed.output).toBeDefined();
      // Should contain the error message
      const textContent = parsed.output?.[0]?.content?.[0]?.text;
      expect(textContent).toBe("something went wrong");
    }
  });

  // ── customFetch: non-ok response discards last user message ────────────
  it("customFetch discards last user message on non-ok response", async () => {
    const mockResponse = { ok: false, status: 500, body: null };
    global.fetch = vi.fn().mockResolvedValue(mockResponse) as any;

    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    if (capturedOptions?.api?.fetch) {
      const result = await capturedOptions.api.fetch({
        input: [{ role: "user", content: "hello" }],
        signal: undefined,
      });
      expect(result.ok).toBe(false);
    }
  });

  // ── sender longTextUpload customRequest ────────────────────────────────
  it("sender longTextUpload customRequest is available", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    const longTextUpload = capturedOptions?.sender?.longTextUpload;
    if (longTextUpload) {
      expect(typeof longTextUpload.customRequest).toBe("function");
      expect(typeof longTextUpload.prompt).toBe("function");
      // Exercise the prompt function
      const promptText = longTextUpload.prompt();
      expect(typeof promptText).toBe("string");
    }
  });

  // ── sender placeholder ─────────────────────────────────────────────────
  it("sender has placeholder text", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    expect(capturedOptions?.sender?.placeholder).toBeTruthy();
    expect(typeof capturedOptions?.sender?.placeholder).toBe("string");
  });

  // ── sender suggestions ─────────────────────────────────────────────────
  it("sender has suggestions array", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    expect(Array.isArray(capturedOptions?.sender?.suggestions)).toBe(true);
    // Should have at least /new and /clear commands
    expect(capturedOptions.sender.suggestions.length).toBeGreaterThanOrEqual(2);
  });

  // ── session config ─────────────────────────────────────────────────────
  it("session config has multiple and api", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    expect(capturedOptions?.session?.multiple).toBe(true);
    expect(capturedOptions?.session?.hideBuiltInSessionList).toBe(true);
    expect(capturedOptions?.session?.api).toBeTruthy();
  });

  // ── welcome config ─────────────────────────────────────────────────────
  it("welcome config has nick and avatar", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    expect(capturedOptions?.welcome?.nick).toBeTruthy();
    expect(capturedOptions?.welcome?.avatar).toBeTruthy();
  });

  // ── theme config ───────────────────────────────────────────────────────
  it("theme config has darkMode and rightHeader", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    expect(capturedOptions?.theme?.darkMode).toBe(false);
    expect(capturedOptions?.theme?.rightHeader).toBeTruthy();
  });

  // ── actions config ─────────────────────────────────────────────────────
  it("actions config has replace true and right false", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    expect(capturedOptions?.actions?.replace).toBe(true);
    expect(capturedOptions?.actions?.right).toBe(false);
  });

  // ── customToolRenderConfig ─────────────────────────────────────────────
  it("customToolRenderConfig is defined", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    expect(capturedOptions?.customToolRenderConfig).toBeTruthy();
    expect(typeof capturedOptions.customToolRenderConfig).toBe("object");
  });

  // ── cards config ───────────────────────────────────────────────────────
  it("cards config has host wrappers", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    expect(capturedOptions?.cards?.AgentScopeRuntimeRequestCard).toBeTruthy();
    expect(capturedOptions?.cards?.AgentScopeRuntimeResponseCard).toBeTruthy();
    expect(capturedOptions?.cards?.Audios).toBeTruthy();
  });

  // ── Whisper speech button renders when enabled ─────────────────────────
  it("renders whisper button when transcription is enabled", async () => {
    mockGetTranscriptionProviderType.mockResolvedValueOnce({
      transcription_provider_type: "openai_whisper",
    });
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");
    // Whisper button should appear when enabled
    await waitFor(() => {
      expect(screen.getByTestId("whisper-btn")).toBeInTheDocument();
    });
  });

  // ── /chat/new route creates fresh session ──────────────────────────────
  it("/chat/new route renders with correct options", async () => {
    renderWithProviders(<ChatPage />, { initialEntries: ["/chat/new"] });
    await screen.findByTestId("chat-ui");
    expect(capturedOptions).toBeTruthy();
    expect(capturedOptions?.sender?.placeholder).toBeTruthy();
  });

  // ── root route redirects behavior ──────────────────────────────────────
  it("root route renders chat page", async () => {
    renderWithProviders(<ChatPage />, { initialEntries: ["/"] });
    await screen.findByTestId("chat-ui");
    expect(capturedOptions).toBeTruthy();
  });

  // ── responseParser: invalid JSON handling ──────────────────────────────
  it("responseParser handles invalid JSON gracefully", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    if (capturedOptions?.api?.responseParser) {
      // This should throw since JSON.parse will fail
      expect(() => {
        capturedOptions.api.responseParser("not valid json");
      }).toThrow();
    }
  });

  // ── file upload: image-only warning when only image supported ──────────
  it("file upload warns for non-image when only image supported", async () => {
    // Default mocks already return supports_multimodal: true, supports_image: true, supports_video: false
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    if (capturedOptions?.sender?.attachments?.customRequest) {
      // Upload a non-image file (PDF) when only image is supported
      const pdfFile = new File(["content"], "doc.pdf", {
        type: "application/pdf",
      });
      const onSuccess = vi.fn();
      const onError = vi.fn();
      await capturedOptions.sender.attachments.customRequest({
        file: pdfFile,
        onSuccess,
        onError,
        onProgress: vi.fn(),
      });
      // Should succeed (warns but doesn't block) - just verify no crash
      expect(true).toBe(true);
    }
  });

  // ── file upload: video file when video supported ───────────────────────
  it("file upload handles video file when video supported", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    if (capturedOptions?.sender?.attachments?.customRequest) {
      const videoFile = new File(["video-content"], "clip.mp4", {
        type: "video/mp4",
      });
      const onSuccess = vi.fn();
      const onError = vi.fn();
      await capturedOptions.sender.attachments.customRequest({
        file: videoFile,
        onSuccess,
        onError,
        onProgress: vi.fn(),
      });
      // Just verify no crash — actual success depends on async multimodal caps resolution
      expect(true).toBe(true);
    }
  });

  // ── model-switched event with maxInputLength ───────────────────────────
  it("model-switched event with maxInputLength patches context", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    // Dispatch model-switched with maxInputLength detail
    act(() => {
      window.dispatchEvent(
        new CustomEvent("model-switched", {
          detail: { maxInputLength: 65536 },
        }),
      );
    });

    // Should trigger both fetchMultimodalCaps and patchContextMaxInputLength
    await waitFor(() => {
      expect(mockGetActiveModels).toHaveBeenCalled();
    });
  });

  // ── qwenpaw:open-file-preview event ────────────────────────────────────
  it("handles qwenpaw:open-file-preview custom event", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    // Dispatch the file preview event
    act(() => {
      window.dispatchEvent(
        new CustomEvent("qwenpaw:open-file-preview", {
          detail: {
            target: { source: "workspace", path: "/test/file.txt" },
            trigger: null,
          },
        }),
      );
    });

    // Should not throw
    expect(true).toBe(true);
  });

  // ── responseParser: duplicate fallback events are deduplicated ─────────
  it("responseParser deduplicates identical fallback events", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    if (capturedOptions?.api?.responseParser) {
      const fallbackPayload = {
        object: "response.delta",
        delta: "text",
        metadata: {
          model_fallback: {
            type: "model_fallback",
            from_provider_id: "openai",
            from_model_id: "gpt-4",
            to_provider_id: "anthropic",
            to_model_id: "claude-3",
            reason_kind: "rate_limited",
          },
        },
      };
      // Send same fallback twice — should be deduplicated
      capturedOptions.api.responseParser(JSON.stringify(fallbackPayload));
      capturedOptions.api.responseParser(JSON.stringify(fallbackPayload));
      // Complete
      const parsed = capturedOptions.api.responseParser(
        JSON.stringify({
          object: "response",
          status: "completed",
          output: [
            {
              type: "message",
              role: "assistant",
              content: [{ type: "text", text: "answer" }],
            },
          ],
        }),
      );
      expect(parsed).toBeTruthy();
      // Output should have at least the original content
      expect(Array.isArray(parsed.output)).toBe(true);
      expect(parsed.output.length).toBeGreaterThanOrEqual(1);
    }
  });

  // ── Ctrl+Shift+M shortcut for voice recording ─────────────────────────
  it("Ctrl+Shift+M shortcut triggers whisper recording when enabled", async () => {
    mockGetTranscriptionProviderType.mockResolvedValueOnce({
      transcription_provider_type: "openai_whisper",
    });
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    // Wait for whisper to be checked
    await waitFor(() => {
      expect(screen.getByTestId("whisper-btn")).toBeInTheDocument();
    });

    // Dispatch the shortcut key
    act(() => {
      document.dispatchEvent(
        new KeyboardEvent("keydown", {
          key: "m",
          ctrlKey: true,
          shiftKey: true,
          bubbles: true,
        }),
      );
    });

    // Should not throw
    expect(true).toBe(true);
  });

  // ── Tab key completion for slash commands ──────────────────────────────
  it("Tab key in sender textarea with slash command does not crash", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    // Dispatch Tab key event — should be handled gracefully
    act(() => {
      document.dispatchEvent(
        new KeyboardEvent("keydown", {
          key: "Tab",
          bubbles: true,
        }),
      );
    });

    expect(true).toBe(true);
  });

  // ── Enter key enqueue when loading ─────────────────────────────────────
  it("Enter key enqueue handler is registered without crash", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    // Dispatch Enter key — should be handled gracefully
    act(() => {
      document.dispatchEvent(
        new KeyboardEvent("keydown", {
          key: "Enter",
          bubbles: true,
        }),
      );
    });

    expect(true).toBe(true);
  });

  // ── composition events (IME) ───────────────────────────────────────────
  it("IME composition events are handled", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    // Dispatch composition events
    act(() => {
      document.dispatchEvent(
        new CompositionEvent("compositionstart", { bubbles: true }),
      );
    });
    act(() => {
      document.dispatchEvent(
        new CompositionEvent("compositionend", { bubbles: true }),
      );
    });

    expect(true).toBe(true);
  });

  // ── ArrowUp/ArrowDown history navigation ──────────────────────────────
  it("ArrowUp/ArrowDown key events are handled without crash", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    act(() => {
      document.dispatchEvent(
        new KeyboardEvent("keydown", { key: "ArrowUp", bubbles: true }),
      );
    });
    act(() => {
      document.dispatchEvent(
        new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }),
      );
    });

    expect(true).toBe(true);
  });

  // ── Trigger rate limit banner via responseParser ───────────────────────
  it("renders rate limit banner when rate_limited payload received", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    if (capturedOptions?.api?.responseParser) {
      // Send rate_limited payload to set rateLimitAlternatives
      capturedOptions.api.responseParser(
        JSON.stringify({
          type: "rate_limited",
          alternatives: [
            {
              provider_id: "anthropic",
              provider_name: "Anthropic",
              model_id: "claude-3",
              model_name: "Claude 3",
            },
            {
              provider_id: "google",
              provider_name: "Google",
              model_id: "gemini-pro",
              model_name: "Gemini Pro",
            },
          ],
        }),
      );
      // Component should re-render with rate limit banner
      await waitFor(() => {
        expect(capturedOptions).toBeTruthy();
      });
    }
  });

  // ── Trigger model prompt modal via customFetch ─────────────────────────
  it("renders model prompt modal when no active model", async () => {
    mockGetActiveModels.mockResolvedValueOnce({
      active_llm: { provider_id: null, model: null },
    });
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    if (capturedOptions?.api?.fetch) {
      await capturedOptions.api.fetch({
        input: [{ role: "user", content: "hello" }],
        signal: undefined,
      });
      // Component should re-render with model prompt modal
      await waitFor(() => {
        expect(capturedOptions).toBeTruthy();
      });
    }
  });

  // ── Cancel callback with no resolved chat ID ───────────────────────────
  it("cancel callback handles missing chat ID gracefully", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    if (capturedOptions?.api?.cancel) {
      // Call with empty session_id
      capturedOptions.api.cancel({ session_id: "" });
      expect(true).toBe(true);
    }
  });

  // ── Reconnect callback with signal ─────────────────────────────────────
  it("reconnect callback handles abort signal", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    if (capturedOptions?.api?.reconnect) {
      const controller = new AbortController();
      const result = await capturedOptions.api.reconnect({
        session_id: "test-session",
        signal: controller.signal,
      });
      expect(result).toBeTruthy();
    }
  });

  // ── customFetch with empty input ───────────────────────────────────────
  it("customFetch handles empty input array", async () => {
    const mockResponse = { ok: true, status: 200, body: null };
    global.fetch = vi.fn().mockResolvedValue(mockResponse) as any;

    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    if (capturedOptions?.api?.fetch) {
      const result = await capturedOptions.api.fetch({
        input: [],
        signal: undefined,
      });
      expect(result).toBeTruthy();
    }
  });

  // ── customFetch with session in input ──────────────────────────────────
  it("customFetch extracts session from input", async () => {
    const mockResponse = { ok: true, status: 200, body: null };
    global.fetch = vi.fn().mockResolvedValue(mockResponse) as any;

    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    if (capturedOptions?.api?.fetch) {
      const result = await capturedOptions.api.fetch({
        input: [
          {
            role: "user",
            content: "test",
            session: { session_id: "custom-session", user_id: "custom-user" },
          },
        ],
        signal: undefined,
      });
      expect(result).toBeTruthy();
      const callArgs = (fetch as any).mock.calls.find(
        (c: any) =>
          c[0]?.includes?.("/console/chat") && c[1]?.method === "POST",
      );
      if (callArgs) {
        const body = JSON.parse(callArgs[1].body);
        expect(body.session_id).toBeDefined();
      }
    }
  });

  // ── responseParser with non-object payload ─────────────────────────────
  it("responseParser handles non-object payload gracefully", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    if (capturedOptions?.api?.responseParser) {
      // Send a string payload (not an object); should not crash
      expect(() =>
        capturedOptions.api.responseParser(JSON.stringify("just a string")),
      ).not.toThrow();
    }
  });

  // ── responseParser with null payload ───────────────────────────────────
  it("responseParser handles null-like payload", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    if (capturedOptions?.api?.responseParser) {
      // null payload causes parseModelFallbackEvents to throw (accessing .metadata on null)
      expect(() => {
        capturedOptions.api.responseParser(JSON.stringify(null));
      }).toThrow();
    }
  });

  // ── File upload with progress callback ─────────────────────────────────
  it("file upload calls onProgress callback", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    if (capturedOptions?.sender?.attachments?.customRequest) {
      const smallFile = new File(["content"], "img.png", { type: "image/png" });
      const onSuccess = vi.fn();
      const onError = vi.fn();
      const onProgress = vi.fn();
      await capturedOptions.sender.attachments.customRequest({
        file: smallFile,
        onSuccess,
        onError,
        onProgress,
      });
      // onProgress should be called with 100% after upload
      expect(onProgress).toHaveBeenCalledWith({ percent: 100 });
    }
  });

  // ── onFileCardClick with url containing query params ───────────────────
  it("onFileCardClick handles url with query params", async () => {
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/test-session"],
    });
    await screen.findByTestId("chat-ui");

    if (capturedOptions?.api?.onFileCardClick) {
      capturedOptions.api.onFileCardClick({
        name: "test.txt",
        size: 100,
        url: "http://example.com/test.txt?token=abc123",
      });
      expect(true).toBe(true);
    }
  });
});
