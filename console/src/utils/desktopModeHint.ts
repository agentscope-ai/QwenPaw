const DESKTOP_MODE_HINT_KEY = "qwenpaw.desktop-mode-hint.dismissed";

export function shouldShowDesktopModeHint(storage: Storage): boolean {
  try {
    return storage.getItem(DESKTOP_MODE_HINT_KEY) !== "1";
  } catch {
    return false;
  }
}

export function dismissDesktopModeHint(storage: Storage): void {
  try {
    storage.setItem(DESKTOP_MODE_HINT_KEY, "1");
  } catch {
    // Storage may be unavailable in restricted browser environments.
  }
}
