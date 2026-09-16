import { useMemo, useSyncExternalStore } from "react";
import { useAuthStore } from "@/stores/authStore";
import { useAgentStore } from "@/stores/agentStore";
import {
  getAccessSessionGeneration,
  subscribeAccessSessionGeneration,
} from "./authSession";

let epoch = 0;
let initialized = false;
let controller = new AbortController();
const listeners = new Set<() => void>();
function advance() {
  epoch++;
  controller.abort();
  controller = new AbortController();
  listeners.forEach((listener) => listener());
}
function initialize() {
  if (initialized) return;
  initialized = true;
  useAuthStore.subscribe((next, previous) => {
    if (
      next.mode !== previous.mode ||
      next.phase !== previous.phase ||
      next.user?.id !== previous.user?.id ||
      next.user?.platform_role !== previous.user?.platform_role
    )
      advance();
  });
  useAgentStore.subscribe((next, previous) => {
    const permissions = (state: typeof next) =>
      state.agents.map((a) => [
        a.id,
        a.enabled,
        a.access_role,
        a.historical_read_only,
      ]);
    if (
      next.selectedAgent !== previous.selectedAgent ||
      JSON.stringify(permissions(next)) !==
        JSON.stringify(permissions(previous))
    )
      advance();
  });
  subscribeAccessSessionGeneration(advance);
}
export function captureVoiceScope() {
  initialize();
  const auth = useAuthStore.getState();
  const agents = useAgentStore.getState();
  const agentId = agents.selectedAgent;
  const agent = agents.agents.find((a) => a.id === agentId);
  const version = epoch;
  const generation = getAccessSessionGeneration();
  const signal = controller.signal;
  const ready =
    auth.phase === "authenticated" ||
    (auth.mode === "legacy" && auth.phase === "disabled");
  const current = () =>
    version === epoch &&
    generation === getAccessSessionGeneration() &&
    !signal.aborted;
  return {
    key: `${version}:${generation}`,
    agentId,
    actor: auth.user?.id ?? null,
    generation,
    signal,
    canManage:
      ready && (auth.mode === "legacy" || auth.user?.platform_role === "admin"),
    canUse:
      ready &&
      !!agentId &&
      !!agent &&
      agent.enabled !== false &&
      !agent.historical_read_only &&
      (auth.mode === "legacy" ||
        ["owner", "collaborator", "user"].includes(agent.access_role ?? "")),
    current,
    assert: () => {
      if (!current())
        throw new DOMException("Voice context changed", "AbortError");
    },
  };
}
export type VoiceScope = ReturnType<typeof captureVoiceScope>;
function subscribe(listener: () => void) {
  initialize();
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
export function useVoiceScope() {
  const version = useSyncExternalStore(subscribe, () => epoch);
  return useMemo(captureVoiceScope, [version]);
}
