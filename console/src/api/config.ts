declare const VITE_API_BASE_URL: string;
declare const TOKEN: string;

const AUTH_TOKEN_KEY = "copaw_auth_token";

declare global {
  interface Window {
    __COPAW_BASE_PATH__?: string;
  }
}

function normalizeBasePath(raw: string): string {
  const trimmed = (raw || "").trim();
  if (!trimmed) return "";
  const withSlash = trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
  const noTrailing = withSlash.replace(/\/+$/, "");
  return noTrailing === "/" ? "" : noTrailing;
}

export function getRuntimeBasePath(): string {
  if (typeof window !== "undefined" && window.__COPAW_BASE_PATH__) {
    return normalizeBasePath(window.__COPAW_BASE_PATH__);
  }
  return "";
}

export function getStaticUrl(assetPath: string): string {
  const base = getRuntimeBasePath();
  const normalized = (assetPath || "").startsWith("/")
    ? (assetPath || "").slice(1)
    : assetPath || "";
  if (base) return `${base}/${normalized}`;
  const viteBase = import.meta.env.BASE_URL || "/";
  const prefix = viteBase.endsWith("/") ? viteBase : `${viteBase}/`;
  return `${prefix}${normalized}`;
}

/**
 * Get the full API URL with /api prefix
 * @param path - API path (e.g., "/models", "/skills")
 * @returns Full API URL (e.g., "http://localhost:8088/api/models" or "/api/models")
 */
export function getApiUrl(path: string): string {
  const runtimeBase = getRuntimeBasePath();
  const base = runtimeBase || VITE_API_BASE_URL || "";
  const apiPrefix = "/api";
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${base}${apiPrefix}${normalizedPath}`;
}

/**
 * Get the API token - checks localStorage first (auth login),
 * then falls back to the build-time TOKEN constant.
 * @returns API token string or empty string
 */
export function getApiToken(): string {
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
