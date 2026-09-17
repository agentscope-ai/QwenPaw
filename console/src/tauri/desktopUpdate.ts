import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { isDesktopApp } from "./backendRuntime";

export interface DesktopUpdateInfo {
  version: string;
  body?: string | null;
  supportsLaterInstall?: boolean;
}

export interface UpdateProgress {
  downloaded: number;
  total: number | null;
}

export interface UpdateError {
  stage: "check" | "download" | "install";
  kind: "network" | "signature" | "appLocation" | "other";
  message: string;
}

export interface DownloadDonePayload {
  version: string;
}

export async function checkDesktopUpdate(): Promise<DesktopUpdateInfo | null> {
  if (!isDesktopApp()) return null;
  return invoke<DesktopUpdateInfo | null>("check_desktop_update");
}

export async function installDesktopUpdate(): Promise<void> {
  if (!isDesktopApp()) return;
  await invoke<void>("install_desktop_update");
}

export async function downloadDesktopUpdate(): Promise<void> {
  if (!isDesktopApp()) return;
  await invoke<void>("download_desktop_update");
}

export async function installDownloadedUpdate(): Promise<void> {
  if (!isDesktopApp()) return;
  await invoke<void>("install_downloaded_update");
}

export async function checkCachedUpdate(): Promise<string | null> {
  if (!isDesktopApp()) return null;
  return invoke<string | null>("check_cached_update");
}

export interface UpdateEventHandlers {
  onCheckStart?: () => void;
  onDownloadProgress?: (progress: UpdateProgress) => void;
  onInstallStart?: () => void;
  onDownloadDone?: (payload: DownloadDonePayload) => void;
  onError?: (error: UpdateError) => void;
}

export async function onUpdateEvent(
  handlers: UpdateEventHandlers,
): Promise<UnlistenFn> {
  const unlisteners: UnlistenFn[] = [];

  const addListener = async <T>(
    eventName: string,
    handler?: (payload: T) => void,
  ) => {
    if (!handler) return;
    unlisteners.push(
      await listen<T>(eventName, (event) => handler(event.payload)),
    );
  };

  const withoutPayload = (
    handler?: () => void,
  ): ((payload: unknown) => void) | undefined =>
    handler ? () => handler() : undefined;

  await Promise.all([
    addListener("update:check-start", withoutPayload(handlers.onCheckStart)),
    addListener("update:download-progress", handlers.onDownloadProgress),
    addListener(
      "update:install-start",
      withoutPayload(handlers.onInstallStart),
    ),
    addListener("update:download-done", handlers.onDownloadDone),
    addListener("update:error", handlers.onError),
  ]);

  return () => {
    unlisteners.forEach((u) => u());
  };
}
