import { afterEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { useLocation } from "react-router-dom";
import { renderWithProviders } from "@/test/common_setup";
import { useChatAnywhereSessionsState } from "@agentscope-ai/chat";
import sessionApi from "../../sessionApi";
import { resolveControlledSdkSessionId } from "../../chatSessionOptions";
import ChatSessionInitializer from "./index";

const { mockSetCurrentSessionId, mockCreateSession } = vi.hoisted(() => ({
  mockSetCurrentSessionId: vi.fn(),
  mockCreateSession: vi.fn(),
}));

vi.mock("@agentscope-ai/chat", () => ({
  useChatAnywhereSessionsState: vi.fn(),
  useChatAnywhereSessions: vi.fn(() => ({ createSession: mockCreateSession })),
}));

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

function renderInitializer(initialEntries = ["/chat"]) {
  return renderWithProviders(
    <>
      <ChatSessionInitializer />
      <LocationProbe />
    </>,
    { initialEntries },
  );
}

function mockSessions(sessions: any[], currentSessionId?: string) {
  vi.mocked(useChatAnywhereSessionsState).mockReturnValue({
    sessions,
    currentSessionId,
    setCurrentSessionId: mockSetCurrentSessionId,
  } as any);
}

describe("ChatSessionInitializer", () => {
  afterEach(() => {
    vi.clearAllMocks();
    sessionApi.isSessionSwitching = false;
    sessionApi.userInitiatedCreate = false;
    sessionApi.suppressBaseAutoSelect = false;
    sessionApi.lastNavigatedChatId = null;
    sessionApi.lastActiveChatId = null;
    sessionApi.preferredChatId = null;
  });

  it("skips an unresolved local session and opens the latest routable history", async () => {
    mockSessions([
      {
        id: "1783058507358-onjn1fo",
        name: "New Chat",
        updatedAt: "2026-07-03T12:00:00Z",
      },
      {
        id: "backend-1",
        name: "Older History",
        updatedAt: "2026-07-03T10:00:00Z",
      },
      {
        id: "backend-2",
        name: "Latest Routable History",
        updatedAt: "2026-07-03T11:00:00Z",
      },
    ]);

    renderInitializer();

    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent(
        "/chat/backend-2",
      ),
    );
    expect(mockSetCurrentSessionId).toHaveBeenCalledWith("backend-2");
  });

  it("auto-opens the latest routable history on a normal base chat route", async () => {
    mockSessions([
      {
        id: "backend-older",
        name: "Older History",
        updatedAt: "2026-07-03T09:00:00Z",
      },
      {
        id: "backend-latest",
        name: "Latest History",
        updatedAt: "2026-07-03T11:00:00Z",
      },
    ]);

    renderInitializer();

    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent(
        "/chat/backend-latest",
      ),
    );
    expect(mockSetCurrentSessionId).toHaveBeenCalledWith("backend-latest");
  });

  it("does not auto-open history while blank-create suppression is active", async () => {
    sessionApi.suppressBaseAutoSelect = true;
    mockSessions([{ id: "backend-1", name: "Latest History" }]);

    renderInitializer();

    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent("/chat"),
    );
    expect(mockSetCurrentSessionId).not.toHaveBeenCalled();
  });

  it("uses the mounted Agent session while the route still belongs to the previous Agent", async () => {
    mockSessions([{ id: "target-agent-chat", name: "Target Agent Chat" }]);

    renderWithProviders(
      <>
        <ChatSessionInitializer resolveChatId={() => "target-agent-chat"} />
        <LocationProbe />
      </>,
      { initialEntries: ["/chat/previous-agent-chat"] },
    );

    await waitFor(() =>
      expect(mockSetCurrentSessionId).toHaveBeenCalledWith("target-agent-chat"),
    );
    expect(mockSetCurrentSessionId).not.toHaveBeenCalledWith(
      "previous-agent-chat",
    );
  });

  it("keeps the local SDK session when its backend route resolves during streaming", async () => {
    const localId = "1783058507358-onjn1fo";
    const backendId = "backend-resolved-id";
    const getLibrarySessionIdSpy = vi
      .spyOn(sessionApi, "getLibrarySessionId")
      .mockImplementation((sessionId) =>
        sessionId === backendId ? localId : sessionId ?? undefined,
      );

    // The SDK session list is deliberately the pre-resolution snapshot. The
    // SessionApi alias map has already resolved the route, but React has not
    // received a new sessions array yet.
    mockSessions(
      [{ id: localId, name: "Streaming Chat", sessionId: localId }],
      localId,
    );

    renderInitializer([`/chat/${backendId}`]);

    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent(
        `/chat/${backendId}`,
      ),
    );
    expect(mockSetCurrentSessionId).not.toHaveBeenCalledWith(backendId);
    expect(mockSetCurrentSessionId).not.toHaveBeenCalled();

    getLibrarySessionIdSpy.mockRestore();
  });

  it("keeps the prepared local session controlled on the blank New Chat route", () => {
    const localId = "1783058507358-onjn1fo";
    sessionApi.lastActiveChatId = localId;
    const getLibrarySessionIdSpy = vi
      .spyOn(sessionApi, "getLibrarySessionId")
      .mockImplementation((sessionId) => sessionId ?? undefined);

    expect(resolveControlledSdkSessionId(undefined)).toBe(localId);

    sessionApi.lastActiveChatId = null;
    expect(resolveControlledSdkSessionId(undefined)).toBeUndefined();

    getLibrarySessionIdSpy.mockRestore();
  });
});
