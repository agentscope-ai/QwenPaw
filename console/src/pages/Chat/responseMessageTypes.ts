import { AgentScopeRuntimeMessageType } from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/types";

const TOOL_LIKE_RESPONSE_TYPES = new Set<AgentScopeRuntimeMessageType>([
  AgentScopeRuntimeMessageType.PLUGIN_CALL,
  AgentScopeRuntimeMessageType.PLUGIN_CALL_OUTPUT,
  AgentScopeRuntimeMessageType.TOOL_CALL,
  AgentScopeRuntimeMessageType.TOOL_CALL_OUTPUT,
  AgentScopeRuntimeMessageType.FUNCTION_CALL,
  AgentScopeRuntimeMessageType.FUNCTION_CALL_OUTPUT,
  AgentScopeRuntimeMessageType.COMPONENT_CALL,
  AgentScopeRuntimeMessageType.COMPONENT_CALL_OUTPUT,
  AgentScopeRuntimeMessageType.MCP_CALL,
  AgentScopeRuntimeMessageType.MCP_CALL_OUTPUT,
]);

export function isToolLikeResponseMessageType(
  type: AgentScopeRuntimeMessageType,
): boolean {
  return TOOL_LIKE_RESPONSE_TYPES.has(type);
}
