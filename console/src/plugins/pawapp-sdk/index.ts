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
import { apiNamespace } from "./api";
import { chat, hostNamespace, notify, storage, toast } from "./host";
import type { PawSdk } from "./types";

/**
 * The top-level `paw` SDK object.
 *
 * Combines API communication (paw.api.*) with host capabilities
 * (paw.chat, paw.storage, paw.toast, paw.notify).
 */
export const paw: PawSdk = {
  api: apiNamespace,
  host: hostNamespace,

  // Convenience re-exports at top level
  chat,
  storage,
  toast,
  notify,
};

// Re-export types and sub-modules for advanced usage
export type {
  PawApiNamespace,
  PawApiResponse,
  PawHostNamespace,
  PawRequestOptions,
  PawSdk,
  PawStorageApi,
  PawTaskEventHandler,
  PawTaskEvents,
  PawTaskHandle,
} from "./types";

export { createPawTask } from "./task";
export { apiNamespace, hostNamespace };
