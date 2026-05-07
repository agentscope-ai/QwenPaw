/**
 * Global stub for @agentscope-ai/chat in tests.
 * The real package is 2.3MB and causes OOM when loaded in vitest workers.
 * Individual tests that need specific behavior override this with vi.mock(..., factory).
 */
import { vi } from "vitest";
import React from "react";

export const AgentScopeRuntimeWebUI = vi.fn(() =>
  React.createElement("div", { "data-testid": "chat-ui" }),
);
export const useChatAnywhereInput = vi.fn(() => ({
  setLoading: vi.fn(),
  getLoading: vi.fn(),
}));
export const useChatAnywhereSessions = vi.fn(() => ({
  createSession: vi.fn(),
}));
export const useChatAnywhereSessionsState = vi.fn(() => ({
  sessions: [],
  currentSessionId: null,
  setCurrentSessionId: vi.fn(),
  setSessions: vi.fn(),
}));
export const ChatAnywhereSessionsContext = React.createContext(null);
export const ChatAnywhereInputContext = React.createContext(null);
export default AgentScopeRuntimeWebUI;
