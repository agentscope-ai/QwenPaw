// VITE_API_BASE_URL and TOKEN are declared globally in src/vite-env.d.ts.

const AUTH_TOKEN_KEY = "qwenpaw_auth_token";

declare global {
  interface Window {
    __TAURI__?: {
      core?: {
        invoke?: <T>(
          command: string,
          args?: Record<string, unknown>,
        ) => Promise<T>;
      };
    };
  }
}

let runtimeApiBaseUrl = "";
let initRuntimeApiBaseUrlPromise: Promise<string> | null = null;

export function getApiBaseUrl(): string {
  return (
    runtimeApiBaseUrl ||
    (typeof VITE_API_BASE_URL !== "undefined" ? VITE_API_BASE_URL : "")
  );
}

export function isTauriRuntime(): boolean {
  return typeof window !== "undefined" && !!window.__TAURI__?.core?.invoke;
}

function getTauriInvoke() {
  return typeof window !== "undefined"
    ? window.__TAURI__?.core?.invoke
    : undefined;
}

export function initRuntimeApiBaseUrl(): Promise<string> {
  if (!initRuntimeApiBaseUrlPromise) {
    initRuntimeApiBaseUrlPromise = resolveRuntimeApiBaseUrl().catch((err) => {
      initRuntimeApiBaseUrlPromise = null;
      throw err;
    });
  }
  return initRuntimeApiBaseUrlPromise;
}

async function resolveRuntimeApiBaseUrl(): Promise<string> {
  const baseUrl = getApiBaseUrl();
  const invoke = getTauriInvoke();
  if (baseUrl || !invoke) {
    if (baseUrl && invoke) {
      // VITE_API_BASE_URL is set while running inside a Tauri runtime.
      // The Rust sidecar will start a second backend process that won't
      // be used — set VITE_API_BASE_URL='' or leave it unset for desktop builds.
      console.warn(
        "[Tauri] VITE_API_BASE_URL is set; ignoring backend_port from Rust. " +
          "You may have two backend processes running.",
      );
    }
    return baseUrl;
  }

  const port = await invoke<number>("backend_port");
  runtimeApiBaseUrl = `http://127.0.0.1:${port}`;

  return runtimeApiBaseUrl;
}

export async function getBackendStartupError(): Promise<string> {
  const invoke = getTauriInvoke();
  if (!invoke) return "";
  return (await invoke<string | null>("backend_startup_error")) || "";
}

export async function restartBackend(): Promise<string> {
  const invoke = getTauriInvoke();
  const configuredBaseUrl =
    typeof VITE_API_BASE_URL !== "undefined" ? VITE_API_BASE_URL : "";
  if (!invoke) {
    return getApiBaseUrl();
  }

  initRuntimeApiBaseUrlPromise = null;

  if (configuredBaseUrl) {
    return configuredBaseUrl;
  }

  runtimeApiBaseUrl = "";
  const port = await invoke<number>("restart_backend");
  runtimeApiBaseUrl = `http://127.0.0.1:${port}`;

  return runtimeApiBaseUrl;
}

/**
 * Get the full API URL with /api prefix
 * @param path - API path (e.g., "/models", "/skills")
 * @returns Full API URL (e.g., "http://localhost:8088/api/models" or "/api/models")
 */
export function getApiUrl(path: string): string {
  const base = getApiBaseUrl();
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
