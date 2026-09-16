declare const VITE_API_BASE_URL: string;
declare const TOKEN: string;

const AUTH_TOKEN_KEY = "qwenpaw_auth_token";
let memoryAuthToken = "";
let authMode: "legacy" | "multi_user" = "legacy";

export function setApiAuthMode(mode: "legacy" | "multi_user"): void {
  authMode = mode;
  if (mode === "multi_user") {
    localStorage.removeItem(AUTH_TOKEN_KEY);
  }
}

export function getApiAuthMode(): "legacy" | "multi_user" {
  return authMode;
}

/**
 * Get the full API URL with /api prefix
 * @param path - API path (e.g., "/models", "/skills")
 * @returns Full API URL (e.g., "http://localhost:8088/api/models" or "/api/models")
 */
export function getApiUrl(path: string): string {
  const base = VITE_API_BASE_URL || "";
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
  if (memoryAuthToken) return memoryAuthToken;
  if (authMode === "multi_user") return "";
  const stored = localStorage.getItem(AUTH_TOKEN_KEY);
  if (stored) return stored;
  return typeof TOKEN !== "undefined" ? TOKEN : "";
}

/**
 * Store the auth token in localStorage after login.
 */
export function setAuthToken(token: string): void {
  if (authMode === "multi_user") {
    memoryAuthToken = token;
    localStorage.removeItem(AUTH_TOKEN_KEY);
    return;
  }
  localStorage.setItem(AUTH_TOKEN_KEY, token);
}

/**
 * Remove the auth token from localStorage (logout / 401).
 */
export function clearAuthToken(): void {
  memoryAuthToken = "";
  localStorage.removeItem(AUTH_TOKEN_KEY);
}

/**
 * Get the backend API port number.
 * Extracted from VITE_API_BASE_URL, then falls back to the current window
 * port and finally the default desktop backend port.
 */
export function getApiPort(): number {
  const base = VITE_API_BASE_URL || "";
  if (base) {
    try {
      const url = new URL(base);
      if (url.port) return parseInt(url.port, 10);
    } catch {
      // Fall through to runtime-derived defaults.
    }
  }

  if (window.location.port) {
    return parseInt(window.location.port, 10);
  }
  return 8088;
}
