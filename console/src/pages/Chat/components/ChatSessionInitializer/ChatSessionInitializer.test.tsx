import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useNavigate } from "react-router-dom";
import { renderWithProviders } from "@/test/common_setup";
import { useSessionListStore } from "@/stores/sessionListStore";
import ChatSessionInitializer from "./index";

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
    lastNavigatedChatId: null,
    preferredChatId: null,
    preloadSession: vi.fn(),
    trackNavigatedSession: vi.fn(),
  },
}));

const HISTORY_SESSION_ID = "history-session";
const NEW_SESSION_ID = "1787000000000-abcdefg";

function NavigationHarness() {
  const navigate = useNavigate();

  return (
    <>
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
});
