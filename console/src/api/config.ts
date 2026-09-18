declare const VITE_API_BASE_URL: string;
declare const TOKEN: string;

const AUTH_TOKEN_KEY = "qwenpaw_auth_token";
let authCleanup: Promise<unknown> = Promise.resolve();

/** Serialize cookie updates so a late old-account response cannot win. */
export function updateBrowserSession<T>(
  operation: () => Promise<T>,
): Promise<T> {
  const result = authCleanup.then(operation);
  authCleanup = result.catch(() => undefined);
  return result;
}

function clearBrowserSessions(): void {
  void updateBrowserSession(() =>
    fetch(getApiUrl("/hub/pawapps/sessions"), {
      method: "DELETE",
      credentials: "include",
    }),
  ).catch(() => undefined);
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
  const stored = localStorage.getItem(AUTH_TOKEN_KEY);
  if (stored) return stored;
  return typeof TOKEN !== "undefined" ? TOKEN : "";
}

/**
 * Store the auth token in localStorage after login.
 */
export function setAuthToken(token: string): void {
  if (getApiToken() !== token) clearBrowserSessions();
  localStorage.setItem(AUTH_TOKEN_KEY, token);
  window.dispatchEvent(new Event("qwenpaw:auth-changed"));
}

/**
 * Remove the auth token from localStorage (logout / 401).
 */
export function clearAuthToken(): void {
  localStorage.removeItem(AUTH_TOKEN_KEY);
  clearBrowserSessions();
  window.dispatchEvent(new Event("qwenpaw:auth-changed"));
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
