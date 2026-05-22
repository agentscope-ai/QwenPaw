import { invoke, isTauri } from "@tauri-apps/api/core";

declare const VITE_API_BASE_URL: string;

let initRuntimeApiBaseUrlPromise: Promise<string> | null = null;

export function isTauriRuntime(): boolean {
  return isTauri();
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
