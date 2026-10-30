import { useSyncExternalStore } from "react";
import { harnessRegistry } from "../plugins/harnesses";
import type { AgentBackend, AgentSummary } from "../api/types/agents";
import type { HarnessCapabilities } from "../api/modules/harness";

export function requiresQwenPawModel(backend: AgentBackend): boolean {
  return backend === "qwenpaw";
}

export function supportsPortabilityImport(agent?: AgentSummary): boolean {
  return (
    agent?.backend === "qwenpaw" &&
    agent.backend_capabilities?.workspace_ui !== false
  );
}

export function supportsAgentAttachments(
  backend: AgentBackend,
  capabilities?: Partial<HarnessCapabilities>,
): boolean {
  return requiresQwenPawModel(backend) || Boolean(capabilities?.attachments);
}

/** Read current declarations so plugin lifecycle changes update every control. */
export function useBackendCapabilities(
  agent?: AgentSummary,
): Partial<HarnessCapabilities> | undefined {
  const catalog = useSyncExternalStore(
    harnessRegistry.subscribe,
    harnessRegistry.getSnapshot,
    harnessRegistry.getSnapshot,
  );
  if (!agent || agent.backend === "qwenpaw") return agent?.backend_capabilities;
  const descriptor = catalog.find((row) => row.id === agent.backend);
  return descriptor?.status === "available"
    ? (descriptor.capabilities as Partial<HarnessCapabilities>)
    : undefined;
}
