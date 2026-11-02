import type { AgentStartupStatus } from "@/api/types/agents";

export function resolveAgentStatus(
  status?: AgentStartupStatus,
  enabled = true,
): AgentStartupStatus {
  if (!enabled) return "disabled";
  return status ?? "pending";
}
