import { useMemo, useSyncExternalStore } from "react";
import { useAuthStore } from "@/stores/authStore";
import { useAgentStore } from "@/stores/agentStore";
import {
  getAccessSessionGeneration,
  subscribeAccessSessionGeneration,
} from "./authSession";
import { request, type RequestOptions } from "./request";

let epoch = 0;
let initialized = false;
let controller = new AbortController();
const listeners = new Set<() => void>();

function advance() {
  epoch += 1;
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
      next.user?.platform_role !== previous.user?.platform_role ||
      next.accessToken !== previous.accessToken
    )
      advance();
  });
  useAgentStore.subscribe((next, previous) => {
    const permissions = (state: typeof next) =>
      state.agents.map((a) => [a.id, a.enabled, a.access_role, a.can_edit]);
    if (
      next.selectedAgent !== previous.selectedAgent ||
      JSON.stringify(permissions(next)) !==
        JSON.stringify(permissions(previous))
    )
      advance();
  });
  subscribeAccessSessionGeneration(advance);
}

export interface SkillScope {
  key: string;
  agentId: string;
  ready: boolean;
  multiUser: boolean;
  canEdit: boolean;
  canSubmit: boolean;
  isAdmin: boolean;
  signal: AbortSignal;
  current: () => boolean;
  assert: () => void;
}

export function captureSkillScope(agentId?: string): SkillScope {
  initialize();
  const auth = useAuthStore.getState();
  const agents = useAgentStore.getState();
  const id = agentId ?? agents.selectedAgent;
  const agent = agents.agents.find((a) => a.id === id);
  const version = epoch;
  const session = getAccessSessionGeneration();
  const signal = controller.signal;
  const multiUser = auth.mode === "multi_user";
  const ready = multiUser
    ? auth.phase === "authenticated" && !!auth.user
    : auth.phase === "authenticated" || auth.phase === "disabled";
  const canEdit =
    ready &&
    !!agent &&
    agent.enabled !== false &&
    agent.can_edit !== false &&
    (multiUser
      ? agent.can_edit === true &&
        (agent.access_role === "owner" || agent.access_role === "collaborator")
      : true);
  const current = () =>
    version === epoch &&
    session === getAccessSessionGeneration() &&
    !signal.aborted;
  return {
    key: `${version}:${session}:${id}`,
    agentId: id,
    ready,
    multiUser,
    canEdit,
    canSubmit: canEdit && multiUser && agent?.access_role === "owner",
    isAdmin: ready && (multiUser ? auth.user?.platform_role === "admin" : true),
    signal,
    current,
    assert: () => {
      if (!current())
        throw new DOMException("Skill context changed", "AbortError");
    },
  };
}

function subscribe(listener: () => void) {
  initialize();
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
export function useSkillScope(agentId?: string) {
  const version = useSyncExternalStore(subscribe, () => epoch);
  return useMemo(() => captureSkillScope(agentId), [version, agentId]);
}

export function skillRequestOptions(
  scope: SkillScope,
  options: RequestOptions = {},
): RequestOptions {
  scope.assert();
  const headers = new Headers(options.headers);
  if (scope.agentId) headers.set("X-Agent-Id", scope.agentId);
  return {
    ...options,
    headers,
    signal: options.signal
      ? AbortSignal.any([scope.signal, options.signal])
      : scope.signal,
  };
}

export async function scopedSkillRequest<T>(
  scope: SkillScope,
  path: string,
  options?: RequestOptions,
): Promise<T> {
  const result = await request<T>(path, skillRequestOptions(scope, options));
  scope.assert();
  return result;
}
