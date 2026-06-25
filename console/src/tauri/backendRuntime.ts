import { invoke, isTauri } from "@tauri-apps/api/core";

declare const VITE_API_BASE_URL: string;

const DESKTOP_QUERY_KEY = "desktop";
const DESKTOP_SESSION_KEY = "qpDesktop";

let initRuntimeApiBaseUrlPromise: Promise<string> | null = null;

export function isTauriRuntime(): boolean {
  return isTauri();
}

/**
 * Reliably detect whether we're running inside the Tauri desktop app, even
 * after the webview has navigated to the backend-hosted console where
 * `__TAURI_INTERNALS__` may or may not be reachable. The bootstrap gate tags
 * the redirect URL with `?desktop=1` and we persist it in sessionStorage so
 * subsequent reloads keep the answer.
 */
export function isDesktopApp(): boolean {
  if (typeof window === "undefined") return false;
  if (isTauriRuntime()) return true;
  try {
    if (sessionStorage.getItem(DESKTOP_SESSION_KEY) === "1") return true;
    const params = new URLSearchParams(window.location.search);
    if (params.get(DESKTOP_QUERY_KEY) === "1") {
      sessionStorage.setItem(DESKTOP_SESSION_KEY, "1");
      return true;
    }
  } catch {
    /* sessionStorage unavailable (e.g., privacy mode) */
  }
  return false;
}

/**
 * Append the desktop marker to a URL so the backend-hosted console can detect
 * it after the bootstrap redirect.
 */
export function withDesktopMarker(url: string): string {
  const sep = url.includes("?") ? "&" : "?";
  return `${url}${sep}${DESKTOP_QUERY_KEY}=1`;
}

export function shouldUseTauriStartupGate(): boolean {
  return isTauriRuntime() && !isBackendHostedConsole();
}

export function initRuntimeApiBaseUrl(): Promise<string> {
  if (!initRuntimeApiBaseUrlPromise) {
    initRuntimeApiBaseUrlPromise = resolveRuntimeApiBaseUrl()
      .then((url) => {
        if (!url) {
          initRuntimeApiBaseUrlPromise = null;
        }
        return url;
      })
      .catch((err) => {
        initRuntimeApiBaseUrlPromise = null;
        throw err;
      });
  }
  return initRuntimeApiBaseUrlPromise;
}

async function resolveRuntimeApiBaseUrl(): Promise<string> {
  const baseUrl = getApiBaseUrl();
  const tauriRuntime = isTauriRuntime();
  if (baseUrl || !tauriRuntime) {
    return baseUrl;
  }

  const port = await invoke<number | null>("backend_port");
  return port ? `http://127.0.0.1:${port}` : "";
}

function getApiBaseUrl(): string {
  return typeof VITE_API_BASE_URL !== "undefined" ? VITE_API_BASE_URL : "";
}

function isBackendHostedConsole(): boolean {
  if (typeof window === "undefined") return false;
  const { protocol, hostname, pathname } = window.location;
  return (
    protocol === "http:" &&
    (hostname === "127.0.0.1" || hostname === "localhost") &&
    /^\/console(?:\/|$)/.test(pathname)
  );
}

export function backendConsoleUrl(apiBaseUrl: string): string {
  return `${apiBaseUrl.replace(/\/+$/, "")}/console`;
}

export async function getBackendStartupError(): Promise<string> {
  if (!isTauriRuntime()) return "";
  return (await invoke<string | null>("backend_startup_error")) || "";
}

export async function restartBackend(): Promise<void> {
  const configuredBaseUrl = getApiBaseUrl();
  if (!isTauriRuntime()) {
    return;
  }

  if (configuredBaseUrl) {
    return;
  }

  initRuntimeApiBaseUrlPromise = null;

  await invoke<void>("restart_backend");
}
