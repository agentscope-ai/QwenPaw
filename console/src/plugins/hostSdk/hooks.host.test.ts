// @vitest-environment jsdom
/**
 * Contract tests for the host hooks exposed to plugins.
 *
 * Division of labour with the existing hooks.test.ts (left byte-for-byte
 * untouched): that file covers the three PawApp-scoping paths of
 * getCurrentSessionId. This file covers the five remaining exports
 * (useHostTheme / useHostLocale / useHostSelectedAgent /
 * useHostCurrentSession / getSelectedAgentId) plus the fallback arms of
 * getCurrentSessionId that the existing file never reaches.
 *
 * One arm stays uncovered on purpose: the `typeof window === "undefined"`
 * guard at the top of getCurrentSessionId cannot be taken under jsdom, so no
 * test here pretends otherwise.
 */
import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const themeMock = vi.hoisted(() => ({ isDark: false }));
const localeMock = vi.hoisted(() => ({ language: "en-US" }));
const agentMock = vi.hoisted(() => ({ selectedAgent: null as string | null }));
const chatMock = vi.hoisted(() => ({
  state: null as { currentSessionId?: string | null } | null,
}));
const sessionApiMock = vi.hoisted(() => ({
  lastActiveChatId: null as string | null,
  getSessionIdentity: vi.fn((id: string) => ({ sessionId: id })),
}));

vi.mock("../../contexts/ThemeContext", () => ({
  useTheme: () => themeMock,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ i18n: localeMock, t: (key: string) => key }),
}));

vi.mock("../../stores/agentStore", () => {
  const useAgentStore = ((selector: (s: typeof agentMock) => unknown) =>
    selector(agentMock)) as unknown as {
    (selector: (s: typeof agentMock) => unknown): unknown;
    getState: () => typeof agentMock;
  };
  useAgentStore.getState = () => agentMock;
  return { useAgentStore };
});

vi.mock("@agentscope-ai/chat", () => ({
  useChatAnywhereSessionsState: () => chatMock.state,
}));

vi.mock("../../pages/Chat/sessionApi", () => ({ default: sessionApiMock }));

import {
  getCurrentSessionId,
  getSelectedAgentId,
  useHostCurrentSession,
  useHostLocale,
  useHostSelectedAgent,
  useHostTheme,
} from "./hooks";

describe("hostSdk/hooks", () => {
  beforeEach(() => {
    themeMock.isDark = false;
    localeMock.language = "en-US";
    agentMock.selectedAgent = null;
    chatMock.state = null;
    sessionApiMock.lastActiveChatId = null;
    sessionApiMock.getSessionIdentity.mockImplementation((id: string) => ({
      sessionId: id,
    }));
  });

  describe("useHostTheme", () => {
    it('reports "dark" while the host theme is dark', () => {
      themeMock.isDark = true;

      expect(renderHook(() => useHostTheme()).result.current).toBe("dark");
    });

    it('reports "light" while the host theme is light', () => {
      themeMock.isDark = false;

      expect(renderHook(() => useHostTheme()).result.current).toBe("light");
    });
  });

  describe("useHostLocale", () => {
    it("reports the language the host i18n instance is on", () => {
      localeMock.language = "zh-CN";

      expect(renderHook(() => useHostLocale()).result.current).toBe("zh-CN");
    });
  });

  describe("useHostSelectedAgent", () => {
    it("reports the agent selected in the host", () => {
      agentMock.selectedAgent = "agent-a";

      expect(renderHook(() => useHostSelectedAgent()).result.current).toEqual({
        id: "agent-a",
      });
    });

    it('reports "default" while no agent is selected', () => {
      agentMock.selectedAgent = null;

      expect(renderHook(() => useHostSelectedAgent()).result.current).toEqual({
        id: "default",
      });
    });
  });

  describe("useHostCurrentSession", () => {
    it("reports the dialogue the host chat is on", () => {
      chatMock.state = { currentSessionId: "session-1" };

      expect(renderHook(() => useHostCurrentSession()).result.current).toEqual({
        id: "session-1",
      });
    });

    it("reports null while the host chat has no state", () => {
      chatMock.state = null;

      expect(
        renderHook(() => useHostCurrentSession()).result.current,
      ).toBeNull();
    });

    it("reports null while the current dialogue id is empty", () => {
      chatMock.state = { currentSessionId: "" };

      expect(
        renderHook(() => useHostCurrentSession()).result.current,
      ).toBeNull();
    });
  });

  describe("getSelectedAgentId", () => {
    it("reads the selected agent without a React tree", () => {
      agentMock.selectedAgent = "agent-b";

      expect(getSelectedAgentId()).toBe("agent-b");
    });

    it('reads "default" while no agent is selected', () => {
      agentMock.selectedAgent = null;

      expect(getSelectedAgentId()).toBe("default");
    });
  });

  describe("getCurrentSessionId fallback arms", () => {
    it("returns null on a chat route whose dialogue has no backend identity", () => {
      window.history.replaceState({}, "", "/chat/temp-1");
      sessionApiMock.getSessionIdentity.mockReturnValue({ sessionId: "" });

      expect(getCurrentSessionId()).toBeNull();
    });

    it("returns null on a route that is neither a chat nor a PawApp", () => {
      window.history.replaceState({}, "", "/settings/models");

      expect(getCurrentSessionId()).toBeNull();
    });

    it("returns null on a PawApp route with no remembered dialogue", () => {
      window.history.replaceState({}, "", "/apps/office");
      sessionApiMock.lastActiveChatId = null;

      expect(getCurrentSessionId()).toBeNull();
    });

    it("returns null when the remembered dialogue lost its backend identity", () => {
      window.history.replaceState({}, "", "/apps/office");
      sessionApiMock.lastActiveChatId = "chat-9";
      sessionApiMock.getSessionIdentity.mockReturnValue({ sessionId: "" });

      expect(getCurrentSessionId()).toBeNull();
    });

    it("returns the id when it is exactly the app namespace", () => {
      window.history.replaceState({}, "", "/apps/office");
      sessionApiMock.lastActiveChatId = "chat-9";
      sessionApiMock.getSessionIdentity.mockReturnValue({
        sessionId: "pawapp:office",
      });

      expect(getCurrentSessionId()).toBe("pawapp:office");
    });
  });
});
