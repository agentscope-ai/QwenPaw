/**
 * @qwenpaw/pawapp-sdk — Frontend SDK for PawApps.
 *
 * In same-origin mode (M0-M2), this is a thin convenience wrapper
 * over `window.QwenPaw.*` host capabilities + authenticated fetch.
 *
 * Usage:
 *   import { paw } from '@qwenpaw/pawapp-sdk';
 *
 *   const result = await paw.api.post('/review', { file, style: '严格' });
 *   await paw.chat('分析这段代码');
 *   await paw.storage.set('key', value);
 *   await paw.toast('完成！');
 */
import { apiNamespace, createApiNamespace } from "./api";
import {
  chat,
  chatSessions,
  chatStream,
  createHostNamespace,
  getChatHistory,
  hostNamespace,
  notify,
  storage,
  toast,
} from "./host";
import { createUiNamespace } from "./ui";
import { createDependenciesNamespace } from "./dependencies";
import type { PawSdk, PawSdkFactory } from "./types";
import { getActivePawAppId } from "./context";
import { normalizeAppId } from "./scope";

/**
 * The top-level `paw` SDK object.
 *
 * Combines API communication (paw.api.*) with host capabilities
 * (paw.chat, paw.storage, paw.toast, paw.notify).
 *
 * @deprecated New apps should use `pawSdkFactory.forApp(appId)`.
 */
export const paw: PawSdk = {
  get appId() {
    return getActivePawAppId();
  },
  api: apiNamespace,
  host: hostNamespace,
  ui: createUiNamespace(getActivePawAppId),
  dependencies: createDependenciesNamespace(apiNamespace),

  // Convenience re-exports at top level
  chat,
  chatStream,
  getChatHistory,
  chatSessions,
  storage,
  toast,
  notify,
};

const scopedApps = new Map<string, PawSdk>();

export function forApp(appId: string): PawSdk {
  const normalized = normalizeAppId(appId);
  const cached = scopedApps.get(normalized);
  if (cached) return cached;
  const appIdProvider = () => normalized;
  const host = createHostNamespace(appIdProvider);
  const scoped: PawSdk = {
    appId: normalized,
    api: createApiNamespace(appIdProvider),
    host,
    ui: createUiNamespace(normalized),
    dependencies: createDependenciesNamespace(
      createApiNamespace(appIdProvider),
    ),
    chat: host.chat,
    chatStream: host.chatStream,
    getChatHistory: host.getChatHistory,
    chatSessions: host.chatSessions,
    storage: host.storage,
    toast: host.toast,
    notify: host.notify,
  };
  scopedApps.set(normalized, scoped);
  return scoped;
}

export const pawSdkFactory: PawSdkFactory = { forApp };

// Re-export types and sub-modules for advanced usage
export type {
  PawApiNamespace,
  PawApiResponse,
  PawHostNamespace,
  PawPageRegistration,
  PawDisposable,
  PawDependenciesNamespace,
  PawDependencyAction,
  PawDependencyHealthState,
  PawDependencyLifecycleState,
  PawDependencyOwnership,
  PawDependencySnapshot,
  PawDependencyStatus,
  PawCapabilityStatus,
  PawRequestOptions,
  PawRequestInit,
  PawSseEvent,
  PawSseOptions,
  PawChatOptions,
  PawChatHistory,
  PawChatHistoryMessage,
  PawChatSession,
  PawChatSessionScope,
  PawChatSessionsApi,
  PawChatStreamEvent,
  PawSdk,
  PawSdkFactory,
  PawStorageApi,
  PawTaskEventHandler,
  PawTaskEvents,
  PawTaskHandle,
} from "./types";

export { createPawTask } from "./task";
export { createDependenciesNamespace } from "./dependencies";
export { PawApiError } from "./api";
export { PawChatStreamError } from "./host";
export { apiNamespace, hostNamespace, createApiNamespace, createHostNamespace };
