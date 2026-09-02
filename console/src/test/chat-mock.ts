/**
 * Global stub for @agentscope-ai/chat in tests.
 * The real package is 2.3MB and causes OOM when loaded in vitest workers.
 * Individual tests that need specific behavior override this with vi.mock(..., factory).
 */
import { vi } from "vitest";
import React from "react";

export const AgentScopeRuntimeMessageType = {
  MESSAGE: "message",
  REASONING: "reasoning",
  PLUGIN_CALL: "plugin_call",
  PLUGIN_CALL_OUTPUT: "plugin_call_output",
  TOOL_CALL: "tool_call",
  TOOL_CALL_OUTPUT: "tool_call_output",
  FUNCTION_CALL: "function_call",
  FUNCTION_CALL_OUTPUT: "function_call_output",
  COMPONENT_CALL: "component_call",
  COMPONENT_CALL_OUTPUT: "component_call_output",
  MCP_LIST_TOOLS: "mcp_list_tools",
  MCP_APPROVAL_REQUEST: "mcp_approval_request",
  MCP_APPROVAL_RESPONSE: "mcp_approval_response",
  MCP_CALL: "mcp_call",
  MCP_CALL_OUTPUT: "mcp_call_output",
  HEARTBEAT: "heartbeat",
  ERROR: "error",
} as const;
export const AgentScopeRuntimeContentType = {
  TEXT: "text",
  DATA: "data",
  IMAGE: "image",
  AUDIO: "audio",
  VIDEO: "video",
  FILE: "file",
  REFUSAL: "refusal",
} as const;
export const AgentScopeRuntimeRunStatus = {
  Created: "created",
  InProgress: "in_progress",
  Completed: "completed",
  Canceled: "canceled",
  Failed: "failed",
  Rejected: "rejected",
  Unknown: "unknown",
} as const;

const EmptyCard = () => null;
export const DefaultCards = {
  Audios: EmptyCard,
  Files: EmptyCard,
  Images: EmptyCard,
  Videos: EmptyCard,
};
export const Markdown = EmptyCard;
export const Bubble = Object.assign(EmptyCard, { Spin: EmptyCard });

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
