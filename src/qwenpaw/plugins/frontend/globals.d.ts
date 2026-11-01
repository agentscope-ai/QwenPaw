import type { QwenPawWindowNamespace } from "./host.js";
declare global {
  interface Window {
    QwenPaw: QwenPawWindowNamespace;
  }
}
export {};
