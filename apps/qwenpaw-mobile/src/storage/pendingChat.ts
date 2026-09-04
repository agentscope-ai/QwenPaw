import AsyncStorage from "@react-native-async-storage/async-storage";

import type {
  Connection,
  DisplayMessage,
} from "../api/types";
import { connectionKey } from "./connectionModel";

const PENDING_CHAT_PREFIX = "qwenpaw.mobile.pending-chat.v1";

export interface PendingChatTurn {
  responseId: string;
  submittedText?: string;
  userMessage: DisplayMessage;
}

export async function loadPendingChatTurn(
  connection: Connection,
  chatId: string,
): Promise<PendingChatTurn | null> {
  const key = pendingChatKey(connection, chatId);
  const stored = await AsyncStorage.getItem(key);
  if (!stored) return null;
  try {
    const pending = JSON.parse(stored) as PendingChatTurn;
    if (
      typeof pending.responseId !== "string" ||
      pending.userMessage?.role !== "user" ||
      !Array.isArray(pending.userMessage.parts)
    ) {
      throw new Error("Invalid pending chat turn");
    }
    return pending;
  } catch {
    await AsyncStorage.removeItem(key);
    return null;
  }
}

export async function savePendingChatTurn(
  connection: Connection,
  chatId: string,
  pending: PendingChatTurn,
): Promise<void> {
  await AsyncStorage.setItem(
    pendingChatKey(connection, chatId),
    JSON.stringify(pending),
  );
}

export async function clearPendingChatTurn(
  connection: Connection,
  chatId: string,
): Promise<void> {
  await AsyncStorage.removeItem(pendingChatKey(connection, chatId));
}

export function pendingUserMessagePersisted(
  messages: DisplayMessage[],
  pending: PendingChatTurn,
): boolean {
  const lastUser = [...messages].reverse().find(
    (message) => message.role === "user",
  );
  if (!lastUser) return false;
  if (messageSignature(lastUser) === messageSignature(pending.userMessage)) {
    return true;
  }
  return Boolean(
    pending.submittedText && messageText(lastUser) === pending.submittedText,
  );
}

export function mergePendingChatTurn(
  messages: DisplayMessage[],
  pending: PendingChatTurn,
): DisplayMessage[] {
  const merged = pendingUserMessagePersisted(messages, pending)
    ? [...messages]
    : [...messages, pending.userMessage];
  if (merged.some((message) => message.id === pending.responseId)) {
    return merged;
  }
  return [
    ...merged,
    {
      id: pending.responseId,
      role: "assistant",
      kind: "message",
      parts: [],
      pending: true,
    },
  ];
}

function pendingChatKey(connection: Connection, chatId: string): string {
  return `${PENDING_CHAT_PREFIX}:${encodeURIComponent(
    connectionKey(connection),
  )}:${encodeURIComponent(chatId)}`;
}

function messageSignature(message: DisplayMessage): string {
  return JSON.stringify(message.parts);
}

function messageText(message: DisplayMessage): string {
  return message.parts.flatMap((part) => part.type === "text"
    ? [part.text]
    : []).join("\n");
}
