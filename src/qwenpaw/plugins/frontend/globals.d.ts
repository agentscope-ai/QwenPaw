import type { QwenPawWindowNamespace } from "./host.js";
declare global {
  /** Includes the SDK 1.1 harness settings namespace. */
  interface Window {
    QwenPaw: QwenPawWindowNamespace;
  }
}
export {};
