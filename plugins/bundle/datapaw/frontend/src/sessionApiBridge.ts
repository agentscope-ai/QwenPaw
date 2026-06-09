import type { IAgentScopeRuntimeWebUISessionAPI } from "@agentscope-ai/chat";
import sessionApiLocal from "./pages/Chat/sessionApi";
import { getHostSessionApi } from "./hostSessionApiPatch";

function onHostChatRoute(): boolean {
  if (typeof window === "undefined") return false;
  const path = window.location.pathname;
  return path === "/" || path.startsWith("/chat");
}

function resolveApi(): IAgentScopeRuntimeWebUISessionAPI {
  const host = getHostSessionApi();
  if (host && onHostChatRoute()) {
    return host as unknown as IAgentScopeRuntimeWebUISessionAPI;
  }
  return sessionApiLocal;
}

/** Delegates to host sessionApi on `/chat` so history and URL stay in sync. */
const sessionApiBridge: IAgentScopeRuntimeWebUISessionAPI = new Proxy(
  sessionApiLocal,
  {
    get(_target, prop: string | symbol) {
      const api = resolveApi() as Record<string | symbol, unknown>;
      const val = api[prop];
      return typeof val === "function" ? (val as (...a: unknown[]) => unknown).bind(api) : val;
    },
  },
);

export default sessionApiBridge;
