import type { AgentBackend } from "../api/types/agents";
import type { HarnessCapabilities } from "../api/modules/harness";

export function requiresQwenPawModel(backend: AgentBackend): boolean {
  return backend === "qwenpaw";
}

export function supportsAgentAttachments(
  backend: AgentBackend,
  capabilities?: Partial<HarnessCapabilities>,
): boolean {
  return requiresQwenPawModel(backend) || Boolean(capabilities?.attachments);
}
