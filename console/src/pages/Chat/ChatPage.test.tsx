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
import { renderWithProviders } from "@/test/common_setup";
import ChatPage from "./index";
import { chatExtensions } from "@/plugins/registry/chatExtensions";

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
  mockDiscardLastUserMessage,
} = vi.hoisted(() => ({
  mockListProviders: vi.fn(),
  mockGetActiveModels: vi.fn(),
  mockUploadFile: vi.fn(),
  mockFilePreviewUrl: vi.fn((f: string) => `/preview/${f}`),
  mockGetApiUrl: vi.fn((p: string) => `/api${p}`),
  mockSelectedAgent: vi.fn(() => "default"),
  mockSetSelectedAgent: vi.fn(),
  mockGetTranscriptionProviderType: vi.fn(),
  mockDiscardLastUserMessage: vi.fn(),
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

vi.mock("@agentscope-ai/chat", () => ({
  // render rightHeader so child components appear in the DOM
  AgentScopeRuntimeWebUI: vi.fn((props: any) => {
    capturedOptions = props.options;
    return (
      <div data-testid="chat-ui">
        {props.options?.theme?.rightHeader}
        <div className="sender">
          <textarea data-testid="sender-input" />
        </div>
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

vi.mock("@/api/modules/skill", () => ({
  skillApi: { listSkills: vi.fn(() => Promise.resolve([])) },
}));

vi.mock("@/stores/uploadLimitStore", () => ({
  useUploadLimitStore: {
    getState: vi.fn(() => ({ uploadMaxSizeMb: 10 })),
  },
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

vi.mock("@/stores/agentStore", () => ({
  useAgentStore: Object.assign(
    vi.fn(() => ({
      agents: [{ id: "default", backend: "qwenpaw" }],
      getLastChatId: vi.fn(() => undefined),
      removeLastChatId: vi.fn(),
      selectedAgent: mockSelectedAgent(),
      setLastChatId: vi.fn(),
      setSelectedAgent: mockSetSelectedAgent,
    })),
    {
      getState: vi.fn(() => ({ selectedAgent: mockSelectedAgent() })),
      subscribe: vi.fn(() => vi.fn()),
    },
  ),
}));

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
    getBackendSessionId: vi.fn((sessionId: string) => sessionId),
    getEffectiveSessionId: vi.fn((sessionId: string) => sessionId),
    getSessionIdentity: vi.fn(() => ({
      sessionId: "",
      userId: "console-user",
      channel: "console",
    })),
    discardLastUserMessage: mockDiscardLastUserMessage,
    isUnresolvedLocalSession: vi.fn(() => false),
    resetWindowIdentity: vi.fn(),
    setLastUserMessage: vi.fn(),
    trackNavigatedSession: vi.fn(),
    triggerResolve: vi.fn(),
    isSessionSwitching: false,
    lastActiveChatId: null,
    preferredChatId: null,
  },
}));

vi.mock("./OptionsPanel/defaultConfig", () => ({
  default: {
    theme: {
      leftHeader: {},
      bubbleList: { userMessageAnchors: { variant: "navigator" } },
    },
    api: {},
  },
  getDefaultConfig: vi.fn(() => ({
    theme: {
      leftHeader: {},
      bubbleList: { userMessageAnchors: { variant: "navigator" } },
    },
    api: {},
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
    localStorage.clear();
    mockListProviders.mockResolvedValue(mockProviders);
    mockGetActiveModels.mockResolvedValue(mockActiveModel);
    mockUploadFile.mockResolvedValue({
      url: "uploaded.png",
      file_name: "uploaded.png",
    });
    mockGetTranscriptionProviderType.mockResolvedValue({
      transcription_provider_type: "disabled",
    });
  });

  afterEach(() => {
    chatExtensions.__resetForTests();
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
    expect(screen.getByTestId("model-selector")).toBeInTheDocument();
    expect(screen.getByTestId("action-group")).toBeInTheDocument();
    expect(screen.getByTestId("header-title")).toBeInTheDocument();
  });

  // ── customFetch: model not configured → show modal ────────────────────────

  it("sends chat when the active-model refresh fails", async () => {
    mockGetActiveModels.mockRejectedValue(new Error("network"));
    global.fetch = vi
      .fn()
      .mockResolvedValue({ ok: true, status: 200 } as Response);
    renderWithProviders(<ChatPage />, { initialEntries: ["/chat"] });
    await screen.findByTestId("chat-ui");

    const response = await capturedOptions.api.fetch({
      input: [{ role: "user", content: "hello" }],
      signal: undefined,
    });

    expect(response.status).toBe(200);
    expect(fetch).toHaveBeenCalledWith(
      "/api/console/chat",
      expect.objectContaining({ method: "POST" }),
    );
    expect(screen.queryByText("modelConfig.promptTitle")).toBeNull();
  });

  it("shows the modal for an explicit backend model error", async () => {
    renderWithProviders(<ChatPage />, { initialEntries: ["/chat"] });
    await screen.findByTestId("chat-ui");

    act(() => {
      capturedOptions.api.responseParser(
        JSON.stringify({
          object: "response",
          status: "failed",
          error: { code: "MODEL_NOT_CONFIGURED", message: "missing" },
        }),
      );
    });

    expect(await screen.findByTestId("modal")).toBeInTheDocument();
  });

  it("does not show the modal for other backend errors", async () => {
    renderWithProviders(<ChatPage />, { initialEntries: ["/chat"] });
    await screen.findByTestId("chat-ui");

    act(() => {
      capturedOptions.api.responseParser(
        JSON.stringify({
          object: "response",
          status: "failed",
          error: { code: "AGENT_CONFIG_UNAVAILABLE", message: "offline" },
        }),
      );
    });

    expect(screen.queryByTestId("modal")).toBeNull();
  });

  it("terminates an empty reconnect stream for the SDK", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValue(new Response(null, { status: 200 }));
    renderWithProviders(<ChatPage />, { initialEntries: ["/chat"] });
    await screen.findByTestId("chat-ui");

    const response = await capturedOptions.api.reconnect({
      session_id: "chat-1",
    });

    expect(response.status).toBe(200);
    await expect(response.text()).resolves.toContain("CHAT_STREAM_INCOMPLETE");
  });

  // ── modal interaction ─────────────────────────────────────────────────────

  it("clicking Skip button closes the modal", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ChatPage />, { initialEntries: ["/chat"] });
    await screen.findByTestId("chat-ui");

    act(() => {
      capturedOptions.api.responseParser(
        JSON.stringify({
          object: "response",
          status: "failed",
          error: { code: "MODEL_NOT_CONFIGURED", message: "missing" },
        }),
      );
    });
    await screen.findByTestId("modal");

    await user.click(screen.getByRole("button", { name: "Skip" }));
    // antd Modal has animations; wait for DOM removal
    await waitFor(
      () => expect(screen.queryByTestId("modal")).not.toBeInTheDocument(),
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

    const chatCall = vi
      .mocked(fetch)
      .mock.calls.find(([url]) => url === "/api/console/chat");
    const init = chatCall?.[1] as RequestInit;
    const body = JSON.parse(String(init.body)) as Record<string, unknown>;
    expect(body.request_context).toEqual(
      expect.objectContaining({
        session_id: "session-1",
        agent_id: "default",
        datasource_id: "ds-123",
      }),
    );
  });

  it("restores submitted text and draft after a network failure", async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error("network"));
    renderWithProviders(<ChatPage />, { initialEntries: ["/chat"] });
    await screen.findByTestId("chat-ui");
    const textarea = screen.getByTestId("sender-input") as HTMLTextAreaElement;
    textarea.value = "keep this message";
    await capturedOptions.sender.beforeSubmit();
    textarea.value = "";

    const response = await capturedOptions.api.fetch({
      input: [{ role: "user", content: "keep this message" }],
      signal: undefined,
    });

    expect(response.status).toBe(503);
    await expect(response.json()).resolves.toEqual({
      detail: { code: "CHAT_REQUEST_FAILED", message: "network" },
    });
    expect(textarea.value).toBe("keep this message");
    expect(
      JSON.parse(
        localStorage.getItem("qwenpaw_chat_input_draft_default") || "{}",
      ).value,
    ).toBe("keep this message");
  });

  it("preserves cancellation semantics for an aborted chat request", async () => {
    const controller = new AbortController();
    const abortError = new DOMException("aborted", "AbortError");
    global.fetch = vi.fn().mockRejectedValue(abortError);
    renderWithProviders(<ChatPage />, { initialEntries: ["/chat"] });
    await screen.findByTestId("chat-ui");
    const textarea = screen.getByTestId("sender-input") as HTMLTextAreaElement;
    textarea.value = "cancel this message";
    await capturedOptions.sender.beforeSubmit();
    textarea.value = "";
    controller.abort();

    await expect(
      capturedOptions.api.fetch({
        input: [{ role: "user", content: "cancel this message" }],
        signal: controller.signal,
      }),
    ).rejects.toBe(abortError);

    act(() => {
      capturedOptions.api.responseParser(
        JSON.stringify({
          object: "response",
          status: "failed",
          error: { code: "MODEL_NOT_CONFIGURED", message: "missing" },
        }),
      );
    });
    expect(textarea.value).toBe("");
    expect(localStorage.getItem("qwenpaw_chat_input_draft_default")).toBeNull();
  });

  it("restores submitted text and opens the modal after an HTTP model error", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 400,
      clone: () => ({
        json: vi.fn().mockResolvedValue({
          detail: { code: "MODEL_NOT_CONFIGURED", message: "missing" },
        }),
      }),
    } as unknown as Response);
    renderWithProviders(<ChatPage />, { initialEntries: ["/chat"] });
    await screen.findByTestId("chat-ui");
    const textarea = screen.getByTestId("sender-input") as HTMLTextAreaElement;
    textarea.value = "retry me";
    await capturedOptions.sender.beforeSubmit();
    textarea.value = "";

    await capturedOptions.api.fetch({
      input: [{ role: "user", content: "retry me" }],
      signal: undefined,
    });

    expect(textarea.value).toBe("retry me");
    expect(await screen.findByTestId("modal")).toBeInTheDocument();
  });

  it("restores submitted text for an SSE model configuration error", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValue(new Response(null, { status: 200 }));
    renderWithProviders(<ChatPage />, { initialEntries: ["/chat"] });
    await screen.findByTestId("chat-ui");
    const textarea = screen.getByTestId("sender-input") as HTMLTextAreaElement;
    textarea.value = "configure then retry";
    await capturedOptions.sender.beforeSubmit();
    textarea.value = "";
    await capturedOptions.api.fetch({
      input: [{ role: "user", content: "configure then retry" }],
      signal: undefined,
    });
    expect(textarea.value).toBe("");

    act(() => {
      capturedOptions.api.responseParser(
        JSON.stringify({
          object: "response",
          status: "failed",
          error: { code: "MODEL_NOT_CONFIGURED", message: "missing" },
        }),
      );
    });

    expect(textarea.value).toBe("configure then retry");
  });

  it("restores and clears pending state for unavailable agent config", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValue(new Response(null, { status: 200 }));
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/chat-config"],
    });
    await screen.findByTestId("chat-ui");
    const textarea = screen.getByTestId("sender-input") as HTMLTextAreaElement;
    textarea.value = "retry after config recovers";
    await capturedOptions.sender.beforeSubmit();
    textarea.value = "";
    await capturedOptions.api.fetch({
      input: [{ role: "user", content: "retry after config recovers" }],
      signal: undefined,
    });

    act(() => {
      capturedOptions.api.responseParser(
        JSON.stringify({
          object: "response",
          status: "failed",
          error: { code: "AGENT_CONFIG_UNAVAILABLE", message: "offline" },
        }),
      );
    });

    expect(textarea.value).toBe("retry after config recovers");
    expect(mockDiscardLastUserMessage).toHaveBeenCalledWith(
      "chat-config",
      expect.any(String),
    );
    expect(screen.queryByTestId("modal")).toBeNull();
  });

  it("does not restore a submission that failed during execution", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValue(new Response(null, { status: 200 }));
    renderWithProviders(<ChatPage />, {
      initialEntries: ["/chat/chat-execution"],
    });
    await screen.findByTestId("chat-ui");
    const textarea = screen.getByTestId("sender-input") as HTMLTextAreaElement;
    textarea.value = "do not run twice";
    await capturedOptions.sender.beforeSubmit();
    textarea.value = "";
    await capturedOptions.api.fetch({
      input: [{ role: "user", content: "do not run twice" }],
      signal: undefined,
    });

    act(() => {
      capturedOptions.api.responseParser(
        JSON.stringify({
          object: "response",
          status: "failed",
          error: { code: "MODEL_EXECUTION_ERROR", message: "upstream" },
        }),
      );
    });

    expect(textarea.value).toBe("");
    expect(mockDiscardLastUserMessage).not.toHaveBeenCalled();
  });

  it("does not overwrite newer input when restoring a failed submission", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValue(new Response(null, { status: 200 }));
    renderWithProviders(<ChatPage />, { initialEntries: ["/chat"] });
    await screen.findByTestId("chat-ui");
    const textarea = screen.getByTestId("sender-input") as HTMLTextAreaElement;
    textarea.value = "old submission";
    await capturedOptions.sender.beforeSubmit();
    textarea.value = "";
    await capturedOptions.api.fetch({
      input: [{ role: "user", content: "old submission" }],
      signal: undefined,
    });
    textarea.value = "newer input";

    act(() => {
      capturedOptions.api.responseParser(
        JSON.stringify({
          object: "response",
          status: "failed",
          error: { code: "MODEL_NOT_CONFIGURED", message: "missing" },
        }),
      );
    });

    expect(textarea.value).toBe("newer input");
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
    expect(capturedOptions.sender.prefix.props.children[0]).toBeNull();

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
      expect(capturedOptions.sender.prefix.props.children[0]).toBeTruthy();
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
      expect(capturedOptions.sender.prefix.props.children[0]).toBeNull();
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
