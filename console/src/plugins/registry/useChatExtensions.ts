/**
 * registry/useChatExtensions.ts — React subscriptions for the chat extension registry.
 *
 * Wraps `useSyncExternalStore` so ChatPage re-renders whenever a plugin
 * registers/disposes. Snapshots are stable refs between mutations
 * (the registry replaces them only on change), so the useMemo
 * dep chain in ChatPage doesn't fire spuriously.
 */
import { useSyncExternalStore } from "react";
import {
  chatExtensions,
  type ChatListSnapshot,
  type ChatScalarSnapshot,
} from "./chatExtensions";

function subscribe(cb: () => void): () => void {
  return chatExtensions.subscribe(cb);
}

export function useChatScalarSnapshot(): ChatScalarSnapshot {
  return useSyncExternalStore(subscribe, () =>
    chatExtensions.getScalarSnapshot(),
  );
}

export function useChatListSnapshot(): ChatListSnapshot {
  return useSyncExternalStore(subscribe, () =>
    chatExtensions.getListSnapshot(),
  );
}
