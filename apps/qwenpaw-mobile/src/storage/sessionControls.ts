import AsyncStorage from "@react-native-async-storage/async-storage";

import type {
  ApprovalLevel,
  ChatSpec,
  Connection,
  ModelSlotOverride,
} from "../api/types";
import {
  isApprovalLevel,
  normalizeModelOverride,
  sessionControlsKey,
} from "./sessionControlsModel";

export { normalizeApprovalLevel, sessionControlsKey } from "./sessionControlsModel";

export interface SessionControlsPreference {
  approvalLevel: ApprovalLevel | null;
  modelOverride: ModelSlotOverride | null;
}

export async function loadSessionControls(
  connection: Connection,
  chat: Pick<ChatSpec, "id" | "session_id">,
): Promise<SessionControlsPreference> {
  const value = await AsyncStorage.getItem(sessionControlsKey(connection, chat));
  if (!value) return { approvalLevel: null, modelOverride: null };
  try {
    const parsed = JSON.parse(value) as {
      approvalLevel?: unknown;
      modelOverride?: unknown;
    };
    return {
      approvalLevel: isApprovalLevel(parsed.approvalLevel)
        ? parsed.approvalLevel
        : null,
      modelOverride: normalizeModelOverride(parsed.modelOverride),
    };
  } catch {
    return { approvalLevel: null, modelOverride: null };
  }
}

export async function saveSessionApprovalLevel(
  connection: Connection,
  chat: Pick<ChatSpec, "id" | "session_id">,
  approvalLevel: ApprovalLevel | null,
): Promise<void> {
  const current = await loadSessionControls(connection, chat);
  await AsyncStorage.setItem(
    sessionControlsKey(connection, chat),
    JSON.stringify({ ...current, approvalLevel }),
  );
}

export async function saveSessionModelOverride(
  connection: Connection,
  chat: Pick<ChatSpec, "id" | "session_id">,
  modelOverride: ModelSlotOverride | null,
): Promise<void> {
  const current = await loadSessionControls(connection, chat);
  await AsyncStorage.setItem(
    sessionControlsKey(connection, chat),
    JSON.stringify({ ...current, modelOverride }),
  );
}
