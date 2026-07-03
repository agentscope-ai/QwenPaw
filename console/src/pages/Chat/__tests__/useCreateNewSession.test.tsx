import { fireEvent, screen, waitFor } from "@testing-library/react";
import { useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/common_setup";
import sessionApi from "../sessionApi";
import { useCreateNewSession } from "../hooks/useCreateNewSession";

const { mockCreateSession } = vi.hoisted(() => ({
  mockCreateSession: vi.fn(),
}));

vi.mock("@agentscope-ai/chat", () => ({
  useChatAnywhereSessions: () => ({ createSession: mockCreateSession }),
}));

function Probe() {
  const createNewSession = useCreateNewSession();
  const location = useLocation();
  return (
    <>
      <button onClick={() => void createNewSession()}>new</button>
      <div data-testid="location">{location.pathname}</div>
    </>
  );
}

describe("useCreateNewSession", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCreateSession.mockResolvedValue(undefined);
    sessionApi.setActiveAgent(`test-agent-${Date.now()}`);
    sessionApi.lastActiveChatId = null;
    (window as any).currentSessionId = undefined;
    (window as any).currentUserId = undefined;
    (window as any).currentChannel = undefined;
  });

  it("prepares a local session identity before delegating to the SDK", async () => {
    renderWithProviders(<Probe />, { initialEntries: ["/chat/history-1"] });

    fireEvent.click(screen.getByRole("button", { name: "new" }));

    await waitFor(() => expect(mockCreateSession).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent("/chat"),
    );
    expect(sessionApi.lastActiveChatId).toMatch(/^\d+(?:-[a-z0-9]+)?$/);
    expect((window as any).currentSessionId).toBe(sessionApi.lastActiveChatId);
  });
});
