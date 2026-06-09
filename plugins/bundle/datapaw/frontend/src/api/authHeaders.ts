import { getApiToken } from "./config";
import { PLUGIN_ID, PLUGIN_ROUTE_BASE } from "../plugin/constants";

/** Built-in DataPaw agent id — must match backend `BUILTIN_DATAPAW_AGENT_ID`. */
export const DATAPAW_AGENT_ID = PLUGIN_ID;

/**
 * True when this JS bundle runs as the DataPaw plugin inside QwenPaw host.
 *
 * Primary: build-time flag (`__DATAPAW_PLUGIN_EMBED__`) — this `frontend/`
 * package only ships via `vite build` → `dist/index.js`, never standalone.
 * Fallback: `window.QwenPaw.host` or `/plugin/datapaw` URL (local dev).
 */
export function isDatapawPluginContext(): boolean {
  if (typeof window === "undefined") return false;
  if (typeof __DATAPAW_PLUGIN_EMBED__ !== "undefined" && __DATAPAW_PLUGIN_EMBED__) {
    return true;
  }
  if ((window as Window).QwenPaw?.host) {
    return true;
  }
  const base = PLUGIN_ROUTE_BASE.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`^${base}(?:/|$)`).test(window.location.pathname);
}

/** Authorization + X-Agent-Id for API requests. Caller sets Content-Type when needed. */
export function buildAuthHeaders(): Record<string, string> {
  const headers: Record<string, string> = {};
  const token = getApiToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  // Legacy plugin route (full SPA) always targets the DataPaw workspace.
  if (
    isDatapawPluginContext() &&
    typeof window !== "undefined" &&
    new RegExp(
      `^${PLUGIN_ROUTE_BASE.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?:/|$)`,
    ).test(window.location.pathname)
  ) {
    headers["X-Agent-Id"] = DATAPAW_AGENT_ID;
    return headers;
  }

  try {
    const agentStorage = sessionStorage.getItem("qwenpaw-agent-storage");
    if (agentStorage) {
      const parsed = JSON.parse(agentStorage);
      const selectedAgent = parsed?.state?.selectedAgent;
      if (selectedAgent) {
        headers["X-Agent-Id"] = selectedAgent;
      }
    }
  } catch (error) {
    console.warn("Failed to get selected agent from storage:", error);
  }
  return headers;
}
