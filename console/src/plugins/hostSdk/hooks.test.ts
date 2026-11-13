import { beforeEach, describe, expect, it, vi } from "vitest";
import { createElement, type ComponentProps } from "react";
import { renderHook } from "@testing-library/react";
import { ChatAnywhereSessionsContext } from "@agentscope-ai/chat";

const sessionApiMock = vi.hoisted(() => ({
  lastActiveChatId: null as string | null,
  getSessionIdentity: vi.fn((id: string) => ({ sessionId: id })),
}));

vi.mock("../../pages/Chat/sessionApi", () => ({ default: sessionApiMock }));

import { getCurrentSessionId, useHostCurrentSession } from "./hooks";

it("observes the same SDK session context across session and fork switches", () => {
  let currentSessionId = "parent-chat";
  const { result, rerender } = renderHook(() => useHostCurrentSession(), {
    wrapper: ({ children }) =>
      createElement(ChatAnywhereSessionsContext.Provider, {
        children,
        // This hook only reads currentSessionId from the SDK state.
        value: { currentSessionId } as ComponentProps<
          typeof ChatAnywhereSessionsContext.Provider
        >["value"],
      }),
  });
  expect(result.current).toEqual({ id: "parent-chat" });
  currentSessionId = "fork-chat";
  rerender();
  expect(result.current).toEqual({ id: "fork-chat" });
  currentSessionId = "";
  rerender();
  expect(result.current).toBeNull();
});

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
