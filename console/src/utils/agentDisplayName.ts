import type { TFunction } from "i18next";
import type { AgentSummary } from "../api/types/agents";

export const DEFAULT_AGENT_ID = "default";

/** UI label for an agent; `default` id uses i18n, others use API `name` (fallback: id). */
export function getAgentDisplayName(
  agent: Pick<AgentSummary, "id" | "name">,
  t: TFunction,
): string {
  if (agent.id === DEFAULT_AGENT_ID) {
    return t("agent.defaultDisplayName");
  }
  return agent.name || agent.id;
}
