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
} = vi.hoisted(() => ({
  mockListProviders: vi.fn(),
  mockGetActiveModels: vi.fn(),
  mockUploadFile: vi.fn(),
  mockFilePreviewUrl: vi.fn((f: string) => `/preview/${f}`),
  mockGetApiUrl: vi.fn((p: string) => `/api${p}`),
  mockSelectedAgent: vi.fn(() => "default"),
  mockSetSelectedAgent: vi.fn(),
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
    return <div data-testid="chat-ui">{props.options?.theme?.rightHeader}</div>;
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
  useAgentStore: vi.fn(() => ({
    selectedAgent: mockSelectedAgent(),
    setSelectedAgent: mockSetSelectedAgent,
  })),
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
    setLastUserMessage: vi.fn(),
  },
}));

vi.mock("./OptionsPanel/defaultConfig", () => ({
  default: { theme: { leftHeader: {} }, api: {} },
  getDefaultConfig: vi.fn(() => ({
    theme: { leftHeader: {} },
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
    capturedOptions = null;
    mockListProviders.mockResolvedValue(mockProviders);
    mockGetActiveModels.mockResolvedValue(mockActiveModel);
    mockUploadFile.mockResolvedValue({
      url: "uploaded.png",
      file_name: "uploaded.png",
    });
  });

  afterEach(() => vi.clearAllMocks());

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
