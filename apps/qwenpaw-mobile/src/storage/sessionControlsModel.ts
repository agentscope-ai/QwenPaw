import type {
  ApprovalLevel,
  ChatSpec,
  Connection,
  ModelSlotOverride,
} from "../api/types";
import { connectionKey } from "./connectionModel";

const PREFIX = "qwenpaw.mobile.session-controls.v1";

export function sessionControlsKey(
  connection: Connection,
  chat: Pick<ChatSpec, "id" | "session_id">,
): string {
  return [
    PREFIX,
    encodeURIComponent(connectionKey(connection)),
    encodeURIComponent(connection.agentId),
    encodeURIComponent(chat.session_id || chat.id),
  ].join(":");
}

export function normalizeApprovalLevel(value: unknown): ApprovalLevel {
  const normalized = typeof value === "string"
    ? value.toLocaleUpperCase()
    : value;
  return isApprovalLevel(normalized) ? normalized : "AUTO";
}

export function isApprovalLevel(value: unknown): value is ApprovalLevel {
  return value === "STRICT" || value === "SMART" ||
    value === "AUTO" || value === "OFF";
}

export function normalizeModelOverride(
  value: unknown,
): ModelSlotOverride | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const candidate = value as Record<string, unknown>;
  const providerId = typeof candidate.provider_id === "string"
    ? candidate.provider_id.trim()
    : "";
  const model = typeof candidate.model === "string"
    ? candidate.model.trim()
    : "";
  return providerId && model ? { provider_id: providerId, model } : null;
}
