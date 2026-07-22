import type { AgentBackend } from "../api/types/agents";

export function requiresQwenPawModel(backend: AgentBackend): boolean {
  return backend === "qwenpaw";
}
