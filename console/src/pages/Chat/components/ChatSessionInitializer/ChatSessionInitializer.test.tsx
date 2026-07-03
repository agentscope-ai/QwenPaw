import { afterEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { useLocation } from "react-router-dom";
import { renderWithProviders } from "@/test/common_setup";
import { useChatAnywhereSessionsState } from "@agentscope-ai/chat";
import sessionApi from "../../sessionApi";
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

function mockSessions(sessions: any[]) {
  vi.mocked(useChatAnywhereSessionsState).mockReturnValue({
    sessions,
    currentSessionId: undefined,
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

  it("does not auto-open history when a blank local session is first", async () => {
    mockSessions([
      { id: "1783058507358-onjn1fo", name: "New Chat" },
      { id: "backend-1", name: "Latest History" },
    ]);

    renderInitializer();

    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent("/chat"),
    );
    expect(mockSetCurrentSessionId).not.toHaveBeenCalled();
  });

  it("auto-opens the latest routable history on a normal base chat route", async () => {
    mockSessions([{ id: "backend-1", name: "Latest History" }]);

    renderInitializer();

    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent(
        "/chat/backend-1",
      ),
    );
    expect(mockSetCurrentSessionId).toHaveBeenCalledWith("backend-1");
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
});
