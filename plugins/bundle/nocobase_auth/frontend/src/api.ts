/**
 * Frontend API client for the NocoBase auth plugin.
 *
 * Uses window.QwenPaw.host helpers to obtain API URL and token.
 */

function getHost() {
  return (window as any).QwenPaw?.host || {};
}

function getHeaders(): Record<string, string> {
  const { getApiToken } = getHost();
  const token = getApiToken?.();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  return headers;
}

function apiUrl(path: string): string {
  const { getApiUrl } = getHost();
  return getApiUrl?.(path) || path;
}

async function getJson(path: string) {
  const res = await fetch(apiUrl(path), { headers: getHeaders() });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json();
}

async function postJson(path: string, body?: any) {
  const res = await fetch(apiUrl(path), {
    method: "POST",
    headers: getHeaders(),
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json();
}

async function putJson(path: string, body: any) {
  const res = await fetch(apiUrl(path), {
    method: "PUT",
    headers: getHeaders(),
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json();
}

export const nocobaseApi = {
  getStatus: () => getJson("/nocobase-auth/status"),
  testConnection: () => postJson("/nocobase-auth/test-connection"),
  getUsers: () => getJson("/nocobase-auth/users"),
  getRoles: () => getJson("/nocobase-auth/roles"),
  getConfig: () => getJson("/nocobase-auth/config"),
  updateConfig: (config: any) => putJson("/nocobase-auth/config", config),
};
