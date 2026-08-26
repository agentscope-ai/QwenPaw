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

  // -------------------------------------------------------------------------
  // Session restore after page refresh — regression for #5142
  // (in Coding Mode a refresh lost the active session and fell back to the
  // first one; the initializer must re-select the session from the URL)
  // -------------------------------------------------------------------------
  it("restores the session from the URL on mount when context is empty (#5142)", async () => {
    // Fresh app state: sessions arrived from the list but nothing selected.
    mockSessionState.sessions = [{ id: HISTORY_SESSION_ID }];
    mockSessionState.currentSessionId = undefined;

    renderWithProviders(<NavigationHarness />, {
      initialEntries: [`/chat/${HISTORY_SESSION_ID}`],
    });

    await waitFor(() => {
      expect(mockSetCurrentSessionId).toHaveBeenCalledWith(HISTORY_SESSION_ID);
    });
  });

  it("matches by realId when the URL carries the backend UUID (#4987)", async () => {
    // During switching the URL already holds the backend UUID while the
    // library session still has its local id.
    const LOCAL_ID = "1787000000000-local";
    const BACKEND_UUID = "55555555-cccc-4ccc-8ccc-555555555555";
    mockSessionState.sessions = [{ id: LOCAL_ID, realId: BACKEND_UUID }];
    mockSessionState.currentSessionId = undefined;

    renderWithProviders(<NavigationHarness />, {
      initialEntries: [`/chat/${BACKEND_UUID}`],
    });

    await waitFor(() => {
      expect(mockSetCurrentSessionId).toHaveBeenCalledWith(LOCAL_ID);
    });
  });

  it("does not re-select while a session switch is in progress (#4987)", async () => {
    const sessionApi = (await import("../../sessionApi")).default;
    sessionApi.isSessionSwitching = true;
    mockSessionState.sessions = [{ id: HISTORY_SESSION_ID }];
    mockSessionState.currentSessionId = undefined;

    renderWithProviders(<NavigationHarness />, {
      initialEntries: [`/chat/${HISTORY_SESSION_ID}`],
    });

    // Give the effect a chance to run; it must bail out.
    await new Promise((r) => setTimeout(r, 50));
    expect(mockSetCurrentSessionId).not.toHaveBeenCalled();

    sessionApi.isSessionSwitching = false;
  });

  it("skips re-application right after onSessionSelected navigated (#4987)", async () => {
    const sessionApi = (await import("../../sessionApi")).default;
    sessionApi.lastNavigatedChatId = HISTORY_SESSION_ID;
    mockSessionState.sessions = [{ id: HISTORY_SESSION_ID }];
    mockSessionState.currentSessionId = undefined;

    renderWithProviders(<NavigationHarness />, {
      initialEntries: [`/chat/${HISTORY_SESSION_ID}`],
    });

    await new Promise((r) => setTimeout(r, 50));
    // The navigation marker is consumed and no duplicate selection fires.
    expect(sessionApi.lastNavigatedChatId).toBeNull();
    expect(mockSetCurrentSessionId).not.toHaveBeenCalled();
  });

  it("does nothing for an unknown chatId with no matching session", async () => {
    mockSessionState.sessions = [{ id: "some-other" }];
    mockSessionState.currentSessionId = undefined;

    renderWithProviders(<NavigationHarness />, {
      initialEntries: [`/chat/${HISTORY_SESSION_ID}`],
    });

    await new Promise((r) => setTimeout(r, 50));
    expect(mockSetCurrentSessionId).not.toHaveBeenCalled();
  });
});
