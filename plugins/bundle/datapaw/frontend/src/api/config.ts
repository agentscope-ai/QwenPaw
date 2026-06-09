declare const VITE_API_BASE_URL: string;
declare const TOKEN: string;

const AUTH_TOKEN_KEY = "qwenpaw_auth_token";

/**
 * Pull the host-provided helpers off `window.QwenPaw.host` if we're running
 * as a plugin inside the QwenPaw console; fall back to local same-origin
 * resolution otherwise (standalone dev, tests). The plugin loader installs
 * `window.QwenPaw.host` before any plugin bundle is evaluated, so once the
 * `App` component renders these are always populated in production.
 */
function getHost(): { getApiUrl?: (path: string) => string; getApiToken?: () => string } | undefined {
  if (typeof window === "undefined") return undefined;
  return (window as Window & { QwenPaw?: { host?: { getApiUrl?: (path: string) => string; getApiToken?: () => string } } })
    .QwenPaw?.host;
}

/**
 * Get the full API URL with /api prefix
 * @param path - API path (e.g., "/models", "/skills")
 * @returns Full API URL (e.g., "http://localhost:8088/api/models" or "/api/models")
 */
export function getApiUrl(path: string): string {
  const host = getHost();
  if (host && typeof host.getApiUrl === "function") {
    return host.getApiUrl(path);
  }
  const base = typeof VITE_API_BASE_URL !== "undefined" ? VITE_API_BASE_URL : "";
  const apiPrefix = "/api";
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${base}${apiPrefix}${normalizedPath}`;
}

/**
 * Get the API token - prefers the host's bearer if running as a plugin,
 * then localStorage (auth login), then the build-time TOKEN constant.
 * @returns API token string or empty string
 */
export function getApiToken(): string {
  const host = getHost();
  if (host && typeof host.getApiToken === "function") {
    const hosted = host.getApiToken();
    if (hosted) return hosted;
  }
  const stored = localStorage.getItem(AUTH_TOKEN_KEY);
  if (stored) return stored;
  return typeof TOKEN !== "undefined" ? TOKEN : "";
}

/**
 * Store the auth token in localStorage after login.
 */
export function setAuthToken(token: string): void {
  localStorage.setItem(AUTH_TOKEN_KEY, token);
}

/**
 * Remove the auth token from localStorage (logout / 401).
 */
export function clearAuthToken(): void {
  localStorage.removeItem(AUTH_TOKEN_KEY);
}
