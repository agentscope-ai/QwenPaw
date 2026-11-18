import type { QwenPawWindowNamespace } from "./qwenpaw-host";

export const PLUGIN_ID = "qwenpaw-openui";

export function getHost(): QwenPawWindowNamespace {
  return (window as unknown as { QwenPaw: QwenPawWindowNamespace }).QwenPaw;
}
