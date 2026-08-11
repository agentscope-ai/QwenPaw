/**
 * Open the operating system's folder chooser and return an absolute path.
 *
 * A browser cannot do this on its own. `<input type="file" webkitdirectory>`
 * and `showDirectoryPicker()` both open the native window, but hand back
 * only a directory handle and paths relative to the chosen folder — the
 * absolute location is withheld by design. Binding a project directory
 * needs that absolute path, so the dialog has to be opened by something
 * outside the web sandbox:
 *
 * - Desktop (Tauri): the dialog plugin, in-process.
 * - Plain browser: the backend, which for a local install runs on this
 *   same machine and so puts the window on this same screen.
 *
 * Neither is possible for a remote console; callers fall back to the
 * in-app directory browser then.
 */
import { open } from "@tauri-apps/plugin-dialog";

import { projectDirectoryApi } from "../api/modules/projectDirectory";
import { isDesktopTauriRuntime } from "./openExternalLink";

/** Distinguishes "user dismissed the dialog" from "no dialog appeared". */
export const PICK_CANCELLED = Symbol("pick-cancelled");

export type PickDirectoryResult = string | typeof PICK_CANCELLED;

let backendAvailability: Promise<boolean> | null = null;

/**
 * Whether an OS dialog can be shown at all.
 *
 * The backend answer is cached: it depends on the host's platform and
 * display, neither of which changes while the console is open.
 */
export async function isNativeDirectoryPickerAvailable(): Promise<boolean> {
  if (isDesktopTauriRuntime()) return true;
  if (!backendAvailability) {
    backendAvailability = projectDirectoryApi
      .nativePickerAvailable()
      .then((res) => res.available)
      .catch(() => false);
  }
  return backendAvailability;
}

/** Test seam: forget the cached backend probe. */
export function resetNativeDirectoryPickerCache(): void {
  backendAvailability = null;
}

/**
 * Show the chooser. Returns the absolute path, or {@link PICK_CANCELLED}
 * when the user dismissed it. Throws when no dialog could be shown, so the
 * caller can degrade instead of leaving the user staring at nothing.
 */
export async function pickDirectory(
  options: { defaultPath?: string; title?: string } = {},
): Promise<PickDirectoryResult> {
  if (isDesktopTauriRuntime()) {
    const selected = await open({
      directory: true,
      multiple: false,
      defaultPath: options.defaultPath,
      title: options.title,
    });
    if (selected === null || selected === undefined) return PICK_CANCELLED;
    // `multiple: false` yields a string, but guard anyway: an array here
    // would otherwise be stringified into a bogus path.
    const path = Array.isArray(selected) ? selected[0] : selected;
    return typeof path === "string" && path ? path : PICK_CANCELLED;
  }

  const result = await projectDirectoryApi.openNativePicker(options.title);
  if (result.cancelled || !result.path) return PICK_CANCELLED;
  return result.path;
}
