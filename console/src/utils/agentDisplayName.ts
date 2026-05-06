import type { TFunction } from "i18next";
import type { AgentSummary } from "../api/types/agents";

export const DEFAULT_AGENT_ID = "default";

/** UI label for an agent; `default` id uses i18n, others use API `name` (fallback: id). */
export function getAgentDisplayName(
  agent: Pick<AgentSummary, "id" | "name">,
  t: TFunction,
): string {
  // Prioritize user-defined name
  if (agent.name) {
    return agent.name;
  }
  // Fallback to localized default name if ID is default
  if (agent.id === DEFAULT_AGENT_ID) {
    return t("agent.defaultDisplayName");
  }
  // Finally fallback to ID
  return agent.id;
}
