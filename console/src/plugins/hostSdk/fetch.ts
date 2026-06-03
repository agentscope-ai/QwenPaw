/**
 * hostSdk/fetch.ts — auth-aware fetch wrapper for plugins.
 *
 * Reuses `buildAuthHeaders()` which already injects `Authorization`
 * and `X-Agent-Id` from the agent store. Plugin callers pass an API path
 * (e.g. "/console/chat") and get back a normal Response.
 */
import { getApiUrl } from "../../api/config";
import { buildAuthHeaders } from "../../api/authHeaders";

export async function hostFetch(
  path: string,
  init?: RequestInit,
): Promise<Response> {
  const headers: Record<string, string> = {
    ...buildAuthHeaders(),
    ...((init?.headers as Record<string, string>) ?? {}),
  };
  return fetch(getApiUrl(path), { ...init, headers });
}
