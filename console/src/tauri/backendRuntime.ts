import { isTauri } from "@tauri-apps/api/core";

/** The native bridge is available before the bundled console has mounted. */
export function isTauriRuntime(): boolean {
  if (typeof window === "undefined") return false;
  return (
    isTauri() ||
    typeof (
      window as {
        __TAURI_INTERNALS__?: { invoke?: unknown };
      }
    ).__TAURI_INTERNALS__?.invoke === "function"
  );
}

export const isDesktopApp = isTauriRuntime;
