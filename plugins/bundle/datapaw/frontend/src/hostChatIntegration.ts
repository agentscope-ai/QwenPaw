/**
 * Mount DataPaw chat UI on the host `/chat` route without `registerRoutes`.
 *
 * Replaces `Chat/index` in `window.QwenPaw.modules` so task graph cards render
 * inside the message stream (not the legacy `/plugin/datapaw` layout with
 * fixed top-right ConsoleCronBubble).
 */

import DatapawChatPage from "./pages/Chat/index";
import { patchHostSessionApi } from "./hostSessionApiPatch";

import { PLUGIN_ID } from "./plugin/constants";

const DATAPAW_AGENT_ID = PLUGIN_ID;
const STORAGE_KEY = "qwenpaw-agent-storage";
const PATCHED = Symbol("datapawHostChatPatched");

function getSelectedAgentId(): string {
  try {
    const sessionRaw = sessionStorage.getItem(STORAGE_KEY);
    if (sessionRaw) {
      const parsed = JSON.parse(sessionRaw);
      const agent = parsed?.state?.selectedAgent;
      if (typeof agent === "string" && agent) return agent;
    }
    const localRaw = localStorage.getItem(STORAGE_KEY);
    if (localRaw) {
      const parsed = JSON.parse(localRaw);
      const agent = parsed?.state?.selectedAgent;
      if (typeof agent === "string" && agent) return agent;
    }
  } catch {
    /* ignore */
  }
  return "default";
}

function tryPatchHostChat(): boolean {
  const modules = (
    window as { QwenPaw?: { modules?: Record<string, Record<string, unknown>> } }
  ).QwenPaw?.modules;
  const chatMod = modules?.["Chat/index"];
  if (!chatMod?.default) return false;

  patchHostSessionApi();

  const current = chatMod.default as { [PATCHED]?: boolean };
  if (current[PATCHED]) return true;

  const OriginalChat = chatMod.default as import("react").ComponentType<
    Record<string, unknown>
  >;
  const { React } = (
    window as { QwenPaw: { host: { React: typeof import("react") } } }
  ).QwenPaw.host;

  function DatapawHostChat(props: Record<string, unknown>) {
    if (getSelectedAgentId() !== DATAPAW_AGENT_ID) {
      return React.createElement(OriginalChat, props);
    }
    return React.createElement(DatapawChatPage, props);
  }
  Object.defineProperty(DatapawHostChat, PATCHED, { value: true });
  Object.defineProperty(DatapawHostChat, "displayName", {
    value: "DatapawHostChat",
  });

  chatMod.default = DatapawHostChat;
  return true;
}

export function installDatapawHostChat(): void {
  if (tryPatchHostChat()) return;

  let attempts = 0;
  const timer = window.setInterval(() => {
    attempts += 1;
    if (tryPatchHostChat()) {
      window.clearInterval(timer);
      return;
    }
    if (attempts >= 200) {
      window.clearInterval(timer);
      console.warn(
        `[${PLUGIN_ID}] Failed to patch Chat/index — task cards will not render on /chat`,
      );
    }
  }, 50);
}
