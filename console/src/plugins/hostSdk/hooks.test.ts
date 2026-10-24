import { beforeEach, describe, expect, it, vi } from "vitest";

const sessionApiMock = vi.hoisted(() => ({
  lastActiveChatId: null as string | null,
  getSessionIdentity: vi.fn((id: string) => ({ sessionId: id })),
}));

vi.mock("../../pages/Chat/sessionApi", () => ({ default: sessionApiMock }));

import { getCurrentSessionId } from "./hooks";

describe("getCurrentSessionId", () => {
  beforeEach(() => {
    sessionApiMock.lastActiveChatId = null;
    sessionApiMock.getSessionIdentity.mockImplementation((id: string) => ({
      sessionId: id,
    }));
  });

  it("resolves the backend identity from a chat route", () => {
    window.history.replaceState({}, "", "/chat/chat-1");
    sessionApiMock.getSessionIdentity.mockReturnValue({
      sessionId: "backend-1",
    });

    expect(getCurrentSessionId()).toBe("backend-1");
  });

  it("preserves the last dialogue owned by the current PawApp", () => {
    window.history.replaceState({}, "", "/apps/office");
    sessionApiMock.lastActiveChatId = "chat-1";
    sessionApiMock.getSessionIdentity.mockReturnValue({
      sessionId: "pawapp:office:dialogue:1",
    });

    expect(getCurrentSessionId()).toBe("pawapp:office:dialogue:1");
  });

  it("does not expose another app or host session to a PawApp", () => {
    window.history.replaceState({}, "", "/apps/office");
    sessionApiMock.lastActiveChatId = "chat-1";
    sessionApiMock.getSessionIdentity.mockReturnValue({
      sessionId: "ordinary-host-session",
    });

    expect(getCurrentSessionId()).toBeNull();
  });
});
