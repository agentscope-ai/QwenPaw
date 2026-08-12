import type { ModelSlotConfig } from "../../api/types";

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
