import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useLocation, useNavigate } from "react-router-dom";
import { renderWithProviders } from "@/test/common_setup";
import { useSessionListStore } from "@/stores/sessionListStore";
import { useAgentStore } from "@/stores/agentStore";
import ChatSessionInitializer from "./index";
import sessionApi from "../../sessionApi";

const {
  mockCreateSession,
  mockSessionState,
  mockSetCurrentSessionId,
  mockSetSessions,
} = vi.hoisted(() => ({
  mockCreateSession: vi.fn(),
  mockSessionState: {
    sessions: [] as Array<{ id: string; realId?: string }>,
    currentSessionId: undefined as string | undefined,
  },
  mockSetCurrentSessionId: vi.fn(),
  mockSetSessions: vi.fn(),
}));

vi.mock("@agentscope-ai/chat", () => ({
  useChatAnywhereSessions: () => ({ createSession: mockCreateSession }),
  useChatAnywhereSessionsState: () => ({
    sessions: mockSessionState.sessions,
    currentSessionId: mockSessionState.currentSessionId,
    setCurrentSessionId: mockSetCurrentSessionId,
    setSessions: mockSetSessions,
  }),
}));

vi.mock("../../sessionApi", () => ({
  default: {
    finishSessionSwitch: vi.fn(),
    getEffectiveSessionId: vi.fn((sessionId: string) => sessionId),
    isSessionSwitching: false,
    lastActiveChatId: null,
    lastNavigatedChatId: null,
    onSessionNotFound: null,
    preferredChatId: null,
    preloadSession: vi.fn(),
    resetWindowIdentity: vi.fn(),
    trackNavigatedSession: vi.fn(),
  },
}));

const HISTORY_SESSION_ID = "history-session";
const NEW_SESSION_ID = "1787000000000-abcdefg";

function NavigationHarness() {
  const navigate = useNavigate();
  const location = useLocation();

  return (
    <>
      <span data-testid="pathname">{location.pathname}</span>
      <button onClick={() => navigate("/chat")}>New chat</button>
      <button onClick={() => navigate(`/chat/${HISTORY_SESSION_ID}`)}>
        History session
      </button>
      <ChatSessionInitializer />
    </>
  );
}

describe("ChatSessionInitializer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSessionState.sessions = [{ id: HISTORY_SESSION_ID }];
    mockSessionState.currentSessionId = HISTORY_SESSION_ID;
    useAgentStore.setState({
      selectedAgent: "default",
      lastChatIdByAgent: {},
      pendingAgentChatSwitch: null,
    });
    sessionApi.lastActiveChatId = null;
    sessionApi.lastNavigatedChatId = null;
    sessionApi.onSessionNotFound = null;
    sessionApi.preferredChatId = null;
    useSessionListStore.setState({
      sessions: [],
      lastUpdated: 0,
      _setLibrarySessions: null,
    });
  });

  it("reopens the only history session after starting a blank chat", async () => {
    const user = userEvent.setup();
    renderWithProviders(<NavigationHarness />, {
      initialEntries: [`/chat/${HISTORY_SESSION_ID}`],
    });

    mockSessionState.sessions = [
      { id: NEW_SESSION_ID },
      { id: HISTORY_SESSION_ID },
    ];
    mockSessionState.currentSessionId = NEW_SESSION_ID;
    await user.click(screen.getByRole("button", { name: "New chat" }));
    await user.click(screen.getByRole("button", { name: "History session" }));

    await waitFor(() => {
      expect(mockSetCurrentSessionId).toHaveBeenCalledWith(HISTORY_SESSION_ID);
    });
  });

  it("validates a URL chat once when it is absent from the agent list", async () => {
    mockSessionState.sessions = [];
    vi.mocked(sessionApi.preloadSession).mockResolvedValue({
      session: { id: "missing-chat" } as never,
      realId: null,
    });

    renderWithProviders(<NavigationHarness />, {
      initialEntries: ["/chat/missing-chat"],
    });

    await waitFor(() => {
      expect(sessionApi.preloadSession).toHaveBeenCalledTimes(1);
    });
    expect(sessionApi.preloadSession).toHaveBeenCalledWith(
      "missing-chat",
      expect.any(AbortSignal),
    );
  });

  it("clears stale chat state and returns to /chat after URL validation gets 404", async () => {
    mockSessionState.sessions = [];
    useAgentStore.setState({
      lastChatIdByAgent: { default: "missing-chat" },
      pendingAgentChatSwitch: {
        agentId: "default",
        chatId: "missing-chat",
      },
    });
    vi.mocked(sessionApi.preloadSession).mockImplementation(async (chatId) => {
      sessionApi.onSessionNotFound?.(chatId, "default");
      return {
        session: { id: chatId } as never,
        realId: null,
      };
    });

    renderWithProviders(<NavigationHarness />, {
      initialEntries: ["/chat/missing-chat"],
    });

    await waitFor(() => {
      expect(screen.getByTestId("pathname")).toHaveTextContent("/chat");
    });
    expect(mockSetCurrentSessionId).toHaveBeenCalledWith(undefined);
    expect(useAgentStore.getState().getLastChatId("default")).toBeUndefined();
    expect(useAgentStore.getState().pendingAgentChatSwitch).toBeNull();
    expect(sessionApi.preferredChatId).toBeNull();
    expect(sessionApi.lastActiveChatId).toBeNull();
    expect(sessionApi.resetWindowIdentity).toHaveBeenCalledOnce();
  });

  it("ignores a late not-found callback owned by a previous agent", async () => {
    mockSessionState.sessions = [];
    vi.mocked(sessionApi.preloadSession).mockResolvedValue({
      session: { id: "current-chat" } as never,
      realId: null,
    });

    renderWithProviders(<NavigationHarness />, {
      initialEntries: ["/chat/current-chat"],
    });

    await waitFor(() =>
      expect(sessionApi.onSessionNotFound).toBeTypeOf("function"),
    );
    sessionApi.onSessionNotFound?.("current-chat", "previous-agent");

    expect(screen.getByTestId("pathname")).toHaveTextContent(
      "/chat/current-chat",
    );
    expect(mockSetCurrentSessionId).not.toHaveBeenCalledWith(undefined);
  });
});
