import type { ModelSlotConfig } from "../../api/types";
import type { ExtendedSession } from "../../stores/sessionListStore";

const KEY_PREFIX = "qwenpaw-session-model-override:";

function storageKey(agentId: string, sessionId: string): string {
  return `${KEY_PREFIX}${agentId}:${sessionId}`;
}

export function getPendingModelOverride(
  agentId: string,
  sessionId: string,
): ModelSlotConfig | null {
  const raw = sessionStorage.getItem(storageKey(agentId, sessionId));
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as Partial<ModelSlotConfig>;
    if (value.provider_id && value.model) {
      return { provider_id: value.provider_id, model: value.model };
    }
  } catch {
    // Invalid pending state is discarded below.
  }
  sessionStorage.removeItem(storageKey(agentId, sessionId));
  return null;
}

export function setPendingModelOverride(
  agentId: string,
  sessionId: string,
  value: ModelSlotConfig | null,
): void {
  const key = storageKey(agentId, sessionId);
  if (value?.provider_id && value.model) {
    sessionStorage.setItem(key, JSON.stringify(value));
  } else {
    sessionStorage.removeItem(key);
  }
  window.dispatchEvent(
    new CustomEvent("session-model-override-changed", {
      detail: { agentId, sessionId, value },
    }),
  );
}

export function migratePendingModelOverride(
  agentId: string,
  fromSessionId: string,
  toSessionId: string,
): void {
  if (fromSessionId === toSessionId) return;
  const value = getPendingModelOverride(agentId, fromSessionId);
  if (!value) return;
  setPendingModelOverride(agentId, toSessionId, value);
  setPendingModelOverride(agentId, fromSessionId, null);
}

export function getPersistedModelOverride(
  sessions: ExtendedSession[],
  ...sessionIds: Array<string | undefined>
): ModelSlotConfig | null {
  const identities = new Set(sessionIds.filter((value) => Boolean(value)));
  if (identities.size === 0) return null;

  const session = sessions.find((item) =>
    [item.id, item.realId, item.sessionId].some((value) =>
      value ? identities.has(value) : false,
    ),
  );
  const runtimeContext = session?.meta?.runtime_context;
  if (!runtimeContext || typeof runtimeContext !== "object") return null;

  const value = (runtimeContext as Record<string, unknown>).model_slot_override;
  if (!value || typeof value !== "object") return null;
  const slot = value as Record<string, unknown>;
  return typeof slot.provider_id === "string" && typeof slot.model === "string"
    ? { provider_id: slot.provider_id, model: slot.model }
    : null;
}

export function modelSlotsEqual(
  left: ModelSlotConfig | null | undefined,
  right: ModelSlotConfig | null | undefined,
): boolean {
  return (
    Boolean(left) &&
    Boolean(right) &&
    left?.provider_id === right?.provider_id &&
    left?.model === right?.model
  );
}

export function withPendingModelOverride(
  requestBody: Record<string, unknown>,
  agentId: string,
  sessionId: string,
  chatId: string | undefined,
): {
  requestBody: Record<string, unknown>;
  modelSlot: ModelSlotConfig | null;
} {
  if (!chatId) return { requestBody, modelSlot: null };
  const modelSlot = getPendingModelOverride(agentId, sessionId);
  if (!modelSlot) return { requestBody, modelSlot: null };
  return {
    requestBody: {
      ...requestBody,
      model_slot_override: modelSlot,
    },
    modelSlot,
  };
}
