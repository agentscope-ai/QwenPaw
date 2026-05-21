import { invoke, isTauri } from "@tauri-apps/api/core";

declare const VITE_API_BASE_URL: string;
declare const __QWENPAW_CONFIGURED_API_BASE_URL__: string;

type RuntimeGlobals = typeof globalThis & {
  __QWENPAW_API_BASE_URL__?: string;
};

let initRuntimeApiBaseUrlPromise: Promise<string> | null = null;

export function isTauriRuntime(): boolean {
  return isTauri();
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
  const tauriRuntime = isTauriRuntime();
  if (baseUrl || !tauriRuntime) {
    if (baseUrl && tauriRuntime) {
      // VITE_API_BASE_URL is set while running inside a Tauri runtime.
      // The Rust sidecar will start a second backend process that won't
      // be used; set VITE_API_BASE_URL='' or leave it unset for desktop builds.
      console.warn(
        "[Tauri] VITE_API_BASE_URL is set; ignoring backend_port from Rust. " +
          "You may have two backend processes running.",
      );
    }
    return baseUrl;
  }

  const port = await invoke<number>("backend_port");
  const runtimeBaseUrl = `http://127.0.0.1:${port}`;
  setRuntimeApiBaseUrl(runtimeBaseUrl);

  return runtimeBaseUrl;
}

function getApiBaseUrl(): string {
  return typeof VITE_API_BASE_URL !== "undefined" ? VITE_API_BASE_URL : "";
}

function getConfiguredApiBaseUrl(): string {
  if (typeof __QWENPAW_CONFIGURED_API_BASE_URL__ !== "undefined") {
    return __QWENPAW_CONFIGURED_API_BASE_URL__;
  }
  return "";
}

function setRuntimeApiBaseUrl(baseUrl: string): void {
  (globalThis as RuntimeGlobals).__QWENPAW_API_BASE_URL__ = baseUrl;
}

function clearRuntimeApiBaseUrl(): void {
  delete (globalThis as RuntimeGlobals).__QWENPAW_API_BASE_URL__;
}

export async function getBackendStartupError(): Promise<string> {
  if (!isTauriRuntime()) return "";
  return (await invoke<string | null>("backend_startup_error")) || "";
}

export async function restartBackend(): Promise<string> {
  const configuredBaseUrl = getConfiguredApiBaseUrl();
  if (!isTauriRuntime()) {
    return getApiBaseUrl();
  }

  if (configuredBaseUrl) {
    return configuredBaseUrl;
  }

  initRuntimeApiBaseUrlPromise = null;
  clearRuntimeApiBaseUrl();

  const port = await invoke<number>("restart_backend");
  const runtimeBaseUrl = `http://127.0.0.1:${port}`;
  setRuntimeApiBaseUrl(runtimeBaseUrl);

  return runtimeBaseUrl;
}
