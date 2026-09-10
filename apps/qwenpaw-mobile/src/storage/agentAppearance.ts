import AsyncStorage from "@react-native-async-storage/async-storage";

import type { AgentSummary, Connection } from "../api/types";

export interface AgentAppearance {
  nickname?: string;
  avatarUri?: string;
}

export type AgentAppearanceMap = Record<string, AgentAppearance>;

const AGENT_APPEARANCE_KEY = "qwenpaw.mobile.agent-appearance.v1";

export async function loadAgentAppearances(): Promise<AgentAppearanceMap> {
  const stored = await AsyncStorage.getItem(AGENT_APPEARANCE_KEY);
  if (!stored) return {};
  try {
    const parsed = JSON.parse(stored) as unknown;
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? parsed as AgentAppearanceMap
      : {};
  } catch {
    await AsyncStorage.removeItem(AGENT_APPEARANCE_KEY);
    return {};
  }
}

export async function saveAgentAppearance(
  current: AgentAppearanceMap,
  connection: Connection,
  agentId: string,
  appearance: AgentAppearance,
): Promise<AgentAppearanceMap> {
  const key = agentAppearanceKey(connection.baseUrl, agentId);
  const nickname = appearance.nickname?.trim();
  const avatarUri = appearance.avatarUri?.trim();
  const next = { ...current };
  if (!nickname && !avatarUri) delete next[key];
  else next[key] = { nickname, avatarUri };
  await AsyncStorage.setItem(AGENT_APPEARANCE_KEY, JSON.stringify(next));
  return next;
}

export function resolveAgentAppearance(
  appearances: AgentAppearanceMap,
  connection: Connection | null,
  agent: Pick<AgentSummary, "id" | "name"> | undefined,
): { name: string; avatarUri?: string } {
  if (!connection || !agent) return { name: agent?.name || "QwenPaw" };
  const appearance = appearances[
    agentAppearanceKey(connection.baseUrl, agent.id)
  ];
  return {
    name: appearance?.nickname?.trim() || agent.name || "QwenPaw",
    avatarUri: appearance?.avatarUri || undefined,
  };
}

export function agentAppearanceKey(baseUrl: string, agentId: string): string {
  return `${baseUrl.replace(/\/$/, "")}::${agentId}`;
}
