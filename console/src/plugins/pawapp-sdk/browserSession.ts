import { getApiToken, getApiUrl, updateBrowserSession } from "../../api/config";
import { resolveBackendMode } from "../../auth/gate";

const pending = new Map<string, Promise<number | null>>();
const hubApps = new Set<string>();
let mode: ReturnType<typeof resolveBackendMode> | undefined;

/** Prepare native browser reads before mounting an app or opening its page. */
export function prepareBrowserSession(appId: string): Promise<number | null> {
  const token = getApiToken();
  const key = `${appId}:${token}`;
  const existing = pending.get(key);
  if (existing) return existing;
  const request = (async () => {
    mode ??= resolveBackendMode().catch((error) => {
      mode = undefined;
      throw error;
    });
    if ((await mode) !== "hub") return null;
    hubApps.add(appId);
    return updateBrowserSession(async () => {
      if (token !== getApiToken()) throw new Error("Account changed");
      const response = await fetch(
        getApiUrl(`/hub/pawapps/${encodeURIComponent(appId)}/session`),
        {
          method: "POST",
          credentials: "same-origin",
          headers: { Authorization: `Bearer ${token}` },
        },
      );
      if (!response.ok) {
        throw new Error(`PawApp authentication failed (${response.status})`);
      }
      if (token !== getApiToken()) throw new Error("Account changed");
      const { expires_in: seconds } = (await response.json()) as {
        expires_in: number;
      };
      return seconds;
    });
  })().finally(() => pending.delete(key));
  pending.set(key, request);
  return request;
}

/** Hub resource URLs never carry account tokens, even during renewal. */
export function usesBrowserSession(appId: string): boolean {
  return hubApps.has(appId);
}
